#!/usr/bin/env python3
"""PagerTAK web console.

A small HTTP server that gives a browser the PagerTAK map, chat, 911, reports,
sensors and settings. It is written for python3-light on OpenWrt: standard
library only, no http.server / email modules (they are separate packages there).

The server never talks to the TAK Server itself. It reads PagerTAK's runtime
directory and hands commands to the payload through a file queue, so the bash
core stays the only place that builds CoT and the only writer to the socket:

  read   RUN/gps lastfix status emergency battery web_cfg tracks.d/* outbox/
         RUN/watch_alerts trk_alerts, LOOT/chat_YYYYMMDD.log, LOOT/reports.log
  write  RUN/webcmd/<id>.req   (key=value lines, one command)
  read   RUN/webcmd/<id>.res   (ok|message  or  err|message, written by the payload)

Things that are only read (radio state, the recon database, fox-hunt samples)
are read here directly, and only while a browser has that tab open.

Security
  - Password login (salted PBKDF2-SHA256, or iterated SHA-256 when the
    Python build has no OpenSSL), session cookie HttpOnly + SameSite=Strict.
  - Failed logins lock the client out (60 s, doubling, max 15 min).
  - Every POST needs the X-PagerTAK header, which a cross-site page cannot send.
  - Binds only to the addresses it is given (the payload passes the USB /
    management address by default, never the Wi-Fi interfaces).
  - Optional HTTPS with a self-signed certificate (needs python3-openssl).
"""
import argparse
import binascii
import glob
import hashlib
import hmac
import json
import os
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time

MAX_HEADER = 16 * 1024
MAX_BODY = 256 * 1024
SESSION_TTL = 12 * 3600
COOKIE = "ptak"
TRACK_MAX_AGE = 1800

ARGS = None
PM = None                     # map helpers (pagertak_map.py), for basemap sources and tile fetching
SESSIONS = {}                 # token -> expiry
FAILS = {}                    # ip -> (count, locked_until)
LOCK = threading.Lock()
FETCH_SEM = threading.Semaphore(3)
BG_QUEUE = []                 # tiles to cache in the background: (src, path, z, x, y)
BG_SET = set()
BG_COND = threading.Condition()
CACHE = {}                    # small time-limited cache: key -> (expires, value)

CMDS = {
    "chat", "chat_read", "sa_now", "emergency", "cancel_emergency", "report", "sensor", "settings",
    "survey_start", "survey_stop", "cert", "channels_set", "marker", "geofence_add", "geofence_del",
    "radio", "fox_start", "fox_stop", "item_send", "item_del", "imok", "clear_received",
    "enroll", "tak_test", "setup_done", "chat_clear", "sensor_install", "watch_scan", "watch_save",
    "web_listen",
}
STREAM_LIMITS = {"/api/share": 8 * 1024 * 1024, "/api/overlays": 4 * 1024 * 1024,
                 "/api/certfile": 256 * 1024, "/api/package": 4 * 1024 * 1024}
TRAILS = {}                   # id -> [[ts, lat, lon], ...]   (last hour, sampled every 15 s)
TRAIL_KEEP = 3600
JOB = {"state": "idle"}       # offline tile download job

MIME = {
    ".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml",
    ".json": "application/json", ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8",
}


# --------------------------------------------------------------------------
# passwords
# --------------------------------------------------------------------------
def hash_password(pw, salt=None, method=None, iters=None):
    salt = salt or binascii.hexlify(os.urandom(16)).decode()
    pwb = pw.encode("utf-8")
    if method is None:
        # Only use PBKDF2 when it is OpenSSL's C version; the pure-Python fallback
        # (Python builds without OpenSSL) is far too slow on a MIPS CPU.
        f = getattr(hashlib, "pbkdf2_hmac", None)
        method = "pbkdf2" if f is not None and type(f).__name__ == "builtin_function_or_method" else "sha256i"
    if method == "pbkdf2":
        iters = iters or 20000
        h = hashlib.pbkdf2_hmac("sha256", pwb, salt.encode(), iters).hex()
    else:
        iters = iters or 5000
        d = hashlib.sha256(salt.encode() + pwb).digest()
        for _ in range(iters):
            d = hashlib.sha256(d + pwb).digest()
        h = d.hex()
    return "%s$%d$%s$%s" % (method, iters, salt, h)


def check_password(pw, line):
    try:
        method, iters, salt, want = line.strip().split("$")
        got = hash_password(pw, salt, method, int(iters)).split("$")[3]
    except (ValueError, IndexError):
        return False
    return hmac.compare_digest(got, want)


# --------------------------------------------------------------------------
# reading PagerTAK state
# --------------------------------------------------------------------------
def rpath(*p):
    return os.path.join(ARGS.run, *p)


def first_line(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.readline().rstrip("\n")
    except OSError:
        return ""


def read_kv(path):
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if "=" in line:
                    k, v = line.rstrip("\n").split("=", 1)
                    out[k] = v
    except OSError:
        pass
    return out


def num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def cached(key, ttl, fn):
    now = time.time()
    with LOCK:
        hit = CACHE.get(key)
        if hit and hit[0] > now:
            return hit[1]
    val = fn()
    with LOCK:
        CACHE[key] = (now + ttl, val)
    return val


def self_position(cfg):
    g = first_line(rpath("gps")).split()
    sats = g[7] if len(g) >= 8 else "-"
    if len(g) >= 9 and g[0] == "1":
        return {"lat": num(g[1]), "lon": num(g[2]), "hae": num(g[3], 0), "ce": num(g[4]),
                "speed": num(g[5], 0), "course": num(g[6]), "sats": sats, "src": "GPS", "fix": True,
                "ts": num(g[8], 0)}
    lf = first_line(rpath("lastfix")).split()
    if len(lf) >= 2 and num(lf[0]) is not None:
        return {"lat": num(lf[0]), "lon": num(lf[1]), "sats": sats, "src": "LAST", "fix": False}
    m = cfg.get("manual_pos", "").replace(" ", "")
    if "," in m:
        a, b = m.split(",", 1)
        if num(a) is not None and num(b) is not None:
            return {"lat": num(a), "lon": num(b), "sats": sats, "src": "MANUAL", "fix": False}
    return {"lat": None, "lon": None, "sats": sats, "src": "NONE", "fix": False}


def dist_m(a1, o1, a2, o2):
    import math
    r = math.pi / 180
    x = (o2 - o1) * r * math.cos((a1 + a2) / 2 * r)
    y = (a2 - a1) * r
    return math.sqrt(x * x + y * y) * 6371008.8


CATS = ("users", "drones", "aircraft", "ground", "vessels", "other")


def category(ctype, kind):
    """What a received item is, for the Contacts / Items tabs and the show/hide filters."""
    if kind == "client":
        return "users"
    if kind in ("drone", "operator") or re.match(r"^a-.-A.*-Q(-|$)", ctype):
        return "drones"
    if re.match(r"^a-.-A", ctype):
        return "aircraft"
    if re.match(r"^a-.-G", ctype):
        return "ground"
    if re.match(r"^a-.-[SU]", ctype):
        return "vessels"
    return "other"


def tracks(center=None, radius_km=0, hide=(), counts=None):
    now = time.time()
    out = []
    for path in glob.glob(rpath("tracks.d", "*")):
        p = first_line(path).split("|")
        if len(p) < 7:
            continue
        lat, lon, ts = num(p[0]), num(p[1]), num(p[5], 0)
        if lat is None or lon is None or now - ts > TRACK_MAX_AGE:
            continue
        if p[6] == "mine":            # your own markers come from items.txt instead
            continue
        stale = num(p[7], 0) if len(p) > 7 else 0
        if stale and stale < now and p[6] != "client":   # TAK users stay, shown as stale (like ATAK)
            continue
        if radius_km > 0 and center and dist_m(center[0], center[1], lat, lon) > radius_km * 1000:
            continue
        cat = category(p[3], p[6])
        if counts is not None:
            counts[cat] = counts.get(cat, 0) + 1
        if cat in hide:
            continue
        out.append({"id": os.path.basename(path), "lat": lat, "lon": lon, "cs": p[2], "type": p[3],
                    "team": p[4], "ts": ts, "kind": p[6], "cat": cat, "stale": stale})
    out.sort(key=lambda t: t["cs"].lower())
    return out


def contacts():
    out = []
    try:
        with open(rpath("contacts"), encoding="utf-8", errors="replace") as fh:
            for line in fh:
                cs, _, uid = line.rstrip("\n").rpartition("|")
                if cs and uid:
                    out.append({"cs": cs, "uid": uid})
    except OSError:
        pass
    out.sort(key=lambda c: c["cs"].lower())
    return out


def device_word():
    """What the console calls the device: "Pager" for PagerTAK, "Pineapple" for PineappleTAK."""
    p = ARGS.product
    return p[:-3] if p.endswith("TAK") and len(p) > 3 else p


def watch_scan():
    """Networks from the last watch_scan command: [{hex, ssid, aps, enc}]."""
    out = []
    for line in tail_lines(rpath("watch_scan.tsv"), 500):
        f = line.split("\t")
        if len(f) < 3:
            continue
        h = f[0]
        try:
            name = "" if h == "-" else bytes.fromhex(h).decode("utf-8", "replace")
        except ValueError:
            continue
        out.append({"hex": h, "ssid": name, "aps": int(num(f[1], 0)), "enc": f[2]})
    return out


def bt_adapter():
    try:
        return bool(os.listdir("/sys/class/bluetooth"))
    except OSError:
        return False


def pid_alive(name):
    try:
        pid = int(first_line(rpath(name)))
        os.kill(pid, 0)
        return True
    except (ValueError, OSError):
        return False


def tail_lines(path, n):
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 64 * 1024))
            data = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    lines = data.splitlines()
    if size > 64 * 1024:
        lines = lines[1:]
    return lines[-n:]


def hex_to_str(h):
    if not h or h == "-":
        return ""
    try:
        return "".join(c for c in binascii.unhexlify(h).decode("utf-8", "replace") if c >= " ")
    except (binascii.Error, ValueError):
        return ""


def alerts():
    out = []
    for line in tail_lines(rpath("watch_alerts"), 30):
        p = line.split("\t")
        if len(p) >= 4:
            mac = ":".join(p[3][i:i + 2] for i in range(0, len(p[3]), 2)).upper()
            out.append({"ts": num(p[0], 0), "kind": p[1], "text": "%s '%s' %s" % (p[1], hex_to_str(p[2]) or "hidden", mac),
                        "sev": "high" if p[1] in ("EVIL TWIN", "DOWNGRADE") else "med"})
    for line in tail_lines(rpath("trk_alerts"), 30):
        p = line.split("|")
        if len(p) >= 4:
            out.append({"ts": num(p[0], 0), "kind": p[1], "text": "%s %s %s %s" % (p[1], p[3], p[2], p[4] if len(p) > 4 else ""),
                        "sev": "high" if p[1] == "FOLLOWING" else "med"})
    for line in tail_lines(rpath("md_alerts"), 30):
        p = line.split("|")
        if len(p) >= 4:
            out.append({"ts": num(p[0], 0), "kind": p[1], "text": "%s %s: %s" % (p[1], p[2], p[3]),
                        "sev": "med" if p[1] == "OK" else "high"})
    for line in tail_lines(rpath("geo_alerts"), 30):
        p = line.split("|")
        if len(p) >= 4:
            out.append({"ts": num(p[0], 0), "kind": "GEOFENCE", "text": "%s %s %s" % (p[3], "entered" if p[1] == "ENTER" else "left", p[2]),
                        "sev": "high" if p[1] == "ENTER" else "med"})
    out.sort(key=lambda a: a["ts"], reverse=True)
    return out[:40]


RE_CHAT = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (IN |OUT) \[([^\]]*)\] ([^:]*): (.*)$")
RE_EMERG = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (?:OUT )?(EMERGENCY.*)$")
RE_FILE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) FILE (.*)$")


def chat_files():
    return sorted(glob.glob(os.path.join(ARGS.loot, "chat_*.log")))[-2:]


def chat_sig():
    sig = []
    try:
        sig.append("r%d" % int(os.stat(rpath("sent.d")).st_mtime))   # receipts arrived
    except OSError:
        pass
    for f in chat_files():
        try:
            st = os.stat(f)
            sig.append("%s:%d:%d" % (os.path.basename(f), st.st_size, int(st.st_mtime)))
        except OSError:
            pass
    return ",".join(sig)


def receipts():
    """{(to_callsign, text): [(epoch, state)]} for messages sent in the last day (sent.d/<messageId>)."""
    out = {}
    for path in glob.glob(os.path.join(rpath("sent.d"), "*")):
        p = first_line(path).split("|")
        if len(p) < 4:
            continue
        out.setdefault((p[1], "|".join(p[2:-1])), []).append((num(p[0], 0), p[-1]))
    return out


def receipt_for(rc, row):
    to = row["room"][3:] if row["room"].startswith("DM ") else "All"
    try:
        t = time.mktime(time.strptime(row["t"], "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return None
    # The chat log has local clock time and sent.d has epoch seconds. The console and
    # the payload can disagree on the time zone (the Mark VII sets one, Python may not
    # see it), so accept any whole time-zone offset (15-minute steps, up to 14 h).
    best = None
    for ts, st in rc.get((to, row["text"]), []):
        d = ts - t
        if abs(d) <= 14 * 3600 + 5 and abs(d - round(d / 900.0) * 900) <= 5:
            if best is None or abs(d) < best[0]:
                best = (abs(d), st)
    return best[1] if best else None


def line_id(line):
    return hashlib.sha1(line.encode("utf-8", "replace")).hexdigest()[:16]


def chat_delete(lid):
    """Removes one message (by line_id) from the chat logs on the Pager. Not from other TAK devices."""
    if not re.match(r"^[0-9a-f]{16}$", lid or ""):
        return False
    for f in reversed(chat_files()):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().split("\n")
        except OSError:
            continue
        for i in range(len(lines) - 1, -1, -1):
            if lines[i] and line_id(lines[i]) == lid:
                del lines[i]
                tmp = f + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(lines))
                os.replace(tmp, f)
                return True
    return False


def chat_history(limit=150):
    files = chat_files()
    rc = receipts()
    lines = []
    for f in files:
        lines.extend(tail_lines(f, limit))
    out = []
    for line in lines[-limit:]:
        m = RE_CHAT.match(line)
        if m:
            row = {"t": m.group(1), "dir": m.group(2).strip().lower(), "room": m.group(3),
                   "from": m.group(4), "text": m.group(5), "id": line_id(line)}
            if row["dir"] == "out" and row["room"].startswith("DM "):
                row["rcpt"] = receipt_for(rc, row)
            out.append(row)
            continue
        m = RE_EMERG.match(line) or RE_FILE.match(line)
        if m:
            out.append({"t": m.group(1), "dir": "sys", "room": "All", "from": "", "text": m.group(2), "id": line_id(line)})
    return out


def reports(limit=20):
    path = os.path.join(ARGS.loot, "reports.log")
    out, cur = [], None
    for line in tail_lines(path, 400):
        if line.startswith("== "):
            cur = {"head": line[3:], "body": []}
            out.append(cur)
        elif cur is not None:
            cur["body"].append(line)
    for r in out:
        r["body"] = "\n".join(r["body"])
    return out[-limit:][::-1]


def surveys():
    root = os.path.join(ARGS.loot, "surveys")
    out = []
    for meta in sorted(glob.glob(os.path.join(root, "*", "meta")))[-10:]:
        p = first_line(meta).split("|")
        d = os.path.dirname(meta)
        out.append({"dir": os.path.basename(d), "name": p[0] if p else "", "start": num(p[1] if len(p) > 1 else 0, 0),
                    "end": num(p[2] if len(p) > 2 else 0, 0), "active": os.path.exists(os.path.join(d, "active")),
                    "zips": [os.path.basename(z) for z in glob.glob(os.path.join(d, "*.zip"))]})
    return out[::-1]


def state():
    cfg = read_kv(rpath("web_cfg"))
    st = first_line(rpath("status")).split("|")
    try:
        queued = len([f for f in os.listdir(rpath("outbox")) if f.endswith(".cot")])
    except OSError:
        queued = 0
    survey_dir = first_line(rpath("survey.dir"))
    me = self_position(cfg)
    radius = num(cfg.get("cot_radius"), 0) or 0
    center = (me["lat"], me["lon"]) if me["lat"] is not None else None
    md = first_line(rpath("mandown")).split("|")
    em = first_line(rpath("emergency")).split("|") if os.path.exists(rpath("emergency")) else None
    hide = tuple(c for c in cfg.get("cot_hide", "").split(",") if c in CATS)
    counts = {}
    trk = tracks(center, radius, hide, counts)
    return {
        "version": cfg.get("version", ""), "device": cfg.get("device", ""),
        "callsign": cfg.get("callsign", ""), "uid": cfg.get("uid", ""), "team": cfg.get("team", ""),
        "role": cfg.get("role", ""),
        "server": {"host": cfg.get("host", ""), "port": cfg.get("port", ""), "proto": cfg.get("proto", ""),
                   "state": st[0] if st and st[0] else "starting", "last_sa": st[1] if len(st) > 1 else "",
                   "error": st[2] if len(st) > 2 else ""},
        "interval": cfg.get("interval", ""), "manual_pos": cfg.get("manual_pos", ""),
        "map_source": cfg.get("map_source", ""), "quick": [q for q in cfg.get("quick", "").split("|") if q],
        "battery": first_line(rpath("battery")), "queued": queued,
        "unread": len(tail_lines(rpath("unread"), 500)), "receipts": cfg.get("receipts", "1") == "1",
        "web": {"listen": cfg.get("web_listen", "all"), "urls": cfg.get("web_urls", "").split()},
        "emergency": em is not None,
        "emergency_info": {"kind": (em[0] if em and em[0] else "911"), "label": em[1] if em and len(em) > 1 else "",
                           "dest": em[2] if em and len(em) > 2 else ""} if em is not None else None,
        "radius_km": radius,
        "self": me, "tracks": trk, "contacts": contacts(), "hide": list(hide), "counts": counts,
        "sensors": {
            "watch": {"on": cfg.get("watch") == "1", "running": pid_alive("watch.pid"), "profile": cfg.get("watch_profile", "")},
            "trk": {"on": cfg.get("trk") == "1", "running": pid_alive("trk.pid"),
                    "tools": bool(shutil.which("btmon") and shutil.which("hcitool")), "adapter": bt_adapter()},
            "rid": {"on": cfg.get("rid") == "1", "running": pid_alive("rid_worker.pid"), "channel": cfg.get("rid_channel", "6"),
                    "tools": bool(shutil.which("tcpdump"))},
            "installing": pid_alive("install.pid"),
            "recon": {"on": cfg.get("recon") == "1"},
            "survey": {"running": pid_alive("survey.pid"), "dir": os.path.basename(survey_dir) if survey_dir else ""},
            "md": {"on": cfg.get("md") == "1", "running": pid_alive("md.pid"), "min": int(num(cfg.get("md_min"), 10) or 10),
                   "me": cfg.get("md_me", "1") == "1", "who": [w for w in cfg.get("md_who", "").split(",") if w],
                   "chat": cfg.get("md_chat") == "1", "state": md[0], "deadline": num(md[1] if len(md) > 1 else 0, 0)},
            "available": [s for s in cfg.get("modules", "").split(",") if s],
        },
        "alerts": alerts(), "geofences": geofences(), "items": items(),
        "fox": os.path.exists(rpath("fox.pid")) and pid_alive("fox.pid"),
        "setup": cfg.get("setup") == "1",
        "cert": {"days": int(num(cfg.get("cert_days"), -9999)) if cfg.get("cert_days", "") != "" else None,
                 "cn": cfg.get("cert_cn", "")},
    }


def state_json():
    def build():
        body = json.dumps(state(), sort_keys=True)
        return body, hashlib.sha1(body.encode()).hexdigest()[:16]
    return cached("state", 1.0, build)


def items():
    """Markers you made (web console): id|kind|name|type|lat|lon|color|remarks|sent|created"""
    out = []
    try:
        with open(ARGS.items, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                p = line.rstrip("\n").split("|")
                if len(p) >= 10 and num(p[4]) is not None and num(p[5]) is not None:
                    out.append({"id": p[0], "kind": p[1], "name": p[2], "type": p[3], "lat": num(p[4]), "lon": num(p[5]),
                                "color": p[6], "remarks": p[7], "sent": p[8], "created": num(p[9], 0)})
    except OSError:
        pass
    return out


def geofences():
    out = []
    try:
        with open(ARGS.geofences, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                p = line.rstrip("\n").split("|")
                if len(p) < 6:
                    continue
                pts = []
                for pair in p[3].split(";"):
                    a = pair.split(",")
                    if len(a) >= 2 and num(a[0]) is not None and num(a[1]) is not None:
                        pts.append([num(a[0]), num(a[1])] + ([num(a[2])] if len(a) > 2 and num(a[2]) is not None else []))
                sent = p[6] if len(p) > 6 else ""
                sent = {"1": "all", "0": ""}.get(sent, sent)
                out.append({"id": p[0], "name": p[1], "shape": p[2], "pts": pts, "who": p[4], "chat": p[5] == "1",
                            "sent": sent, "alert": p[7] if len(p) > 7 else ""})
    except OSError:
        pass
    return out


# --------------------------------------------------------------------------
# SIGINT (read-only; only while the SIGINT tab is open)
# --------------------------------------------------------------------------
MON_IF = "wlan1mon"


def run(cmd, timeout=6):
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout)
        return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def find_iface(data, iface):
    if isinstance(data, list):
        for item in data:
            f = find_iface(item, iface)
            if f is not None:
                return f
    elif isinstance(data, dict):
        names = [data.get(k) for k in ("interface", "iface", "ifname", "name", "device")]
        if iface in names:
            return data
        for k, v in data.items():
            if k == iface and isinstance(v, dict):
                return v
            f = find_iface(v, iface)
            if f is not None:
                return f
    return None


def radio_state():
    out = {"iface": MON_IF, "hop": None, "channel": None, "owner": first_line(rpath("radio.owner")),
           "pineap": False}
    raw = run(["_pineap", "INTERFACE", "LIST", "format=json"])
    if raw:
        out["pineap"] = True
        try:
            d = find_iface(json.loads(raw), MON_IF)
        except ValueError:
            d = None
        if d:
            hop = d.get("hoprate", d.get("hop_rate", d.get("hopRate")))
            out["hop"] = int(hop) if num(hop) is not None else None
            out["channel"] = int(d["channel"]) if num(d.get("channel")) is not None else None
    if not out["channel"]:
        m = re.search(r"^\s*channel\s+(\d+)", run(["iw", "dev", MON_IF, "info"]), re.M)
        if m:
            out["channel"] = int(m.group(1))
    out["rid"] = pid_alive("rid_worker.pid")
    return out


def enc_name(e):
    e = int(num(e, 0) or 0)
    if e == 0:
        return "Open"
    if (e & 16 or e & 64) and e & 8:
        return "WPA2/3"
    if e & 16 or e & 64:
        return "WPA3"
    if e & 8:
        return "WPA2"
    if e & 4:
        return "WPA"
    if e & 2:
        return "WEP"
    return "?%d" % e


def fmt_mac(m):
    m = (m or "").lower().replace("-", ":")
    if re.match(r"^[0-9a-f]{12}$", m):
        m = ":".join(m[i:i + 2] for i in range(0, 12, 2))
    return m


def recon_query(sql):
    db = read_kv(rpath("web_cfg")).get("recon_db", "")
    if not db or not os.path.exists(db):
        return None
    out = run(["sqlite3", "-readonly", "-separator", "\t", "-cmd", ".timeout 2000", db, sql], timeout=8)
    return [line.split("\t") for line in out.splitlines() if line]


def wifi_tables(mins):
    since = int(time.time()) - mins * 60
    aps = recon_query(
        "SELECT lower(bssid), CASE WHEN ssid IS NULL OR hex(ssid)='' THEN '-' ELSE hex(ssid) END, IFNULL(encryption,0),"
        " IFNULL(channel,0), IFNULL(signal,0), MAX(time), COUNT(*) FROM ssid WHERE type=8 AND bssid!='' AND time>=%d"
        " GROUP BY lower(bssid) ORDER BY 5 DESC LIMIT 400;" % since)
    probes = recon_query(
        "SELECT lower(wifi_device), CASE WHEN ssid IS NULL OR hex(ssid)='' THEN '-' ELSE hex(ssid) END, IFNULL(signal,0),"
        " MAX(time), COUNT(*) FROM ssid WHERE type=4 AND IFNULL(wifi_device,'')!='' AND time>=%d"
        " GROUP BY lower(wifi_device), hex(IFNULL(ssid,'')) ORDER BY 4 DESC LIMIT 600;" % since)
    res = {"db": aps is not None, "aps": [], "probes": [], "clients": []}
    for r in aps or []:
        if len(r) >= 7:
            res["aps"].append({"mac": fmt_mac(r[0]), "ssid": hex_to_str(r[1]), "hidden": r[1] == "-", "enc": enc_name(r[2]),
                               "ch": int(num(r[3], 0)), "sig": int(num(r[4], 0)), "ts": num(r[5], 0), "n": int(num(r[6], 0))})
    for r in probes or []:
        if len(r) >= 5:
            res["probes"].append({"mac": fmt_mac(r[0]), "ssid": hex_to_str(r[1]), "sig": int(num(r[2], 0)),
                                  "ts": num(r[3], 0), "n": int(num(r[4], 0))})
    raw = run(["_pineap", "RECON", "CLIENTS", "limit=200", "format=json"])
    try:
        data = json.loads(raw) if raw else []
    except ValueError:
        data = []
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    for c in data if isinstance(data, list) else []:
        if isinstance(c, dict) and c.get("mac"):
            res["clients"].append({"mac": fmt_mac(str(c.get("mac", ""))), "ap": fmt_mac(str(c.get("ap_mac", c.get("bssid", "")))),
                                   "ssid": str(c.get("ssid", c.get("ap_ssid", "")) or ""),
                                   "sig": int(num(c.get("signal", c.get("rssi")), 0) or 0),
                                   "ch": int(num(c.get("channel"), 0) or 0)})
    return res


def fox_state():
    cur = first_line(rpath("fox.cur")).split("|")
    out = {"running": pid_alive("fox.pid"), "target": "", "label": "", "dbm": None, "best": None, "best_pos": None,
           "n": 0, "ts": 0, "track": []}
    if len(cur) >= 9:
        out.update({"target": cur[0], "label": cur[1], "start": num(cur[2], 0), "dbm": num(cur[3]), "best": num(cur[4]),
                    "best_pos": [num(cur[5]), num(cur[6])] if num(cur[5]) is not None else None,
                    "n": int(num(cur[7], 0)), "ts": num(cur[8], 0)})
    for line in tail_lines(rpath("fox.track"), 600):
        p = line.split()
        if len(p) >= 4 and num(p[1]) is not None:
            out["track"].append([num(p[0], 0), num(p[1]), num(p[2]), num(p[3])])
    return out


# --------------------------------------------------------------------------
# breadcrumb trails (sampled here every 15 s; kept one hour, in memory)
# --------------------------------------------------------------------------
def trail_sampler():
    while True:
        try:
            now = time.time()
            cfg = read_kv(rpath("web_cfg"))
            pts = [("self", self_position(cfg))]
            pts += [(t["id"], t) for t in tracks() if t["cat"] in ("users", "drones", "aircraft", "vessels")]
            if os.path.exists(rpath("trails.clear")):        # "Clear received items" was pressed
                with LOCK:
                    TRAILS.clear()
                try:
                    os.remove(rpath("trails.clear"))
                except OSError:
                    pass
            with LOCK:
                for tid, p in pts:
                    if p.get("lat") is None:
                        continue
                    tr = TRAILS.setdefault(tid, [])
                    if not tr or dist_m(tr[-1][1], tr[-1][2], p["lat"], p["lon"]) >= 10:
                        tr.append([int(now), round(p["lat"], 6), round(p["lon"], 6)])
                    while tr and now - tr[0][0] > TRAIL_KEEP:
                        tr.pop(0)
                for tid in [k for k, v in TRAILS.items() if not v]:
                    del TRAILS[tid]
        except Exception as e:  # never let the sampler die
            sys.stderr.write("trails: %r\n" % e)
        time.sleep(15)


# --------------------------------------------------------------------------
# offline tile download (one job at a time, in the background)
# --------------------------------------------------------------------------
def tile_range(s, w, n, e, z):
    import math

    def xy(lat, lon):
        lat = max(-85.0511, min(85.0511, lat))
        x = int((lon + 180) / 360 * 2 ** z)
        y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * 2 ** z)
        return min(max(x, 0), 2 ** z - 1), min(max(y, 0), 2 ** z - 1)
    x0, y0 = xy(n, w)
    x1, y1 = xy(s, e)
    return x0, x1, y0, y1


def job_plan(b):
    s_, w, n, e = (float(b[k]) for k in ("s", "w", "n", "e"))
    z0, z1 = int(b["zmin"]), int(b["zmax"])
    if not (-90 <= s_ < n <= 90 and -180 <= w < e <= 180 and 0 <= z0 <= z1 <= 19):
        raise ValueError("bad area")
    count = 0
    for z in range(z0, z1 + 1):
        x0, x1, y0, y1 = tile_range(s_, w, n, e, z)
        count += (x1 - x0 + 1) * (y1 - y0 + 1)
    return (s_, w, n, e, z0, z1), count


def job_run(src, plan, total):
    s_, w, n, e, z0, z1 = plan
    done = got = 0
    for z in range(z0, z1 + 1):
        x0, x1, y0, y1 = tile_range(s_, w, n, e, z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                if JOB.get("cancel"):
                    JOB.update(state="cancelled")
                    return
                path = os.path.join(ARGS.tiles, src["slug"], str(z), str(x), "%d.png" % y)
                if not os.path.exists(path):
                    with FETCH_SEM:
                        if PM.fetch_tile(src, path, z, x, y):
                            got += 1
                done += 1
                JOB.update(done=done, got=got)
    JOB.update(state="done", done=done, got=got)


# --------------------------------------------------------------------------
# overlays (KML / KMZ files, drawn by the browser)
# --------------------------------------------------------------------------
def overlay_list():
    out = []
    for f in sorted(glob.glob(os.path.join(ARGS.overlays, "*"))):
        if f.lower().endswith((".kml", ".kmz")):
            out.append({"name": os.path.basename(f), "size": os.path.getsize(f)})
    return out


def move_file(src, dst):
    """os.replace, but also across filesystems (uploads land in /tmp, overlays live on the payload's disk)."""
    try:
        os.replace(src, dst)
        return
    except OSError:
        pass
    tmp = dst + ".part"
    with open(src, "rb") as fi, open(tmp, "wb") as fo:
        while True:
            b = fi.read(65536)
            if not b:
                break
            fo.write(b)
    os.replace(tmp, dst)
    os.remove(src)


def safe_name(name, exts):
    base = os.path.basename(name or "")
    root, ext = os.path.splitext(base)
    root = re.sub(r"[^A-Za-z0-9 ._-]", "_", root).strip(" .")[:60] or "file"
    ext = ext.lower()
    return (root + ext) if ext in exts else None


# --------------------------------------------------------------------------
# CoT details (last raw event per track, saved by the payload in RUN/cot.d)
# --------------------------------------------------------------------------
def attrs(tag_xml):
    # TAK clients use either quote style
    return {k: (a if a or not b else b) for k, a, b in re.findall(r"""([A-Za-z_][\w:.-]*)=(?:"([^"]*)"|'([^']*)')""", tag_xml)}


def xml_unesc(v):
    return v.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&")


def cot_details(tid):
    if not re.match(r"^[A-Za-z0-9._-]{1,200}$", tid):
        return None
    try:
        with open(rpath("cot.d", tid), encoding="utf-8", errors="replace") as fh:
            raw = fh.read(16000)
    except OSError:
        return None
    out = {"raw": raw}
    m = re.search(r"<event\b[^>]*>", raw)
    if m:
        out["event"] = {k: xml_unesc(v) for k, v in attrs(m.group(0)).items()}
    for tag in ("point", "contact", "__group", "takv", "track", "status", "precisionlocation", "uid", "emergency"):
        m = re.search(r"<%s\b[^>]*/?>" % re.escape(tag), raw)
        if m:
            out[tag.strip("_")] = {k: xml_unesc(v) for k, v in attrs(m.group(0)).items()}
    m = re.search(r"<remarks\b[^>]*>(.*?)</remarks>", raw, re.S)
    if m:
        out["remarks"] = xml_unesc(m.group(1))[:2000]
    out["links"] = [{k: xml_unesc(v) for k, v in attrs(t).items()} for t in re.findall(r"<link\b[^>]*/?>", raw)][:10]
    return out


# --------------------------------------------------------------------------
# commands -> payload
# --------------------------------------------------------------------------
RE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,30}$")


def clean(v, maxlen=400):
    if isinstance(v, bool):
        v = "1" if v else "0"
    v = str(v)
    v = "".join(c if c >= " " or c == "\t" else " " for c in v).replace("\t", " ")
    return v[:maxlen].strip()


def submit(cmd, fields, upload=None, upload_path=None, wait=15):
    qdir = rpath("webcmd")
    os.makedirs(qdir, exist_ok=True)
    cid = "%d-%s" % (int(time.time() * 1000), binascii.hexlify(os.urandom(4)).decode())
    lines = ["cmd=" + cmd]
    for k, v in fields.items():
        if k == "cmd" or not RE_KEY.match(k):
            continue
        if isinstance(v, (list, tuple)):
            v = " ".join(clean(x, 40) for x in v)
        if isinstance(v, (dict,)):
            continue
        lines.append("%s=%s" % (k, clean(v)))
    if upload_path is not None:
        up = os.path.join(qdir, cid + ".upload")
        os.replace(upload_path, up)
        os.chmod(up, 0o600)
        lines.append("upload=" + up)
    if upload is not None:
        up = os.path.join(qdir, cid + ".upload")
        with open(up, "wb") as fh:
            fh.write(upload)
        os.chmod(up, 0o600)
        lines.append("upload=" + up)
    tmp = os.path.join(qdir, cid + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        os.chmod(tmp, 0o600)                         # may hold a certificate password
        fh.write("\n".join(lines) + "\n")
    os.rename(tmp, os.path.join(qdir, cid + ".req"))
    res = os.path.join(qdir, cid + ".res")
    deadline = time.time() + wait
    while time.time() < deadline:
        if os.path.exists(res):
            line = first_line(res)
            try:
                os.remove(res)
            except OSError:
                pass
            ok, _, msg = line.partition("|")
            return {"ok": ok == "ok", "msg": msg}
        time.sleep(0.2)
    return {"ok": True, "msg": "Queued - the payload has not answered yet", "queued": True}


# --------------------------------------------------------------------------
# tiles
# --------------------------------------------------------------------------
def sources():
    out = []
    if PM is not None:
        out = PM.load_sources(ARGS.sources)
        if ARGS.tile_url and "example.com" not in ARGS.tile_url:
            out.append(PM.make_source("Custom", ARGS.tile_url, 0, 19))
    return out


def build_package(path, name):
    """Wraps one file in an ATAK data package (MANIFEST + file, stored, no compression)."""
    from ptak_zip import ZipWriter, uuid4      # zipfile needs urllib, which python3-light lacks
    uid = uuid4()
    zpath = path + ".zip"
    manifest = ('<MissionPackageManifest version="2"><Configuration>'
                '<Parameter name="uid" value="%s"/><Parameter name="name" value="%s"/>'
                '</Configuration><Contents><Content ignore="false" zipEntry="%s/%s"/></Contents>'
                '</MissionPackageManifest>') % (uid, esc(os.path.splitext(name)[0]), uid, esc(name))
    with ZipWriter(zpath, deflate=False) as z:
        z.add("MANIFEST/manifest.xml", manifest)
        z.add_file("%s/%s" % (uid, name), path)
    return zpath


def _pref(xml, key):
    m = re.search(r'<entry[^>]*key="%s"[^>]*>([^<]*)</entry>' % re.escape(key), xml)
    return m.group(1).strip() if m else ""


def read_connection_package(path):
    """ATAK connection data package (.zip with a .pref and .p12 files) -> import_pkg fields.
    The .p12 files are written next to the command queue for the payload to convert."""
    from ptak_zip import read_zip
    with open(path, "rb") as fh:
        files = read_zip(fh.read())
    prefs = [n for n in files if n.lower().endswith(".pref")]
    if not prefs:
        raise ValueError("No .pref file in that package - is it an ATAK connection data package?")
    xml = "\n".join(files[n].decode("utf-8", "replace") for n in prefs)
    conn = _pref(xml, "connectString0")
    parts = conn.split(":")
    if len(parts) < 2:
        raise ValueError("No TAK Server connection (connectString0) in that package")
    host, port, proto = parts[0], parts[1], (parts[2] if len(parts) > 2 else "ssl")
    by_base = {os.path.basename(n): n for n in files if n.lower().endswith(".p12")}
    fields = {"host": host, "port": port, "proto": proto,
              "client_pw": _pref(xml, "clientPassword") or "atakatak", "ca_pw": _pref(xml, "caPassword") or "atakatak"}
    qdir = rpath("webcmd")
    os.makedirs(qdir, exist_ok=True)
    tag = binascii.hexlify(os.urandom(6)).decode()
    for kind, key in (("client", "certificateLocation"), ("ca", "caLocation")):
        name = os.path.basename(_pref(xml, key))
        if name in by_base:
            out = os.path.join(qdir, "%s-%s.p12" % (tag, kind))
            fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(files[by_base[name]])
            fields[kind + "_file"] = os.path.basename(out)
    return fields


def esc(v):
    return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def bg_worker():
    """Caches tiles the browser fetched straight from the internet, one at a time."""
    while True:
        with BG_COND:
            while not BG_QUEUE:
                BG_COND.wait()
            src, path, z, x, y = BG_QUEUE.pop()          # newest first: what the user is looking at now
            BG_SET.discard(path)
        if not os.path.exists(path):
            with FETCH_SEM:
                PM.fetch_tile(src, path, z, x, y)
        time.sleep(0.05)


def bg_cache(src, path, z, x, y):
    with BG_COND:
        if path in BG_SET:
            return
        if len(BG_QUEUE) >= 300:
            BG_SET.discard(BG_QUEUE.pop(0)[1])
        BG_QUEUE.append((src, path, z, x, y))
        BG_SET.add(path)
        BG_COND.notify()


def tile(slug, z, x, y, fetch):
    """-> (data, None) | (None, redirect_url) | (None, None)"""
    if not re.match(r"^[a-z0-9_]{1,64}$", slug) or not (0 <= z <= 22) or x < 0 or y < 0 or x >= 2 ** z or y >= 2 ** z:
        return None, None
    path = os.path.join(ARGS.tiles, slug, str(z), str(x), "%d.png" % y)
    if not os.path.exists(path) and not ARGS.offline:
        src = next((s for s in cached("sources", 30, sources) if s["slug"] == slug), None)
        if src and "example.com" not in src["url"] and src["minz"] <= z <= max(src["maxz"], 19):
            if not fetch:
                # fastest: the browser loads it from the internet, the Pager caches a copy behind it
                bg_cache(src, path, z, x, y)
                return None, PM.tile_url(src, z, x, y)
            with FETCH_SEM:
                if not os.path.exists(path):
                    PM.fetch_tile(src, path, z, x, y)
    try:
        with open(path, "rb") as fh:
            return fh.read(), None
    except OSError:
        return None, None


def tile_type(data):
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF":
        return "image/webp"
    return "image/png"


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class Req:
    def __init__(self, method, path, query, headers, body, ip, version="HTTP/1.0"):
        self.method, self.path, self.query, self.headers, self.body, self.ip = method, path, query, headers, body, ip
        self.version = version

    def cookie(self, name):
        for part in self.headers.get("cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return ""

    def json(self):
        try:
            v = json.loads(self.body.decode("utf-8") or "{}")
            return v if isinstance(v, dict) else {}
        except (ValueError, UnicodeDecodeError):
            return {}


def unquote(s):
    s = s.replace("+", " ")
    out, i = bytearray(), 0
    b = s.encode("utf-8", "replace")
    while i < len(b):
        if b[i:i + 1] == b"%" and i + 2 < len(b) and re.match(rb"[0-9A-Fa-f]{2}", b[i + 1:i + 3]):
            out.append(int(b[i + 1:i + 3], 16))
            i += 3
        else:
            out.append(b[i])
            i += 1
    return out.decode("utf-8", "replace")


def parse_query(q):
    out = {}
    for part in q.split("&"):
        if part:
            k, _, v = part.partition("=")
            out[unquote(k)] = unquote(v)
    return out


class Handler(socketserver.BaseRequestHandler):
    def setup(self):
        self.request.settimeout(20)
        self.buf = b""
        self.keep = False

    def read_request(self):
        buf = self.buf
        while b"\r\n\r\n" not in buf:
            chunk = self.request.recv(8192)
            if not chunk:
                return None
            buf += chunk
            if len(buf) > MAX_HEADER:
                return "too_big"
        head, _, rest = buf.partition(b"\r\n\r\n")
        lines = head.decode("iso-8859-1").split("\r\n")
        try:
            method, target, version = lines[0].split(" ", 2)
        except ValueError:
            return None
        headers = {}
        for line in lines[1:]:
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()
        try:
            n = int(headers.get("content-length", "0"))
        except ValueError:
            n = 0
        path, _, query = target.partition("?")
        spath = unquote(path)
        if method.upper() == "POST" and spath in STREAM_LIMITS:
            return self.stream_body(method, spath, query, headers, rest, n, version)
        if n > MAX_BODY or n < 0:
            return "too_big"
        body, self.buf = rest[:n], rest[n:]
        while len(body) < n:
            chunk = self.request.recv(min(65536, n - len(body)))
            if not chunk:
                break
            body += chunk
        return Req(method.upper(), spath, parse_query(query), headers, body[:n], self.client_address[0],
                   version.strip().upper())

    def stream_body(self, method, path, query, headers, rest, n, version):
        """Large uploads go straight to a temp file, and only for a signed-in browser."""
        req = Req(method.upper(), path, parse_query(query), headers, b"", self.client_address[0], version.strip().upper())
        if n <= 0 or n > STREAM_LIMITS[path] or headers.get("x-pagertak") != "1" or not self.authed(req):
            return "too_big"
        os.makedirs(rpath("webcmd"), exist_ok=True)
        tmp = rpath("webcmd", "upl-%s.part" % binascii.hexlify(os.urandom(6)).decode())
        got = 0
        with open(tmp, "wb") as fh:
            part = rest[:n]
            fh.write(part)
            got = len(part)
            while got < n:
                chunk = self.request.recv(min(65536, n - got))
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
        self.buf = rest[n:] if len(rest) > n else b""
        if got < n:
            os.remove(tmp)
            return None
        req.file = tmp
        return req

    def send(self, code, body=b"", ctype="application/json", extra=None):
        reason = {200: "OK", 204: "No Content", 302: "Found", 304: "Not Modified", 400: "Bad Request", 401: "Unauthorized",
                  403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed", 413: "Payload Too Large",
                  429: "Too Many Requests", 500: "Internal Server Error"}.get(code, "OK")
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        h = ["HTTP/1.1 %d %s" % (code, reason), "Content-Type: " + ctype, "Content-Length: %d" % len(body),
             "Connection: " + ("keep-alive" if self.keep else "close"), "X-Content-Type-Options: nosniff",
             "X-Frame-Options: DENY",
             "Referrer-Policy: no-referrer",
             "Content-Security-Policy: default-src 'self'; img-src 'self' data: blob: https: http:; "
             "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"]
        if ctype.startswith("application/json"):
            h.append("Cache-Control: no-store")
        for k, v in (extra or {}).items():
            h.append("%s: %s" % (k, v))
        try:
            self.request.sendall(("\r\n".join(h) + "\r\n\r\n").encode() + body)
        except OSError:
            pass

    def handle(self):
        for _ in range(500):                      # HTTP/1.1 keep-alive: many requests per connection
            try:
                req = self.read_request()
            except (OSError, socket.timeout):
                return
            if req is None:
                return
            if req == "too_big":
                self.keep = False
                self.send(413, {"error": "too large"})
                return
            conn = req.headers.get("connection", "").lower()
            self.keep = (req.version == "HTTP/1.1" and conn != "close") or conn == "keep-alive"
            try:
                self.route(req)
            except Exception as e:  # keep serving; report the error to the browser
                sys.stderr.write("error %s %s: %r\n" % (req.method, req.path, e))
                self.keep = False
                self.send(500, {"error": "server error"})
            if not self.keep:
                return
            self.request.settimeout(15)

    # ---- auth helpers
    def authed(self, req):
        tok = req.cookie(COOKIE)
        now = time.time()
        with LOCK:
            exp = SESSIONS.get(tok)
            if tok and exp and exp > now:
                SESSIONS[tok] = now + SESSION_TTL
                return True
        return False

    def login(self, req):
        now = time.time()
        with LOCK:
            cnt, until = FAILS.get(req.ip, (0, 0))
        if until > now:
            self.send(429, {"error": "Too many attempts. Try again in %d s." % int(until - now)})
            return
        pw = str(req.json().get("password", ""))[:200]
        auth = first_line(ARGS.auth)
        if auth and pw and check_password(pw, auth):
            tok = binascii.hexlify(os.urandom(24)).decode()
            with LOCK:
                FAILS.pop(req.ip, None)
                for k in [k for k, v in SESSIONS.items() if v < now]:
                    del SESSIONS[k]
                while len(SESSIONS) >= 20:
                    del SESSIONS[min(SESSIONS, key=SESSIONS.get)]
                SESSIONS[tok] = now + SESSION_TTL
            flags = "; HttpOnly; SameSite=Strict; Path=/" + ("; Secure" if ARGS.tls_cert else "")
            self.send(200, {"ok": True}, extra={"Set-Cookie": "%s=%s%s" % (COOKIE, tok, flags)})
            return
        cnt += 1
        lock = 0 if cnt < 5 else min(900, 60 * (2 ** (cnt - 5)))
        with LOCK:
            FAILS[req.ip] = (cnt, now + lock)
        time.sleep(1)
        self.send(401, {"error": "Wrong password" + (" - locked for %d s" % lock if lock else "")})

    # ---- routing
    def route(self, req):
        p = req.path
        if req.method == "GET" and (p == "/" or p.startswith("/static/")):
            return self.static("index.html" if p == "/" else p[len("/static/"):])
        if req.method == "GET" and p == "/favicon.ico":
            return self.send(204)
        if req.method == "POST":
            if req.headers.get("x-pagertak") != "1":
                return self.send(403, {"error": "missing X-PagerTAK header"})
            if p == "/api/login":
                return self.login(req)
        if p == "/api/session":
            return self.send(200, {"authed": self.authed(req), "configured": bool(first_line(ARGS.auth))})
        if not self.authed(req):
            return self.send(401, {"error": "login required"})

        if req.method == "GET":
            if p == "/api/state":
                body, sig = state_json()
                if req.query.get("v") == sig:
                    return self.send(200, {"same": True, "v": sig})
                return self.send(200, body[:-1] + ', "v": "%s"}' % sig)
            if p == "/api/chat":
                sig = chat_sig()
                if req.query.get("m") == sig:
                    return self.send(200, {"same": True, "m": sig})
                return self.send(200, {"m": sig, "rows": chat_history()})
            if p == "/api/channels":
                r = submit("channels_get", {})
                try:
                    with open(rpath("channels.json"), encoding="utf-8") as fh:
                        data = json.load(fh)
                except (OSError, ValueError):
                    data = {}
                groups = data.get("data", data) if isinstance(data, dict) else data
                out = [{"name": g.get("name", ""), "direction": g.get("direction", ""), "active": bool(g.get("active")),
                        "description": g.get("description") or ""} for g in (groups if isinstance(groups, list) else [])
                       if isinstance(g, dict)]
                return self.send(200, {"ok": r["ok"], "msg": r["msg"], "groups": out})
            if p == "/api/trails":
                with LOCK:
                    return self.send(200, {k: [[t[1], t[2]] for t in v] for k, v in TRAILS.items() if len(v) > 1})
            if p == "/api/tiles/job":
                return self.send(200, JOB)
            if p == "/api/overlays":
                return self.send(200, overlay_list())
            m = re.match(r"^/overlays/([^/]+)$", p)
            if m:
                name = safe_name(m.group(1), (".kml", ".kmz"))
                f = os.path.join(ARGS.overlays, name) if name else ""
                if not name or not os.path.isfile(f):
                    return self.send(404, {"error": "not found"})
                with open(f, "rb") as fh:
                    return self.send(200, fh.read(), "application/octet-stream")
            m = re.match(r"^/api/cot/([A-Za-z0-9._-]+)$", p)
            if m:
                d = cot_details(m.group(1))
                return self.send(200 if d else 404, d or {"error": "no details for that item"})
            if p == "/api/share":
                return self.send(200, {"status": first_line(rpath("share.status"))})
            m = re.match(r"^/api/job/(enroll|test)$", p)
            if m:
                return self.send(200, {"status": first_line(rpath(m.group(1) + ".status"))})
            if p == "/api/sigint/radio":
                return self.send(200, cached("radio", 2.5, radio_state))
            if p == "/api/sigint/wifi":
                mins = max(1, min(120, int(num(req.query.get("mins"), 10))))
                return self.send(200, cached("wifi%d" % mins, 4.0, lambda: wifi_tables(mins)))
            if p == "/api/sigint/fox":
                return self.send(200, cached("fox", 0.8, fox_state))
            if p == "/api/reports":
                return self.send(200, reports())
            if p == "/api/surveys":
                return self.send(200, surveys())
            if p == "/api/watch/scan":
                return self.send(200, watch_scan())
            if p == "/api/sources":
                return self.send(200, [{"name": s["name"], "slug": s["slug"], "minz": s["minz"], "maxz": s["maxz"],
                                         "url": s["url"], "parts": s["parts"]} for s in sources()])
            m = re.match(r"^/tiles/([a-z0-9_]+)/(\d+)/(\d+)/(\d+)\.png$", p)
            if m:
                data, url = tile(m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), "fetch" in req.query)
                if url:
                    return self.send(302, b"", "text/plain", {"Location": url, "Cache-Control": "no-store"})
                if data is None:
                    return self.send(404, b"", "text/plain", {"Cache-Control": "no-store"})
                return self.send(200, data, tile_type(data), {"Cache-Control": "max-age=2592000, immutable"})
            m = re.match(r"^/download/surveys/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+\.(?:zip|kml|csv))$", p)
            if m:
                return self.download(os.path.join(ARGS.loot, "surveys", m.group(1), m.group(2)))
            return self.send(404, {"error": "not found"})

        if req.method == "POST":
            if p == "/api/logout":
                with LOCK:
                    SESSIONS.pop(req.cookie(COOKIE), None)
                return self.send(200, {"ok": True}, extra={"Set-Cookie": COOKIE + "=; Max-Age=0; Path=/"})
            if p == "/api/share":
                f = getattr(req, "file", None)
                name = safe_name(req.query.get("name", ""), (".jpg", ".jpeg", ".png", ".gif", ".heic", ".pdf", ".txt", ".kml", ".kmz",
                                                             ".zip", ".mp4", ".mov", ".doc", ".docx", ".xlsx", ".csv"))
                if not f or not name:
                    if f:
                        os.remove(f)
                    return self.send(400, {"ok": False, "msg": "That file type cannot be sent"})
                try:
                    zpath = build_package(f, name)
                except Exception as e:                 # never leave the browser guessing
                    return self.send(500, {"ok": False, "msg": "Could not build the data package (%s)" % e.__class__.__name__})
                finally:
                    if os.path.exists(f):
                        os.remove(f)
                fields = {k: req.query.get(k, "") for k in ("send", "to_uid", "to_cs")}
                fields["name"] = name
                return self.send(200, submit("share", fields, upload_path=zpath))
            if p == "/api/certfile":
                f, kind = getattr(req, "file", None), req.query.get("kind", "")
                if not f or kind not in ("client", "ca"):
                    if f:
                        os.remove(f)
                    return self.send(400, {"ok": False, "msg": "Choose a certificate file"})
                pw = req.headers.get("x-p12-password", "")
                return self.send(200, submit("certfile", {"kind": kind, "password": pw}, upload_path=f, wait=120))
            if p == "/api/package":
                f = getattr(req, "file", None)
                if not f:
                    return self.send(400, {"ok": False, "msg": "Choose the data package (.zip)"})
                try:
                    fields = read_connection_package(f)
                except ValueError as e:
                    return self.send(400, {"ok": False, "msg": str(e)})
                finally:
                    if os.path.exists(f):
                        os.remove(f)
                return self.send(200, submit("import_pkg", fields, wait=120))
            if p == "/api/overlays":
                f = getattr(req, "file", None)
                name = safe_name(req.query.get("name", ""), (".kml", ".kmz"))
                if not f or not name:
                    if f:
                        os.remove(f)
                    return self.send(400, {"ok": False, "msg": "Only .kml or .kmz files"})
                try:
                    with open(f, "rb") as fh:
                        head = fh.read(4096)
                    if name.lower().endswith(".kmz") and not head.startswith(b"PK"):
                        raise ValueError("this .kmz is not a ZIP file")
                    if name.lower().endswith(".kml") and b"<kml" not in head.lower() and b"<document" not in head.lower():
                        raise ValueError("this .kml has no <kml> element")
                    os.makedirs(ARGS.overlays, exist_ok=True)
                    move_file(f, os.path.join(ARGS.overlays, name))
                except (OSError, ValueError) as e:
                    if os.path.exists(f):
                        os.remove(f)
                    return self.send(200, {"ok": False, "msg": "Overlay not saved: %s" % e})
                return self.send(200, {"ok": True, "name": name, "msg": "Overlay %s saved on the %s" % (name, device_word())})
            if p == "/api/chat/delete":
                ok = chat_delete(str(req.json().get("id", "")))
                return self.send(200, {"ok": ok, "msg": "Message deleted from the %s" % device_word() if ok else "Message not found"})
            if p == "/api/overlays/delete":
                name = safe_name(str(req.json().get("name", "")), (".kml", ".kmz"))
                f = os.path.join(ARGS.overlays, name) if name else ""
                if name and os.path.isfile(f):
                    os.remove(f)
                    return self.send(200, {"ok": True, "msg": "Overlay deleted"})
                return self.send(200, {"ok": False, "msg": "No such overlay"})
            if p == "/api/tiles/job":
                b = req.json()
                if JOB.get("state") == "running":
                    return self.send(200, {"ok": False, "msg": "A download is already running"})
                src = next((x for x in sources() if x["slug"] == b.get("slug")), None)
                if not src or PM is None or "example.com" in src["url"]:
                    return self.send(200, {"ok": False, "msg": "Pick a basemap first"})
                try:
                    plan, total = job_plan(b)
                except (KeyError, ValueError, TypeError):
                    return self.send(200, {"ok": False, "msg": "Bad area or zoom levels"})
                if b.get("check"):
                    return self.send(200, {"ok": True, "count": total})
                if total > 25000:
                    return self.send(200, {"ok": False, "msg": "%d tiles is too many (limit 25,000). Use a smaller area or lower max zoom." % total})
                os.makedirs(ARGS.tiles, exist_ok=True)
                st = os.statvfs(ARGS.tiles)
                free = st.f_bavail * st.f_frsize
                if total * 25000 > free:
                    return self.send(200, {"ok": False, "msg": "Not enough space: about %d MB needed, %d MB free" % (total * 25000 // 1048576, free // 1048576)})
                JOB.clear()
                JOB.update(state="running", total=total, done=0, got=0, slug=src["slug"], name=src["name"], started=time.time())
                threading.Thread(target=job_run, args=(src, plan, total), daemon=True).start()
                return self.send(200, {"ok": True, "msg": "Downloading %d tiles in the background" % total})
            if p == "/api/tiles/cancel":
                JOB["cancel"] = True
                return self.send(200, {"ok": True, "msg": "Stopping the download"})
            if p == "/api/password":
                body = req.json()
                old, new = str(body.get("old", "")), str(body.get("new", ""))
                if not check_password(old, first_line(ARGS.auth)):
                    time.sleep(1)
                    return self.send(200, {"ok": False, "msg": "Current password is wrong"})
                if len(new) < 8:
                    return self.send(200, {"ok": False, "msg": "Use at least 8 characters"})
                tmp = ARGS.auth + ".tmp"
                with open(tmp, "w") as fh:
                    fh.write(hash_password(new) + "\n")
                os.chmod(tmp, 0o600)
                os.replace(tmp, ARGS.auth)
                with LOCK:
                    tok = req.cookie(COOKIE)
                    for k in [k for k in SESSIONS if k != tok]:
                        del SESSIONS[k]
                return self.send(200, {"ok": True, "msg": "Password changed - other sessions signed out"})
            if p == "/api/cmd":
                body = req.json()
                cmd = str(body.get("cmd", ""))
                if cmd not in CMDS:
                    return self.send(400, {"ok": False, "msg": "unknown command"})
                upload = None
                if cmd == "channels_set":
                    try:
                        with open(rpath("channels.json"), encoding="utf-8") as fh:
                            data = json.load(fh)
                    except (OSError, ValueError):
                        return self.send(200, {"ok": False, "msg": "Load the channel list first"})
                    groups = data.get("data", data) if isinstance(data, dict) else data
                    want = {(str(g.get("name")), str(g.get("direction"))): bool(g.get("active"))
                            for g in body.get("groups", []) if isinstance(g, dict)}
                    for g in groups if isinstance(groups, list) else []:
                        k = (str(g.get("name")), str(g.get("direction")))
                        if k in want:
                            g["active"] = want[k]
                    upload = json.dumps(groups).encode()
                    body = {}
                if cmd == "cert":
                    text = str(body.get("pem", ""))
                    if "-----BEGIN" not in text or len(text) > 64 * 1024:
                        return self.send(400, {"ok": False, "msg": "Not a PEM file"})
                    upload = text.encode("utf-8")
                    body = {"kind": body.get("kind", "")}
                return self.send(200, submit(cmd, body, upload))
        return self.send(405, {"error": "method not allowed"})

    def static(self, name):
        root = os.path.realpath(ARGS.static)
        path = os.path.realpath(os.path.join(root, name))
        if not path.startswith(root + os.sep) or not os.path.isfile(path):
            return self.send(404, b"not found", "text/plain")
        with open(path, "rb") as fh:
            data = fh.read()
        ext = os.path.splitext(path)[1].lower()
        if name in ("index.html", "app.js") and ARGS.product != "PagerTAK":   # the same console on other devices
            p = ARGS.product.encode("utf-8")
            if name == "index.html":
                data = data.replace(b"Pager<b>TAK</b>", p[:-3] + b"<b>TAK</b>" if p.endswith(b"TAK") else p).replace(b"PagerTAK", p)
            data = re.sub(rb"\bPager\b", device_word().encode("utf-8"), data)        # "the Pager" -> "the Pineapple"
        cache = {"Cache-Control": "no-cache"} if ext in (".html", ".js", ".css") else {"Cache-Control": "max-age=86400"}
        return self.send(200, data, MIME.get(ext, "application/octet-stream"), cache)

    def download(self, path):
        real = os.path.realpath(path)
        if not real.startswith(os.path.realpath(ARGS.loot) + os.sep) or not os.path.isfile(real):
            return self.send(404, {"error": "not found"})
        with open(real, "rb") as fh:
            data = fh.read()
        return self.send(200, data, "application/octet-stream",
                         {"Content-Disposition": 'attachment; filename="%s"' % os.path.basename(real)})


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32

    def __init__(self, addr, handler, ssl_ctx=None):
        self.ssl_ctx = ssl_ctx
        if ":" in addr[0]:
            self.address_family = socket.AF_INET6
        socketserver.ThreadingTCPServer.__init__(self, addr, handler)

    def get_request(self):
        sock, addr = self.socket.accept()
        if self.ssl_ctx is not None:
            sock.settimeout(10)
            sock = self.ssl_ctx.wrap_socket(sock, server_side=True)
        return sock, addr

    def handle_error(self, request, client_address):
        pass


def main(argv=None):
    global ARGS, PM, TRACK_MAX_AGE
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="/tmp/pagertak")
    ap.add_argument("--loot", default="/root/loot/PagerTAK")
    ap.add_argument("--product", default="PagerTAK", help="name shown in the console (the device this runs on)")
    ap.add_argument("--bind", default="127.0.0.1", help="comma-separated addresses to listen on")
    ap.add_argument("--port", type=int, default=8484)
    ap.add_argument("--auth", default=os.path.join(here, "auth"))
    ap.add_argument("--static", default=os.path.join(here, "static"))
    ap.add_argument("--map-dir", default=os.path.join(here, "..", "map"))
    ap.add_argument("--sources", default="")
    ap.add_argument("--tiles", default=os.path.join(here, "..", "tiles"))
    ap.add_argument("--tile-url", default="")
    ap.add_argument("--offline", action="store_true", help="never fetch tiles, serve the cache only")
    ap.add_argument("--max-age", type=int, default=1800)
    ap.add_argument("--geofences", default=os.path.join(here, "..", "geofences.txt"))
    ap.add_argument("--items", default=os.path.join(here, "..", "items.txt"))
    ap.add_argument("--overlays", default=os.path.join(here, "..", "overlays"))
    ap.add_argument("--tls-cert", default="")
    ap.add_argument("--tls-key", default="")
    ap.add_argument("--hash-password", action="store_true", help="read a password on stdin, print its hash line")
    ap.add_argument("--self-check", action="store_true")
    ARGS = ap.parse_args(argv)

    if ARGS.hash_password:
        pw = sys.stdin.readline().rstrip("\r\n")
        if len(pw) < 8:
            print("ERROR password must be at least 8 characters", file=sys.stderr)
            return 2
        print(hash_password(pw))
        return 0

    TRACK_MAX_AGE = ARGS.max_age
    ARGS.sources = ARGS.sources or os.path.join(ARGS.map_dir, "sources")
    try:
        sys.path.insert(0, os.path.realpath(ARGS.map_dir))
        import pagertak_map as pm  # noqa: E402
        PM = pm
    except ImportError as e:
        sys.stderr.write("map helpers not available (%s) - no basemaps\n" % e)

    if ARGS.self_check:
        print("web OK, %d basemaps" % len(sources()))
        return 0
    if not first_line(ARGS.auth):
        print("ERROR no password set (%s)" % ARGS.auth, file=sys.stderr)
        return 2

    ctx = None
    if ARGS.tls_cert:
        try:
            import ssl
        except ImportError:
            print("ERROR HTTPS needs python3-openssl", file=sys.stderr)
            return 3
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(ARGS.tls_cert, ARGS.tls_key or None)

    servers = []
    for addr in [a.strip() for a in ARGS.bind.split(",") if a.strip()]:
        try:
            servers.append(Server((addr, ARGS.port), Handler, ctx))
            print("listening on %s://%s:%d" % ("https" if ctx else "http", addr, ARGS.port), flush=True)
        except OSError as e:
            print("cannot listen on %s:%d (%s)" % (addr, ARGS.port, e), file=sys.stderr, flush=True)
    if not servers:
        return 1
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    if PM is not None:
        threading.Thread(target=bg_worker, daemon=True).start()
    threading.Thread(target=trail_sampler, daemon=True).start()

    import signal

    def stop(*_):
        threading.Thread(target=servers[0].shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    servers[0].serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
