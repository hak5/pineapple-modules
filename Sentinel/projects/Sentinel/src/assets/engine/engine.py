#!/usr/bin/env python3
"""
Sentinel capture engine.

Runs as a background process next to the Pineapple module. It listens on one
or more monitor-mode interfaces (or replays a pcap file), decodes management
frames and writes aggregated observations to SQLite. The module backend only
reads that database, so the web UI stays responsive.

With two radios (e.g. the built-in 2.4 GHz radio and the 5 GHz extension),
each radio hops its own channel list in parallel.

Usage:
    engine.py --settings /root/.Sentinel/settings.json --db /root/.Sentinel/sentinel.db
    engine.py --iface wlan1mon --db sentinel.db
    engine.py --pcap capture.pcap --db test.db        # offline analysis
"""

import argparse
import json
import os
import select
import signal
import socket
import sqlite3
import struct
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dot11  # noqa: E402
import store  # noqa: E402

ETH_P_ALL = 0x0003
ARPHRD_IEEE80211_RADIOTAP = 803

CHANNELS_24 = [1, 6, 11, 2, 7, 3, 8, 4, 9, 5, 10]
# Every 20 MHz 5 GHz channel, DFS included (52-144): listening is receive-only, so DFS
# rules do not apply. Channels the radio or regulatory domain refuses are skipped
# automatically by ChannelHopper (marked "unusable").
CHANNELS_5 = [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128,
              132, 136, 140, 144, 149, 153, 157, 161, 165]
DEFAULT_CHANNELS = CHANNELS_24 + CHANNELS_5

FLUSH_INTERVAL = 5.0
RETENTION_INTERVAL = 600.0
BAD_CHANNEL_FAILURES = 3     # failures in a row before a channel is skipped
USE_NL80211 = True           # channel changes without starting `iw` (falls back to it)
RADIO_RETRY = 30.0           # seconds between two attempts to reopen a lost radio
# Frame budget per second (all radios). Normal listening is about 150 frames/s. Above SOFT,
# only management frames are processed (beacons, deauthentications...); above HARD, frames are
# dropped and counted. A flood then costs reading the socket, not decoding every frame.
FRAME_BUDGET_SOFT = 800
FRAME_BUDGET_HARD = 2000
SUMMARY_INTERVAL = 60.0      # seconds between two dashboard summaries (summary.py)
NICENESS = 10                # live capture runs below the web interface
BAD_CHANNEL_RETRY = 300.0    # seconds before skipped channels are tried again
STUCK_MESSAGE = ('%s cannot change channel: the radio refuses every channel. Another '
                 'interface of the same radio is probably up and keeps it busy.')


class ChannelHopper(threading.Thread):
    """Cycles one monitor interface through a list of channels."""

    def __init__(self, iface, channels, dwell):
        super(ChannelHopper, self).__init__()
        self.daemon = True
        self.iface = iface
        self.channels = list(channels)
        self.dwell = dwell
        self.current = None
        self.bad = set()
        self.failures = {}
        self.retry_at = 0.0
        self.stuck = False   # True while every channel is refused
        self._halt = threading.Event()
        # Change channel through nl80211 directly (no process started at each hop);
        # `iw` stays as the fallback
        self.nl = None
        self.method = 'iw'
        if USE_NL80211:
            try:
                import nl80211
                self.nl = nl80211.Nl80211()
                self.method = 'nl80211'
            except Exception:
                self.nl = None

    def _iw(self, ch):
        try:
            return subprocess.call(['iw', 'dev', self.iface, 'set', 'channel', str(ch)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
        except OSError:  # `iw` missing or not runnable: do not kill the hopper thread
            return False

    def set_channel(self, ch):
        if self.nl is not None:
            try:
                if self.nl.set_channel(self.iface, ch):
                    return True
            except Exception:
                pass
            # Refused through nl80211: if `iw` succeeds where nl80211 failed, this
            # device does not take our message, so keep using `iw` from now on
            if self._iw(ch):
                self.nl.close()
                self.nl, self.method = None, 'iw'
                return True
            return False
        return self._iw(ch)

    def run(self):
        while not self._halt.is_set():
            now = time.time()
            if self.bad and now >= self.retry_at:
                # Give skipped channels another chance: the radio may only have
                # been busy (another tool scanning, interface going down and up).
                self.bad.clear()
                self.failures.clear()
            usable = [c for c in self.channels if c not in self.bad]
            if not usable:
                # Every channel was refused, e.g. another interface of this radio is up
                self.stuck = True
                self._halt.wait(5)
                continue
            for ch in usable:
                if self._halt.is_set():
                    return
                if not self.set_channel(ch):
                    # Refused: either the radio cannot do this channel (regulatory
                    # domain, band) or it was busy. Skip it after a few failures in a row.
                    self.failures[ch] = self.failures.get(ch, 0) + 1
                    if self.failures[ch] >= BAD_CHANNEL_FAILURES:
                        if not self.bad:
                            self.retry_at = time.time() + BAD_CHANNEL_RETRY
                        self.bad.add(ch)
                    self._halt.wait(0.05)
                    continue
                self.failures.pop(ch, None)
                self.stuck = False
                self.current = ch
                self._halt.wait(self.dwell)

    def stop(self):
        self._halt.set()


class Radio(object):
    """One capture interface with its own socket and channel hopper."""

    def __init__(self, iface, channels, hop, dwell):
        self.iface = iface
        self.channels = channels or DEFAULT_CHANNELS
        self.hop = hop
        self.dwell = dwell
        self.sock = None
        self.hopper = None
        self.frames = 0
        self.error = None
        self.retry_at = None           # set while the radio is lost

    def open(self):
        type_path = '/sys/class/net/%s/type' % self.iface
        if not os.path.exists(type_path):
            raise RuntimeError('Interface %s does not exist' % self.iface)
        with open(type_path, encoding='utf-8') as fh:
            link_type = int(fh.read().strip())
        if link_type != ARPHRD_IEEE80211_RADIOTAP:
            raise RuntimeError('Interface %s is not in monitor mode' % self.iface)
        s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
        s.bind((self.iface, 0))
        s.setblocking(False)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
        except OSError:
            pass
        self.sock = s
        if self.hop:
            self.hopper = ChannelHopper(self.iface, self.channels, self.dwell)
            self.hopper.start()

    def close(self):
        if self.hopper:
            self.hopper.stop()
            self.hopper = None
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def status(self):
        return {
            'iface': self.iface,
            'hopping': bool(self.hopper),
            'current_channel': self.hopper.current if self.hopper else None,
            'channels': self.channels if self.hopper else [],
            'unusable_channels': sorted(self.hopper.bad) if self.hopper else [],
            'channel_method': self.hopper.method if self.hopper else None,
            'frames': self.frames,
            'error': self.error or (STUCK_MESSAGE % self.iface
                                    if self.hopper and self.hopper.stuck else None),
        }


def read_local_macs(sysfs='/sys/class/net'):
    """MAC addresses of this device's network interfaces, lower case."""
    out = set()
    try:
        names = os.listdir(sysfs)
    except OSError:
        return out
    for name in names:
        try:
            with open(os.path.join(sysfs, name, 'address'), encoding='utf-8') as fh:
                mac = fh.read().strip().lower()
        except (IOError, OSError):
            continue
        if len(mac) == 17 and mac not in ('00:00:00:00:00:00', 'ff:ff:ff:ff:ff:ff'):
            out.add(mac)
    return out


class Engine(object):

    def __init__(self, db_path, radios=None, track_clients=False, track_probes=False,
                 local_bssids=None, wids=True, my_networks_path=None, summary_path=None):
        self.db_path = db_path
        # The Pineapple's own access points (and every other local interface): never a
        # neighbour, never an intruder
        self.local_bssids = set(local_bssids) if local_bssids is not None else read_local_macs()
        self.radios = radios or []
        # Privacy by default: devices of third parties (MAC addresses) and the network
        # names they search for (probe requests) are only stored when enabled.
        self.track_clients = track_clients
        self.track_probes = track_probes

        self.conn = store.connect(db_path)
        self.agg = store.Aggregator(self.conn)
        self.running = False

        self.started_at = time.time()
        self.frames_total = 0
        self.frames_parsed = 0
        self.frames_window = 0
        self.window_start = time.time()
        self.fps = 0.0
        self.last_error = None
        self.frames_rejected = 0       # frames that made the decoder or aggregator fail
        self.db_errors = 0             # flushes lost to a database error (full, locked...)
        self.frames_over_budget = 0    # frames skipped by the per-second budget (a flood)
        self._budget_second = 0
        self._budget_used = 0
        self._errors_logged = {}       # error type -> count, to log each kind only a few times
        self.last_ts = None            # time of the last frame: the detector's clock (pcap replay too)
        self.last_status = {}
        self.my_networks_path = (my_networks_path
                                 or os.path.join(os.path.dirname(db_path) or '.', 'my_networks.json'))
        self.summary_path = summary_path  # None: no summary file (pcap replay, tests)

        # Intrusion detection: reads each 5 s window before it is written
        self.detector = None
        if wids:
            try:
                import detect
                self.detector = detect.Detector(
                    self.conn, self.my_networks_path, self.local_bssids, track_clients)
            except Exception as e:  # detection must never prevent listening
                self._log_once('detector', 'intrusion detection disabled: %s' % e)

    # -- frame handling ---------------------------------------------------

    def _log_once(self, kind, message):
        """Log a message at most three times per kind."""
        seen = self._errors_logged.get(kind, 0)
        self._errors_logged[kind] = seen + 1
        if seen < 3:
            print(message, file=sys.stderr, flush=True)

    def flush_window(self):
        """
        End of a 5 s window: the detector reads it, the aggregator writes it, then the
        detector writes its events. Each step has its own guard: detection never stops
        the capture, and a database error is counted, not fatal.
        """
        if self.detector is not None:
            try:
                self.detector.run(self.agg, self.last_ts or time.time())
            except Exception as e:
                self._log_once('detector', 'intrusion detection error: %s' % e)
        self.agg.flush()
        if self.detector is not None:
            try:
                self.detector.commit(self.conn)
            except Exception as e:
                self._log_once('detector', 'intrusion detection error: %s' % e)

    def handle(self, buf, ts):
        """Process one frame. Never raises: a malformed or hostile frame from anyone in
        radio range must not be able to stop the sensor."""
        self.frames_total += 1
        self.frames_window += 1
        self.last_ts = ts
        try:
            self._handle(buf, ts)
        except Exception as e:  # noqa: BLE001 - deliberate: the capture loop must survive
            self.frames_rejected += 1
            kind = type(e).__name__
            seen = self._errors_logged.get(kind, 0)
            self._errors_logged[kind] = seen + 1
            if seen < 3:
                print('Rejected a frame (%s: %s)' % (kind, str(e)[:120]), file=sys.stderr, flush=True)

    def within_budget(self, buf, ts):
        """The per-second frame budget (audit 4.1). Over the soft limit only management frames
        go through, over the hard limit nothing does. Reads two bytes, never raises."""
        second = int(ts)
        if second != self._budget_second:
            self._budget_second = second
            self._budget_used = 0
        self._budget_used += 1
        if self._budget_used <= FRAME_BUDGET_SOFT:
            return True
        if self._budget_used <= FRAME_BUDGET_HARD:
            try:
                hdr = buf[2] | (buf[3] << 8)        # radiotap length
                if (buf[hdr] >> 2) & 3 == 0:          # 802.11 management frame
                    return True
            except IndexError:
                pass
        self.frames_over_budget += 1
        return False

    def _lose(self, radio, error, now):
        """A radio stopped working (adapter unplugged, driver reset): close it and try again
        every RADIO_RETRY seconds, while the status says it is in error (audit 3.4)."""
        radio.close()
        radio.error = '%s stopped working (%s). Trying again every %d s.' % (
            radio.iface, error, RADIO_RETRY)
        radio.retry_at = now + RADIO_RETRY
        self._log_once('radio-' + radio.iface, radio.error)

    def _retry(self, radio, now):
        try:
            radio.open()
        except Exception as e:  # still gone: try later
            radio.close()
            radio.retry_at = now + RADIO_RETRY
            radio.error = '%s is not available (%s). Trying again every %d s.' % (
                radio.iface, e, RADIO_RETRY)
            return False
        radio.error = None
        radio.retry_at = None
        self._log_once('radio-' + radio.iface, '%s is back' % radio.iface)
        return True

    def _handle(self, buf, ts):
        try:
            f = dot11.parse_frame(buf, want_data=True)
        except (struct.error, IndexError, ValueError):
            return
        if f is None:
            return
        self.frames_parsed += 1

        if f.channel:
            self.agg.channel(f, ts, dot11.band_of(f.freq, f.channel))

        if f.ftype == dot11.TYPE_MGMT:
            st = f.subtype
            if st in (dot11.ST_BEACON, dot11.ST_PROBE_RESP):
                self.agg.ap(f, ts)
            elif st == dot11.ST_PROBE_REQ and self.track_probes:
                ssid = f.info.get('ssid')
                if ssid:  # skip wildcard probes
                    self.agg.probe(f.addr2, ssid, ts)
            elif st in (dot11.ST_DEAUTH, dot11.ST_DISASSOC):
                self.agg.disconnection(f, ts, keep_macs=self.track_clients)
        elif f.ftype == dot11.TYPE_DATA and self.track_clients:
            link = dot11.data_frame_link(f)
            if link:
                bssid, client = link
                rssi = f.rssi if (f.to_ds and not f.from_ds) else None
                self.agg.client(bssid, client, rssi, ts,
                                dot11.is_locally_administered(client))

    # -- status -----------------------------------------------------------

    def write_status(self, extra=None):
        now = time.time()
        elapsed = now - self.window_start
        if elapsed > 0:
            self.fps = self.frames_window / elapsed
        self.frames_window = 0
        self.window_start = now
        radios = [r.status() for r in self.radios]
        first = radios[0] if radios else {}
        status = {
            'running': self.running,
            'pid': os.getpid(),
            'started_at': self.started_at,
            'heartbeat': now,
            'frames_total': self.frames_total,
            'frames_parsed': self.frames_parsed,
            'frames_per_sec': round(self.fps, 1),
            'frames_rejected': self.frames_rejected,
            'dropped_by_limits': self.agg.dropped,
            'frames_over_budget': self.frames_over_budget,
            'healthy': self.running and not any(r.get('error') for r in radios),
            'db_errors': self.db_errors,
            'beacon_cache': dict(dot11.cache_stats),
            'wids': self.detector is not None,
            'detector_errors': self.detector.errors if self.detector is not None else 0,
            'local_bssids': sorted(self.local_bssids)[:64],
            'radios': radios,
            # Kept for compatibility with single-radio consumers
            'iface': first.get('iface'),
            'current_channel': first.get('current_channel'),
            'last_error': self.last_error,
        }
        if extra:
            status.update(extra)
        self.last_status = status
        with self.conn:
            store.set_meta(self.conn, {'engine': status})

    def write_summary(self):
        """The dashboard summary (summary.py). Never raises: it must not stop listening."""
        if not self.summary_path:
            return False
        try:
            import summary
            return summary.write(self.summary_path,
                                 summary.build(self.conn, self.last_status, self.my_networks_path))
        except Exception as e:
            self._log_once('summary', 'summary not written: %s' % e)
            return False

    # -- live capture -----------------------------------------------------

    def run_live(self):
        self.running = True
        opened = []
        errors = []
        for r in self.radios:
            try:
                r.open()
                opened.append(r)
            except Exception as e:  # one bad radio must not stop the other
                r.close()
                r.error = str(e)
                r.retry_at = time.time() + RADIO_RETRY
                errors.append(str(e))
        if not opened:
            self.last_error = ' ; '.join(errors) or 'No radio configured'
            self.running = False
            self.write_status()
            raise RuntimeError(self.last_error)
        self.last_error = ' ; '.join(errors) or None

        self.write_status()
        last_flush = time.time()
        last_retention = 0.0
        last_summary = 0.0
        try:
            while self.running:
                live = [r for r in self.radios if r.sock is not None]
                by_sock = dict((r.sock, r) for r in live)
                try:
                    ready, _, _ = select.select(list(by_sock), [], [], 1.0)
                except (OSError, ValueError, select.error):
                    if not self.running:
                        break
                    raise
                for s in ready:
                    radio = by_sock[s]
                    # Drain what is queued on this socket, bounded to stay fair
                    for _ in range(256):
                        try:
                            buf = s.recv(65535)
                        except (BlockingIOError, InterruptedError):
                            break
                        except OSError as e:
                            self._lose(radio, e, time.time())
                            break
                        radio.frames += 1
                        ts = time.time()
                        if self.within_budget(buf, ts):
                            self.handle(buf, ts)

                now = time.time()
                for radio in self.radios:
                    if radio.retry_at is not None and now >= radio.retry_at:
                        self._retry(radio, now)
                try:
                    if now - last_flush >= FLUSH_INTERVAL:
                        last_flush = now
                        self.flush_window()
                        if (self.last_error or '').startswith('Database error'):
                            self.last_error = None  # the database works again
                        self.write_status()
                    if now - last_retention >= RETENTION_INTERVAL:
                        last_retention = now
                        store.apply_retention(self.conn)
                    if now - last_summary >= SUMMARY_INTERVAL:
                        last_summary = now
                        self.write_summary()
                except sqlite3.Error as e:
                    # Database full, locked or damaged: drop this batch and keep listening
                    # rather than stop the probe; the next cycle tries again.
                    self.db_errors += 1
                    self.last_error = 'Database error: %s' % e
                    self.agg.reset()
                    if self.db_errors <= 3:
                        print('database error: %s' % e, file=sys.stderr)
        finally:
            for r in self.radios:
                r.close()
            self.flush_window()
            self.running = False
            self.write_status()
            self.write_summary()  # says the engine stopped

    # -- offline replay ---------------------------------------------------

    def run_pcap(self, path):
        self.running = True
        count = 0
        last_ts = None
        window_start = None
        for ts, buf in read_pcap(path):
            # Windows follow the capture's own clock, so a replay gives the same
            # detections as the live run did
            if window_start is None:
                window_start = ts
            elif ts - window_start >= FLUSH_INTERVAL or count % 5000 == 4999:
                self.flush_window()
                window_start = ts
            self.handle(buf, ts)
            count += 1
            last_ts = ts
        self.flush_window()
        self.running = False
        self.write_status({'replayed_file': os.path.basename(path), 'replayed_frames': count,
                           'replay_last_ts': last_ts})
        return count

    def stop(self, *_):
        self.running = False


# --------------------------------------------------------------------------
# pcap reader (classic libpcap format, radiotap or raw 802.11)
# --------------------------------------------------------------------------

LINKTYPE_IEEE802_11 = 105
LINKTYPE_RADIOTAP = 127
_FAKE_RADIOTAP = b'\x00\x00\x08\x00\x00\x00\x00\x00'


def read_pcap(path):
    with open(path, 'rb') as fh:
        header = fh.read(24)
        if len(header) < 24:
            raise ValueError('Invalid pcap file')
        magic = header[:4]
        if magic in (b'\xd4\xc3\xb2\xa1', b'\x4d\x3c\xb2\xa1'):
            endian = '<'
        elif magic in (b'\xa1\xb2\xc3\xd4', b'\xa1\xb2\x3c\x4d'):
            endian = '>'
        elif magic == b'\x0a\x0d\x0d\x0a':
            raise ValueError('pcapng is not supported, convert it with '
                             '"editcap -F pcap input.pcapng output.pcap"')
        else:
            raise ValueError('Invalid pcap file')
        nano = magic in (b'\x4d\x3c\xb2\xa1', b'\xa1\xb2\x3c\x4d')
        linktype = struct.unpack(endian + 'I', header[20:24])[0]
        if linktype not in (LINKTYPE_RADIOTAP, LINKTYPE_IEEE802_11):
            raise ValueError('Link type %d is not supported (radiotap or 802.11 required)' % linktype)
        divisor = 1e9 if nano else 1e6
        rec = struct.Struct(endian + 'IIII')
        while True:
            h = fh.read(16)
            if len(h) < 16:
                return
            sec, frac, incl, _ = rec.unpack(h)
            data = fh.read(incl)
            if len(data) < incl:
                return
            if linktype == LINKTYPE_IEEE802_11:
                data = _FAKE_RADIOTAP + data
            yield sec + frac / divisor, data


# --------------------------------------------------------------------------

def load_settings(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (IOError, ValueError):
        return {}


def radios_from_settings(settings):
    """
    settings['radios'] = [{'iface': 'wlan1mon', 'enabled': true,
                           'hopping': true, 'channels': [1, 6, 11]}, ...]
    Older settings with a single 'iface' are still understood.
    """
    dwell = float(settings.get('dwell_ms', 750)) / 1000.0
    radios = []
    entries = settings.get('radios')
    if not entries and settings.get('iface'):
        entries = [{'iface': settings['iface'], 'enabled': True,
                    'hopping': settings.get('channel_hopping', True),
                    'channels': settings.get('channels') or DEFAULT_CHANNELS}]
    seen = set()
    for e in entries or []:
        iface = (e.get('iface') or '').strip()
        if not iface or not e.get('enabled', True) or iface in seen:
            continue
        seen.add(iface)
        radios.append(Radio(iface, e.get('channels') or DEFAULT_CHANNELS,
                            e.get('hopping', True), dwell))
    return radios


def main():
    p = argparse.ArgumentParser(description='Sentinel capture engine')
    p.add_argument('--db', required=True)
    p.add_argument('--iface', help='single interface, overrides settings')
    p.add_argument('--pcap')
    p.add_argument('--settings', help='settings.json written by the module')
    p.add_argument('--no-hop', action='store_true')
    p.add_argument('--pidfile')
    p.add_argument('--summary', default='/tmp/sentinel-summary.json',
                   help='dashboard summary written every minute while listening live')
    args = p.parse_args()

    settings = load_settings(args.settings) if args.settings else {}
    if args.iface:
        settings['radios'] = [{'iface': args.iface, 'hopping': not args.no_hop,
                               'channels': DEFAULT_CHANNELS}]
    radios = radios_from_settings(settings)
    engine = Engine(args.db, radios=radios, track_clients=settings.get('track_clients', False),
                    track_probes=settings.get('track_probes', False),
                    wids=settings.get('wids_enabled', True) is not False,
                    my_networks_path=os.path.join(os.path.dirname(os.path.abspath(args.db)), 'my_networks.json'),
                    summary_path=None if args.pcap else args.summary)

    if args.pcap:
        n = engine.run_pcap(args.pcap)
        print('Replayed %d frames into %s' % (n, args.db))
        return 0

    if not radios:
        engine.last_error = 'No radio configured'
        engine.write_status()
        print('No interface configured', file=sys.stderr)
        return 2

    if args.pidfile:
        with open(args.pidfile, 'w', encoding='utf-8') as fh:
            fh.write(str(os.getpid()))

    signal.signal(signal.SIGTERM, engine.stop)
    signal.signal(signal.SIGINT, engine.stop)
    # Lower priority (audit 4.1): the Pineapple has one core, and its web interface and the
    # module's answers should not wait behind a burst of frames. Listening is unchanged.
    try:
        os.nice(NICENESS)
    except (OSError, AttributeError):
        pass
    try:
        engine.run_live()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1
    finally:
        if args.pidfile and os.path.exists(args.pidfile):
            os.unlink(args.pidfile)
    return 0


if __name__ == '__main__':
    sys.exit(main())
