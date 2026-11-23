#!/usr/bin/env python3
"""PagerTAK map viewer for the WiFi Pineapple Pager.

Draws slippy-map tiles, the Pager's own position, TAK contacts and markers
received by PagerTAK, using pagerfb.py, PagerTAK's own pure-Python screen
driver (no compiled library, nothing to download).

Data comes from PagerTAK's runtime directory (default /tmp/pagertak):
  gps          fix lat lon hae ce speed track sats epoch
  lastfix      lat lon hae ce
  tracks.d/*   lat|lon|callsign|cot_type|team|epoch|kind|stale   (kind = client|marker|drone|operator|mine)
  lastchat     epoch|label|callsign|text
  status       state|last_sa|last_error

Controls
  D-pad            pan (leaves follow mode)
  A                re-center on me / follow
  hold B + UP/DOWN zoom in / out
  hold B + LEFT/RIGHT  toggle the nearest-contacts sidebar
  hold B + A       next basemap source
  tap B            exit

Basemaps are ATAK-format map source XML files (<customMapSource>) in
map/sources/, so the same files used in ATAK can be dropped in. Supported URL
tokens: {$z} {$x} {$y} {$q} (quadkey) {$serverpart}. Tiles are cached per
source in tiles/<source>/{z}/{x}/{y}.png. ArcGIS MapServer sources (the USGS
basemaps) are fetched as PNG through the service's export call, because the
screen driver decodes PNG only.
"""
import argparse
import glob
import re
import math
import os
import subprocess
import sys
import threading
import time

import pagerfb

W, H = 480, 222
TILE = 256
SIDEBAR_W = 150
TOPBAR_H = 11
ZMIN, ZMAX = 3, 18
PAN_STEP = 64

TEAM_RGB = {
    "White": (255, 255, 255), "Yellow": (255, 255, 0), "Orange": (255, 128, 0),
    "Magenta": (255, 0, 255), "Red": (255, 0, 0), "Maroon": (128, 0, 0),
    "Purple": (128, 0, 128), "Dark Blue": (0, 0, 160), "Blue": (0, 80, 255),
    "Cyan": (0, 255, 255), "Teal": (0, 128, 128), "Green": (0, 200, 0),
    "Dark Green": (0, 100, 0), "Brown": (139, 69, 19),
}
DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------
def world_px(lat, lon, z):
    n = TILE * (2 ** z)
    lat = max(-85.0511, min(85.0511, lat))
    r = math.radians(lat)
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * n
    return x, y


def latlon_px(x, y, z):
    n = TILE * (2 ** z)
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


def dist_bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    d = 2 * 6371000.0 * math.asin(min(1.0, math.sqrt(a)))
    b = math.degrees(math.atan2(math.sin(dl) * math.cos(p2),
                                math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)))
    return d, (b + 360.0) % 360.0


def fmt_dist(m):
    if m < 1000:
        return "%dm" % int(m)
    if m < 10000:
        return "%.1fkm" % (m / 1000.0)
    return "%dkm" % int(m / 1000.0)


def meters_per_px(lat, z):
    return 156543.03392 * math.cos(math.radians(lat)) / (2 ** z)


# --------------------------------------------------------------------------
# data from PagerTAK
# --------------------------------------------------------------------------
def read_first_line(path):
    try:
        with open(path) as fh:
            return fh.readline().strip()
    except OSError:
        return ""


def read_self(run, manual=None):
    """Returns (lat, lon, track, speed, sats, has_fix, source) or None.
    source: GPS (live fix), LAST (last known fix), MANUAL (Settings > Manual position)."""
    f = read_first_line(os.path.join(run, "gps")).split()
    if len(f) >= 9 and f[0] == "1":
        try:
            trk = float(f[6]) if f[6] != "-" else None
            spd = float(f[5]) if f[5] != "-" else 0.0
            return float(f[1]), float(f[2]), trk, spd, f[7], True, "GPS"
        except ValueError:
            pass
    sats = f[7] if len(f) >= 8 else "-"
    lf = read_first_line(os.path.join(run, "lastfix")).split()
    if len(lf) >= 2:
        try:
            return float(lf[0]), float(lf[1]), None, 0.0, sats, False, "LAST"
        except ValueError:
            pass
    if manual:
        return manual[0], manual[1], None, 0.0, sats, False, "MANUAL"
    return None


def category(ctype, kind):
    """Same categories as the web console (users, drones, aircraft, ground, vessels, other)."""
    import re
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


def haversine_km(a1, o1, a2, o2):
    r = math.pi / 180
    x = (o2 - o1) * r * math.cos((a1 + a2) / 2 * r)
    y = (a2 - a1) * r
    return math.sqrt(x * x + y * y) * 6371.0088


def read_tracks(run, max_age):
    now = time.time()
    out = []
    for path in glob.glob(os.path.join(run, "tracks.d", "*")):
        parts = read_first_line(path).split("|")
        if len(parts) < 7:
            continue
        try:
            lat, lon, ts = float(parts[0]), float(parts[1]), float(parts[5])
        except ValueError:
            continue
        if now - ts > max_age:
            continue
        is_stale = len(parts) > 7 and parts[7].isdigit() and 0 < int(parts[7]) < now
        if is_stale and parts[6] != "client":           # stale in TAK; TAK users stay, greyed like ATAK
            continue
        out.append({"lat": lat, "lon": lon, "cs": parts[2], "type": parts[3],
                    "team": parts[4], "ts": ts, "kind": parts[6], "stale": is_stale})
    return out


# --------------------------------------------------------------------------
# map sources (ATAK customMapSource XML)
# --------------------------------------------------------------------------
def _tag(xml, name, default=""):
    m = re.search(r"<%s>\s*(.*?)\s*</%s>" % (name, name), xml, re.S | re.I)
    return m.group(1).strip() if m else default


def slugify(name):
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower() or "source"


def make_source(name, url, minz=0, maxz=18, parts=None):
    url = url.replace("&amp;", "&")
    for a, b in (("{$z}", "{z}"), ("{$x}", "{x}"), ("{$y}", "{y}"), ("{$q}", "{q}"), ("{$serverpart}", "{s}")):
        url = url.replace(a, b)
    return {"name": name, "slug": slugify(name), "url": url, "minz": minz,
            "maxz": max(ZMIN, min(ZMAX, maxz)), "parts": parts or []}


def load_sources(src_dir):
    out = []
    for path in sorted(glob.glob(os.path.join(src_dir or "", "*.xml"))):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                xml = fh.read()
        except OSError:
            continue
        if "<customMapSource" not in xml:
            continue          # WMS / multi-layer sources are not supported
        url = _tag(xml, "url")
        if not url:
            continue
        name = _tag(xml, "name") or os.path.splitext(os.path.basename(path))[0]
        try:
            minz, maxz = int(_tag(xml, "minZoom", "0")), int(_tag(xml, "maxZoom", "18"))
        except ValueError:
            minz, maxz = 0, 18
        parts = _tag(xml, "serverParts").split()
        out.append(make_source(name, url, minz, maxz, parts))
    return out


def tile_url(src, z, x, y, png=False):
    """URL of one tile. png=True asks ArcGIS MapServer sources for a PNG of
    the tile's area instead of their cached tile (often JPEG), because the
    Pager screen driver decodes PNG only."""
    url = src["url"]
    if png and "/MapServer/tile/" in url:
        e = 20037508.342789244
        size = 2 * e / (1 << z)
        x0, y1 = -e + x * size, e - y * size
        return "%s/export?bbox=%.3f,%.3f,%.3f,%.3f&bboxSR=3857&imageSR=3857&size=256,256&format=png8&transparent=false&f=image" % (
            url.split("/tile/")[0], x0, y1 - size, x0 + size, y1)
    q = ""
    for i in range(z, 0, -1):
        d = 0
        m = 1 << (i - 1)
        if x & m:
            d += 1
        if y & m:
            d += 2
        q += str(d)
    url = url.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y)).replace("{q}", q)
    if "{s}" in url:
        parts = src["parts"] or ["a", "b", "c"]
        url = url.replace("{s}", parts[(x + y) % len(parts)])
    return url


# --------------------------------------------------------------------------
# tiles
# --------------------------------------------------------------------------
class TileCache:
    """Decoded tiles in memory (LRU). Missing tiles are read from disk, or
    fetched and then read, by a background thread so the buttons stay quick."""

    def __init__(self, pager, tile_root, source, max_handles=30):
        self.p = pager
        self.src = source
        self.dir = os.path.join(tile_root, source["slug"]) if source else os.path.join(tile_root, "none")
        self.url = source["url"] if source and "example.com" not in source["url"] else ""
        self.max = max_handles
        self.handles = {}
        self.order = []
        self.pending = set()
        self.failed = {}
        self.lock = threading.Lock()
        self.queue = []
        self.wake = threading.Event()
        self.dirty = False
        threading.Thread(target=self._worker, daemon=True).start()

    def path(self, z, x, y):
        return os.path.join(self.dir, str(z), str(x), "%d.png" % y)

    def get(self, z, x, y):
        key = (z, x, y)
        with self.lock:
            h = self.handles.get(key)
            if h:
                self.order.remove(key)
                self.order.append(key)
                return h
            if key in self.pending or time.time() < self.failed.get(key, 0):
                return None
            self.pending.add(key)
            self.queue.append(key)
        self.wake.set()
        return None

    def _load(self, key):
        path = self.path(*key)
        img = load_tile(self.p, path)
        if img is None and self.url:
            if os.path.isfile(path):
                os.remove(path)                       # a JPEG or broken file: fetch a PNG instead
            if fetch_tile(self.src, path, *key):
                img = load_tile(self.p, path)
        return img

    def _worker(self):
        while True:
            self.wake.wait(5)
            self.wake.clear()
            while True:
                with self.lock:
                    if not self.queue:
                        break
                    key = self.queue.pop()          # newest request first: what is on screen now
                img = self._load(key)
                with self.lock:
                    self.pending.discard(key)
                    if img:
                        self.handles[key] = img
                        self.order.append(key)
                        while len(self.order) > self.max:
                            self.p.free_image(self.handles.pop(self.order.pop(0)))
                        self.dirty = True
                    else:
                        self.failed[key] = time.time() + 120

    def free_all(self):
        with self.lock:
            for h in self.handles.values():
                self.p.free_image(h)
            self.handles.clear()
            self.order = []


def load_tile(p, path):
    """Tile PNG -> image. Slow-to-decode tiles keep a decoded copy (.565) next to them."""
    if not (os.path.isfile(path) and os.path.getsize(path) > 0):
        return None
    raw = path + ".565"
    try:
        if os.path.getmtime(raw) >= os.path.getmtime(path):
            with open(raw, "rb") as f:
                data = f.read()
            w, h = int.from_bytes(data[:2], "little"), int.from_bytes(data[2:4], "little")
            if len(data) == 4 + 2 * w * h:
                return pagerfb.Image(w, h, bytearray(data[4:]))
    except (OSError, NameError):
        pass
    t = time.time()
    img = p.load_image(path)
    if img is not None and time.time() - t > 0.4 and isinstance(img, getattr(pagerfb, "Image", ())):
        try:
            with open(raw + ".tmp", "wb") as f:
                f.write(img.w.to_bytes(2, "little") + img.h.to_bytes(2, "little") + bytes(img.px))
            os.replace(raw + ".tmp", raw)
        except OSError:
            pass
    return img


def fetch_tile(src, path, z, x, y):
    """Downloads one tile as PNG (see tile_url). Returns True when saved."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    urls = [tile_url(src, z, x, y, png=True)]
    if urls[0] != tile_url(src, z, x, y):
        urls.append(tile_url(src, z, x, y))           # export refused: the plain tile still serves the browser
    for url in urls:
        try:
            r = subprocess.run(["curl", "-sf", "--max-time", "15", "-A", "PagerTAK/2.3.2 (WiFi Pineapple Pager)",
                                "-o", tmp, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            if r.returncode == 0 and os.path.getsize(tmp) > 100:
                os.replace(tmp, path)
                return True
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        os.remove(tmp)
    except OSError:
        pass
    return False


def cache_area(src, tile_root, lat, lon, km, zmin, zmax, limit=6000):
    """Pre-download tiles around lat/lon. Prints progress lines 'done/total'."""
    tile_dir = os.path.join(tile_root, src["slug"])
    zmin, zmax = max(zmin, src["minz"]), min(zmax, src["maxz"])
    jobs = []
    for z in range(zmin, zmax + 1):
        cx, cy = world_px(lat, lon, z)
        r_px = km * 1000.0 / meters_per_px(lat, z)
        n = 2 ** z
        for tx in range(int((cx - r_px) // TILE), int((cx + r_px) // TILE) + 1):
            for ty in range(int((cy - r_px) // TILE), int((cy + r_px) // TILE) + 1):
                if 0 <= ty < n:
                    jobs.append((z, tx % n, ty))
    total, done, fetched, failed = len(jobs), 0, 0, 0
    if total > limit:
        print("ERROR %d tiles is over the %d limit - use a smaller radius" % (total, limit), flush=True)
        return 4
    for z, x, y in jobs:
        path = os.path.join(tile_dir, str(z), str(x), "%d.png" % y)
        if not (os.path.isfile(path) and os.path.getsize(path) > 0):
            if fetch_tile(src, path, z, x, y):
                fetched += 1
            else:
                failed += 1
        done += 1
        if done % 25 == 0 or done == total:
            print("%d/%d" % (done, total), flush=True)
    print("DONE total=%d fetched=%d failed=%d" % (total, fetched, failed), flush=True)
    return 0 if failed == 0 else 3


# --------------------------------------------------------------------------
# viewer
# --------------------------------------------------------------------------
class MapView:
    def __init__(self, Pager, p, args):
        self.Pager = Pager
        self.p = p
        self.args = args
        self.z = max(ZMIN, min(ZMAX, args.zoom))
        self.follow = args.center is None
        self.sidebar = True
        self.cx = self.cy = None
        self.sources = args.sources_list
        self.src_i = 0
        for i, s in enumerate(self.sources):
            if args.source and args.source.lower() in (s["name"].lower(), s["slug"]):
                self.src_i = i
        self.tiles = TileCache(p, args.tiles, self.source())
        self.z = self.clamp_z(self.z)
        self.hint_until = time.time() + 5
        self.c = {
            "bg": p.rgb(6, 14, 8), "grid": p.rgb(18, 44, 24), "bar": p.rgb(0, 0, 0),
            "text": p.rgb(170, 255, 170), "dim": p.rgb(90, 140, 90), "self": p.rgb(0, 255, 255),
            "hostile": p.rgb(255, 40, 40), "suspect": p.rgb(255, 120, 0), "unknown": p.rgb(255, 230, 0),
            "neutral": p.rgb(0, 220, 0), "friend": p.rgb(60, 140, 255), "white": p.WHITE,
            "black": p.BLACK, "panel": p.rgb(0, 20, 6), "chat": p.rgb(255, 255, 120),
        }
        if args.center:
            lat, lon = args.center
            self.cx, self.cy = world_px(lat, lon, self.z)

    # -- helpers -----------------------------------------------------------
    def source(self):
        return self.sources[self.src_i] if self.sources else None

    def clamp_z(self, z):
        s = self.source()
        lo, hi = (max(ZMIN, s["minz"]), s["maxz"]) if s else (ZMIN, ZMAX)
        return max(lo, min(hi, z))

    def next_source(self):
        if len(self.sources) < 2:
            return
        self.tiles.free_all()
        self.src_i = (self.src_i + 1) % len(self.sources)
        self.tiles = TileCache(self.p, self.args.tiles, self.source())
        lat, lon = latlon_px(self.cx, self.cy, self.z)
        self.z = self.clamp_z(self.z)
        self.cx, self.cy = world_px(lat, lon, self.z)
        try:
            with open(os.path.join(self.args.run, "map_source"), "w") as fh:
                fh.write(self.source()["name"])
        except OSError:
            pass
    def map_w(self):
        return W - SIDEBAR_W if self.sidebar else W

    def to_screen(self, lat, lon):
        wx, wy = world_px(lat, lon, self.z)
        return int(wx - self.cx + self.map_w() / 2), int(wy - self.cy + (H + TOPBAR_H) / 2)

    def color_for(self, t):
        if t.get("stale"):                                  # TAK user past its stale time
            return self.p.rgb(120, 120, 120)
        if t.get("type", "").startswith("a-f") or t.get("kind") == "client":
            rgb = TEAM_RGB.get(t.get("team", ""))
            return self.p.rgb(*rgb) if rgb else self.c["friend"]
        aff = t.get("type", "a-u")[2:3]
        return {"h": self.c["hostile"], "j": self.c["hostile"], "k": self.c["hostile"],
                "s": self.c["suspect"], "n": self.c["neutral"]}.get(aff, self.c["unknown"])

    def zoom(self, dz):
        nz = self.clamp_z(self.z + dz)
        if nz == self.z:
            return
        lat, lon = latlon_px(self.cx, self.cy, self.z)
        self.z = nz
        self.cx, self.cy = world_px(lat, lon, self.z)

    # -- drawing -----------------------------------------------------------
    def draw_tiles(self):
        p, mw = self.p, self.map_w()
        p.fill_rect(0, 0, mw, H, self.c["bg"])
        oy = (H + TOPBAR_H) / 2
        left, top = self.cx - mw / 2, self.cy - oy
        n = 2 ** self.z
        for tx in range(int(left // TILE), int((left + mw) // TILE) + 1):
            for ty in range(int(top // TILE), int((top + H) // TILE) + 1):
                if not 0 <= ty < n:
                    continue
                sx, sy = int(tx * TILE - left), int(ty * TILE - top)
                h = self.tiles.get(self.z, tx % n, ty)
                if h:
                    p.draw_image(sx, sy, h)
                else:
                    p.rect(sx, sy, TILE, TILE, self.c["grid"])

    def draw_marker(self, t, sx, sy, col):
        p = self.p
        if t["kind"] == "client":
            p.fill_circle(sx, sy, 5, self.c["black"])
            p.fill_circle(sx, sy, 4, col)
        else:  # diamond for map markers / alerts
            for d in range(6):
                p.hline(sx - (5 - d), sy - d, 2 * (5 - d) + 1, col)
                p.hline(sx - (5 - d), sy + d, 2 * (5 - d) + 1, col)
        label = t["cs"][:16]
        tw = 6 * len(label)
        p.fill_rect(sx + 7, sy - 4, tw + 2, 9, self.c["black"])
        p.draw_text(sx + 8, sy - 3, label, col, 1)

    def draw_self(self, me, sx, sy):
        p, col = self.p, self.c["self"]
        lat, lon, trk, spd, sats, fix = me[:6]
        if not fix:
            col = self.c["dim"]
        if trk is not None and spd > 0.5:
            a = math.radians(trk)
            pts = [(sx + 10 * math.sin(a), sy - 10 * math.cos(a)),
                   (sx + 6 * math.sin(a + 2.5), sy - 6 * math.cos(a + 2.5)),
                   (sx + 6 * math.sin(a - 2.5), sy - 6 * math.cos(a - 2.5))]
            for i in range(3):
                x0, y0 = pts[i]
                x1, y1 = pts[(i + 1) % 3]
                p.line(int(x0), int(y0), int(x1), int(y1), col)
            p.fill_circle(sx, sy, 3, col)
        else:
            p.fill_circle(sx, sy, 6, self.c["black"])
            p.fill_circle(sx, sy, 5, col)
            p.fill_circle(sx, sy, 2, self.c["black"])
        p.circle(sx, sy, 9, col)

    def draw_scale(self, lat):
        p = self.p
        mpp = meters_per_px(lat, self.z)
        target = mpp * 80
        nice = 1
        for v in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000):
            if v <= target:
                nice = v
        px = max(1, int(nice / mpp))
        y = H - 8
        p.fill_rect(3, y - 9, px + 40, 14, self.c["black"])
        p.hline(6, y, px, self.c["white"])
        p.vline(6, y - 3, 4, self.c["white"])
        p.vline(6 + px, y - 3, 4, self.c["white"])
        p.draw_text(10 + px, y - 4, fmt_dist(nice), self.c["white"], 1)

    def draw_topbar(self, me, n_contacts):
        p = self.p
        st = read_first_line(os.path.join(self.args.run, "status")).split("|")
        link = {"connected": "OK", "connecting": "...", "disconnected": "DOWN"}.get(st[0] if st else "", "?")
        sats = me[4] if me else "-"
        fix = (me[6] if me[6] != "GPS" else "FIX") if me else "NOFIX"
        mode = "FOLLOW" if self.follow else "PAN"
        src = self.source()["name"][:14] if self.source() else "no map"
        txt = "%s TAK:%s GPS:%s/%s z%d %s %s" % (
            self.args.callsign[:10], link[:4], fix, sats, self.z, mode, src)
        p.fill_rect(0, 0, W, TOPBAR_H, self.c["bar"])
        p.draw_text(2, 2, txt[:79], self.c["text"], 1)

    def draw_sidebar(self, me, tracks):
        p = self.p
        x0 = W - SIDEBAR_W
        p.fill_rect(x0, TOPBAR_H, SIDEBAR_W, H - TOPBAR_H, self.c["panel"])
        p.vline(x0, TOPBAR_H, H - TOPBAR_H, self.c["dim"])
        p.draw_text(x0 + 4, TOPBAR_H + 3, "NEAREST", self.c["dim"], 1)
        if not me:
            p.draw_text(x0 + 4, TOPBAR_H + 16, "no own position", self.c["dim"], 1)
            return
        rows = []
        for t in tracks:
            d, b = dist_bearing(me[0], me[1], t["lat"], t["lon"])
            rows.append((d, b, t))
        rows.sort(key=lambda r: r[0])
        y = TOPBAR_H + 15
        for d, b, t in rows[:9]:
            col = self.color_for(t)
            p.fill_rect(x0 + 4, y + 1, 5, 5, col)
            p.draw_text(x0 + 12, y, t["cs"][:11], self.c["text"], 1)
            p.draw_text(x0 + 82, y, "%s %s" % (fmt_dist(d), DIRS[int((b + 22.5) // 45) % 8]), self.c["white"], 1)
            y += 21
            if y > H - 10:
                break
        if not rows:
            p.draw_text(x0 + 4, TOPBAR_H + 16, "no contacts yet", self.c["dim"], 1)

    def draw_banner(self):
        line = read_first_line(os.path.join(self.args.run, "lastchat")).split("|", 3)
        if len(line) == 4:
            try:
                age = time.time() - float(line[0])
            except ValueError:
                return
            if age < 30:
                txt = "[%s] %s: %s" % (line[1], line[2], line[3])
                p, mw = self.p, self.map_w()
                p.fill_rect(0, H - 32, mw, 11, self.c["black"])
                p.draw_text(3, H - 30, txt[: mw // 6 - 1], self.c["chat"], 1)

    def render(self):
        me = read_self(self.args.run, self.args.manual)
        tracks = read_tracks(self.args.run, self.args.max_age)
        hide = set(c for c in self.args.hide.split(",") if c)
        if hide:
            tracks = [t for t in tracks if category(t.get("type", ""), t.get("kind", "")) not in hide]
        if self.args.radius_km > 0 and me:
            km = self.args.radius_km
            tracks = [t for t in tracks if haversine_km(me[0], me[1], t["lat"], t["lon"]) <= km]
        if self.cx is None or (self.follow and me):
            if me:
                self.cx, self.cy = world_px(me[0], me[1], self.z)
            elif self.cx is None:
                self.cx, self.cy = world_px(39.8, -98.6, self.z)       # centre of the US until there is a position
        self.draw_tiles()
        mw = self.map_w()
        for t in tracks:
            sx, sy = self.to_screen(t["lat"], t["lon"])
            if -20 < sx < mw + 20 and TOPBAR_H - 10 < sy < H + 10:
                self.draw_marker(t, sx, sy, self.color_for(t))
        if me:
            sx, sy = self.to_screen(me[0], me[1])
            self.draw_self(me, sx, sy)
        if self.sidebar:
            self.draw_sidebar(me, tracks)
        lat, _ = latlon_px(self.cx, self.cy, self.z)
        self.draw_scale(lat)
        self.draw_banner()
        self.draw_topbar(me, len(tracks))
        if time.time() < self.hint_until:
            hint = "A:center  red B+UP/DN:zoom +A:map +L/R:list  B:exit"
            self.p.fill_rect(0, TOPBAR_H, mw, 11, self.c["black"])
            self.p.draw_text(3, TOPBAR_H + 2, hint[: mw // 6 - 1], self.c["chat"], 1)
        self.p.flip()

    KEYLOG = "/tmp/pagertak-keys.log"
    KEYNAME = {0x01: "UP", 0x02: "DOWN", 0x04: "LEFT", 0x08: "RIGHT", 0x10: "A", 0x20: "B", 0x40: "POWER"}

    def log_keys(self, evs, b_held):
        """Last button events, for checking the buttons: cat /tmp/pagertak-keys.log"""
        try:
            try:
                with open(self.KEYLOG) as fh:
                    old = fh.read().splitlines()[-60:]
            except OSError:
                old = []
            t = time.strftime("%H:%M:%S")
            new = ["%s %s %s z%d%s" % (t, self.KEYNAME.get(b, b), "down" if d else "up", self.z, " (B held)" if b_held else "")
                   for b, d in evs]
            with open(self.KEYLOG, "w") as fh:
                fh.write("\n".join((old + new)[-60:]) + "\n")
        except OSError:
            pass

    def run(self, should_run):
        P = self.Pager
        p = self.p
        b_held = b_combo = False
        next_draw = 0
        self.render()
        while should_run():
            changed = False
            # events in order, so hold B + UP still zooms when a redraw was slow
            evs = p.poll_events()
            if evs:
                self.log_keys(evs, b_held)
            for bit, down in evs:
                if bit == P.BTN_B:
                    if down:
                        b_held, b_combo = True, False
                    else:
                        b_held = False
                        if not b_combo:
                            return 0
                    continue
                if not down:
                    continue
                changed = True
                if bit == P.BTN_UP:
                    if b_held:
                        self.zoom(+1); b_combo = True
                    else:
                        self.cy -= PAN_STEP; self.follow = False
                elif bit == P.BTN_DOWN:
                    if b_held:
                        self.zoom(-1); b_combo = True
                    else:
                        self.cy += PAN_STEP; self.follow = False
                elif bit in (P.BTN_LEFT, P.BTN_RIGHT):
                    if b_held:
                        self.sidebar = not self.sidebar; b_combo = True
                    else:
                        self.cx += PAN_STEP if bit == P.BTN_RIGHT else -PAN_STEP
                        self.follow = False
                elif bit == P.BTN_A:
                    if b_held:
                        self.next_source(); b_combo = True
                    else:
                        self.follow = True
            if self.tiles.dirty:
                self.tiles.dirty = False
                changed = True
            now = time.time()
            if changed or now >= next_draw:
                self.render()
                next_draw = now + 1.0
            time.sleep(0.03)
        return 0


# --------------------------------------------------------------------------
# navigate to one contact: big arrow, range and bearing
# --------------------------------------------------------------------------
class NavView:
    """Arrow to one track. North up, or heading up while you move (GPS course).
    A: open the map on the target. B: back."""

    def __init__(self, Pager, p, args):
        self.Pager, self.p, self.args = Pager, p, args
        self.path = os.path.join(args.run, "tracks.d", os.path.basename(args.nav))
        self.c = {"bg": p.BLACK, "text": p.rgb(170, 255, 170), "dim": p.rgb(90, 140, 90),
                  "arrow": p.rgb(0, 255, 255), "ring": p.rgb(18, 60, 30), "warn": p.rgb(255, 200, 0),
                  "white": p.WHITE, "red": p.rgb(255, 60, 60)}

    def target(self):
        parts = read_first_line(self.path).split("|")
        if len(parts) < 7:
            return None
        try:
            t = {"lat": float(parts[0]), "lon": float(parts[1]), "cs": parts[2], "ts": float(parts[5]),
                 "kind": parts[6]}
        except ValueError:
            return None
        t["stale"] = len(parts) > 7 and parts[7].isdigit() and 0 < int(parts[7]) < time.time()
        return t

    def fill_tri(self, pts, col):
        (x0, y0), (x1, y1), (x2, y2) = sorted(pts, key=lambda q: q[1])

        def edge(xa, ya, xb, yb, y):
            return xa if yb == ya else xa + (xb - xa) * (y - ya) / (yb - ya)
        for y in range(int(math.ceil(y0)), int(y2) + 1):
            xa = edge(x0, y0, x2, y2, y)
            xb = edge(x0, y0, x1, y1, y) if y < y1 else edge(x1, y1, x2, y2, y)
            if xa > xb:
                xa, xb = xb, xa
            self.p.hline(int(xa), y, int(xb - xa) + 1, col)

    def arrow(self, cx, cy, r, ang, col):
        a = math.radians(ang)

        def pt(dist, off):
            return (cx + dist * math.sin(a + off), cy - dist * math.cos(a + off))
        tip, left, right, back = pt(r, 0), pt(r * 0.55, 2.5), pt(r * 0.55, -2.5), pt(r * 0.25, math.pi)
        self.fill_tri([tip, left, back], col)
        self.fill_tri([tip, right, back], col)

    def render(self):
        p, c = self.p, self.c
        p.clear(c["bg"])
        me = read_self(self.args.run, self.args.manual)
        t = self.target()
        cx, cy, r = 112, 118, 92
        p.fill_circle(cx, cy, r, c["ring"])
        p.circle(cx, cy, r, c["dim"])
        x0 = 232
        if not t:
            p.draw_text(x0, 40, "TARGET GONE", c["red"], 2)
            p.draw_text(x0, 70, "No update for this contact.", c["dim"], 1)
            p.draw_text(x0, 200, "B: back", c["dim"], 1)
            p.flip()
            return
        p.draw_text(x0, 8, t["cs"][:20], c["white"], 2)
        if not me:
            p.draw_text(x0, 50, "NO OWN POSITION", c["warn"], 2)
            p.draw_text(x0, 80, "Need a GPS fix or a manual position.", c["dim"], 1)
            p.draw_text(x0, 200, "A: map   B: back", c["dim"], 1)
            p.flip()
            return
        d, b = dist_bearing(me[0], me[1], t["lat"], t["lon"])
        moving = me[2] is not None and (me[3] or 0) > 1.0
        up = me[2] if moving else 0.0
        rel = (b - up) % 360
        # compass mark: N (or your course when moving) at the top
        n_ang = math.radians((0 - up) % 360)
        nx, ny = cx + (r - 12) * math.sin(n_ang), cy - (r - 12) * math.cos(n_ang)
        p.draw_text(int(nx) - 3, int(ny) - 4, "N", c["red"], 1)
        self.arrow(cx, cy, r - 22, rel, c["warn"] if t["stale"] else c["arrow"])
        p.fill_circle(cx, cy, 4, c["white"])
        p.draw_text(x0, 44, fmt_dist(d), c["text"], 4)
        p.draw_text(x0, 84, "%03d %s" % (int(round(b)) % 360, DIRS[int((b + 22.5) // 45) % 8]), c["text"], 3)
        age = int(time.time() - t["ts"])
        ages = "%ds ago" % age if age < 60 else "%dm ago" % (age // 60)
        p.draw_text(x0, 122, "Last update " + ages + (" (stale)" if t["stale"] else ""),
                    c["warn"] if t["stale"] else c["dim"], 1)
        p.draw_text(x0, 136, "Heading up (your course)" if moving else "North up - turn until N points north", c["dim"], 1)
        if me[6] != "GPS":
            p.draw_text(x0, 150, "Own position: %s, not a live fix" % me[6].lower(), c["warn"], 1)
        p.draw_text(x0, 200, "A: map   red B: back", c["dim"], 1)
        p.flip()

    def run(self, should_run):
        P, p = self.Pager, self.p
        next_draw = 0
        while should_run():
            for bit, down in p.poll_events():
                if bit == P.BTN_B and not down:
                    return 0
                if bit == P.BTN_A and down and self.target():
                    return 20                    # open the map on the target
            now = time.time()
            if now >= next_draw:
                self.render()
                next_draw = now + 1.0
            time.sleep(0.05)
        return 0


def load_display(libdir=None):
    """The screen driver: pagerfb (pure Python, ships with PagerTAK)."""
    return pagerfb.Pager


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="/tmp/pagertak")
    ap.add_argument("--lib", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib", "active"))
    ap.add_argument("--tiles", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tiles"))
    ap.add_argument("--tile-url", default="", help="custom {z}/{x}/{y} URL, added as source 'Custom'")
    ap.add_argument("--sources", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources"))
    ap.add_argument("--source", default="", help="name or slug of the basemap to start with")
    ap.add_argument("--list-sources", action="store_true")
    ap.add_argument("--zoom", type=int, default=15)
    ap.add_argument("--center", default=None, help="lat,lon to open on (disables follow)")
    ap.add_argument("--manual", default=None, help="lat,lon manual position used when there is no GPS fix")
    ap.add_argument("--callsign", default="PAGER")
    ap.add_argument("--max-age", type=int, default=1800)
    ap.add_argument("--radius-km", type=float, default=0, help="only show TAK items this close to you (0 = all)")
    ap.add_argument("--hide", default="", help="comma list of categories to hide: users,drones,aircraft,ground,vessels,other")
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--cache-km", type=float, default=0)
    ap.add_argument("--cache-zoom", default="10-16")
    ap.add_argument("--nav", default="", help="track file name in RUN/tracks.d: arrow, range and bearing to it")
    args = ap.parse_args(argv)
    def parse_ll(v):
        try:
            a, b = v.split(",")
            return float(a), float(b)
        except (AttributeError, ValueError):
            return None
    args.center = parse_ll(args.center) if args.center else None
    args.manual = parse_ll(args.manual) if args.manual else None

    args.sources_list = load_sources(args.sources)
    if args.tile_url and "example.com" not in args.tile_url:
        args.sources_list.append(make_source("Custom", args.tile_url, 0, 19))
    if args.list_sources:
        for s in args.sources_list:
            print(s["name"])
        return 0

    if args.cache_km > 0:
        src = None
        for s in args.sources_list:
            if args.source and args.source.lower() in (s["name"].lower(), s["slug"]):
                src = s
        src = src or (args.sources_list[0] if args.sources_list else None)
        if not src:
            print("ERROR no map source configured", flush=True)
            return 2
        me = read_self(args.run, args.manual)
        center = args.center or (me[:2] if me else None)
        if not center:
            print("ERROR no position", flush=True)
            return 2
        zmin, zmax = (int(v) for v in args.cache_zoom.split("-"))
        return cache_area(src, args.tiles, center[0], center[1], args.cache_km, zmin, zmax)

    Pager = load_display(args.lib)
    if args.self_check:
        print("display OK")
        return 0

    state = {"run": True}

    def stop(*_):
        state["run"] = False

    import signal
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with Pager() as p:
        p.set_rotation(270)
        p.clear_input_events()
        if args.nav:
            nav = NavView(Pager, p, args)
            if nav.run(lambda: state["run"]) != 20:
                p.clear(p.BLACK)
                p.flip()
                return 0
            t = nav.target()
            args.center = (t["lat"], t["lon"]) if t else None
            p.clear_input_events()
        view = MapView(Pager, p, args)
        if args.center:
            view.follow = False
            view.cx, view.cy = world_px(args.center[0], args.center[1], view.z)
        try:
            return view.run(lambda: state["run"])
        finally:
            view.tiles.free_all()
            p.clear(p.BLACK)
            p.flip()


if __name__ == "__main__":
    sys.exit(main())
