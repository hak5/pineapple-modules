"""
Sentinel - passive intrusion detection (WIDS).

Every 5 seconds the engine hands the detector the window it has aggregated in
memory, BEFORE it is written and cleared. The detector only reads that window
and its own bounded state, and prepares events; `commit` then writes them in
one transaction. It never answers what it sees: no frame is ever sent.

Rules (constants below, no setting in the interface for this version):
  evil_twin        another BSSID announces the name of one of your networks
  my_ap_conflict   one of your BSSIDs announces two securities, or a known and an
                   unknown fingerprint, in the same window
  my_ap_downgrade  one of your BSSIDs announces a weaker security, or loses
                   required PMF, for two windows in a row
  my_ap_changed    one of your BSSIDs has a new fingerprint (often a router update)
  my_ap_channel    one of your BSSIDs is on a channel outside its reference for
                   three windows in a row
  deauth_flood     a burst of deauthentication/disassociation frames on a BSSID
  beacon_flood     a burst of never-seen BSSIDs (forged beacons)
  karma_ap         one BSSID answers for many different network names

Standard library only. `run` and `commit` never raise.
"""

import collections
import os

import dot11
import mynets
import store

WINDOW_S = 5.0                 # the engine's flush interval
HISTORY = 12                   # windows kept for the 60 s rules
MIN_FRAMES = 3                 # beacons + probe responses of a BSSID in a window
DEAUTH_WINDOW = 10             # deauth/disassoc frames in one window...
DEAUTH_MINUTE = 30             # ...or over 60 s
FLOOD_WINDOW = 30              # never-seen BSSIDs in one window...
FLOOD_MINUTE = 100             # ...or over 60 s
FLOOD_HOLD_S = 60.0            # how long new BSSIDs are kept out of the database
KARMA_SSIDS = 5                # distinct names announced by one BSSID over 60 s
DOWNGRADE_WINDOWS = 2
CHANNEL_WINDOWS = 3

MAX_KNOWN = 5000
MAX_TRACKED = 256              # BSSIDs followed by the 60 s histories
MAX_SSIDS_PER_BSSID = 16
MAX_COOLDOWN = 1024
EVENTS_PER_HOUR = 60           # all rules together...
PROTECTED_PER_HOUR = 20        # ...plus a reserve for attacks on your networks
PROTECTED = ('evil_twin', 'my_ap_conflict', 'my_ap_downgrade')

COOLDOWN_S = {
    'evil_twin': 3600, 'my_ap_conflict': 3600, 'my_ap_downgrade': 3600,
    'my_ap_changed': 6 * 3600, 'my_ap_channel': 6 * 3600,
    'deauth_flood': 600, 'beacon_flood': 600, 'karma_ap': 3600, 'suppressed': 0,
}

STRENGTH = {
    'Open': 0, 'WEP': 1,
    'WPA-PSK': 2, 'WPA-Enterprise': 2,
    'WPA/WPA2-PSK': 3, 'WPA/WPA2-Enterprise': 3,
    'WPA2-PSK': 4, 'WPA2-?': 4, 'OWE': 4,
    'WPA2-Enterprise': 5, 'WPA3-Transition': 5,
    'WPA3-SAE': 6, 'WPA3-Enterprise': 6,
}


def strength(security):
    return STRENGTH.get(security, 4)


def _title(text):
    return text if len(text) <= 120 else text[:119] + '…'


def _name(ssid):
    return dot11.clean_ssid(ssid or '') or '(hidden)'


class _Bounded(collections.OrderedDict):
    """A dict that forgets its oldest entry beyond `limit` (most recently set last)."""

    def __init__(self, limit):
        super(_Bounded, self).__init__()
        self.limit = limit

    def touch(self, key, value):
        if key in self:
            del self[key]
        self[key] = value
        while len(self) > self.limit:
            self.popitem(last=False)


class Detector(object):

    def __init__(self, conn, my_networks_path, local_bssids, track_clients):
        self.path = my_networks_path
        self.local = set(local_bssids or ())
        self.track_clients = track_clients
        self.pending = []
        self.errors = 0
        self.flood_until = 0.0

        self.known = _Bounded(MAX_KNOWN)
        self.disc_hist = _Bounded(MAX_TRACKED)     # bssid -> deque of window counts
        self.ssid_hist = _Bounded(MAX_TRACKED)     # bssid -> {ssid: last seen}
        self.new_hist = collections.deque(maxlen=HISTORY)
        self.cooldown = _Bounded(MAX_COOLDOWN)     # (kind, bssid) -> ts
        self.downgrade_streak = _Bounded(MAX_TRACKED)
        self.channel_streak = _Bounded(MAX_TRACKED)
        self.hour = None
        self.sent = {'normal': 0, 'protected': 0}
        self.suppressed_sent = False

        self.mine = {}
        self.mine_ssids = {}
        self._mine_mtime = None
        self._reload_mine()

        # What the database already knows, so a restart does not see everything as new
        # and does not replay the alerts of the last hours
        for (bssid,) in conn.execute('SELECT bssid FROM aps ORDER BY last_seen DESC LIMIT ?',
                                     (MAX_KNOWN,)).fetchall()[::-1]:
            self.known.touch(bssid, True)
        rows = conn.execute("SELECT kind, COALESCE(bssid, ''), MAX(ts) FROM events "
                            "WHERE source = 'wids' GROUP BY kind, bssid ORDER BY MAX(ts)").fetchall()
        for kind, bssid, ts in rows[-MAX_COOLDOWN:]:
            self.cooldown.touch((kind, bssid), ts)

    # -- my networks ------------------------------------------------------

    def _reload_mine(self):
        """Read my_networks.json again when its modification time changes."""
        try:
            mtime = os.stat(self.path).st_mtime if self.path else None
        except OSError:
            mtime = None
        if mtime == self._mine_mtime:
            return
        self._mine_mtime = mtime
        self.mine = mynets.load(self.path) if mtime is not None else {}
        by_ssid = {}
        for e in self.mine.values():
            name = dot11.clean_ssid(e.get('ssid') or '')
            if name:
                by_ssid.setdefault(name, []).append(e)
        self.mine_ssids = by_ssid

    # -- events -----------------------------------------------------------

    def _emit(self, now, kind, severity, bssid, title, details):
        key = (kind, bssid or '')
        last = self.cooldown.get(key)
        if last is not None and now - last < COOLDOWN_S[kind]:
            return False
        hour = int(now // 3600)
        if hour != self.hour:
            self.hour, self.sent, self.suppressed_sent = hour, {'normal': 0, 'protected': 0}, False
        bucket, cap = ('protected', PROTECTED_PER_HOUR) if kind in PROTECTED else ('normal', EVENTS_PER_HOUR)
        if self.sent[bucket] >= cap:
            if not self.suppressed_sent:
                self.suppressed_sent = True
                self.pending.append((now, 'suppressed', 'medium', None,
                                     'More alerts were suppressed', {'window_s': 3600}))
            return False
        self.sent[bucket] += 1
        self.cooldown.touch(key, now)
        self.pending.append((now, kind, severity, bssid, _title(title), details))
        return True

    # -- the rules --------------------------------------------------------

    def run(self, agg, now):
        """Read the current window of `agg` and prepare events. Never raises."""
        try:
            self._run(agg, now)
        except Exception:
            self.errors += 1

    def _run(self, agg, now):
        self._reload_mine()

        # What each BSSID announced in this window
        frames, ssids, securities = {}, {}, {}
        for bssid, a in agg.aps.items():
            frames[bssid] = a.get('beacons', 0) + a.get('probe_resps', 0)
            names = ssids.setdefault(bssid, set())
            info = a.get('info') or {}
            for s in (info.get('ssid'), a.get('revealed')):
                if s:
                    names.add(dot11.clean_ssid(s))
        for (bssid, ssid, _channel, security) in agg.ap_chans:
            ssids.setdefault(bssid, set()).add(dot11.clean_ssid(ssid))
            securities.setdefault(bssid, set()).add(security)
        fps = {}
        for (bssid, fp) in agg.fps:
            fps.setdefault(bssid, set()).add(fp)

        self._beacon_flood(agg, now)
        self._karma(now, frames, ssids)
        self._evil_twin(agg, now, frames, ssids)
        self._my_networks(agg, now, securities, fps)
        self._deauth(agg, now)

    def _beacon_flood(self, agg, now):
        new = [b for b in agg.aps if b not in self.known and b not in self.mine and b not in self.local]
        self.new_hist.append(len(new))
        total = sum(self.new_hist)
        if len(new) >= FLOOD_WINDOW or total >= FLOOD_MINUTE:
            self.flood_until = now + FLOOD_HOLD_S
            self._emit(now, 'beacon_flood', 'high', None,
                       'Burst of %d never-seen access points (forged beacons?)' % max(len(new), total),
                       {'count': max(len(new), total), 'window_s': WINDOW_S if len(new) >= FLOOD_WINDOW else 60})
        if now < self.flood_until:
            # Keep the flood out of the database (and out of `known`); known access
            # points and your networks are still recorded
            for b in new:
                agg.aps.pop(b, None)
            agg.fps = dict((k, v) for k, v in agg.fps.items() if k[0] in agg.aps)
            agg.ap_chans = dict((k, v) for k, v in agg.ap_chans.items() if k[0] in agg.aps)
        else:
            for b in new:
                self.known.touch(b, True)

    def _karma(self, now, frames, ssids):
        for bssid, names in ssids.items():
            if bssid in self.mine or bssid in self.local or not names:
                continue
            hist = self.ssid_hist.get(bssid) or {}
            for n in names:
                if n in hist or len(hist) < MAX_SSIDS_PER_BSSID:
                    hist[n] = now
            hist = dict((n, t) for n, t in hist.items() if now - t <= 60)
            self.ssid_hist.touch(bssid, hist)
            if len(hist) >= KARMA_SSIDS and frames.get(bssid, 0) >= MIN_FRAMES:
                shown = sorted(hist)[:8]
                self._emit(now, 'karma_ap', 'high', bssid,
                           'One access point answers for %d different network names' % len(hist),
                           {'count': len(hist), 'ssids': shown, 'window_s': 60})

    def _evil_twin(self, agg, now, frames, ssids):
        if not self.mine_ssids:
            return
        for bssid, names in ssids.items():
            if bssid in self.mine or bssid in self.local or frames.get(bssid, 0) < MIN_FRAMES:
                continue
            for name in names & set(self.mine_ssids):
                refs = self.mine_ssids[name]
                expected = max((e['baseline'].get('security') for e in refs), key=strength)
                info = (agg.aps.get(bssid) or {}).get('info') or {}
                observed = info.get('security')
                weaker = observed is not None and strength(observed) < strength(expected)
                a = agg.aps.get(bssid) or {}
                rs = a.get('rssi') or []
                self._emit(now, 'evil_twin', 'critical' if weaker else 'high', bssid,
                           'Another access point is using your network name "%s"' % name,
                           {'ssid': name, 'channel': a.get('channel'), 'rssi': rs[-1] if rs else None,
                            'expected': {'security': expected},
                            'observed': {'security': observed, 'channel': a.get('channel')}})

    def _my_networks(self, agg, now, securities, fps):
        for bssid, entry in self.mine.items():
            a = agg.aps.get(bssid)
            if a is None:
                continue
            base = entry['baseline']
            info = a.get('info') or {}
            name = _name(entry.get('ssid'))
            security, pmf, channel = info.get('security'), info.get('pmf'), a.get('channel')
            known_fps = set(base.get('fingerprints') or [])
            seen_fps = fps.get(bssid, set())
            expected = {'security': base.get('security'), 'pmf': base.get('pmf'),
                        'channels': base.get('channels')}

            conflict = len(securities.get(bssid, set())) > 1 or (
                bool(known_fps) and bool(seen_fps & known_fps) and bool(seen_fps - known_fps))
            if conflict:
                self._emit(now, 'my_ap_conflict', 'critical', bssid,
                           'Two different access points are announcing "%s" with the same address' % name,
                           {'ssid': name, 'expected': expected,
                            'observed': {'security': sorted(securities.get(bssid, set())) or security,
                                         'channel': channel, 'fingerprint': sorted(seen_fps)[:8]}})

            weaker = security is not None and strength(security) < strength(base.get('security'))
            lost_pmf = base.get('pmf') == 'required' and pmf is not None and pmf != 'required'
            if weaker or lost_pmf:
                streak = self.downgrade_streak.get(bssid, 0) + 1
                self.downgrade_streak.touch(bssid, streak)
                if streak >= DOWNGRADE_WINDOWS and not conflict:
                    self._emit(now, 'my_ap_downgrade', 'critical', bssid,
                               'Your access point "%s" is now announced as %s%s'
                               % (name, security, '' if not lost_pmf else ' without required PMF'),
                               {'ssid': name, 'expected': expected,
                                'observed': {'security': security, 'pmf': pmf, 'channel': channel}})
            else:
                self.downgrade_streak.touch(bssid, 0)

            if known_fps and (seen_fps - known_fps) and not conflict and not (weaker or lost_pmf):
                self._emit(now, 'my_ap_changed', 'medium', bssid,
                           'Your access point "%s" changed: accept its current settings if you updated it' % name,
                           {'ssid': name, 'expected': expected,
                            'observed': {'security': security, 'pmf': pmf, 'channel': channel,
                                         'fingerprint': sorted(seen_fps - known_fps)[0]}})

            channels = base.get('channels') or []
            if channels and channel and channel not in channels:
                streak = self.channel_streak.get(bssid, 0) + 1
                self.channel_streak.touch(bssid, streak)
                if streak >= CHANNEL_WINDOWS:
                    self._emit(now, 'my_ap_channel', 'info', bssid,
                               'Your access point "%s" moved to channel %d' % (name, channel),
                               {'ssid': name, 'channel': channel, 'expected': expected,
                                'observed': {'channel': channel}})
            elif channel:
                self.channel_streak.touch(bssid, 0)

    def _deauth(self, agg, now):
        counts, reasons = {}, {}
        for (_, bssid, _, _, _, reason), n in agg.disc.items():
            counts[bssid] = counts.get(bssid, 0) + n
            r = reasons.setdefault(bssid, {})
            r[str(reason)] = r.get(str(reason), 0) + n
        for bssid in set(counts) | set(self.disc_hist):
            hist = self.disc_hist.get(bssid) or collections.deque(maxlen=HISTORY)
            hist.append(counts.get(bssid, 0))
            if not any(hist):
                self.disc_hist.pop(bssid, None)
                continue
            self.disc_hist.touch(bssid, hist)
            if bssid in self.local:
                continue
            n, minute_total = counts.get(bssid, 0), sum(hist)
            if n >= DEAUTH_WINDOW or (n and minute_total >= DEAUTH_MINUTE):
                entry = self.mine.get(bssid)
                name = _name(entry['ssid']) if entry else None
                if name is None:
                    a = agg.aps.get(bssid) or {}
                    name = _name(((a.get('info') or {}).get('ssid')))
                # Only the BSSID and counts: no device address, whatever the settings
                self._emit(now, 'deauth_flood', 'high' if entry else 'medium', bssid,
                           'Burst of %d deauthentication frames on "%s"' % (max(n, minute_total), name),
                           {'ssid': name, 'count': max(n, minute_total),
                            'window_s': WINDOW_S if n >= DEAUTH_WINDOW else 60,
                            'reasons': dict(sorted(reasons.get(bssid, {}).items())[:16]),
                            'broadcast': agg.disc_broadcast.get(bssid, 0)})

    # -- writing ----------------------------------------------------------

    def commit(self, conn):
        """Write the prepared events in one transaction. Never raises."""
        if not self.pending:
            return
        pending, self.pending = self.pending, []
        try:
            with conn:
                for ts, kind, severity, bssid, title, details in pending:
                    store.add_event(conn, 'wids', kind, severity, title, details=details,
                                    bssid=bssid, ts=ts)
        except Exception:
            self.errors += 1
