"""
Sentinel - lightweight 802.11 / radiotap parser.

Pure standard library, written for the WiFi Pineapple Mark VII (Python 3.7+,
MIPS CPU). The parser only decodes what the defensive suite needs and bails
out early on everything else, so it stays cheap on busy channels.
"""

import hashlib
import struct
import unicodedata

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

TYPE_MGMT = 0
TYPE_CTRL = 1
TYPE_DATA = 2

ST_ASSOC_REQ = 0
ST_ASSOC_RESP = 1
ST_REASSOC_REQ = 2
ST_PROBE_REQ = 4
ST_PROBE_RESP = 5
ST_BEACON = 8
ST_DISASSOC = 10
ST_AUTH = 11
ST_DEAUTH = 12
ST_ACTION = 13

BROADCAST = 'ff:ff:ff:ff:ff:ff'

# RSN suite selectors (OUI 00-0F-AC)
CIPHERS = {
    0: 'GROUP', 1: 'WEP40', 2: 'TKIP', 4: 'CCMP', 5: 'WEP104',
    6: 'BIP-CMAC', 8: 'GCMP', 9: 'GCMP-256', 10: 'CCMP-256',
    11: 'BIP-GMAC', 12: 'BIP-GMAC-256', 13: 'BIP-CMAC-256',
}

AKMS = {
    1: '802.1X', 2: 'PSK', 3: 'FT-802.1X', 4: 'FT-PSK',
    5: '802.1X-SHA256', 6: 'PSK-SHA256', 8: 'SAE', 9: 'FT-SAE',
    11: '802.1X-SuiteB', 12: '802.1X-SuiteB-192', 13: 'FT-802.1X-SHA384',
    18: 'OWE', 24: 'SAE-EXT-KEY', 25: 'FT-SAE-EXT-KEY',
}

ENTERPRISE_AKMS = {'802.1X', 'FT-802.1X', '802.1X-SHA256', '802.1X-SuiteB',
                   '802.1X-SuiteB-192', 'FT-802.1X-SHA384'}
SAE_AKMS = {'SAE', 'FT-SAE', 'SAE-EXT-KEY', 'FT-SAE-EXT-KEY'}
PSK_AKMS = {'PSK', 'FT-PSK', 'PSK-SHA256'}

# Radiotap fields we may walk over: bit -> (alignment, size)
# Only fields up to bit 5 (dBm antenna signal) matter to us.
_RT_FIELDS = {
    0: (8, 8),   # TSFT
    1: (1, 1),   # Flags
    2: (1, 1),   # Rate
    3: (2, 4),   # Channel (freq u16 + flags u16)
    4: (1, 2),   # FHSS
    5: (1, 1),   # dBm antenna signal
}

RT_FLAG_FCS = 0x10
RT_FLAG_BADFCS = 0x40


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def mac_str(b):
    return '%02x:%02x:%02x:%02x:%02x:%02x' % tuple(b)


def freq_to_channel(freq):
    if not freq:
        return 0
    if freq == 2484:
        return 14
    if 2412 <= freq < 2484:
        return (freq - 2407) // 5
    if 5000 <= freq <= 5900:
        return (freq - 5000) // 5
    if 5955 <= freq <= 7115:
        return (freq - 5950) // 5
    return 0


def channel_to_freq(channel, band):
    if band == '2.4':
        return 2484 if channel == 14 else 2407 + 5 * channel
    if band == '5':
        return 5000 + 5 * channel
    if band == '6':
        return 5950 + 5 * channel
    return 0


def band_of(freq, channel=0):
    if freq:
        if freq < 3000:
            return '2.4'
        if freq < 5925:
            return '5'
        return '6'
    if 1 <= channel <= 14:
        return '2.4'
    if channel:
        return '5'
    return '?'


def is_locally_administered(mac):
    """Randomized client MACs have the locally administered bit set."""
    try:
        return bool(int(mac[0:2], 16) & 0x02)
    except ValueError:
        return False


# --------------------------------------------------------------------------
# Radiotap
# --------------------------------------------------------------------------

def parse_radiotap(buf):
    """Return (header_len, freq, rssi, has_fcs, bad_fcs) or None."""
    if len(buf) < 8 or buf[0] != 0:
        return None
    rt_len = struct.unpack_from('<H', buf, 2)[0]
    if rt_len > len(buf) or rt_len < 8:
        return None

    present = struct.unpack_from('<I', buf, 4)[0]
    offset = 8
    # Skip extended presence bitmaps (bit 31 = another word follows)
    word = present
    while word & 0x80000000:
        if offset + 4 > rt_len:
            return None
        word = struct.unpack_from('<I', buf, offset)[0]
        offset += 4

    freq = 0
    rssi = None
    flags = 0

    for bit in range(6):
        if not present & (1 << bit):
            continue
        align, size = _RT_FIELDS[bit]
        if offset % align:
            offset += align - (offset % align)
        if offset + size > rt_len:
            break
        if bit == 1:
            flags = buf[offset]
        elif bit == 3:
            freq = struct.unpack_from('<H', buf, offset)[0]
        elif bit == 5:
            rssi = struct.unpack_from('<b', buf, offset)[0]
        offset += size

    return rt_len, freq, rssi, bool(flags & RT_FLAG_FCS), bool(flags & RT_FLAG_BADFCS)


# --------------------------------------------------------------------------
# Information elements
# --------------------------------------------------------------------------

SSID_MAX_BYTES = 32


def clean_ssid(ssid):
    """
    A network name is chosen by whoever runs the access point. Characters that could
    mislead the display (control, format such as right-to-left overrides, line and
    paragraph separators) become "·", and the name is cut to 32 bytes of UTF-8.
    """
    if not ssid:
        return ssid
    out = ''.join('\u00b7' if unicodedata.category(c) in ('Cc', 'Cf', 'Zl', 'Zp') else c
                  for c in ssid)
    raw = out.encode('utf-8')
    if len(raw) > SSID_MAX_BYTES:
        out = raw[:SSID_MAX_BYTES].decode('utf-8', 'ignore')
    return out


def iter_ies(buf, offset):
    end = len(buf)
    while offset + 2 <= end:
        eid = buf[offset]
        elen = buf[offset + 1]
        start = offset + 2
        if start + elen > end:
            return
        yield eid, buf[start:start + elen]
        offset = start + elen


def _parse_suite_list(data, pos):
    if pos + 2 > len(data):
        return [], pos
    count = struct.unpack_from('<H', data, pos)[0]
    pos += 2
    suites = []
    for _ in range(count):
        if pos + 4 > len(data):
            break
        suites.append((bytes(data[pos:pos + 3]), data[pos + 3]))
        pos += 4
    return suites, pos


def parse_rsn(data):
    """Parse an RSN IE body. Returns dict or None."""
    if len(data) < 2:
        return None
    rsn = {'group': None, 'pairwise': [], 'akm': [], 'mfpc': False, 'mfpr': False}
    pos = 2  # version
    if pos + 4 <= len(data):
        rsn['group'] = CIPHERS.get(data[pos + 3], 'unknown(%d)' % data[pos + 3])
        pos += 4
    pw, pos = _parse_suite_list(data, pos)
    rsn['pairwise'] = [CIPHERS.get(t, 'unknown(%d)' % t) for _, t in pw]
    akm, pos = _parse_suite_list(data, pos)
    rsn['akm'] = [AKMS.get(t, 'unknown(%d)' % t) if oui == b'\x00\x0f\xac' else 'vendor'
                  for oui, t in akm]
    if pos + 2 <= len(data):
        caps = struct.unpack_from('<H', data, pos)[0]
        rsn['mfpr'] = bool(caps & 0x0040)
        rsn['mfpc'] = bool(caps & 0x0080)
    return rsn


def parse_wpa1(data):
    """Parse a WPA1 vendor IE body (after OUI + type)."""
    if len(data) < 2:
        return None
    wpa = {'group': None, 'pairwise': [], 'akm': []}
    pos = 2
    if pos + 4 <= len(data):
        wpa['group'] = CIPHERS.get(data[pos + 3], 'unknown')
        pos += 4
    pw, pos = _parse_suite_list(data, pos)
    wpa['pairwise'] = [CIPHERS.get(t, 'unknown') for _, t in pw]
    akm, pos = _parse_suite_list(data, pos)
    wpa['akm'] = [{1: '802.1X', 2: 'PSK'}.get(t, 'unknown') for _, t in akm]
    return wpa


def classify_security(privacy, rsn, wpa1):
    """Return a short human label for the advertised security."""
    if rsn:
        akms = set(rsn['akm'])
        if 'OWE' in akms:
            return 'OWE'
        has_sae = bool(akms & SAE_AKMS)
        has_psk = bool(akms & PSK_AKMS)
        has_ent = bool(akms & ENTERPRISE_AKMS)
        if has_ent:
            if rsn['mfpr'] and ('802.1X-SHA256' in akms or '802.1X-SuiteB-192' in akms):
                return 'WPA3-Enterprise'
            return 'WPA2-Enterprise' if not wpa1 else 'WPA/WPA2-Enterprise'
        if has_sae and has_psk:
            return 'WPA3-Transition'
        if has_sae:
            return 'WPA3-SAE'
        if has_psk:
            return 'WPA2-PSK' if not wpa1 else 'WPA/WPA2-PSK'
        return 'WPA2-?'
    if wpa1:
        return 'WPA-Enterprise' if '802.1X' in wpa1['akm'] else 'WPA-PSK'
    if privacy:
        return 'WEP'
    return 'Open'


# --------------------------------------------------------------------------
# Frame parsing
# --------------------------------------------------------------------------

class Frame(object):
    # channel: the channel the radio was tuned to when it heard the frame.
    # ap_channel: for beacons / probe responses, the channel the AP says it is on.
    __slots__ = ('ftype', 'subtype', 'freq', 'channel', 'rssi', 'addr1', 'addr2',
                 'addr3', 'to_ds', 'from_ds', 'protected', 'info', 'length', 'ap_channel')

    def __init__(self):
        self.info = None
        self.ap_channel = 0


def parse_beacon_body(body, subtype):
    """Parse the fixed fields + IEs of a beacon / probe response."""
    if len(body) < 12:
        return None
    interval, caps = struct.unpack_from('<HH', body, 8)
    info = {
        'ssid': None, 'hidden': False, 'ds_channel': 0, 'ht_channel': 0,
        'beacon_interval': interval,
        'privacy': bool(caps & 0x0010), 'rsn': None, 'wpa1': None, 'wps': False,
        'ht': False, 'vht': False, 'he': False, 'rates': [], 'country': None,
    }
    ie_ids = []
    for eid, data in iter_ies(body, 12):
        if eid == 221 and len(data) >= 4:
            ie_ids.append('221:%s:%d' % (bytes(data[:3]).hex(), data[3]))
        elif eid == 255 and len(data) >= 1:
            ie_ids.append('255:%d' % data[0])
        else:
            ie_ids.append(str(eid))

        if eid == 0:
            if len(data) == 0 or data.count(0) == len(data):
                info['hidden'] = True
                info['ssid'] = ''
            else:
                info['ssid'] = clean_ssid(bytes(data).decode('utf-8', 'replace'))
        elif eid in (1, 50):
            info['rates'].extend(r & 0x7f for r in data)
        elif eid == 3 and len(data) >= 1:
            info['ds_channel'] = data[0]
        elif eid == 7 and len(data) >= 2:
            info['country'] = bytes(data[:2]).decode('ascii', 'replace')
        elif eid == 48:
            info['rsn'] = parse_rsn(data)
        elif eid == 45:
            info['ht'] = True
        elif eid == 61 and len(data) >= 1:
            info['ht_channel'] = data[0]  # HT Operation: primary channel
        elif eid == 191:
            info['vht'] = True
        elif eid == 255 and len(data) >= 1 and data[0] == 35:
            info['he'] = True
        elif eid == 221 and len(data) >= 4 and bytes(data[:3]) == b'\x00\x50\xf2':
            if data[3] == 1:
                info['wpa1'] = parse_wpa1(data[4:])
            elif data[3] == 4:
                info['wps'] = True

    info['security'] = classify_security(info['privacy'], info['rsn'], info['wpa1'])
    rsn = info['rsn']
    if rsn:
        info['pmf'] = 'required' if rsn['mfpr'] else ('capable' if rsn['mfpc'] else 'none')
    else:
        info['pmf'] = 'none'

    # Fingerprint: how the AP advertises itself, independent of the SSID.
    # Same idea as nzyme: IE order + capabilities + rates + beacon interval.
    if subtype == ST_BEACON:
        fp_src = '%d|%04x|%s|%s' % (interval, caps & 0xfffe,
                                    ','.join(str(r) for r in sorted(set(info['rates']))),
                                    ','.join(i for i in ie_ids if i not in ('0', '3', '5')))
        info['fingerprint'] = hashlib.sha1(fp_src.encode()).hexdigest()[:16]
    else:
        info['fingerprint'] = None
    return info


def parse_probe_req(body):
    for eid, data in iter_ies(body, 0):
        if eid == 0:
            if len(data) == 0:
                return ''
            return clean_ssid(bytes(data).decode('utf-8', 'replace'))
    return None


# Beacon cache: an access point sends about ten beacons a second, almost always the same.
# A beacon is fully decoded only when its content changed; otherwise the previous result is
# reused. Only the parts that change on their own every beacon are left out of the
# comparison: the timestamp and the TIM element (DTIM count, power-save bitmap). Any other
# difference (security, name, fingerprint, size...) means a full decode, so a forged copy
# of a known beacon is always decoded.
BEACON_CACHE_MAX = 4096
_SKIP_IN_SIGNATURE = (5,)   # TIM
_beacon_cache = {}
cache_stats = {'hits': 0, 'misses': 0}


def beacon_signature(body, subtype):
    """The beacon body without its timestamp and TIM element, or None if malformed."""
    if len(body) < 12:
        return None
    parts = [bytes([subtype]), body[8:12]]
    offset, end = 12, len(body)
    while offset + 2 <= end:
        eid, elen = body[offset], body[offset + 1]
        nxt = offset + 2 + elen
        if nxt > end:
            break
        if eid not in _SKIP_IN_SIGNATURE:
            parts.append(body[offset:nxt])
        offset = nxt
    parts.append(body[offset:])    # trailing bytes, if any, are part of the content
    return b''.join(parts)


def cached_beacon_info(bssid, body, subtype):
    """parse_beacon_body, through the cache."""
    sig = beacon_signature(body, subtype)
    if sig is None:
        return None
    key = (bssid, subtype)  # beacons and probe responses of one AP differ: one slot each
    hit = _beacon_cache.get(key)
    if hit is not None and hit[0] == sig:
        cache_stats['hits'] += 1
        return hit[1]
    cache_stats['misses'] += 1
    info = parse_beacon_body(body, subtype)
    if info is not None:
        if len(_beacon_cache) >= BEACON_CACHE_MAX and key not in _beacon_cache:
            _beacon_cache.clear()  # bounded: a flood of new BSSIDs only empties the cache
        _beacon_cache[key] = (sig, info)
    return info


def parse_frame(buf, want_data=True):
    """
    Parse one radiotap-encapsulated 802.11 frame.
    Returns a Frame or None when the frame is irrelevant or malformed.
    """
    rt = parse_radiotap(buf)
    if rt is None:
        return None
    rt_len, freq, rssi, has_fcs, bad_fcs = rt
    if bad_fcs:
        return None

    end = len(buf) - 4 if has_fcs else len(buf)
    if end - rt_len < 10:
        return None

    fc0 = buf[rt_len]
    fc1 = buf[rt_len + 1]
    ftype = (fc0 >> 2) & 0x3
    subtype = (fc0 >> 4) & 0xf

    if ftype == TYPE_CTRL:
        f = Frame()
        f.ftype, f.subtype, f.freq, f.rssi = ftype, subtype, freq, rssi
        f.channel = freq_to_channel(freq)
        f.addr1 = f.addr2 = f.addr3 = None
        f.length = end - rt_len
        return f

    if end - rt_len < 24:
        return None

    f = Frame()
    f.ftype = ftype
    f.subtype = subtype
    f.freq = freq
    f.channel = freq_to_channel(freq)
    f.rssi = rssi
    f.to_ds = bool(fc1 & 0x01)
    f.from_ds = bool(fc1 & 0x02)
    f.protected = bool(fc1 & 0x40)
    f.length = end - rt_len
    h = rt_len
    f.addr1 = mac_str(buf[h + 4:h + 10])
    f.addr2 = mac_str(buf[h + 10:h + 16])
    f.addr3 = mac_str(buf[h + 16:h + 22])

    if ftype == TYPE_MGMT:
        body = buf[h + 24:end]
        if subtype in (ST_BEACON, ST_PROBE_RESP):
            f.info = cached_beacon_info(f.addr3, body, subtype)
            if f.info is None:
                return None
            # In 2.4 GHz a beacon is also heard on the neighbouring channels, so the
            # tuned channel is not the AP's channel. Trust what the AP advertises,
            # as long as it is in the band we are listening on.
            advertised = f.info['ds_channel'] or f.info['ht_channel']
            if advertised and (not freq or band_of(0, advertised) == band_of(freq)):
                f.ap_channel = advertised
            if not f.channel:
                f.channel = f.ap_channel
        elif subtype == ST_PROBE_REQ:
            f.info = {'ssid': parse_probe_req(body)}
        elif subtype in (ST_DEAUTH, ST_DISASSOC):
            reason = struct.unpack_from('<H', body, 0)[0] if len(body) >= 2 else 0
            f.info = {'reason': reason}
        return f

    if ftype == TYPE_DATA:
        if not want_data:
            return None
        return f

    return None


def data_frame_link(f):
    """
    For a data frame, return (bssid, client) or None.
    Ignores WDS (to_ds and from_ds) and ad-hoc frames.
    """
    if f.to_ds and not f.from_ds:
        bssid, client = f.addr1, f.addr2
    elif f.from_ds and not f.to_ds:
        bssid, client = f.addr2, f.addr1
    else:
        return None
    if client == BROADCAST or int(client[0:2], 16) & 0x01:
        return None  # multicast / broadcast destination
    return bssid, client
