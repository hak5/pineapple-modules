"""
Sentinel - storage layer.

Frames are aggregated in memory and written to SQLite in one transaction
every few seconds. This keeps CPU usage low and limits flash wear on the
Pineapple's eMMC.
"""

import json
import sqlite3
import time

import dot11

SCHEMA = """
CREATE TABLE IF NOT EXISTS aps (
    bssid TEXT PRIMARY KEY,
    ssid TEXT, hidden INTEGER DEFAULT 0,
    channel INTEGER, freq INTEGER, band TEXT,
    security TEXT, akm TEXT, pairwise TEXT, group_cipher TEXT,
    pmf TEXT, wps INTEGER DEFAULT 0, wpa1 INTEGER DEFAULT 0,
    ht INTEGER DEFAULT 0, vht INTEGER DEFAULT 0, he INTEGER DEFAULT 0,
    beacon_interval INTEGER, country TEXT, fingerprint TEXT,
    first_seen REAL, last_seen REAL,
    rssi_last INTEGER, rssi_min INTEGER, rssi_max INTEGER, rssi_avg REAL,
    beacons INTEGER DEFAULT 0, probe_resps INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ap_fingerprints (
    bssid TEXT, fingerprint TEXT, first_seen REAL, last_seen REAL, count INTEGER,
    PRIMARY KEY (bssid, fingerprint)
);
CREATE TABLE IF NOT EXISTS ap_channels (
    bssid TEXT, ssid TEXT, channel INTEGER, security TEXT,
    first_seen REAL, last_seen REAL, count INTEGER,
    PRIMARY KEY (bssid, ssid, channel, security)
);
CREATE TABLE IF NOT EXISTS clients (
    mac TEXT PRIMARY KEY, bssid TEXT, randomized INTEGER,
    first_seen REAL, last_seen REAL, rssi_last INTEGER, frames INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS probes (
    mac TEXT, ssid TEXT, first_seen REAL, last_seen REAL, count INTEGER,
    PRIMARY KEY (mac, ssid)
);
CREATE TABLE IF NOT EXISTS channel_stats (
    minute INTEGER, channel INTEGER, band TEXT,
    frames INTEGER, mgmt INTEGER, data INTEGER, ctrl INTEGER,
    rssi_sum INTEGER, rssi_n INTEGER,
    PRIMARY KEY (minute, channel)
);
CREATE TABLE IF NOT EXISTS disconnections (
    minute INTEGER, bssid TEXT, src TEXT, dst TEXT, subtype INTEGER, reason INTEGER,
    count INTEGER,
    PRIMARY KEY (minute, bssid, src, dst, subtype, reason)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL, source TEXT, kind TEXT, severity TEXT, title TEXT,
    details TEXT, bssid TEXT, acknowledged INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS idx_aps_ssid ON aps(ssid);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_chan_minute ON channel_stats(minute);
CREATE INDEX IF NOT EXISTS idx_disc_minute ON disconnections(minute);
"""


# Limits against a flood of forged frames (e.g. beacons with random BSSIDs): without them the
# database would grow until the flash is full. Past a limit, new entries are dropped and
# counted; what is already known keeps being updated.
BROADCAST = 'ff:ff:ff:ff:ff:ff'
MAX_APS = 5000                 # access points kept in the database
MAX_NEW_PER_FLUSH = 500        # new access points, clients, probes or deauth keys per flush
MAX_DB_BYTES = 64 * 1024 * 1024  # hard ceiling of the database file (SQLITE_FULL beyond)


MAX_CONFIGS_PER_AP = 8   # distinct configurations kept per access point in one window


def connect(path, readonly=False):
    if readonly:
        conn = sqlite3.connect('file:%s?mode=ro' % path, uri=True, timeout=5)
    else:
        conn = sqlite3.connect(path, timeout=10)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        page = conn.execute('PRAGMA page_size').fetchone()[0] or 4096
        conn.execute('PRAGMA max_page_count = %d' % (MAX_DB_BYTES // page))
        conn.executescript(SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def add_event(conn, source, kind, severity, title, details=None, bssid=None, ts=None,
              acknowledged=False):
    """The shared event bus: every tab writes its alerts here. `acknowledged`: written as
    already read (a muted alert type, see muted.py)."""
    conn.execute(
        'INSERT INTO events (ts, source, kind, severity, title, details, bssid, acknowledged) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (ts or time.time(), source, kind, severity, title,
         json.dumps(details) if details is not None else None, bssid, 1 if acknowledged else 0))


def set_meta(conn, values):
    conn.executemany('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)',
                     [(k, json.dumps(v)) for k, v in values.items()])


def get_meta(conn):
    out = {}
    for row in conn.execute('SELECT key, value FROM meta'):
        try:
            out[row['key']] = json.loads(row['value'])
        except ValueError:
            out[row['key']] = row['value']
    return out


class Aggregator(object):
    """Collects observations between two flushes."""

    def __init__(self, conn):
        self.conn = conn
        self.dropped = 0  # observations dropped by the limits above, since the start
        self.reset()

    def _room(self, table, key):
        """False (and counted) when a new key would exceed the per-flush limit."""
        if key in table or len(table) < MAX_NEW_PER_FLUSH:
            return True
        self.dropped += 1
        return False

    def reset(self):
        self.aps = {}
        self.fps = {}
        self.ap_chans = {}
        self.clients = {}
        self.probes = {}
        self.chan = {}
        self.disc = {}
        self.disc_broadcast = {}  # bssid -> deauth/disassoc frames sent to everyone

    # -- observations -----------------------------------------------------

    def ap(self, f, ts):
        info = f.info
        bssid = f.addr3
        if not self._room(self.aps, bssid):
            return
        a = self.aps.get(bssid)
        if a is None:
            a = self.aps[bssid] = {'beacons': 0, 'probe_resps': 0, 'rssi': [],
                                   'first': ts}
        if f.subtype == 8:
            a['beacons'] += 1
            # Beacons are authoritative, but one forged beacon must not rewrite the access
            # point's security: the window keeps the configuration announced most often.
            votes = a.setdefault('votes', {})
            key = (info.get('fingerprint'), info.get('security'), info.get('pmf'), bool(info.get('wps')))
            v = votes.get(key)
            if v is None:
                if len(votes) < MAX_CONFIGS_PER_AP:
                    votes[key] = [1, info]
            else:
                v[0] += 1
                v[1] = info
            a['info'] = max(votes.values(), key=lambda c: c[0])[1] if votes else info
        else:
            a['probe_resps'] += 1
            if info.get('ssid'):
                a['revealed'] = info['ssid']  # name of a hidden network
            if a['beacons'] == 0:
                a['info'] = info
        a['last'] = ts
        channel = f.ap_channel or f.channel
        if channel:
            a['channel'] = channel
            band = dot11.band_of(f.freq, channel)
            a['freq'] = dot11.channel_to_freq(channel, band) or f.freq
        if f.rssi is not None:
            a['rssi'].append(f.rssi)

        if info.get('fingerprint'):
            k = (bssid, info['fingerprint'])
            e = self.fps.get(k)
            if e is None:
                self.fps[k] = [ts, ts, 1]
            else:
                e[1] = ts
                e[2] += 1

        if info.get('ssid'):
            k = (bssid, info['ssid'], f.ap_channel or f.channel or 0, info['security'])
            e = self.ap_chans.get(k)
            if e is None:
                self.ap_chans[k] = [ts, ts, 1]
            else:
                e[1] = ts
                e[2] += 1

    def client(self, bssid, mac, rssi, ts, randomized):
        if not self._room(self.clients, mac):
            return
        c = self.clients.get(mac)
        if c is None:
            c = self.clients[mac] = {'first': ts, 'frames': 0, 'randomized': randomized}
        c['bssid'] = bssid
        c['last'] = ts
        c['frames'] += 1
        if rssi is not None:
            c['rssi'] = rssi

    def probe(self, mac, ssid, ts):
        k = (mac, ssid)
        if not self._room(self.probes, k):
            return
        e = self.probes.get(k)
        if e is None:
            self.probes[k] = [ts, ts, 1]
        else:
            e[1] = ts
            e[2] += 1

    def channel(self, f, ts, band):
        minute = int(ts // 60) * 60
        k = (minute, f.channel)
        c = self.chan.get(k)
        if c is None:
            c = self.chan[k] = [band, 0, 0, 0, 0, 0, 0]
        c[1] += 1
        c[2 + min(f.ftype, 2)] += 1  # mgmt / ctrl / data, see column order below
        if f.rssi is not None:
            c[5] += f.rssi
            c[6] += 1

    def disconnection(self, f, ts, keep_macs=False):
        """
        Deauthentication and disassociation frames, counted per access point. The source
        and destination addresses belong to devices: they are kept only when client
        tracking is on.
        """
        minute = int(ts // 60) * 60
        src, dst = (f.addr2, f.addr1) if keep_macs else ('', '')
        k = (minute, f.addr3, src, dst, f.subtype, f.info.get('reason', 0))
        if self._room(self.disc, k):
            self.disc[k] = self.disc.get(k, 0) + 1
        if f.addr1 == BROADCAST and self._room(self.disc_broadcast, f.addr3):
            self.disc_broadcast[f.addr3] = self.disc_broadcast.get(f.addr3, 0) + 1

    # -- flush ------------------------------------------------------------

    def _known_aps(self):
        """Drops the new access points that would take the table past MAX_APS."""
        c = self.conn
        room = MAX_APS - c.execute('SELECT COUNT(*) FROM aps').fetchone()[0]
        keep = {}
        for bssid, a in self.aps.items():
            if c.execute('SELECT 1 FROM aps WHERE bssid = ?', (bssid,)).fetchone():
                keep[bssid] = a
            elif room > 0:
                keep[bssid] = a
                room -= 1
            else:
                self.dropped += 1
        if len(keep) < len(self.aps):
            self.fps = dict((k, v) for k, v in self.fps.items() if k[0] in keep)
            self.ap_chans = dict((k, v) for k, v in self.ap_chans.items() if k[0] in keep)
        self.aps = keep

    def flush(self):
        c = self.conn
        self._known_aps()
        with c:
            for bssid, a in self.aps.items():
                info = a.get('info') or {}
                rs = a['rssi']
                rssi_last = rs[-1] if rs else None
                rssi_min = min(rs) if rs else None
                rssi_max = max(rs) if rs else None
                rssi_mean = (sum(rs) / float(len(rs))) if rs else None
                rsn = info.get('rsn') or {}
                wpa1 = info.get('wpa1') or {}
                akm = rsn.get('akm') or wpa1.get('akm') or []
                pairwise = rsn.get('pairwise') or wpa1.get('pairwise') or []
                group = rsn.get('group') or wpa1.get('group')
                hidden = bool(info.get('hidden')) and a['beacons'] > 0
                ssid = info.get('ssid')
                if not ssid and a.get('revealed'):
                    ssid = a['revealed']
                c.execute(
                    """INSERT INTO aps (bssid, ssid, hidden, channel, freq, band, security, akm,
                        pairwise, group_cipher, pmf, wps, wpa1, ht, vht, he, beacon_interval,
                        country, fingerprint, first_seen, last_seen, rssi_last, rssi_min,
                        rssi_max, rssi_avg, beacons, probe_resps)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(bssid) DO UPDATE SET
                        ssid = CASE WHEN COALESCE(excluded.ssid, '') = '' THEN aps.ssid
                                    ELSE excluded.ssid END,
                        hidden = CASE WHEN excluded.beacons > 0 THEN excluded.hidden
                                      ELSE aps.hidden END,
                        channel = COALESCE(excluded.channel, aps.channel),
                        freq = COALESCE(excluded.freq, aps.freq),
                        band = excluded.band, security = excluded.security,
                        akm = excluded.akm, pairwise = excluded.pairwise,
                        group_cipher = excluded.group_cipher, pmf = excluded.pmf,
                        wps = excluded.wps, wpa1 = excluded.wpa1, ht = excluded.ht,
                        vht = excluded.vht, he = excluded.he,
                        beacon_interval = excluded.beacon_interval,
                        country = COALESCE(excluded.country, aps.country),
                        fingerprint = COALESCE(excluded.fingerprint, aps.fingerprint),
                        last_seen = excluded.last_seen,
                        rssi_last = COALESCE(excluded.rssi_last, aps.rssi_last),
                        rssi_min = NULLIF(MIN(COALESCE(excluded.rssi_min, 127),
                                              COALESCE(aps.rssi_min, 127)), 127),
                        rssi_max = NULLIF(MAX(COALESCE(excluded.rssi_max, -128),
                                              COALESCE(aps.rssi_max, -128)), -128),
                        rssi_avg = CASE WHEN excluded.rssi_avg IS NULL THEN aps.rssi_avg
                                        WHEN aps.rssi_avg IS NULL THEN excluded.rssi_avg
                                        ELSE aps.rssi_avg * 0.7 + excluded.rssi_avg * 0.3 END,
                        beacons = aps.beacons + excluded.beacons,
                        probe_resps = aps.probe_resps + excluded.probe_resps
                    """,
                    (bssid, ssid, 1 if hidden else 0, a.get('channel'),
                     a.get('freq'), _band(a), info.get('security'), ','.join(akm),
                     ','.join(pairwise), group, info.get('pmf'), int(bool(info.get('wps'))),
                     int(bool(info.get('wpa1'))), int(bool(info.get('ht'))),
                     int(bool(info.get('vht'))), int(bool(info.get('he'))),
                     info.get('beacon_interval'), info.get('country'), info.get('fingerprint'),
                     a['first'], a['last'], rssi_last, rssi_min, rssi_max, rssi_mean,
                     a['beacons'], a['probe_resps']))

            c.executemany(
                """INSERT INTO ap_fingerprints VALUES (?,?,?,?,?)
                   ON CONFLICT(bssid, fingerprint) DO UPDATE SET
                   last_seen = excluded.last_seen, count = count + excluded.count""",
                [(k[0], k[1], v[0], v[1], v[2]) for k, v in self.fps.items()])

            c.executemany(
                """INSERT INTO ap_channels VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(bssid, ssid, channel, security) DO UPDATE SET
                   last_seen = excluded.last_seen, count = count + excluded.count""",
                [(k[0], k[1], k[2], k[3], v[0], v[1], v[2]) for k, v in self.ap_chans.items()])

            c.executemany(
                """INSERT INTO clients (mac, bssid, randomized, first_seen, last_seen, rssi_last, frames)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(mac) DO UPDATE SET bssid = excluded.bssid,
                   last_seen = excluded.last_seen,
                   rssi_last = COALESCE(excluded.rssi_last, clients.rssi_last),
                   frames = clients.frames + excluded.frames""",
                [(mac, v['bssid'], int(v['randomized']), v['first'], v['last'], v.get('rssi'),
                  v['frames']) for mac, v in self.clients.items()])

            c.executemany(
                """INSERT INTO probes VALUES (?,?,?,?,?)
                   ON CONFLICT(mac, ssid) DO UPDATE SET
                   last_seen = excluded.last_seen, count = count + excluded.count""",
                [(k[0], k[1], v[0], v[1], v[2]) for k, v in self.probes.items()])

            # channel_stats columns: band, frames, mgmt, ctrl, data, rssi_sum, rssi_n
            c.executemany(
                """INSERT INTO channel_stats (minute, channel, band, frames, mgmt, ctrl, data,
                       rssi_sum, rssi_n) VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(minute, channel) DO UPDATE SET
                   frames = frames + excluded.frames, mgmt = mgmt + excluded.mgmt,
                   ctrl = ctrl + excluded.ctrl, data = data + excluded.data,
                   rssi_sum = rssi_sum + excluded.rssi_sum, rssi_n = rssi_n + excluded.rssi_n""",
                [(k[0], k[1], v[0], v[1], v[2], v[3], v[4], v[5], v[6])
                 for k, v in self.chan.items()])

            c.executemany(
                """INSERT INTO disconnections VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(minute, bssid, src, dst, subtype, reason) DO UPDATE SET
                   count = count + excluded.count""",
                [k + (v,) for k, v in self.disc.items()])
        self.reset()


def _band(a):
    freq = a.get('freq') or 0
    ch = a.get('channel') or 0
    if freq:
        return '2.4' if freq < 3000 else ('5' if freq < 5925 else '6')
    if 1 <= ch <= 14:
        return '2.4'
    return '5' if ch else '?'


def apply_retention(conn, hours_stats=48, days_devices=30, max_events=5000, now=None):
    now = now or time.time()
    with conn:
        conn.execute('DELETE FROM channel_stats WHERE minute < ?', (now - hours_stats * 3600,))
        conn.execute('DELETE FROM disconnections WHERE minute < ?', (now - hours_stats * 3600,))
        cutoff = now - days_devices * 86400
        conn.execute('DELETE FROM aps WHERE last_seen < ?', (cutoff,))
        conn.execute('DELETE FROM clients WHERE last_seen < ?', (cutoff,))
        conn.execute('DELETE FROM probes WHERE last_seen < ?', (cutoff,))
        conn.execute('DELETE FROM ap_fingerprints WHERE last_seen < ?', (cutoff,))
        conn.execute('DELETE FROM ap_channels WHERE last_seen < ?', (cutoff,))
        conn.execute('DELETE FROM events WHERE id NOT IN '
                     '(SELECT id FROM events ORDER BY id DESC LIMIT ?)', (max_events,))
