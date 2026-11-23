"""pagerfb - pure-Python screen and button driver for the WiFi Pineapple Pager.

Draws to the Pager's framebuffer (/dev/fb0, 222x480 RGB565) and reads its
buttons (/dev/input/event*), using only the Python standard library. It needs
no compiled code and no download, and it runs on python3-light.

The drawing API matches the parts of pagerctl (MIT, pineapple-pager-projects)
that PagerTAK uses, so the map code works with either. The 5x7 bitmap font is
pagerctl's (MIT License).

Speed comes from working in the framebuffer's own layout: rectangles, lines
of tiles and text are written as whole byte slices, PNG tiles are decoded
with zlib plus big-integer arithmetic for the common row filters, and flip()
writes only the rows that changed.

Testing without a Pager: set PAGERFB_FB=/path/file (a 222*480*2-byte file is
created) and PAGERFB_INPUT=none (or a device path to read buttons from); PAGERFB_SHOT=/path.png saves every non-blank
frame there as a screenshot (needs only zlib).
"""
import os
import struct
import sys
import time
import zlib

FB_W, FB_H = 222, 480                      # native panel: portrait, RGB565
KEYS = {103: 0x01, 108: 0x02, 105: 0x04, 106: 0x08, 305: 0x10, 304: 0x20, 116: 0x40}
_EV = struct.Struct("llHHi")              # struct input_event (32-bit userspace)
_LE = sys.byteorder == "little"

_FONT = bytes.fromhex(
    "000000000000005f00000007000700147f147f14242a7f2a12231308646236495522500005030000001c224100"
    "0041221c00082a1c2a0808083e080800503000000808080808006060000020100804023e5149453e00427f4000"
    "42615149462141454b311814127f1027454545393c4a49493001710905033649494936064949291e0036360000"
    "00563600000008142241141414141441221408000201510906324979413e7e1111117e7f494949363e41414122"
    "7f4141221c7f494949417f090901013e414151327f0808087f00417f41002040413f017f081422417f40404040"
    "7f0204027f7f0408107f3e4141413e7f090909063e4151215e7f09192946464949493101017f01013f4040403f"
    "1f2040201f7f2018207f63140814630304780403615149454300007f4141020408102041417f00000402010204"
    "4040404040000102040020545454787f484444383844444420384444487f3854545418087e090102081454543c"
    "7f0804047800447d40002040443d00007f10284400417f40007c041804787c0804047838444444387c14141408"
    "081414187c7c080404084854545420043f4440203c4040207c1c2040201c3c4030403c44281028440c5050503c"
    "4464544c44000836410000007f0000004136080008082a1c08081c2a0808")


def rgb(r, g, b):
    """RGB (0-255) to RGB565."""
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


class Image:
    """A decoded image: width, height and RGB565 pixels (little-endian, row-major)."""
    __slots__ = ("w", "h", "px", "_cols")

    def __init__(self, w, h, px):
        self.w, self.h, self.px, self._cols = w, h, px, None

    def columns(self):
        """Each image column, bottom pixel first: one framebuffer row when rotated 270."""
        if self._cols is None:
            w, h, px = self.w, self.h, self.px
            cols = []
            for c in range(w):
                col = bytearray(2 * h)
                col[0::2] = px[2 * c::2 * w][::-1]
                col[1::2] = px[2 * c + 1::2 * w][::-1]
                cols.append(bytes(col))
            self._cols = cols
        return self._cols


# -------------------------------------------------------------------- PNG
_H80, _M7F = {}, {}


def _masks(n):
    if n not in _H80:
        _H80[n] = int.from_bytes(b"\x80" * n, "little")
        _M7F[n] = int.from_bytes(b"\x7f" * n, "little")
    return _H80[n], _M7F[n]


def _add(a, b, n):
    """Byte-wise (a + b) mod 256 over n bytes packed in two integers."""
    h, m = _masks(n)
    return ((a & m) + (b & m)) ^ ((a ^ b) & h)


def _unfilter(raw, h, stride, bpp):
    out = bytearray(h * stride)
    prev = bytes(stride)
    pos = 0
    full = (1 << (8 * stride)) - 1
    for y in range(h):
        f = raw[pos]
        row = raw[pos + 1:pos + 1 + stride]
        pos += 1 + stride
        if f == 0:
            cur = row
        elif f == 2:                                   # Up
            cur = _add(int.from_bytes(row, "little"), int.from_bytes(prev, "little"), stride).to_bytes(stride, "little")
        elif f == 1:                                   # Sub: prefix sum per byte lane, by doubling
            x = int.from_bytes(row, "little")
            s = bpp
            while s < stride:
                x = _add(x, (x << (8 * s)) & full, stride)
                s *= 2
            cur = x.to_bytes(stride, "little")
        elif f == 3:                                   # Average
            c = bytearray(row)
            for i in range(stride):
                a = c[i - bpp] if i >= bpp else 0
                c[i] = (c[i] + ((a + prev[i]) >> 1)) & 255
            cur = c
        elif f == 4:                                   # Paeth
            c = bytearray(row)
            for i in range(stride):
                if i >= bpp:
                    a, cc = c[i - bpp], prev[i - bpp]
                else:
                    a = cc = 0
                b = prev[i]
                p = a + b - cc
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - cc)
                c[i] = (c[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else cc)) & 255
            cur = c
        else:
            raise ValueError("bad PNG filter %d" % f)
        out[y * stride:(y + 1) * stride] = cur
        prev = cur
    return out


_T = {}


def _tables():
    if not _T:
        _T["rh"] = bytes(v & 0xF8 for v in range(256))            # red -> high byte bits 7..3
        _T["gh"] = bytes(v >> 5 for v in range(256))              # green -> high byte bits 2..0
        _T["gl"] = bytes((v << 3) & 0xE0 for v in range(256))     # green -> low byte bits 7..5
        _T["bl"] = bytes(v >> 3 for v in range(256))              # blue -> low byte bits 4..0
    return _T


def _or(a, b):
    n = len(a)
    return (int.from_bytes(a, "little") | int.from_bytes(b, "little")).to_bytes(n, "little")


def _to565(r, g, b):
    t = _tables()
    hi = _or(r.translate(t["rh"]), g.translate(t["gh"]))
    lo = _or(g.translate(t["gl"]), b.translate(t["bl"]))
    out = bytearray(2 * len(r))
    out[0::2], out[1::2] = (lo, hi) if _LE else (hi, lo)
    return out


def decode_png(data):
    """PNG bytes -> Image, or None for anything unsupported (interlaced, JPEG...)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos, idat, plte = 8, [], b""
    w = h = depth = ctype = interlace = 0
    while pos + 8 <= len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            plte = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if not w or interlace or ctype not in (0, 2, 3, 4, 6):
        return None
    chans = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    bits = depth * chans
    stride = (w * bits + 7) // 8
    bpp = max(1, bits // 8)
    px = _unfilter(zlib.decompress(b"".join(idat)), h, stride, bpp)
    if depth == 16:                                    # keep the high byte of each sample
        px = px[0::2]
        depth = 8
        stride //= 2
    if depth < 8:                                      # expand packed palette / gray to 1 byte per pixel
        per = 8 // depth
        mask = (1 << depth) - 1
        exp = bytearray(w * h)
        for y in range(h):
            row = px[y * stride:(y + 1) * stride]
            o = y * w
            for x in range(w):
                exp[o + x] = (row[x // per] >> (8 - depth * (1 + x % per))) & mask
        if ctype == 0:
            scale = 255 // mask
            exp = exp.translate(bytes(min(255, v * scale) for v in range(256)))
        px = exp
    if ctype == 3:
        pal = [bytes(plte[i:i + 3]) for i in range(0, len(plte), 3)]
        pal += [b"\x00\x00\x00"] * (256 - len(pal))
        lut = []
        for c in pal:
            v = rgb(c[0], c[1], c[2])
            lut.append(struct.pack("<H" if _LE else ">H", v))
        return Image(w, h, bytearray(b"".join(map(lut.__getitem__, px))))
    if ctype == 0:
        g = bytes(px)
        return Image(w, h, _to565(g, g, g))
    if ctype == 4:
        g = bytes(px[0::2])
        return Image(w, h, _to565(g, g, g))
    step = 3 if ctype == 2 else 4
    return Image(w, h, _to565(bytes(px[0::step]), bytes(px[1::step]), bytes(px[2::step])))


def encode_png(w, h, rgb_rows):
    """Minimal RGB PNG writer (used for screenshots)."""
    raw = b"".join(b"\x00" + r for r in rgb_rows)

    def chunk(k, d):
        return struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# -------------------------------------------------------------------- the driver
class Pager:
    BLACK, WHITE = 0x0000, 0xFFFF
    RED, GREEN, BLUE, YELLOW, CYAN = 0xF800, 0x07E0, 0x001F, 0xFFE0, 0x07FF
    BTN_UP, BTN_DOWN, BTN_LEFT, BTN_RIGHT, BTN_A, BTN_B, BTN_POWER = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40
    rgb = staticmethod(rgb)

    def __init__(self):
        self.fb = None
        self.inputs = []
        self.buf = bytearray(FB_W * FB_H * 2)
        self.rot = 0
        self.width, self.height = FB_W, FB_H
        self.cur = 0
        self.dirty = None                          # (first row, last row) changed since flip()
        self._pat = {}
        self._txt = {}                             # compiled text: (text, size) -> runs
        self._evq = []                             # button events in order: (bit, 1 down / 0 up)
        self._shot = os.environ.get("PAGERFB_SHOT")      # test aid: save each non-blank frame

    # -- lifetime
    def __enter__(self):
        path = os.environ.get("PAGERFB_FB", "/dev/fb0")
        if path != "/dev/fb0" and not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(bytes(len(self.buf)))
        self._check_size()
        self.fb = os.open(path, os.O_RDWR)
        # Buttons: one device, like pagerctl (event0, else event1). Reading every input device
        # can mix in a second source of key events. PAGERFB_INPUT=/dev/input/eventN picks one.
        want = os.environ.get("PAGERFB_INPUT", "")
        if want != "none":
            for dev in ([want] if want else ["/dev/input/event0", "/dev/input/event1"]):
                try:
                    self.inputs.append(os.open(dev, os.O_RDONLY | os.O_NONBLOCK))
                    break
                except OSError:
                    pass
        return self

    def __exit__(self, *exc):
        self.clear(0)
        self.flip()
        for fd in self.inputs:
            os.close(fd)
        self.inputs = []
        if self.fb is not None:
            os.close(self.fb)
            self.fb = None

    @staticmethod
    def _check_size():
        try:
            with open("/sys/class/graphics/fb0/virtual_size") as f:
                w, h = (int(v) for v in f.read().split(","))
            with open("/sys/class/graphics/fb0/bits_per_pixel") as f:
                bpp = int(f.read())
        except (OSError, ValueError):
            return
        if (w, h, bpp) != (FB_W, FB_H, 16):
            sys.stderr.write("pagerfb: unexpected framebuffer %dx%d %d bpp\n" % (w, h, bpp))

    def set_rotation(self, deg):
        self.rot = deg % 360
        self.width, self.height = (FB_H, FB_W) if self.rot in (90, 270) else (FB_W, FB_H)

    # -- low level
    def _c(self, color):
        p = self._pat.get(color)
        if p is None:
            p = struct.pack("<H" if _LE else ">H", color & 0xFFFF) * max(FB_W, FB_H)
            self._pat[color] = p
        return p

    def _mark(self, r0, r1):
        d = self.dirty
        self.dirty = (r0, r1) if d is None else (min(d[0], r0), max(d[1], r1))

    def _native(self, x, y):
        r = self.rot
        if r == 270:
            return FB_W - 1 - y, x
        if r == 0:
            return x, y
        if r == 90:
            return y, FB_H - 1 - x
        return FB_W - 1 - x, FB_H - 1 - y

    def set_pixel(self, x, y, color):
        if 0 <= x < self.width and 0 <= y < self.height:
            fx, fy = self._native(x, y)
            o = (fy * FB_W + fx) * 2
            self.buf[o:o + 2] = self._c(color)[:2]
            self._mark(fy, fy)

    # -- drawing
    def clear(self, color=0):
        self.buf[:] = (self._c(color)[:FB_W * 2]) * FB_H
        self._mark(0, FB_H - 1)

    def fill_rect(self, x, y, w, h, color):
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.width, x + w), min(self.height, y + h)
        if x0 >= x1 or y0 >= y1:
            return
        pat, buf = self._c(color), self.buf
        if self.rot == 270:                        # logical column = framebuffer row
            n = (y1 - y0) * 2
            seg = pat[:n]
            fx = FB_W - y1
            for fy in range(x0, x1):
                o = (fy * FB_W + fx) * 2
                buf[o:o + n] = seg
            self._mark(x0, x1 - 1)
        elif self.rot == 0:
            n = (x1 - x0) * 2
            seg = pat[:n]
            for fy in range(y0, y1):
                o = (fy * FB_W + x0) * 2
                buf[o:o + n] = seg
            self._mark(y0, y1 - 1)
        else:
            for yy in range(y0, y1):
                for xx in range(x0, x1):
                    self.set_pixel(xx, yy, color)

    def hline(self, x, y, w, color):
        self.fill_rect(x, y, w, 1, color)

    def vline(self, x, y, h, color):
        self.fill_rect(x, y, 1, h, color)

    def rect(self, x, y, w, h, color):
        self.hline(x, y, w, color)
        self.hline(x, y + h - 1, w, color)
        self.vline(x, y, h, color)
        self.vline(x + w - 1, y, h, color)

    draw_rect = rect

    def line(self, x0, y0, x1, y1, color):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        for _ in range(dx - dy + 1):
            self.set_pixel(x0, y0, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    draw_line = line

    def fill_circle(self, cx, cy, r, color):
        for dy in range(-r, r + 1):
            dx = int((r * r - dy * dy) ** 0.5)
            self.fill_rect(cx - dx, cy + dy, 2 * dx + 1, 1, color)

    def circle(self, cx, cy, r, color):
        x, y, err = r, 0, 0
        while x >= y:
            for px, py in ((x, y), (y, x), (-y, x), (-x, y), (-x, -y), (-y, -x), (y, -x), (x, -y)):
                self.set_pixel(cx + px, cy + py, color)
            y += 1
            err += 1 + 2 * y
            if 2 * (err - x) + 1 > 0:
                x -= 1
                err += 1 - 2 * x

    draw_circle = circle

    def _text_runs(self, text, size):
        """Lit runs of a string as (dx, y0, y1) logical rectangles size px wide, plus width and height."""
        key = (text, size)
        r = self._txt.get(key)
        if r is not None:
            return r
        runs, x, y, w, h = [], 0, 0, 0, 7 * size
        for ch in text:
            if ch == "\n":
                x, y = 0, y + 8 * size
                h = y + 7 * size
                continue
            o = ord(ch)
            g = _FONT[(o - 32) * 5:(o - 32) * 5 + 5] if 32 <= o <= 127 else _FONT[31 * 5:32 * 5]
            for col in range(5):
                bits, row = g[col], 0
                while bits:
                    if bits & 1:
                        n = 0
                        while bits & 1:
                            bits >>= 1
                            n += 1
                        for k in range(size):
                            runs.append((x + col * size + k, y + row * size, y + (row + n) * size))
                        row += n
                    else:
                        bits >>= 1
                        row += 1
            x += 6 * size
            w = max(w, x)
        if len(self._txt) > 3000:
            self._txt.clear()
        r = self._txt[key] = (runs, w, h)
        return r

    def draw_text(self, x, y, text, color, size=1):
        runs, w, h = self._text_runs(text, size)
        if self.rot == 270 and x >= 0 and y >= 0 and x + w <= self.width and y + h <= self.height:
            # fast path: each run is one slice of a framebuffer row
            pat, buf, base = self._c(color), self.buf, FB_W - y
            for dx, y0, y1 in runs:
                n = (y1 - y0) * 2
                o = ((x + dx) * FB_W + base - y1) * 2
                buf[o:o + n] = pat[:n]
            if runs:
                self._mark(x, x + w - 1)
            return w
        return self._draw_text_slow(x, y, text, color, size)

    def _draw_text_slow(self, x, y, text, color, size=1):
        sx = x
        for ch in text:
            if ch == "\n":
                x, y = sx, y + 8 * size
                continue
            o = ord(ch)
            g = _FONT[(o - 32) * 5:(o - 32) * 5 + 5] if 32 <= o <= 127 else _FONT[31 * 5:32 * 5]
            for col in range(5):
                bits = g[col]
                if bits:
                    row = 0
                    while bits:                        # runs of lit pixels as one rectangle
                        if bits & 1:
                            run = 0
                            while bits & 1:
                                bits >>= 1
                                run += 1
                            self.fill_rect(x + col * size, y + row * size, size, run * size, color)
                            row += run
                        else:
                            bits >>= 1
                            row += 1
            x += 6 * size
        return x - sx

    def text_width(self, text, size=1):
        return max(0, 6 * size * len(text) - size)

    def draw_text_centered(self, y, text, color, size=1):
        self.draw_text((self.width - self.text_width(text, size)) // 2, y, text, color, size)

    # -- images
    def load_image(self, path):
        """PNG file -> Image (None if it is not a PNG this driver can read)."""
        try:
            with open(path, "rb") as f:
                return decode_png(f.read())
        except (OSError, ValueError, zlib.error, struct.error):
            return None

    def free_image(self, img):
        pass

    def draw_image(self, x, y, img):
        if img is None:
            return
        if self.rot == 270:
            r0, r1 = max(0, -y), min(img.h, self.height - y)          # visible image rows
            c0, c1 = max(0, -x), min(img.w, self.width - x)
            if r0 >= r1 or c0 >= c1:
                return
            cols, buf = img.columns(), self.buf
            a, b = 2 * (img.h - r1), 2 * (img.h - r0)
            fx = FB_W - (y + r1)
            for c in range(c0, c1):
                o = ((x + c) * FB_W + fx) * 2
                buf[o:o + b - a] = cols[c][a:b]
            self._mark(x + c0, x + c1 - 1)
        elif self.rot == 0:
            c0, c1 = max(0, -x), min(img.w, FB_W - x)
            for r in range(max(0, -y), min(img.h, FB_H - y)):
                o = ((y + r) * FB_W + x + c0) * 2
                self.buf[o:o + 2 * (c1 - c0)] = img.px[2 * (r * img.w + c0):2 * (r * img.w + c1)]
            self._mark(max(0, y), min(FB_H, y + img.h) - 1)
        else:
            raise NotImplementedError("draw_image supports rotation 0 and 270")

    # -- output
    def flip(self):
        if self.fb is None or self.dirty is None:
            return
        a, b = self.dirty[0] * FB_W * 2, (self.dirty[1] + 1) * FB_W * 2
        os.pwrite(self.fb, memoryview(self.buf)[a:b], a)
        self.dirty = None
        if self._shot and self.buf.count(0) != len(self.buf):
            self.screenshot(self._shot)

    def screenshot(self, path):
        """Saves the current frame, as the viewer sees it, to a PNG file."""
        rows = []
        for y in range(self.height):
            row = bytearray(3 * self.width)
            for x in range(self.width):
                fx, fy = self._native(x, y)
                o = (fy * FB_W + fx) * 2
                v = self.buf[o] | (self.buf[o + 1] << 8) if _LE else (self.buf[o] << 8) | self.buf[o + 1]
                row[3 * x:3 * x + 3] = bytes(((v >> 8) & 0xF8, (v >> 3) & 0xFC, (v << 3) & 0xF8))
            rows.append(bytes(row))
        with open(path, "wb") as f:
            f.write(encode_png(self.width, self.height, rows))

    # -- buttons
    def _read_events(self):
        pressed = released = 0
        for fd in self.inputs:
            while True:
                try:
                    data = os.read(fd, _EV.size * 32)
                except (BlockingIOError, InterruptedError):
                    break
                except OSError:
                    break
                if not data:
                    break
                for i in range(0, len(data) - _EV.size + 1, _EV.size):
                    _, _, typ, code, val = _EV.unpack_from(data, i)
                    bit = KEYS.get(code) if typ == 1 else None
                    if not bit:
                        continue
                    if val == 1:
                        self.cur |= bit
                        pressed |= bit
                        self._evq.append((bit, 1))
                    elif val == 0:
                        self.cur &= ~bit
                        released |= bit
                        self._evq.append((bit, 0))
        if len(self._evq) > 256:
            del self._evq[:-256]
        return pressed, released

    def poll_input(self):
        """(held, pressed since last call, released since last call) as BTN_* bitmasks."""
        pressed, released = self._read_events()
        self._evq = []
        return self.cur, pressed, released

    def poll_events(self):
        """Button events since the last call, in the order they happened: [(BTN_*, 1 down / 0 up)].
        Use this for combos (hold B + UP): bitmasks lose the order when drawing is slow."""
        self._read_events()
        ev, self._evq = self._evq, []
        return ev

    def clear_input_events(self):
        self._read_events()
        self._evq = []
        self.cur = 0


if __name__ == "__main__":
    # Self-test pattern: python3 pagerfb.py  (any button exits, or 10 s)
    with Pager() as p:
        p.set_rotation(270)
        p.clear(p.BLACK)
        for i, c in enumerate((p.RED, p.GREEN, p.BLUE, p.YELLOW, p.CYAN, p.WHITE)):
            p.fill_rect(10 + i * 76, 40, 70, 60, c)
        p.rect(0, 0, p.width, p.height, p.WHITE)
        p.draw_text(10, 10, "pagerfb OK - press any button", p.WHITE, 2)
        p.draw_text(10, 120, "ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz 0123456789", p.GREEN, 1)
        p.fill_circle(400, 170, 30, p.RED)
        p.circle(400, 170, 40, p.WHITE)
        p.line(10, 210, 300, 140, p.YELLOW)
        t = time.time()
        p.flip()
        print("frame drawn in %.3f s" % (time.time() - t))
        end = time.time() + 10
        while time.time() < end:
            if p.poll_input()[1]:
                break
            time.sleep(0.05)
