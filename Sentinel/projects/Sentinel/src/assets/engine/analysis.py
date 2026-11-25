"""
Sentinel - read-side analysis used by the module backend.

Everything here works on the SQLite database written by the engine, so it can
be called from an API request without touching the capture loop.
"""

import time

CHANNELS_24 = list(range(1, 14))
CANDIDATES_24 = [1, 6, 11]
CANDIDATES_5 = [36, 40, 44, 48, 149, 153, 157, 161, 165]

SEVERITY_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4, 'good': 5}


def _rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params)]


def _signal_weight(rssi):
    """-40 dBm (very close) -> 1.0, -95 dBm (barely heard) -> ~0.05"""
    if rssi is None:
        return 0.3
    return max(0.05, min(1.0, (rssi + 100) / 60.0))


# --------------------------------------------------------------------------
# Access points
# --------------------------------------------------------------------------

MAX_LISTED_APS = 1000  # strongest first; the table itself holds at most store.MAX_APS


def list_aps(conn, max_age=3600, now=None, limit=MAX_LISTED_APS):
    now = now or time.time()
    return _rows(conn,
                 'SELECT * FROM aps WHERE last_seen >= ? ORDER BY rssi_last DESC LIMIT ?',
                 (now - max_age, limit))


# --------------------------------------------------------------------------
# Channel analyzer
# --------------------------------------------------------------------------

def channels_report(conn, window_minutes=10, now=None):
    now = now or time.time()
    since = now - window_minutes * 60

    stats = {}
    for r in conn.execute(
            'SELECT channel, band, SUM(frames) AS frames, SUM(mgmt) AS mgmt, SUM(data) AS data, '
            'SUM(ctrl) AS ctrl, SUM(rssi_sum) AS rssi_sum, SUM(rssi_n) AS rssi_n '
            'FROM channel_stats WHERE minute >= ? GROUP BY channel', (since - 60,)):
        stats[r['channel']] = {
            'channel': r['channel'], 'band': r['band'], 'frames': r['frames'] or 0,
            'mgmt': r['mgmt'] or 0, 'data': r['data'] or 0, 'ctrl': r['ctrl'] or 0,
            'avg_rssi': round(r['rssi_sum'] / float(r['rssi_n']), 1) if r['rssi_n'] else None,
            'aps': 0, 'strongest_rssi': None, 'ssids': [],
        }

    aps = _rows(conn, 'SELECT bssid, ssid, channel, band, rssi_last FROM aps '
                      'WHERE last_seen >= ? AND channel > 0', (since,))
    for ap in aps:
        ch = ap['channel']
        s = stats.get(ch)
        if s is None:
            s = stats[ch] = {'channel': ch, 'band': ap['band'], 'frames': 0, 'mgmt': 0,
                             'data': 0, 'ctrl': 0, 'avg_rssi': None, 'aps': 0,
                             'strongest_rssi': None, 'ssids': []}
        s['aps'] += 1
        if ap['rssi_last'] is not None and (s['strongest_rssi'] is None
                                            or ap['rssi_last'] > s['strongest_rssi']):
            s['strongest_rssi'] = ap['rssi_last']
        if ap['ssid'] and ap['ssid'] not in s['ssids'] and len(s['ssids']) < 8:
            s['ssids'].append(ap['ssid'])

    max_frames = max([s['frames'] for s in stats.values()] or [0]) or 1
    for s in stats.values():
        s['utilization'] = round(100.0 * s['frames'] / max_frames)

    channels = sorted(stats.values(), key=lambda s: (s['band'] != '2.4', s['channel']))

    rec_24 = _recommend(aps, stats, max_frames, '2.4')
    rec_5 = _recommend(aps, stats, max_frames, '5')

    return {
        'window_minutes': window_minutes,
        'generated_at': now,
        'channels': channels,
        'recommendation': {'2.4': rec_24, '5': rec_5},
    }


def _overlap_24(a, b):
    """Spectral overlap between two 20 MHz channels in 2.4 GHz (0..1)."""
    d = abs(a - b)
    return max(0.0, 1.0 - d / 5.0)


def _recommend(aps, stats, max_frames, band):
    candidates = CANDIDATES_24 if band == '2.4' else CANDIDATES_5
    scores = []
    for cand in candidates:
        interference = 0.0
        busy = 0.0
        for ap in aps:
            if ap['band'] != band:
                continue
            ov = _overlap_24(cand, ap['channel']) if band == '2.4' else (
                1.0 if ap['channel'] == cand else 0.0)
            if ov:
                interference += ov * _signal_weight(ap['rssi_last'])
        for ch, s in stats.items():
            if s['band'] != band:
                continue
            ov = _overlap_24(cand, ch) if band == '2.4' else (1.0 if ch == cand else 0.0)
            if ov:
                busy += ov * s['frames'] / float(max_frames)
        score = interference + 2.0 * busy
        scores.append({'channel': cand, 'score': round(score, 2),
                       'interference': round(interference, 2), 'busy': round(busy, 2)})
    if not any(s['band'] == band for s in stats.values()):
        return {'best': None, 'scores': scores, 'observed': False}
    scores.sort(key=lambda s: s['score'])
    return {'best': scores[0]['channel'], 'scores': scores, 'observed': True}


# --------------------------------------------------------------------------
# WPA3 / PMF security auditor
# --------------------------------------------------------------------------

def _finding(code, severity, title, detail):
    return {'code': code, 'severity': severity, 'title': title, 'detail': detail}


def audit_ap(ap):
    findings = []
    sec = ap.get('security') or '?'
    pmf = ap.get('pmf') or 'none'
    pairwise = (ap.get('pairwise') or '').split(',')
    group = ap.get('group_cipher') or ''

    if sec == 'Open':
        findings.append(_finding(
            'open', 'critical', 'Open network',
            'No encryption: all traffic travels in clear text and anyone can impersonate '
            'this network. Switch to WPA3, or at least to OWE (Enhanced Open).'))
    elif sec == 'WEP':
        findings.append(_finding(
            'wep', 'critical', 'WEP',
            'WEP can be cracked in minutes. This network needs to be migrated urgently.'))
    else:
        if ap.get('wpa1') or sec.startswith('WPA-') or sec.startswith('WPA/'):
            findings.append(_finding(
                'wpa1', 'high', 'WPA1 still enabled',
                'WPA1 is obsolete. Disable it and keep only WPA2/WPA3.'))
        if 'TKIP' in pairwise or group == 'TKIP':
            findings.append(_finding(
                'tkip', 'high', 'TKIP encryption',
                'TKIP is deprecated and vulnerable. Use AES-CCMP only.'))

        if sec not in ('OWE',) and pmf == 'none':
            findings.append(_finding(
                'no_pmf', 'medium', 'PMF disabled (802.11w)',
                'Without Protected Management Frames, clients can be kicked off with forged '
                'deauthentication frames, the first step of most evil twin and handshake '
                'capture attacks.'))
        elif pmf == 'capable' and sec.startswith('WPA2'):
            findings.append(_finding(
                'pmf_optional', 'low', 'PMF optional',
                'PMF is offered but not required, so older clients can still be deauthenticated. '
                'Require it if all your devices support it.'))

        if sec == 'WPA3-Transition':
            findings.append(_finding(
                'wpa3_transition', 'low', 'WPA2/WPA3 transition mode',
                'Convenient for compatibility, but an attacker can force clients down to WPA2. '
                'Switch to WPA3-only when you can.'))

        if sec in ('WPA2-PSK', 'WPA/WPA2-PSK'):
            findings.append(_finding(
                'psk_offline', 'medium', 'WPA2-Personal (PSK)',
                'A captured handshake allows an offline attack on the password. '
                'Use a long random passphrase, or switch to WPA3-SAE.'))

    if ap.get('wps'):
        findings.append(_finding(
            'wps', 'medium', 'WPS enabled',
            'WPS is vulnerable to PIN brute force and Pixie Dust on many routers. '
            'Turn it off.'))

    if ap.get('hidden'):
        findings.append(_finding(
            'hidden', 'info', 'Hidden SSID',
            'Hiding the SSID adds no security: clients reveal it in their probe requests '
            'wherever they go.'))

    if not findings or all(f['severity'] == 'info' for f in findings):
        if sec in ('WPA3-SAE', 'WPA3-Enterprise', 'OWE') or (
                sec == 'WPA2-Enterprise' and pmf == 'required'):
            findings.append(_finding('good', 'good', 'Good configuration',
                                     'Modern encryption and protected management frames.'))
        else:
            findings.append(_finding('ok', 'low', 'Acceptable',
                                     'No major weakness found.'))

    findings.sort(key=lambda f: SEVERITY_ORDER[f['severity']])
    worst = findings[0]['severity'] if findings[0]['severity'] != 'info' else (
        findings[1]['severity'] if len(findings) > 1 else 'info')
    return worst, findings


# An access point seen only once in the hour is not audited (unless it is yours): a single
# forged beacon must not change the neighbourhood's score.
MIN_FRAMES_TO_AUDIT = 2


def _conflicting(conn, since):
    """BSSIDs that announced two or more configurations (fingerprint or security), each at
    least twice, since `since`."""
    out = set(r[0] for r in conn.execute(
        'SELECT bssid FROM ap_fingerprints WHERE last_seen >= ? AND count >= 2 '
        'GROUP BY bssid HAVING COUNT(*) >= 2', (since,)))
    out.update(r[0] for r in conn.execute(
        'SELECT bssid FROM ap_channels WHERE last_seen >= ? AND count >= 2 '
        'GROUP BY bssid HAVING COUNT(DISTINCT security) >= 2', (since,)))
    return out


def _score(summary, total):
    healthy = summary['good'] + summary['low']
    return round(100.0 * healthy / total) if total else None


def security_audit(conn, max_age=3600, now=None, mine=None):
    """
    `mine`: the BSSIDs the user marked as theirs. They get `mine: True`, come first,
    and have their own score (`my_score`); `score` stays the whole neighbourhood's.
    """
    mine = mine or set()
    aps = list_aps(conn, max_age=max_age, now=now)
    networks = []
    summary = {k: 0 for k in SEVERITY_ORDER}
    my_summary = {k: 0 for k in SEVERITY_ORDER}
    pmf_counts = {'required': 0, 'capable': 0, 'none': 0}
    sec_counts = {}
    since = (now or time.time()) - max_age
    conflicting = _conflicting(conn, since)
    for ap in aps:
        if ap['bssid'] not in mine and (ap.get('beacons') or 0) + (ap.get('probe_resps') or 0) < MIN_FRAMES_TO_AUDIT:
            continue
        worst, findings = audit_ap(ap)
        if ap['bssid'] in conflicting:
            findings.append(_finding(
                'conflicting', 'info', 'Two different configurations',
                'This address announced two different configurations in this period. Usually a '
                'settings change or a firmware update, but it can also be someone imitating it.'))
        summary[worst] += 1
        is_mine = ap['bssid'] in mine
        if is_mine:
            my_summary[worst] += 1
        pmf_counts[ap.get('pmf') or 'none'] = pmf_counts.get(ap.get('pmf') or 'none', 0) + 1
        sec = ap.get('security') or '?'
        sec_counts[sec] = sec_counts.get(sec, 0) + 1
        networks.append({
            'bssid': ap['bssid'], 'ssid': ap['ssid'], 'hidden': bool(ap['hidden']),
            'channel': ap['channel'], 'band': ap['band'], 'security': sec,
            'akm': ap['akm'], 'pairwise': ap['pairwise'], 'group_cipher': ap['group_cipher'],
            'pmf': ap['pmf'], 'wps': bool(ap['wps']), 'rssi': ap['rssi_last'],
            'last_seen': ap['last_seen'], 'grade': worst, 'findings': findings,
            'mine': is_mine,
        })
    networks.sort(key=lambda n: (not n['mine'], SEVERITY_ORDER[n['grade']], -(n['rssi'] or -100)))
    total = len(networks)
    my_total = sum(1 for n in networks if n['mine'])
    return {
        'generated_at': now or time.time(),
        'total': total,
        'score': _score(summary, total),
        'summary': summary,
        'my_total': my_total,
        'my_score': _score(my_summary, my_total),
        'my_summary': my_summary,
        'pmf': pmf_counts,
        'security_types': sec_counts,
        'networks': networks,
    }


# --------------------------------------------------------------------------
# Spectrum view: every AP as a signal arc, coloured by its security grade
# --------------------------------------------------------------------------

def spectrum(conn, max_age=600, now=None, mine=None):
    mine = mine or set()
    out = []
    for ap in list_aps(conn, max_age=max_age, now=now):
        if not ap.get('channel'):
            continue
        grade, _ = audit_ap(ap)
        out.append({
            'bssid': ap['bssid'], 'ssid': ap['ssid'], 'hidden': bool(ap['hidden']),
            'channel': ap['channel'], 'band': ap['band'], 'rssi': ap['rssi_last'],
            'security': ap['security'], 'grade': grade, 'last_seen': ap['last_seen'],
            'mine': ap['bssid'] in mine,
        })
    return out


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------

def dashboard(conn, now=None):
    now = now or time.time()
    hour = now - 3600
    one = lambda sql, p=(): conn.execute(sql, p).fetchone()[0]  # noqa: E731
    return {
        'aps_last_hour': one('SELECT COUNT(*) FROM aps WHERE last_seen >= ?', (hour,)),
        'aps_total': one('SELECT COUNT(*) FROM aps'),
        'ssids_last_hour': one('SELECT COUNT(DISTINCT ssid) FROM aps WHERE last_seen >= ? '
                               "AND ssid != ''", (hour,)),
        'clients_last_hour': one('SELECT COUNT(*) FROM clients WHERE last_seen >= ?', (hour,)),
        'probing_devices_last_hour': one('SELECT COUNT(DISTINCT mac) FROM probes '
                                         'WHERE last_seen >= ?', (hour,)),
        'disconnections_last_hour': one('SELECT COALESCE(SUM(count), 0) FROM disconnections '
                                        'WHERE minute >= ?', (hour - 60,)),
        'events_unacknowledged': one("SELECT COUNT(*) FROM events WHERE acknowledged = 0 "
                                     "AND source = 'wids'"),
    }


def recent_events(conn, limit=50, source=None):
    if source:
        rows = _rows(conn, 'SELECT * FROM events WHERE source = ? ORDER BY id DESC LIMIT ?',
                     (source, limit))
    else:
        rows = _rows(conn, 'SELECT * FROM events ORDER BY id DESC LIMIT ?', (limit,))
    return rows
