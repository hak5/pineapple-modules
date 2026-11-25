"""
Sentinel - a small summary for dashboards.

Once a minute the engine writes /tmp/sentinel-summary.json (about 1 KB), from the
database it already has open. A dashboard reads that file (for example through an
SSH key restricted to `cat /tmp/sentinel-summary.json`) instead of starting Python
on the Pineapple at every poll, which costs about 3 s of CPU on the Mark VII.

Standard library only. `write` never raises.
"""

import json
import os
import time

import analysis
import mynets

FORMAT = 1
RECENT_ALERTS = 5
SEVERITIES = ('critical', 'high', 'medium', 'low', 'info')


def build(conn, status, my_networks_path, now=None):
    """The summary as a dict. `status` is the engine status (Engine.status_dict)."""
    now = now or time.time()
    mine = mynets.load(my_networks_path) if my_networks_path else {}
    audit = analysis.security_audit(conn, max_age=3600, now=now, mine=set(mine))
    seen = set(n['bssid'] for n in audit['networks'] if n['mine'])
    missing = [{'bssid': b, 'ssid': e.get('ssid') or ''} for b, e in sorted(mine.items()) if b not in seen]

    unread = dict((s, 0) for s in SEVERITIES)
    for severity, count in conn.execute(
            "SELECT severity, COUNT(*) FROM events WHERE source = 'wids' AND acknowledged = 0 "
            "GROUP BY severity"):
        if severity in unread:
            unread[severity] = count
    recent = [{'ts': r[0], 'severity': r[1], 'kind': r[2], 'title': r[3], 'bssid': r[4]}
              for r in conn.execute("SELECT ts, severity, kind, title, bssid FROM events "
                                    "WHERE source = 'wids' ORDER BY id DESC LIMIT ?", (RECENT_ALERTS,))]
    # Rules still in observation (detect.PMKID_MODE): what they would have reported, last 7 days
    observed = dict((kind, count) for kind, count in conn.execute(
        "SELECT kind, COUNT(*) FROM events WHERE source = 'observe' AND ts >= ? GROUP BY kind",
        (now - 7 * 86400,)))
    deauth = conn.execute('SELECT COALESCE(SUM(count), 0) FROM disconnections WHERE minute >= ?',
                          (now - 3660,)).fetchone()[0]
    my_summary = audit['my_summary']
    worst = next((g for g in ('critical', 'high', 'medium', 'low', 'good') if my_summary.get(g)), None)

    return {
        'format': FORMAT,
        'generated_at': now,               # the Pineapple's clock, so a reader can see any drift
        'listening': bool(status.get('running')),
        'frames_per_sec': status.get('frames_per_sec'),
        'radios': [{'iface': r.get('iface'), 'channel': r.get('current_channel'),
                    'error': r.get('error')} for r in status.get('radios') or []],
        'last_error': status.get('last_error'),
        'my_networks': {
            'marked': len(mine),
            'seen_last_hour': len(seen),
            'score': audit['my_score'],
            'worst': worst,
            'not_seen': missing[:16],
        },
        'neighbourhood': {'networks': audit['total'], 'score': audit['score']},
        'alerts': {'unread': unread, 'unread_total': sum(unread.values()), 'recent': recent},
        'deauth_last_hour': deauth,
        'observed_7d': observed,
    }


def write(path, data):
    """Atomic write, readable by root only (it holds network names). Never raises."""
    try:
        tmp = path + '.tmp'
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as fh:
            json.dump(data, fh, separators=(',', ':'))
        os.rename(tmp, path)
        return True
    except (IOError, OSError, TypeError, ValueError):
        return False
