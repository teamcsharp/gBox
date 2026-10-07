"""Read-only PlayStation disc access: CHD v4/v5-zlib containers (as in the HyperSpin set) -> raw 2352-byte sectors ->
ISO9660 file listing + file reads (Mode 2 Form 1 user data). No external tools (chdman not needed)."""
from __future__ import annotations

import struct
import zlib
from functools import lru_cache


class CHD:
    """CHD v4 (zlib / zlib+ CD hunks). v5 raises (needs LZMA/FLAC + Huffman map)."""

    def __init__(self, path):
        self.f = open(path, "rb")
        h = self.f.read(0x6C)
        if h[:8] != b"MComprHD":
            raise ValueError("not a CHD")
        hlen, ver = struct.unpack_from(">II", h, 8)
        if ver != 4:
            raise NotImplementedError(f"CHD v{ver} not supported (v4 only)")
        _flags, self.comp, self.nhunks = struct.unpack_from(">III", h, 16)
        self.logical, _meta = struct.unpack_from(">QQ", h, 28)
        self.hunkbytes = struct.unpack_from(">I", h, 44)[0]
        self.f.seek(hlen)
        raw = self.f.read(16 * self.nhunks)
        self.map = [struct.unpack_from(">QIHBB", raw, 16 * i) for i in range(self.nhunks)]
        self.frame = 2448                                  # 2352 sector + 96 subcode
        self.frames_per_hunk = self.hunkbytes // self.frame
        self._hunk = lru_cache(64)(self._read_hunk)

    def _read_hunk(self, i: int) -> bytes:
        off, crc, lo, hi, flags = self.map[i]
        ln = lo | (hi << 16)
        t = flags & 0xF
        if t == 1:                                         # compressed
            self.f.seek(off)
            d = self.f.read(ln)
            try:
                return zlib.decompress(d, -15)
            except zlib.error:
                return zlib.decompress(d)
        if t == 2:                                         # uncompressed
            self.f.seek(off)
            return self.f.read(self.hunkbytes)
        if t == 3:                                         # mini: 8-byte pattern repeated
            return struct.pack(">Q", off) * (self.hunkbytes // 8)
        if t == 4:                                         # same as another hunk
            return self._hunk(off)
        raise NotImplementedError(f"hunk type {t}")

    def sector(self, lba: int) -> bytes:
        """Raw 2352-byte sector by frame index (frame 0 = start of track 1)."""
        h, k = divmod(lba, self.frames_per_hunk)
        return self._hunk(h)[k * self.frame:k * self.frame + 2352]


class PSXDisc:
    def __init__(self, path):
        self.chd = CHD(path)
        pvd = self.data(16)
        assert pvd[1:6] == b"CD001", "no ISO9660 PVD"
        root = pvd[156:156 + 34]
        self.files: dict[str, tuple[int, int]] = {}
        self._walk(struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0], "")

    def data(self, lba: int) -> bytes:
        s = self.chd.sector(lba)
        return s[24:24 + 2048] if s[15] == 2 else s[16:16 + 2048]

    def read(self, name: str) -> bytes:
        lba, size = self.files[name]
        return b"".join(self.data(lba + i) for i in range((size + 2047) // 2048))[:size]

    def _walk(self, lba, size, prefix):
        buf = b"".join(self.data(lba + i) for i in range((size + 2047) // 2048))
        o = 0
        while o < len(buf):
            ln = buf[o]
            if ln == 0:
                o = (o // 2048 + 1) * 2048
                continue
            elba, esize = struct.unpack_from("<I", buf, o + 2)[0], struct.unpack_from("<I", buf, o + 10)[0]
            flags, nl = buf[o + 25], buf[o + 32]
            name = buf[o + 33:o + 33 + nl]
            if name not in (b"\0", b"\1"):
                n = name.decode("latin-1").split(";")[0]
                if flags & 2:
                    self._walk(elba, esize, f"{prefix}{n}/")
                else:
                    self.files[f"{prefix}{n}"] = (elba, esize)
            o += ln
