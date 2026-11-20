"""
Sentinel - "My networks": the access points the user says are theirs.

The list lives in its own file (my_networks.json), not in the database, so that
"Clear collected data" keeps it. Each entry is one BSSID, never an SSID alone:
a network name can be copied with a single beacon. When a BSSID is marked, what
it announces (security, PMF, channel, fingerprints) is frozen as its reference;
the detector compares later observations to it.

Standard library only. Nothing here raises on a missing or damaged file.
"""

import json
import os
import re
import time

MAX_NETWORKS = 64
MAX_CHANNELS = 8
MAX_FINGERPRINTS = 8
MIN_BEACONS = 20        # no reference from a single, possibly forged, observation (audit 6.1)
MAX_SUGGESTIONS = 16
SUGGEST_WINDOW = 24 * 3600

BSSID_RE = re.compile(r'^[0-9a-f]{2}(:[0-9a-f]{2}){5}$')


def valid_bssid(value):
    """The BSSID in lower case, or None when it is not one."""
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if BSSID_RE.match(value) else None


def _clean_entry(e):
    """A well-formed entry, or None. Everything read from the file is checked."""
    if not isinstance(e, dict):
        return None
    bssid = valid_bssid(e.get('bssid'))
    base = e.get('baseline')
    if not bssid or not isinstance(base, dict):
        return None
    ssid = e.get('ssid') if isinstance(e.get('ssid'), str) else ''
    channels = [c for c in base.get('channels') or [] if isinstance(c, int) and 0 < c < 256]
    fps = [f for f in base.get('fingerprints') or [] if isinstance(f, str) and len(f) <= 64]
    added = e.get('added_at')
    return {
        'bssid': bssid,
        'ssid': ssid[:64],
        'added_at': float(added) if isinstance(added, (int, float)) else 0.0,
        'baseline': {
            'security': base.get('security') if isinstance(base.get('security'), str) else None,
            'pmf': base.get('pmf') if isinstance(base.get('pmf'), str) else None,
            'channels': channels[:MAX_CHANNELS],
            'fingerprints': fps[:MAX_FINGERPRINTS],
        },
    }


def load(path):
    """{bssid: entry}; {} when the file is absent, unreadable or malformed."""
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (IOError, OSError, ValueError):
        return {}
    if not isinstance(data, dict) or not isinstance(data.get('networks'), list):
        return {}
    out = {}
    for e in data['networks']:
        e = _clean_entry(e)
        if e and len(out) < MAX_NETWORKS:
            out[e['bssid']] = e
    return out


def save(path, entries):
    """Atomic write (temporary file, then rename); the folder is created root-only."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, mode=0o700, exist_ok=True)
    networks = sorted(entries.values(), key=lambda e: (e.get('ssid') or '', e['bssid']))
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump({'version': 1, 'networks': networks[:MAX_NETWORKS]}, fh, indent=2)
    os.rename(tmp, path)


def baseline_from_db(conn, bssid):
    """
    What `bssid` announces now, as a reference. None when the database does not know
    it, or has seen fewer than MIN_BEACONS of its beacons.
    """
    row = conn.execute('SELECT ssid, security, pmf, channel, beacons FROM aps WHERE bssid = ?',
                       (bssid,)).fetchone()
    if row is None or (row[4] or 0) < MIN_BEACONS:
        return None
    fps = [r[0] for r in conn.execute(
        'SELECT fingerprint FROM ap_fingerprints WHERE bssid = ? ORDER BY last_seen DESC LIMIT ?',
        (bssid, MAX_FINGERPRINTS))]
    return {
        'ssid': row[0] or '',
        'baseline': {
            'security': row[1],
            'pmf': row[2],
            'channels': [row[3]] if row[3] else [],
            'fingerprints': fps,
        },
    }


def make_entry(bssid, found, now=None):
    return {'bssid': bssid, 'ssid': found['ssid'], 'added_at': now or time.time(),
            'baseline': found['baseline']}


def ssids(entries):
    """The non-empty network names of the list."""
    return set(e['ssid'] for e in entries.values() if e.get('ssid'))


def same_device(a, b):
    """
    True when two BSSIDs look like two networks of the same access point. Vendors derive
    one address per network from the radio's base address: they keep its middle four
    bytes and the high digit of the last byte, and change the first byte (locally
    administered variants) and the last digit (band, network index). UniFi does that:
    0c:aa:bb:cc:dd:1e, 12:aa:bb:cc:dd:1e and 22:aa:bb:cc:dd:1f are one access point.
    """
    return a != b and a[3:14] == b[3:14] and a[15] == b[15]


def suggestions(conn, bssid, entries, now=None):
    """
    Other access points that probably belong to the user too, never ticked by default:

    * "same device": another network name of the same access point (see same_device),
      whatever its name and security;
    * "same vendor prefix" or "same fingerprint": the same network on another access
      point (same exact SSID and security, plus the first three bytes or a fingerprint
      in common).

    All were seen in the last 24 h with at least MIN_BEACONS beacons; already marked
    access points are left out.
    """
    now = now or time.time()
    ref = conn.execute('SELECT ssid, security FROM aps WHERE bssid = ?', (bssid,)).fetchone()
    if ref is None:
        return []
    out, seen = [], set()
    recent = (now - SUGGEST_WINDOW, MIN_BEACONS)

    # Other networks of the same access point
    for other, ssid, channel, band, rssi in conn.execute(
            'SELECT bssid, ssid, channel, band, rssi_last FROM aps WHERE last_seen >= ? AND beacons >= ? '
            'AND substr(bssid, 4, 11) = ? ORDER BY ssid, band LIMIT 64', recent + (bssid[3:14],)):
        if other in entries or not same_device(bssid, other):
            continue
        seen.add(other)
        out.append({'bssid': other, 'ssid': ssid, 'channel': channel, 'band': band,
                    'rssi': rssi, 'reason': 'same device'})

    # The same network on other access points
    if ref[0]:
        own_fps = set(r[0] for r in conn.execute(
            'SELECT fingerprint FROM ap_fingerprints WHERE bssid = ?', (bssid,)))
        rows = conn.execute(
            'SELECT bssid, ssid, channel, band, rssi_last FROM aps WHERE ssid = ? AND security IS ? '
            'AND bssid != ? AND last_seen >= ? AND beacons >= ? ORDER BY rssi_last DESC LIMIT 200',
            (ref[0], ref[1], bssid) + recent)
        for other, ssid, channel, band, rssi in rows:
            if other in entries or other in seen:
                continue
            if other[:8] == bssid[:8]:
                reason = 'same vendor prefix'
            else:
                theirs = set(r[0] for r in conn.execute(
                    'SELECT fingerprint FROM ap_fingerprints WHERE bssid = ?', (other,)))
                if not (own_fps & theirs):
                    continue
                reason = 'same fingerprint'
            out.append({'bssid': other, 'ssid': ssid, 'channel': channel, 'band': band,
                        'rssi': rssi, 'reason': reason})
    return out[:MAX_SUGGESTIONS]
