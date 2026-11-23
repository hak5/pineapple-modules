#!/usr/bin/env python3
"""PagerTAK drone Remote ID receiver.

Passively decodes ASTM F3411 / ASD-STAN EN 4709-002 broadcast Remote ID
("Open Drone ID") and writes a live state file that map/rid_bridge.py turns
into TAK CoT. Standard library only (python3-light).

  Wi-Fi Beacon   vendor IE, OUI FA:0B:BC, type 0x0D, counter, message pack
  Wi-Fi NAN      public action frame (vendor, OUI 50:6F:9A type 0x13), service
                 descriptor attribute with the Open Drone ID service ID, whose
                 service info holds counter + message pack
  Bluetooth 4    advertising service data, UUID 0xFFFA, app code 0x0D, counter,
                 one 25-byte message (read from btmon's decoded output)

Wi-Fi frames come from `tcpdump -w -` on the monitor interface (pcap with
radiotap headers). The radio is parked on one channel (default 6, where
Wi-Fi Remote ID beacons live) while running and set back to hopping on exit.

Written for PagerTAK from the published message formats (ASTM F3411-22a,
the opendroneid "core-c" reference). Remote ID Radar by JustCallMeKoko (Hak5
payload library) showed that this works on the Pager's radios.
"""
import argparse
import hashlib
import json
import math
import os
import re
import signal
import struct
import subprocess
import sys
import threading
import time

ODID_OUI = b"\xfa\x0b\xbc"          # ASD-STAN, beacon vendor IE
WFA_OUI = b"\x50\x6f\x9a"           # Wi-Fi Alliance, NAN
NAN_SERVICE_ID = hashlib.sha256(b"org.opendroneid.remoteid").digest()[:6]
MSG_SIZE = 25
LOST_AFTER = 60                      # seconds without a frame -> "lost"
FORGET_AFTER = 1800

STOP = threading.Event()
LOCK = threading.Lock()
RECORDS = {}                         # key (UAS ID, else MAC) -> record
STATS = {"frames": 0, "ble_frames": 0, "decoded": 0, "wifi_alive": False, "ble_alive": False}
ERRORS = []


# ---------------------------------------------------------------------------
# message decoding (25-byte messages)
# ---------------------------------------------------------------------------
def alt(raw):
    """altitudes: uint16 * 0.5 - 1000 m; 0 = unknown"""
    return None if raw == 0 else raw * 0.5 - 1000.0


def text(b):
    return b.split(b"\0", 1)[0].decode("ascii", "replace").strip()


def decode_message(m, rec):
    """Updates rec from one 25-byte message. Returns the message type."""
    if len(m) < MSG_SIZE:
        return None
    mtype = m[0] >> 4
    if mtype == 0:                                   # Basic ID
        id_type, ua_type = m[1] >> 4, m[1] & 0x0F
        uid = text(m[2:22])
        if uid and id_type in (1, 2, 3, 4):          # serial, CAA reg, UTM UUID, specific session
            rec["uas_id"] = uid
            rec["id_type"] = id_type
        rec["ua_type"] = ua_type
    elif mtype == 1:                                 # Location / vector
        flags = m[1]
        rec["operational_status"] = flags >> 4
        direction = m[2] + (180 if flags & 0x02 else 0)
        rec["direction_valid"] = m[2] <= 179
        rec["direction_deg"] = direction if rec["direction_valid"] else None
        sp = m[3]
        speed = sp * 0.25 if not flags & 0x01 else sp * 0.75 + 255 * 0.25
        rec["horizontal_speed_valid"] = sp != 255
        rec["horizontal_speed_mps"] = round(speed, 2) if sp != 255 else None
        vs = struct.unpack("<b", m[4:5])[0]
        rec["vertical_speed_mps"] = vs * 0.5 if vs != 63 else None
        lat, lon = struct.unpack("<ii", m[5:13])
        if (lat or lon) and abs(lat) <= 900000000 and abs(lon) <= 1800000000:
            rec["latitude_e7"], rec["longitude_e7"] = lat, lon
            rec["has_location"] = True
        baro, geo, height = struct.unpack("<HHH", m[13:19])
        rec["geo_altitude_m"] = alt(geo)
        rec["geo_altitude_valid"] = geo != 0
        rec["pressure_altitude_m"] = alt(baro)
        rec["height_m"] = alt(height)
        rec["height_valid"] = height != 0
        rec["height_reference"] = "ground" if flags & 0x04 else "takeoff"
    elif mtype == 3:                                 # Self-ID (free text)
        d = text(m[2:25])
        if d:
            rec["description"] = d
    elif mtype == 4:                                 # System (operator position)
        lat, lon = struct.unpack("<ii", m[2:10])
        if (lat or lon) and abs(lat) <= 900000000 and abs(lon) <= 1800000000:
            rec["operator_latitude_e7"], rec["operator_longitude_e7"] = lat, lon
            rec["has_operator_location"] = True
        oalt = struct.unpack("<H", m[18:20])[0]
        rec["operator_altitude_geo_m"] = alt(oalt)
        rec["operator_altitude_valid"] = oalt != 0
        rec["area_count"] = struct.unpack("<H", m[10:12])[0]
    elif mtype == 5:                                 # Operator ID
        o = text(m[2:22])
        if o:
            rec["operator_id"] = o
    return mtype


def decode_payload(data, rec):
    """data = one message or a message pack. Returns number of messages decoded."""
    if len(data) < MSG_SIZE:
        return 0
    if data[0] >> 4 == 0x0F:                         # message pack
        if len(data) < 3:
            return 0
        size, count = data[1], data[2]
        if size != MSG_SIZE or count > 9:
            return 0
        n = 0
        for i in range(count):
            m = data[3 + i * MSG_SIZE: 3 + (i + 1) * MSG_SIZE]
            if decode_message(m, rec) is not None:
                n += 1
        return n
    return 1 if decode_message(data[:MSG_SIZE], rec) is not None else 0


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------
def update(mac, transport, data, rssi=None):
    tmp = {}
    n = decode_payload(data, tmp)
    if not n:
        return
    now = time.time()
    with LOCK:
        STATS["decoded"] += n
        rec = None
        uid = tmp.get("uas_id")
        if uid and uid in RECORDS:
            rec = RECORDS[uid]
        if rec is None:
            rec = next((r for r in RECORDS.values() if r.get("mac") == mac), None)
        if rec is None:
            rec = {"mac": mac, "first_seen": now, "has_location": False, "has_operator_location": False}
            RECORDS[uid or mac] = rec
        elif uid and uid not in RECORDS:              # learned the UAS ID: re-key by it
            for k in [k for k, v in RECORDS.items() if v is rec]:
                del RECORDS[k]
            RECORDS[uid] = rec
        rec.update(tmp)
        rec["mac"] = mac
        rec["transport"] = transport
        rec["last_seen"] = now
        if rssi is not None:
            rec["rssi"] = rssi


# ---------------------------------------------------------------------------
# Wi-Fi: pcap stream from tcpdump (radiotap)
# ---------------------------------------------------------------------------
def ies(body):
    i = 0
    while i + 2 <= len(body):
        eid, ln = body[i], body[i + 1]
        yield eid, body[i + 2:i + 2 + ln]
        i += 2 + ln


def nan_odid(body):
    """NAN SDF body (after OUI type) -> ODID service info bytes, or None"""
    i = 0
    while i + 3 <= len(body):
        aid = body[i]
        ln = struct.unpack("<H", body[i + 1:i + 3])[0]
        a = body[i + 3:i + 3 + ln]
        i += 3 + ln
        if aid != 0x03 or len(a) < 9 or a[0:6] != NAN_SERVICE_ID:
            continue
        ctrl = a[8]
        p = 9
        if ctrl & 0x40:                              # binding bitmap
            p += 2
        if ctrl & 0x04:                              # matching filter
            p += 1 + (a[p] if p < len(a) else 0)
        if ctrl & 0x08:                              # service response filter
            p += 1 + (a[p] if p < len(a) else 0)
        if ctrl & 0x10 and p < len(a):               # service info
            sl = a[p]
            return a[p + 1:p + 1 + sl]
    return None


def handle_80211(frame, rssi):
    if len(frame) < 24:
        return
    fc = frame[0]
    mac = ":".join("%02x" % b for b in frame[10:16])
    if fc == 0x80:                                   # beacon
        for eid, v in ies(frame[24 + 12:]):
            if eid == 221 and len(v) > 5 and v[0:3] == ODID_OUI and v[3] == 0x0D:
                update(mac, "wifi-beacon", v[5:], rssi)   # v[4] = message counter
    elif fc == 0xD0:                                 # action
        b = frame[24:]
        if len(b) > 6 and b[0] == 0x04 and b[1] == 0x09 and b[2:5] == WFA_OUI and b[5] == 0x13:
            info = nan_odid(b[6:])
            if info and len(info) > 1:
                update(mac, "wifi-nan", info[1:], rssi)   # info[0] = message counter


def radiotap(pkt):
    """-> (802.11 frame, rssi dBm or None)"""
    if len(pkt) < 8:
        return b"", None
    ln = struct.unpack("<H", pkt[2:4])[0]
    rssi = None
    try:
        present = struct.unpack("<I", pkt[4:8])[0]
        off = 8
        p = present
        while p & 0x80000000:                         # extended present bitmaps
            p = struct.unpack("<I", pkt[off:off + 4])[0]
            off += 4
        # fields in order with alignment: tsft(8) flags(1) rate(1) channel(2+2) fhss(2) dbm_signal(1)
        sizes = [(8, 8), (1, 1), (1, 1), (4, 2), (2, 1), (1, 1)]
        for bit, (size, align) in enumerate(sizes):
            if present & (1 << bit):
                off = (off + align - 1) // align * align
                if bit == 5:
                    rssi = struct.unpack("<b", pkt[off:off + 1])[0]
                off += size
    except (struct.error, IndexError):
        rssi = None
    return pkt[ln:], rssi


def read_pcap(stream):
    hdr = stream.read(24)
    if len(hdr) < 24:
        return
    magic = struct.unpack("<I", hdr[:4])[0]
    endian = "<" if magic in (0xA1B2C3D4, 0xA1B23C4D) else ">"
    linktype = struct.unpack(endian + "I", hdr[20:24])[0]
    while not STOP.is_set():
        rh = stream.read(16)
        if len(rh) < 16:
            return
        incl = struct.unpack(endian + "IIII", rh)[2]
        pkt = stream.read(incl)
        if len(pkt) < incl:
            return
        STATS["frames"] += 1
        if linktype == 127:
            frame, rssi = radiotap(pkt)
        else:
            frame, rssi = pkt, None
        try:
            handle_80211(frame, rssi)
        except (IndexError, struct.error):
            pass


def wifi_thread(iface):
    cmd = ["tcpdump", "-i", iface, "-U", "-s", "0", "-w", "-",
           "type mgt subtype beacon or type mgt subtype action"]
    while not STOP.is_set():
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError as e:
            ERRORS.append("tcpdump: %s" % e)
            return
        STATS["wifi_alive"] = True
        read_pcap(p.stdout)
        STATS["wifi_alive"] = False
        p.terminate()
        if not STOP.is_set():
            ERRORS.append("Wi-Fi capture stopped; restarting")
            STOP.wait(3)


# ---------------------------------------------------------------------------
# Bluetooth: btmon text (Service Data UUID 0xfffa)
# ---------------------------------------------------------------------------
RE_ADDR = re.compile(r"^\s+Address: ([0-9A-Fa-f:]{17})")
RE_FFFA = re.compile(r"Service Data.*0xfffa\)?:?\s*([0-9a-fA-F]*)")
RE_DATA = re.compile(r"^\s+Data: ([0-9a-fA-F]+)")
RE_RSSI = re.compile(r"^\s+RSSI: (-?\d+) dBm")


def ble_thread(scan):
    try:
        mon = subprocess.Popen(["btmon"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
    except OSError:
        return
    scanner = None
    if scan:
        try:
            scanner = subprocess.Popen(["hcitool", "lescan", "--passive", "--duplicates"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            scanner = None
    STATS["ble_alive"] = True
    mac, want, hexdata = None, False, None
    try:
        for line in mon.stdout:
            if STOP.is_set():
                break
            if "Advertising Report" in line:
                mac, want, hexdata = None, False, None
                continue
            m = RE_ADDR.match(line)
            if m and mac is None:
                mac = m.group(1).lower()
                continue
            m = RE_FFFA.search(line)
            if m:
                if m.group(1):
                    hexdata = m.group(1)
                else:
                    want = True
                continue
            if want:
                m = RE_DATA.match(line)
                if m:
                    hexdata, want = m.group(1), False
                continue
            m = RE_RSSI.match(line)
            if m and mac and hexdata:
                STATS["ble_frames"] += 1
                try:
                    d = bytes.fromhex(hexdata)
                except ValueError:
                    d = b""
                if len(d) > 2 and d[0] == 0x0D:          # app code, then counter, then the message
                    update(mac, "bluetooth", d[2:], int(m.group(1)))
                mac, hexdata = None, None
    finally:
        STATS["ble_alive"] = False
        for p in (scanner, mon):
            if p:
                p.terminate()


# ---------------------------------------------------------------------------
# radio channel (park on one channel, give it back on exit)
# ---------------------------------------------------------------------------
def radio_park(iface, ch):
    try:
        r = subprocess.run(["_pineap", "INTERFACE", "SET", iface, "CHANNEL", str(ch)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        if r.returncode == 0:
            return "pineap"
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        subprocess.run(["iw", "dev", iface, "set", "channel", str(ch)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        return "iw"
    except (OSError, subprocess.SubprocessError):
        ERRORS.append("could not set channel %s" % ch)
        return None


def radio_restore(iface, how):
    if how == "pineap":
        try:
            subprocess.run(["_pineap", "INTERFACE", "SET", iface, "HOP", "fast"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass


# ---------------------------------------------------------------------------
# state file
# ---------------------------------------------------------------------------
def my_position(run):
    for name in ("gps", "lastfix"):
        try:
            with open(os.path.join(run, name)) as fh:
                p = fh.readline().split()
        except OSError:
            continue
        try:
            if name == "gps" and len(p) >= 3 and p[0] == "1":
                return float(p[1]), float(p[2])
            if name == "lastfix" and len(p) >= 2:
                return float(p[0]), float(p[1])
        except ValueError:
            pass
    return None


def range_bearing(a, b):
    r = math.pi / 180
    dl = (b[1] - a[1]) * r
    x = dl * math.cos((a[0] + b[0]) / 2 * r)
    y = (b[0] - a[0]) * r
    d = math.sqrt(x * x + y * y) * 6371008.8
    br = math.degrees(math.atan2(math.sin(dl) * math.cos(b[0] * r),
                                 math.cos(a[0] * r) * math.sin(b[0] * r) - math.sin(a[0] * r) * math.cos(b[0] * r) * math.cos(dl)))
    return int(d), int((br + 360) % 360)


def write_state(path, run, channel, csv):
    logged = {}
    while not STOP.is_set():
        now = time.time()
        me = my_position(run)
        with LOCK:
            for k in [k for k, r in RECORDS.items() if now - r["last_seen"] > FORGET_AFTER]:
                del RECORDS[k]
            recs = []
            for r in RECORDS.values():
                r = dict(r)
                r["is_lost"] = now - r["last_seen"] > LOST_AFTER
                if me and r.get("has_location"):
                    r["distance_m"], r["bearing_deg"] = range_bearing(me, (r["latitude_e7"] / 1e7, r["longitude_e7"] / 1e7))
                recs.append(r)
            stats = dict(STATS)
        state = dict(stats, status="running", wifi_channel=channel, active_count=sum(1 for r in recs if not r["is_lost"]),
                     records=recs, capture_errors=ERRORS[-5:], updated=now)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(state, fh)
        os.replace(tmp, path)
        if csv:
            for r in recs:
                key = r.get("uas_id") or r["mac"]
                if r.get("has_location") and not r["is_lost"] and now - logged.get(key, 0) >= 5:
                    logged[key] = now
                    new = not os.path.exists(csv)
                    with open(csv, "a") as fh:
                        if new:
                            fh.write("time,uas_id,mac,lat,lon,geo_alt_m,height_m,speed_mps,operator_lat,operator_lon,operator_id\n")
                        fh.write("%s,%s,%s,%.7f,%.7f,%s,%s,%s,%s,%s,%s\n" % (
                            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), key.replace(",", " "), r["mac"],
                            r["latitude_e7"] / 1e7, r["longitude_e7"] / 1e7, r.get("geo_altitude_m") or "",
                            r.get("height_m") or "", r.get("horizontal_speed_mps") or "",
                            "%.7f" % (r["operator_latitude_e7"] / 1e7) if r.get("has_operator_location") else "",
                            "%.7f" % (r["operator_longitude_e7"] / 1e7) if r.get("has_operator_location") else "",
                            (r.get("operator_id") or "").replace(",", " ")))
        STOP.wait(1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--interface", default="wlan1mon")
    ap.add_argument("--channel", type=int, default=6)
    ap.add_argument("--state", required=True)
    ap.add_argument("--run", default="/tmp/pagertak")
    ap.add_argument("--csv", default="")
    ap.add_argument("--no-wifi", action="store_true")
    ap.add_argument("--no-ble", action="store_true")
    ap.add_argument("--ble-scan", action="store_true", help="also run hcitool lescan (off when tracker watch scans)")
    ap.add_argument("--pcap", default="", help="decode a pcap file and print the records (testing)")
    a = ap.parse_args(argv)

    if a.pcap:
        with open(a.pcap, "rb") as fh:
            read_pcap(fh)
        print(json.dumps(list(RECORDS.values()), indent=1, default=str))
        return 0

    def stop(*_):
        STOP.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    how = None
    threads = []
    if not a.no_wifi:
        how = radio_park(a.interface, a.channel)
        threads.append(threading.Thread(target=wifi_thread, args=(a.interface,), daemon=True))
    if not a.no_ble:
        threads.append(threading.Thread(target=ble_thread, args=(a.ble_scan,), daemon=True))
    for t in threads:
        t.start()
    try:
        write_state(a.state, a.run, a.channel, a.csv)
    finally:
        STOP.set()
        radio_restore(a.interface, how)
        subprocess.run(["pkill", "-f", "tcpdump -i %s -U" % a.interface], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
