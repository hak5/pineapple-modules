#!/usr/bin/env python3
"""PagerTAK site survey -> ATAK data package builder.

Input: a survey folder written by PagerTAK (include/survey.sh):
  meta      name|start_epoch|end_epoch|callsign
  samples   epoch lat lon bssid ssid_hex enc channel signal     (one line per AP heard per sample)
  track     epoch lat lon
Optional: --approved <watch profile .approved> to highlight your own networks.

Output: <out>.zip  ATAK data package (MANIFEST/manifest.xml + survey KML + CSV + summary),
        and prints "ZIP <path>" / "STATS ..." lines for the caller.

Each access point is placed at the signal-weighted center of its strongest
samples (top 3), so positions come from where the Pager actually walked.
"""
import argparse
import os
import time
from ptak_zip import ZipWriter, uuid4   # zipfile and uuid are not in python3-light

COLORS = {  # KML aabbggrr
    "open": "ff0000ff", "weak": "ff00a5ff", "secured": "ff00c000", "yours": "ffff8000", "hidden": "ff909090",
}
FOLDERS = [("yours", "Your networks"), ("open", "Open networks"), ("weak", "Weak security (WEP/WPA)"),
           ("secured", "Secured (WPA2/WPA3)"), ("hidden", "Hidden networks")]


def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def enc_name(e):
    e = int(e or 0)
    if e == 0:
        return "Open"
    if (e & 16 or e & 64) and e & 8:
        return "WPA2/WPA3"
    if e & 16 or e & 64:
        return "WPA3"
    if e & 8:
        return "WPA2"
    if e & 4:
        return "WPA"
    if e & 2:
        return "WEP"
    return "enc:%d" % e


def hex_to_str(h):
    try:
        return bytes.fromhex(h).decode("utf-8", "replace").replace("\x00", "")
    except ValueError:
        return ""


def fmt_mac(b):
    return ":".join(b[i:i + 2] for i in range(0, 12, 2)).upper() if len(b) == 12 else b.upper()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("survey")
    ap.add_argument("--out", required=True, help="output path without .zip")
    ap.add_argument("--approved", default="")
    args = ap.parse_args()

    name, start, end, callsign = "Survey", 0, 0, "PAGER"
    try:
        with open(os.path.join(args.survey, "meta")) as fh:
            p = fh.readline().strip().split("|")
            name, start, end, callsign = p[0], int(p[1]), int(p[2] or 0), p[3]
    except (OSError, ValueError, IndexError):
        pass
    end = end or int(time.time())

    aps = {}
    with open(os.path.join(args.survey, "samples")) as fh:
        for line in fh:
            f = line.split()
            if len(f) < 8 or f[1] == "-":
                continue
            try:
                t, lat, lon, sig = int(f[0]), float(f[1]), float(f[2]), int(float(f[7]))
            except ValueError:
                continue
            a = aps.setdefault(f[3], {"ssid": f[4] if f[4] != "-" else "", "enc": f[5], "ch": f[6], "samples": []})
            a["samples"].append((sig, lat, lon, t))

    approved_ssids, approved_bssids = set(), set()
    if args.approved and os.path.exists(args.approved):
        with open(args.approved) as fh:
            for line in fh:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 2:
                    approved_ssids.add(p[0].upper())
                    approved_bssids.add(p[1].lower())

    rows = []
    for bssid, a in aps.items():
        top = sorted(a["samples"], reverse=True)[:3]
        w = [10 ** (s / 20.0) for s, _, _, _ in top]          # stronger signal = more weight
        lat = sum(wi * x[1] for wi, x in zip(w, top)) / sum(w)
        lon = sum(wi * x[2] for wi, x in zip(w, top)) / sum(w)
        ssid = hex_to_str(a["ssid"])
        enc = enc_name(a["enc"])
        if a["ssid"].upper() in approved_ssids or bssid.lower() in approved_bssids:
            cat = "yours"
        elif not ssid:
            cat = "hidden"
        elif enc == "Open":
            cat = "open"
        elif enc in ("WEP", "WPA"):
            cat = "weak"
        else:
            cat = "secured"
        first = min(x[3] for x in a["samples"])
        last = max(x[3] for x in a["samples"])
        rows.append({"bssid": fmt_mac(bssid), "ssid": ssid, "enc": enc, "ch": a["ch"], "best": top[0][0],
                     "n": len(a["samples"]), "lat": lat, "lon": lon, "cat": cat, "first": first, "last": last})
    rows.sort(key=lambda r: (r["cat"] != "yours", r["cat"] != "open", -r["best"]))

    track = []
    try:
        with open(os.path.join(args.survey, "track")) as fh:
            for line in fh:
                f = line.split()
                if len(f) >= 3 and f[1] != "-":
                    track.append((float(f[1]), float(f[2])))
    except OSError:
        pass

    counts = {c: sum(1 for r in rows if r["cat"] == c) for c, _ in FOLDERS}
    mins = max(1, (end - start) // 60)
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(start))
    nets = len({r["ssid"] for r in rows if r["ssid"]})

    # ---- KML
    k = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
         "<name>%s</name>" % esc("Site survey: %s (%s)" % (name, when)),
         "<description>%s</description>" % esc("Wi-Fi site survey by %s, %s, %d min. %d access points, %d networks; "
                                               "%d open, %d weak, %d hidden." % (callsign, when, mins, len(rows), nets,
                                                                                 counts["open"], counts["weak"], counts["hidden"]))]
    for c, color in COLORS.items():
        k.append('<Style id="%s"><IconStyle><color>%s</color><scale>0.9</scale><Icon><href>'
                 'http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon></IconStyle>'
                 '<LabelStyle><scale>0.7</scale></LabelStyle></Style>' % (c, color))
    k.append('<Style id="track"><LineStyle><color>ffffff00</color><width>3</width></LineStyle></Style>')
    for c, title in FOLDERS:
        sel = [r for r in rows if r["cat"] == c]
        if not sel:
            continue
        k.append("<Folder><name>%s (%d)</name>" % (esc(title), len(sel)))
        for r in sel:
            desc = ("SSID: %s<br/>BSSID: %s<br/>Security: %s<br/>Channel: %s<br/>Best signal: %s dBm<br/>"
                    "Heard: %d samples, %s - %s" % (esc(r["ssid"] or "(hidden)"), r["bssid"], r["enc"], r["ch"], r["best"],
                                                    r["n"], time.strftime("%H:%M", time.localtime(r["first"])),
                                                    time.strftime("%H:%M", time.localtime(r["last"]))))
            k.append("<Placemark><name>%s</name><styleUrl>#%s</styleUrl><description><![CDATA[%s]]></description>"
                     "<Point><coordinates>%.7f,%.7f,0</coordinates></Point></Placemark>"
                     % (esc((r["ssid"] or "hidden") + " " + r["bssid"][-5:]), c, desc, r["lon"], r["lat"]))
        k.append("</Folder>")
    if len(track) >= 2:
        k.append("<Placemark><name>%s</name><styleUrl>#track</styleUrl><LineString><tessellate>1</tessellate>"
                 "<coordinates>%s</coordinates></LineString></Placemark>"
                 % (esc("Survey track (%s)" % callsign), " ".join("%.7f,%.7f,0" % (lo, la) for la, lo in track)))
    k.append("</Document></kml>")

    csv = ["bssid,ssid,security,channel,best_signal_dbm,samples,lat,lon,category"]
    for r in rows:
        csv.append('%s,"%s",%s,%s,%s,%d,%.7f,%.7f,%s' % (r["bssid"], r["ssid"].replace('"', "'"), r["enc"], r["ch"],
                                                         r["best"], r["n"], r["lat"], r["lon"], r["cat"]))
    summary = ("SITE SURVEY: %s\nBy: %s\nWhen: %s (%d min)\nAccess points: %d   Networks: %d\n"
               "Your networks: %d APs\nOpen: %d   Weak (WEP/WPA): %d   Secured: %d   Hidden: %d\n\nOpen networks:\n%s\n"
               % (name, callsign, when, mins, len(rows), nets, counts["yours"], counts["open"], counts["weak"],
                  counts["secured"], counts["hidden"],
                  "\n".join("  %s  %s  ch%s  %sdBm" % (r["ssid"], r["bssid"], r["ch"], r["best"])
                            for r in rows if r["cat"] == "open") or "  none"))

    base = "survey_%s_%s" % ("".join(c if c.isalnum() else "_" for c in name), time.strftime("%Y%m%d_%H%M", time.localtime(start)))
    manifest = ('<MissionPackageManifest version="2"><Configuration>'
                '<Parameter name="uid" value="%s"/><Parameter name="name" value="%s"/>'
                '</Configuration><Contents>'
                '<Content ignore="false" zipEntry="%s/%s.kml"/>'
                '<Content ignore="false" zipEntry="%s/%s.csv"/>'
                '<Content ignore="false" zipEntry="%s/summary.txt"/>'
                '</Contents></MissionPackageManifest>' % (uuid4(), esc(base + ".zip"), base, base, base, base, base))
    out = args.out + ".zip"
    with ZipWriter(out) as z:
        z.add("MANIFEST/manifest.xml", manifest)
        z.add("%s/%s.kml" % (base, base), "\n".join(k))
        z.add("%s/%s.csv" % (base, base), "\n".join(csv) + "\n")
        z.add("%s/summary.txt" % base, summary)
    print("ZIP %s" % out)
    print("NAME %s.zip" % base)
    print("STATS %d APs, %d networks, %d open, %d weak, %d yours, %d min" %
          (len(rows), nets, counts["open"], counts["weak"], counts["yours"], mins))


if __name__ == "__main__":
    main()
