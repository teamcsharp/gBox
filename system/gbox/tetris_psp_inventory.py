"""Tetris (PSP, game 25da54968d78f816) owned-build inventory: CISO container + ISO9660 walk.

Read-only. CISO header: magic 'CISO', u32 header_size, u64 total_bytes, u32 block_size,
u8 version, u8 index_shift, u16 pad; then (total/block+1) u32 index entries
(bit31 = stored raw, else raw deflate; offset = (v & 0x7fffffff) << shift).
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass

SECTOR = 2048


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


class CisoReader:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        head = self.f.read(0x18)
        magic, self.header_size, self.total, self.block, self.version, self.shift, _ = struct.unpack("<4sIQIBBH", head)
        if magic != b"CISO":
            raise ValueError("not a CISO container")
        if self.block <= 0 or self.total % self.block:
            raise ValueError("bad CISO block size")
        self.nblocks = self.total // self.block
        raw = self.f.read(4 * (self.nblocks + 1))
        if len(raw) != 4 * (self.nblocks + 1):
            raise ValueError("truncated CISO index")
        self.index = struct.unpack("<%dI" % (self.nblocks + 1), raw)

    def close(self):
        self.f.close()

    def block_data(self, i):
        a, b = self.index[i], self.index[i + 1]
        off = (a & 0x7FFFFFFF) << self.shift
        end = (b & 0x7FFFFFFF) << self.shift
        self.f.seek(off)
        d = self.f.read(end - off)
        out = d if a & 0x80000000 else zlib.decompress(d, -15)
        return out[: self.block]

    def read(self, offset, size):
        out = bytearray()
        while size > 0:
            i, o = divmod(offset, self.block)
            d = self.block_data(i)[o : o + size]
            if not d:
                break
            out += d
            offset += len(d)
            size -= len(d)
        return bytes(out)


@dataclass
class IsoEntry:
    path: str
    lba: int
    size: int
    is_dir: bool


def walk_iso(rd: CisoReader):
    pvd = rd.read(16 * SECTOR, SECTOR)
    if pvd[1:6] != b"CD001":
        raise ValueError("no ISO9660 PVD at LBA16")
    root_lba, root_size = struct.unpack("<II", pvd[158:162] + pvd[166:170])
    out = []
    stack = [("", root_lba, root_size)]
    while stack:
        base, lba, size = stack.pop()
        data = rd.read(lba * SECTOR, size)
        o = 0
        while o < len(data):
            n = data[o]
            if n == 0:
                o = (o // SECTOR + 1) * SECTOR
                continue
            rec = data[o : o + n]
            o += n
            nl = rec[32]
            name = rec[33 : 33 + nl]
            if name in (b"\x00", b"\x01"):
                continue
            nm = name.decode("ascii", "replace").split(";")[0]
            elba, esz = struct.unpack("<II", rec[2:6] + rec[10:14])
            isdir = bool(rec[25] & 2)
            path = f"{base}/{nm}"
            out.append(IsoEntry(path, elba, esz, isdir))
            if isdir:
                stack.append((path, elba, esz))
    return sorted(out, key=lambda e: e.path)


def parse_sfo(data):
    magic, ver, kt, dt, n = struct.unpack("<4sIIII", data[:20])
    if magic != b"\0PSF":
        raise ValueError("bad SFO")
    res = {}
    for i in range(n):
        ko, fmt, ln, mx, do = struct.unpack("<HHIII", data[20 + 16 * i : 36 + 16 * i])
        k = data[kt + ko : data.index(b"\0", kt + ko)].decode()
        v = data[dt + do : dt + do + ln]
        res[k] = struct.unpack("<I", v[:4])[0] if fmt == 0x404 else v.rstrip(b"\0").decode("utf-8", "replace")
    return res


def inventory(path):
    rd = CisoReader(path)
    try:
        ents = walk_iso(rd)
        files = [e for e in ents if not e.is_dir]
        by = {e.path: e for e in files}
        sfo = None
        if "/PSP_GAME/PARAM.SFO" in by:
            e = by["/PSP_GAME/PARAM.SFO"]
            sfo = parse_sfo(rd.read(e.lba * SECTOR, e.size))
        eboot = by.get("/PSP_GAME/SYSDIR/EBOOT.BIN")
        eboot_magic = rd.read(eboot.lba * SECTOR, 4) if eboot else b""
        return {
            "platform": "psp",
            "container": "CISO",
            "block_size": rd.block,
            "uncompressed_bytes": rd.total,
            "index_entries": len(rd.index),
            "byte_order": "little",
            "offset_base": "ISO9660 LBA * 2048",
            "param_sfo": sfo,
            "eboot": {"path": eboot.path, "lba": eboot.lba, "size": eboot.size, "magic": eboot_magic.hex()} if eboot else None,
            "file_count": len(files),
            "files": [(e.path, e.lba, e.size) for e in files],
        }
    finally:
        rd.close()


TARGET_ASSET = "/PSP_GAME/USRDIR/TETRIS/GLOBAL/GLOBAL.PSP"
LU_MAGIC = bytes.fromhex("03033f23")


def identify_target(path, target=TARGET_ASSET):
    """Identify the native target asset (GLOBAL.PSP 'LU' package) and hash its decompressed bytes."""
    rd = CisoReader(path)
    try:
        by = {e.path: e for e in walk_iso(rd) if not e.is_dir}
        e = by[target]
        h = hashlib.sha256()
        off = e.lba * SECTOR
        head = rd.read(off, 0x30)
        left = e.size
        while left:
            n = min(left, 1 << 20)
            h.update(rd.read(off + e.size - left, n))
            left -= n
        return {
            "path": e.path, "lba": e.lba, "size": e.size, "sha256": h.hexdigest(),
            "magic": head[:4].hex(), "lu_magic_ok": head[:4] == LU_MAGIC,
            "names": [x.decode() for x in head[16:].split(b"\0") if x],
        }
    finally:
        rd.close()
