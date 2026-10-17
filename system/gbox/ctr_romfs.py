"""Read-only Nintendo 3DS cartridge image (NCSD/.3ds) reader.

Parses the NCSD partition table, the first NCCH (game) partition, its ExeFS
directory, the SMDH icon (titles + region lockout) and walks the IVFC level-3
RomFS directory tree.  Only *decrypted* images are supported: an encrypted
partition is reported as such and never decrypted here (no keys, no bypass).

The image is opened read-only; nothing in the owned dump is modified.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

MEDIA = 0x200

REGIONS = {0x01: "JPN", 0x02: "USA", 0x04: "EUR", 0x08: "AUS", 0x10: "CHN", 0x20: "KOR", 0x40: "TWN"}
# Last product-code letter -> region (CTR-P-xxxY).  E = USA, P = EUR/PAL, J = JPN ...
PRODUCT_REGION = {"E": "USA", "P": "EUR", "J": "JPN", "U": "AUS", "Z": "EUR", "K": "KOR", "C": "CHN", "W": "TWN",
                  "A": "ALL"}


class CtrError(ValueError):
    pass


@dataclass
class RomFile:
    path: str
    offset: int  # absolute offset in the image
    size: int


@dataclass
class Ncch:
    offset: int
    title_id: int
    program_id: int
    product_code: str
    flags: bytes
    exheader_size: int
    exefs: tuple[int, int]  # absolute offset, size
    romfs: tuple[int, int]
    exefs_files: dict = field(default_factory=dict)  # name -> (abs offset, size)

    @property
    def no_crypto_flag(self) -> bool:
        return bool(self.flags[7] & 0x04)


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


class CtrImage:
    def __init__(self, path):
        self.path = Path(path)
        self._f = open(self.path, "rb")
        hdr = self.read(0, 0x200)
        if hdr[0x100:0x104] != b"NCSD":
            raise CtrError("not an NCSD (.3ds) image")
        self.media_id = struct.unpack_from("<Q", hdr, 0x108)[0]
        self.partitions = []
        for i in range(8):
            off, size = struct.unpack_from("<II", hdr, 0x120 + i * 8)
            if size:
                self.partitions.append((i, off * MEDIA, size * MEDIA))
        if not self.partitions or self.partitions[0][0] != 0:
            raise CtrError("NCSD has no game partition 0")
        self.ncch = self._ncch(self.partitions[0][1])

    # -- io
    def read(self, off: int, n: int) -> bytes:
        self._f.seek(off)
        return self._f.read(n)

    def close(self):
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # -- NCCH / ExeFS
    def _ncch(self, base: int) -> Ncch:
        h = self.read(base, 0x200)
        if h[0x100:0x104] != b"NCCH":
            raise CtrError(f"partition at {base:#x} is not NCCH")
        exo, exs = struct.unpack_from("<II", h, 0x1A0)
        rfo, rfs = struct.unpack_from("<II", h, 0x1B0)
        n = Ncch(offset=base,
                 title_id=struct.unpack_from("<Q", h, 0x108)[0],
                 program_id=struct.unpack_from("<Q", h, 0x118)[0],
                 product_code=h[0x150:0x160].split(b"\0")[0].decode("ascii", "replace"),
                 flags=h[0x188:0x190],
                 exheader_size=_u32(h, 0x180),
                 exefs=(base + exo * MEDIA, exs * MEDIA),
                 romfs=(base + rfo * MEDIA, rfs * MEDIA))
        if exs:
            eh = self.read(n.exefs[0], 0x200)
            for i in range(10):
                name, off, size = struct.unpack_from("<8sII", eh, i * 16)
                name = name.split(b"\0")[0].decode("ascii", "replace")
                if name and size:
                    n.exefs_files[name] = (n.exefs[0] + 0x200 + off, size)
        return n

    def decrypted(self) -> bool:
        """True when ExeFS/RomFS are plaintext (checks content, not just the NoCrypto flag:
        many decrypted dumps keep the original crypto flags)."""
        n = self.ncch
        ok = True
        if n.exefs[1]:
            eh = self.read(n.exefs[0], 0x10)
            ok &= eh[:5] == b".code"
        if n.romfs[1]:
            ok &= self.read(n.romfs[0], 4) == b"IVFC"
        return bool(ok)

    def exheader(self) -> dict:
        n = self.ncch
        if not n.exheader_size:
            return {}
        e = self.read(n.offset + 0x200, 0x400)
        return {"name": e[:8].split(b"\0")[0].decode("ascii", "replace"),
                "code_compressed": bool(e[0xD] & 1),
                "sd_app": bool(e[0xD] & 2),
                "text_address": _u32(e, 0x10)}

    def exefs_file(self, name: str) -> bytes:
        off, size = self.ncch.exefs_files[name]
        return self.read(off, size)

    def smdh(self) -> dict:
        if "icon" not in self.ncch.exefs_files:
            return {}
        s = self.exefs_file("icon")
        if s[:4] != b"SMDH":
            return {}

        def t(i, a, b):
            o = 8 + i * 0x200
            return s[o + a:o + b].decode("utf-16le", "replace").split("\0")[0]

        lock = _u32(s, 0x2018)
        return {"short_title": t(1, 0, 0x80), "long_title": t(1, 0x80, 0x180), "publisher": t(1, 0x180, 0x200),
                "region_lockout": lock,
                "regions": [v for k, v in REGIONS.items() if lock & k] if lock != 0x7FFFFFFF else ["region-free"]}

    def region(self) -> dict:
        """Region evidence: product-code suffix and SMDH lockout bits (both from the dump itself)."""
        pc = self.ncch.product_code
        return {"product_code": pc, "product_region": PRODUCT_REGION.get(pc[-1:], "?"),
                "smdh_regions": self.smdh().get("regions", [])}

    # -- RomFS
    def romfs_level3(self) -> int:
        off, size = self.ncch.romfs
        iv = self.read(off, 0x60)
        if iv[:4] != b"IVFC":
            raise CtrError("RomFS is not plaintext IVFC (encrypted image?)")
        master = _u32(iv, 0x08)
        bs = 1 << _u32(iv, 0x4C)
        return off + ((0x60 + master + bs - 1) // bs) * bs

    def romfs_files(self) -> list[RomFile]:
        l3 = self.romfs_level3()
        hdr = self.read(l3, 0x28)
        (hs, dho, dhl, dmo, dml, fho, fhl, fmo, fml, fdo) = struct.unpack("<10I", hdr)
        if hs != 0x28:
            raise CtrError(f"unexpected RomFS level-3 header size {hs:#x}")
        dm = self.read(l3 + dmo, dml)
        fm = self.read(l3 + fmo, fml)
        out: list[RomFile] = []
        stack = [(0, "")]
        seen = set()
        while stack:
            doff, parent = stack.pop()
            if doff in seen:
                raise CtrError("RomFS directory loop")
            seen.add(doff)
            _p, _sib, child, fil, _n, nl = struct.unpack_from("<6I", dm, doff)
            name = dm[doff + 0x18:doff + 0x18 + nl].decode("utf-16le")
            path = parent + name + "/" if doff else "/"
            fo = fil
            while fo != 0xFFFFFFFF:
                _par, fsib, doff_, size, _nh, fnl = struct.unpack_from("<IIQQII", fm, fo)
                fn = fm[fo + 0x20:fo + 0x20 + fnl].decode("utf-16le")
                out.append(RomFile(path + fn, l3 + fdo + doff_, size))
                fo = fsib
            kids = []
            c = child
            while c != 0xFFFFFFFF:
                kids.append(c)
                c = _u32(dm, c + 4)
            stack.extend((k, path) for k in reversed(kids))
        out.sort(key=lambda r: r.path)
        return out

    def read_file(self, rf: RomFile) -> bytes:
        return self.read(rf.offset, rf.size)


def blz_decompress(data: bytes) -> bytes:
    """Decompress a 3DS ExeFS ``.code`` stored with the backward LZ77 ("BLZ") scheme
    (exheader system-control flag bit 0).  The 8-byte footer holds
    ``(header_len << 24) | compressed_len`` and the number of extra bytes the output grows by."""
    if len(data) < 8:
        raise CtrError("BLZ input too short")
    word, add = struct.unpack_from("<II", data, len(data) - 8)
    enc, hl = word & 0xFFFFFF, word >> 24
    if enc > len(data) or hl < 8 or hl > enc:
        raise CtrError("bad BLZ footer")
    out = bytearray(len(data) + add)
    out[:len(data)] = data
    src, dst, end = len(data) - hl, len(out), len(data) - enc
    while src > end:
        src -= 1
        flags = out[src]
        for _ in range(8):
            if src <= end:
                break
            if flags & 0x80:
                src -= 2
                v = out[src] | out[src + 1] << 8
                disp, n = (v & 0xFFF) + 3, (v >> 12) + 3
                if dst + disp - 1 >= len(out) or dst - n < src:
                    raise CtrError("BLZ back-reference out of range")
                for _ in range(n):
                    dst -= 1
                    out[dst] = out[dst + disp]
            else:
                src -= 1
                dst -= 1
                out[dst] = out[src]
            flags = (flags << 1) & 0xFF
    if dst != src:
        raise CtrError(f"BLZ ended misaligned (dst={dst}, src={src})")
    return bytes(out)
