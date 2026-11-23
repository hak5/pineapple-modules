#!/usr/bin/env python3
"""PagerTAK Remote ID -> TAK bridge.

Reads the live state file written by map/rid_decode.py (PagerTAK's Remote ID
receiver) and queues CoT for PagerTAK's TAK connection:

  drone     a-u-A-M-H-Q (rotary/VTOL) / a-u-A-M-F-Q (fixed-wing) / a-u-A (other)
  operator  a-u-G-E-S-E (home point / operator position)

Events are written to PagerTAK's outbox ($RUN/outbox/*.cot); PagerTAK's engine
is the only writer to the socket. Drones also go to $RUN/tracks.d for the Pager
map, and each new drone raises a Pager alert + one GeoChat message.
"""
import argparse
import json
import os
import subprocess
import time

def escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;").replace("\n", "&#10;"))


def quoteattr(text):
    return '"%s"' % escape(text)


ROTARY = {2, 3, 4}          # ASTM F3411 UA type: helicopter/multirotor, gyroplane, hybrid lift (VTOL)
FIXED = {1, 6}              # aeroplane, glider
UA_NAMES = {0: "Undeclared", 1: "Aeroplane", 2: "Helicopter/Multirotor", 3: "Gyroplane", 4: "Hybrid VTOL",
            5: "Ornithopter", 6: "Glider", 7: "Kite", 8: "Free balloon", 9: "Captive balloon", 10: "Airship",
            11: "Parachute", 12: "Rocket", 13: "Tethered aircraft", 14: "Ground obstacle", 15: "Other"}
STATUS = {0: "Undeclared", 1: "Ground", 2: "Airborne", 3: "Emergency", 4: "Remote ID failure"}


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def as_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def drone_type(rec):
    t = as_int(rec.get("ua_type"), -1)
    if t in ROTARY:
        return "a-u-A-M-H-Q"
    if t in FIXED:
        return "a-u-A-M-F-Q"
    return "a-u-A"


def ident(rec):
    return (rec.get("uas_id") or "").strip() or rec.get("mac") or "unknown"


def safe_uid(text):
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in text)[:60]


def event_xml(uid, ctype, lat, lon, hae, callsign, remarks, stale, now, extra=""):
    return ('<event version="2.0" uid=%s type="%s" how="m-g" time="%s" start="%s" stale="%s">'
            '<point lat="%.7f" lon="%.7f" hae="%.1f" ce="9999999.0" le="9999999.0"/>'
            '<detail><contact callsign=%s/>%s<remarks>%s</remarks></detail></event>'
            % (quoteattr(uid), ctype, iso(now), iso(now), iso(now + stale), lat, lon, hae,
               quoteattr(callsign), extra, escape(remarks)))


def chat_xml(my_uid, my_callsign, text, lat, lon, now):
    mid = "rid-%d" % int(now * 1000)
    room = "All Chat Rooms"
    return ('<event version="2.0" uid="GeoChat.%s.%s.%s" type="b-t-f" how="h-g-i-g-o" time="%s" start="%s" stale="%s">'
            '<point lat="%.7f" lon="%.7f" hae="0" ce="9999999.0" le="9999999.0"/><detail>'
            '<__chat parent="RootContactGroup" groupOwner="false" messageId="%s" chatroom="%s" id="%s" senderCallsign=%s>'
            '<chatgrp uid0="%s" uid1="%s" id="%s"/></__chat><link uid="%s" type="a-f-G-U-C" relation="p-p"/>'
            '<remarks source="BAO.F.ATAK.%s" to="%s" time="%s">%s</remarks></detail></event>'
            % (my_uid, room, mid, iso(now), iso(now), iso(now + 86400), lat, lon, mid, room, room,
               quoteattr(my_callsign), my_uid, room, room, my_uid, my_uid, room, iso(now), escape(text)))


def queue(outbox, xml):
    os.makedirs(outbox, exist_ok=True)
    base = os.path.join(outbox, "%d-rid-%d" % (time.time(), os.getpid()))
    n = 0
    while os.path.exists(base + "-%d.cot" % n):
        n += 1
    tmp = base + "-%d.tmp" % n
    with open(tmp, "w") as fh:
        fh.write(xml.replace("\n", " ") + "\n")
    os.replace(tmp, base + "-%d.cot" % n)


def track(run, uid, lat, lon, callsign, ctype, kind="drone"):
    d = os.path.join(run, "tracks.d")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, safe_uid(uid))
    with open(path + ".tmp", "w") as fh:
        fh.write("%.7f|%.7f|%s|%s||%d|%s|0\n" % (lat, lon, callsign.replace("|", "/"), ctype, time.time(), kind))
    os.replace(path + ".tmp", path)


def pager(cmd, *args):
    try:
        subprocess.Popen([cmd] + list(args), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def remarks_for(rec, me):
    lines = ["Remote ID drone heard by %s" % me,
             "UAS ID: %s" % (rec.get("uas_id") or "-"),
             "Type: %s   Status: %s" % (UA_NAMES.get(as_int(rec.get("ua_type"), -1), "Unknown"),
                                        STATUS.get(as_int(rec.get("operational_status"), -1), "Unknown"))]
    if rec.get("geo_altitude_valid") or rec.get("height_valid"):
        lines.append("Alt: %s m geo, %s m AGL" % (rec.get("geo_altitude_m", "-"), rec.get("height_m", "-")))
    if rec.get("horizontal_speed_valid"):
        lines.append("Speed: %.1f m/s  Heading: %s" % (float(rec.get("horizontal_speed_mps", 0)), rec.get("direction_deg", "-")))
    if rec.get("operator_id"):
        lines.append("Operator ID: %s" % rec["operator_id"])
    if rec.get("description"):
        lines.append("Self-ID: %s" % rec["description"])
    if rec.get("distance_m") is not None:
        lines.append("From %s: %d m, bearing %d" % (me, int(rec["distance_m"]), int(rec.get("bearing_deg", 0))))
    lines.append("MAC: %s" % (rec.get("mac") or "-"))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--run", default="/tmp/pagertak")
    ap.add_argument("--uid", required=True, help="PagerTAK's own UID")
    ap.add_argument("--product", default="PagerTAK", help="prefix for the drones' UIDs (PagerTAK, PineappleTAK...)")
    ap.add_argument("--callsign", default="PAGER")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--stale", type=int, default=30)
    ap.add_argument("--min-send", type=float, default=3.0, help="min seconds between updates per drone")
    ap.add_argument("--chat", type=int, default=1, help="1 = GeoChat on each new drone")
    ap.add_argument("--log", default="")
    ap.add_argument("--once", action="store_true", help="process the state once (testing)")
    args = ap.parse_args()

    outbox = os.path.join(args.run, "outbox")
    sent = {}          # key -> (last_seen sent, time sent)
    announced = set()
    while not os.path.exists(os.path.join(args.run, "stop")):
        try:
            with open(args.state) as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            state = {"records": []}
        now = time.time()
        for rec in state.get("records", []):
            if rec.get("is_lost") or not rec.get("has_location"):
                continue
            lat, lon = as_int(rec.get("latitude_e7")) / 1e7, as_int(rec.get("longitude_e7")) / 1e7
            if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
                continue
            key = ident(rec)
            last_seen = rec.get("last_seen", 0)
            prev = sent.get(key)
            if prev and (prev[0] == last_seen or now - prev[1] < args.min_send):
                continue
            sent[key] = (last_seen, now)
            uid = args.product + "-RID-" + safe_uid(key)
            hae = float(rec.get("geo_altitude_m") or 0) if rec.get("geo_altitude_valid") else 0.0
            cs = "UAS " + key[-12:]
            ctype = drone_type(rec)
            extra = ""
            if rec.get("horizontal_speed_valid") or rec.get("direction_valid"):
                extra = '<track course="%s" speed="%s"/>' % (rec.get("direction_deg", 0) or 0, rec.get("horizontal_speed_mps", 0) or 0)
            extra += '<link uid="%s" type="a-f-G-U-C" relation="p-p"/>' % args.uid
            queue(outbox, event_xml(uid, ctype, lat, lon, hae, cs, remarks_for(rec, args.callsign), args.stale, now, extra))
            track(args.run, uid, lat, lon, cs, ctype)
            if rec.get("has_operator_location"):
                olat, olon = as_int(rec.get("operator_latitude_e7")) / 1e7, as_int(rec.get("operator_longitude_e7")) / 1e7
                if (olat, olon) != (0, 0) and -90 <= olat <= 90 and -180 <= olon <= 180:
                    ohae = float(rec.get("operator_altitude_geo_m") or 0) if rec.get("operator_altitude_valid") else 0.0
                    ocs = "OPR " + key[-12:]
                    queue(outbox, event_xml(uid + "-OPR", "a-u-G-E-S-E", olat, olon, ohae, ocs,
                                            "Operator / home point for %s\n%s" % (key, remarks_for(rec, args.callsign)),
                                            max(args.stale, 120), now,
                                            '<link uid="%s" type="%s" relation="p-p"/>' % (uid, ctype)))
                    track(args.run, uid + "-OPR", olat, olon, ocs, "a-u-G-E-S-E", "operator")
            if key not in announced:
                announced.add(key)
                text = "DRONE (Remote ID) near %s: %s %s at %.5f,%.5f" % (
                    args.callsign, UA_NAMES.get(as_int(rec.get("ua_type"), -1), "UAS"), key, lat, lon)
                if rec.get("has_operator_location"):
                    text += " - operator %.5f,%.5f" % (as_int(rec.get("operator_latitude_e7")) / 1e7,
                                                      as_int(rec.get("operator_longitude_e7")) / 1e7)
                if args.chat:
                    queue(outbox, chat_xml(args.uid, args.callsign, text, lat, lon, now))
                pager("LOG", "red", "DRONE: %s" % key)
                pager("RINGTONE", "alert")
                if args.log:
                    with open(args.log, "a") as fh:
                        fh.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
