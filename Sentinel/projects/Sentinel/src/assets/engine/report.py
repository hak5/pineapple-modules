"""
Sentinel - the Reports tab: how your Wi-Fi did over a period.

`record_day` keeps one row per day in the `daily` table (written every hour by the engine,
so the last write of a day is that day's state); `build` puts the report together.
Standard library only.
"""

import time

import analysis
import mynets

SEVERITY_ORDER = ('critical', 'high', 'medium', 'low', 'info')
SERIOUS = ('critical', 'high')
TOP_ALERTS = 10

# What to change on the router, for each audit finding (analysis.audit_ap)
ADVICE = {
    'open': 'Turn on encryption: WPA2 or WPA3.',
    'wep': 'Replace WEP with WPA2 or WPA3. WEP can be broken in minutes.',
    'wpa1': 'Turn off WPA (version 1) and keep WPA2 and WPA3 only.',
    'tkip': 'Use AES (CCMP) only and turn off TKIP.',
    'no_pmf': 'Turn on Protected Management Frames (802.11w), at least as optional.',
    'pmf_optional': 'If all your devices support it, set Protected Management Frames to required.',
    'wpa3_transition': 'Once all your devices support WPA3, switch to WPA3 only.',
    'psk_offline': 'Use a long passphrase (12 random characters or more), or WPA3 if your devices support it.',
    'wps': 'Turn off WPS in the router settings.',
    'hidden': 'Hiding the name adds no security. You can show it again.',
}


def _day(ts):
    return time.strftime('%Y-%m-%d', time.localtime(ts))


def _day_start(ts):
    t = time.localtime(ts)
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def record_day(conn, my_networks_path, now=None):
    """Write (or update) today's row. Raises sqlite3.Error like any other write."""
    now = now or time.time()
    mine = mynets.load(my_networks_path) if my_networks_path else {}
    audit = analysis.security_audit(conn, max_age=3600, now=now, mine=set(mine))
    seen = sum(1 for n in audit['networks'] if n['mine'])
    worst = next((g for g in ('critical', 'high', 'medium', 'low', 'good')
                  if audit['my_summary'].get(g)), None)
    start = _day_start(now)
    alerts, serious = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(severity IN ('critical', 'high')), 0) FROM events "
        "WHERE source = 'wids' AND ts >= ? AND kind != 'suppressed'", (start,)).fetchone()
    deauth = conn.execute('SELECT COALESCE(SUM(count), 0) FROM disconnections WHERE minute >= ?',
                          (start,)).fetchone()[0]
    with conn:
        conn.execute(
            'INSERT OR REPLACE INTO daily (day, ts, my_score, my_marked, my_seen, my_worst, '
            'area_score, area_networks, alerts, alerts_serious, deauth) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (_day(now), now, audit['my_score'], len(mine), seen, worst, audit['score'],
             audit['total'], alerts, serious, deauth))


def _trend(conn, since, until):
    """Rows in [since, until]: a row from the future (the clock was ahead) is left out."""
    try:
        rows = conn.execute(
            'SELECT day, my_score, area_score, alerts, alerts_serious FROM daily '
            'WHERE ts >= ? AND ts <= ? ORDER BY day', (since, until)).fetchall()
    except Exception:  # a database from before 0.8.4 has no daily table yet
        return []
    return [{'day': r[0], 'my_score': r[1], 'area_score': r[2], 'alerts': r[3],
             'alerts_serious': r[4]} for r in rows]


def build(conn, my_networks_path, days=7, now=None):
    """The report for the last `days` days (1, 7 or 30)."""
    now = now or time.time()
    since = now - days * 86400
    mine = mynets.load(my_networks_path) if my_networks_path else {}
    audit = analysis.security_audit(conn, max_age=days * 86400, now=now, mine=set(mine))

    networks = []
    for n in audit['networks']:
        if not n['mine']:
            continue
        findings = [{'code': f['code'], 'severity': f['severity'], 'title': f['title'],
                     'detail': f['detail'], 'advice': ADVICE.get(f['code'])}
                    for f in n['findings'] if f['code'] not in ('good', 'ok')]
        networks.append({'bssid': n['bssid'], 'ssid': n['ssid'], 'hidden': n['hidden'],
                         'security': n['security'], 'pmf': n['pmf'], 'wps': n['wps'],
                         'channel': n['channel'], 'band': n['band'], 'grade': n['grade'],
                         'last_seen': n['last_seen'], 'findings': findings})
    seen = set(n['bssid'] for n in networks)
    not_seen = [{'bssid': b, 'ssid': e.get('ssid') or ''} for b, e in sorted(mine.items())
                if b not in seen]
    # The changes to make, once each, the most serious first
    todo = {}
    for n in networks:
        for f in n['findings']:
            if f['advice']:
                t = todo.setdefault(f['code'], {'advice': f['advice'], 'severity': f['severity'],
                                                'networks': []})
                label = n['ssid'] or n['bssid']
                if label not in t['networks']:
                    t['networks'].append(label)
    todo = sorted(todo.values(), key=lambda t: SEVERITY_ORDER.index(t['severity']))

    by_severity = dict((s, 0) for s in SEVERITY_ORDER)
    by_kind = {}
    for kind, severity, count in conn.execute(
            "SELECT kind, severity, COUNT(*) FROM events WHERE source = 'wids' AND ts >= ? "
            "AND kind != 'suppressed' GROUP BY kind, severity", (since,)):
        if severity in by_severity:
            by_severity[severity] += count
        by_kind[kind] = by_kind.get(kind, 0) + count
    top = [{'ts': r[0], 'severity': r[1], 'kind': r[2], 'title': r[3], 'acknowledged': bool(r[4])}
           for r in conn.execute(
               "SELECT ts, severity, kind, title, acknowledged FROM events "
               "WHERE source = 'wids' AND ts >= ? AND kind != 'suppressed' ORDER BY "
               "CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 "
               "WHEN 'low' THEN 3 ELSE 4 END, ts DESC LIMIT ?", (since, TOP_ALERTS))]

    # Deauthentication statistics are kept 48 hours
    deauth_hours = min(days * 24, 48)
    deauth = conn.execute('SELECT COALESCE(SUM(count), 0) FROM disconnections WHERE minute >= ?',
                          (now - deauth_hours * 3600,)).fetchone()[0]
    channels = analysis.channels_report(conn, window_minutes=60, now=now)

    worst = next((g for g in ('critical', 'high', 'medium', 'low', 'good')
                  if audit['my_summary'].get(g)), None)
    return {
        'generated_at': now,
        'days': days,
        'since': since,
        'mine': {'score': audit['my_score'], 'marked': len(mine), 'seen': len(networks),
                 'worst': worst, 'networks': networks, 'not_seen': not_seen, 'todo': todo},
        'area': {'score': audit['score'], 'total': audit['total'], 'summary': audit['summary']},
        'alerts': {'total': sum(by_severity.values()), 'by_severity': by_severity,
                   'by_kind': by_kind, 'top': top},
        'deauth': {'count': deauth, 'hours': deauth_hours},
        'channels': {'best': channels.get('recommendation', {}),
                     'yours': sorted(set((n['band'], n['channel']) for n in networks
                                         if n['channel']))},
        'trend': _trend(conn, now - (days + 1) * 86400, now + 3600),
    }
