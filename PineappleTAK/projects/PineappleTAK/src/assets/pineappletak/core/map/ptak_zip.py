"""Small ZIP writer and UUID helper for python3-light.

On the Pager, Python's zipfile module pulls in pathlib, which needs urllib,
and urllib ships in a separate package (python3-urllib). This writer covers
what PagerTAK needs - building TAK data packages - with only os, struct,
time, binascii and (optionally) zlib.
"""
import binascii
import os
import struct
import time

try:
    import zlib
except ImportError:          # python3-light without zlib: store only
    zlib = None


def uuid4():
    """Random UUID (version 4) as a string, without the uuid module."""
    b = bytearray(os.urandom(16))
    b[6] = (b[6] & 0x0F) | 0x40
    b[8] = (b[8] & 0x3F) | 0x80
    h = b.hex()
    return "%s-%s-%s-%s-%s" % (h[:8], h[8:12], h[12:16], h[16:20], h[20:])


def _dos_time(t):
    lt = time.localtime(t)
    return (lt.tm_hour << 11) | (lt.tm_min << 5) | (lt.tm_sec // 2), \
        ((max(lt.tm_year, 1980) - 1980) << 9) | (lt.tm_mon << 5) | lt.tm_mday


class ZipWriter:
    """with ZipWriter(path, deflate=True) as z: z.add(name, data) / z.add_file(name, path)"""

    def __init__(self, path, deflate=True):
        self.fh = open(path, "wb")
        self.deflate = bool(deflate and zlib)
        self.entries = []

    def add(self, name, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        crc = binascii.crc32(data) & 0xFFFFFFFF
        method, body = 0, data
        if self.deflate and len(data) > 64:
            c = zlib.compressobj(6, zlib.DEFLATED, -15)
            packed = c.compress(data) + c.flush()
            if len(packed) < len(data):
                method, body = 8, packed
        self._write(name, crc, method, body, len(data))

    def add_file(self, name, path):
        with open(path, "rb") as f:
            self.add(name, f.read())

    def _write(self, name, crc, method, body, size):
        fname = name.encode("utf-8")
        mtime, mdate = _dos_time(time.time())
        offset = self.fh.tell()
        flags = 0x0800                                   # names are UTF-8
        self.fh.write(struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, flags, method, mtime, mdate,
                                  crc, len(body), size, len(fname), 0))
        self.fh.write(fname)
        self.fh.write(body)
        self.entries.append((fname, crc, method, mtime, mdate, len(body), size, offset, flags))

    def close(self):
        if self.fh is None:
            return
        start = self.fh.tell()
        for fname, crc, method, mtime, mdate, csize, size, offset, flags in self.entries:
            self.fh.write(struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, flags, method, mtime, mdate,
                                      crc, csize, size, len(fname), 0, 0, 0, 0, 0, offset))
            self.fh.write(fname)
        end = self.fh.tell()
        self.fh.write(struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(self.entries), len(self.entries),
                                  end - start, start, 0))
        self.fh.close()
        self.fh = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def read_zip(data, max_total=8 * 1024 * 1024):
    """ZIP bytes -> {name: bytes} for stored and deflated entries (central directory based)."""
    end = data.rfind(b"PK\x05\x06")
    if end < 0:
        raise ValueError("not a zip file")
    count, cd_size, cd_off = struct.unpack("<HII", data[end + 10:end + 20])
    out, pos, total = {}, cd_off, 0
    for _ in range(count):
        if data[pos:pos + 4] != b"PK\x01\x02":
            raise ValueError("bad zip directory")
        (method, crc, csize, size, nlen, xlen, clen, off) = struct.unpack("<HxxxxIIIHHH8xI", data[pos + 10:pos + 46])
        name = data[pos + 46:pos + 46 + nlen].decode("utf-8", "replace")
        pos += 46 + nlen + xlen + clen
        if name.endswith("/"):
            continue
        lnlen, lxlen = struct.unpack("<HH", data[off + 26:off + 30])
        body = data[off + 30 + lnlen + lxlen:off + 30 + lnlen + lxlen + csize]
        total += size
        if total > max_total:
            raise ValueError("zip too large")
        if method == 0:
            raw = body
        elif method == 8 and zlib:
            raw = zlib.decompress(body, -15)
        else:
            raise ValueError("unsupported zip compression")
        if binascii.crc32(raw) & 0xFFFFFFFF != crc:
            raise ValueError("zip checksum error in " + name)
        out[name] = raw
    return out
