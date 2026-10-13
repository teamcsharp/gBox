"""Parasite Eve II (PS1, USA, SLUS-01042/01043): disc identity, STAGE0.HED/CDF archive, chunk codec (#559).

Everything here was read off the operator's own Disc 1 CHD and its boot EXE (SLUS_010.42, disassembled with capstone);
nothing downloaded. Layout:

Disc 1 (ISO9660): SYSTEM.CNF -> SLUS_010.42 (boot EXE), INIT.BS, STAGE0.HED (index), STAGE0.CDF (61.5 MB, the field
game: rooms, Aya, weapons, enemies, menus, text), STAGE1..3.CDF (self-indexed event/cut-scene streams), INTER0.STR
(movies), DUMMY.DMY (padding).

STAGE0.HED: three 0x28-byte records (bit 31 set on the first u32), then (u32 file id, u32 start sector) pairs in
ascending sector order up to 0xFFFFFFFF. A file runs to the next pair's sector. Ids are decimal-coded: 0..44 boot /
picture files, 1xxxx class 1 (Aya's outfit models 10200..10600, weapons 10301..10332, voice banks 110xx), 2xxxx
messages/item pictures, 30xxx stills, 40xxx music (hMPK), 50xxx weapon code + sounds, 1xxxxx..6xxxxx rooms
(area*100000 + room*100), 80xxxx/90xxxx menus. (The EXE's resolver also files them by id // 10000; see FILE_CLASSES.)

A file is a chain of chunks. Each chunk starts on a sector with a 16-byte header
    u8 type, u8 flag (1 = more chunks follow, 0xFF = last), u16 bytes used in the chunk's last sector,
    u32 sectors, u32 RAM address (type 0/3), u32 0
and its payload runs from header+16 to (sectors-1)*2048 + used. The EXE's dispatcher (0x80022CF0, jump table at
0x80013294) handles: 0 = LZ-compressed data to RAM (decoder 0x80010024), 1 = LZ-compressed VRAM image (0x800248B4:
(u16 x, u16 y, u32 offset) entries until x = 0xFFFF, each a 64x256 column sent as eight independent 64x32 LZ strips),
2 = LZ-compressed CLUT (0x800246B0: u16 x, y, h, w; data at +16), 3 = raw RAM copy, 4 = streamed-audio table,
5 = MDEC picture (BS v2), 6 = sound pack (hSPK/hONE), 7 = text.

The LZ (0x80010024 / 0x80010398): MSB-first bits; flag 1 -> literal byte (8 bits); flag 0 -> 8-bit ring position
(0 = end of stream), 4-bit length (+2 bytes copied from that absolute position of a 256-byte ring whose write pointer
starts at 1). After an end marker the EXE's eager byte fetch leaves the input on byte (bitpos // 8) + 1.

Aya: the field overlay (file 0, decompressed to 0x80093800) maps the outfit byte (RAM 0x80073BAE, 1..5) through
the table at 0x800938CC (04 03 02 05 06) to class-1 file 10000 + 100*n: 10400, 10300, 10200, 10500, 10600. Each is a
CLUT chunk (rows 245..246), a two-column 8-bit texture at VRAM (384..511, 256), and her model at 0x80115770 whose
header the EXE points at (0x8011C210, SLUS offset 0x58144). The model format is gbox.pe2_models.

  python -m gbox.pe2_inventory <disc.chd | dir with STAGE0.HED/CDF> [--json] [--files]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path

SECTOR = 2048
GAME_IDS = {"1b8acc6f11536a68": "Parasite Eve II (USA) (Disc 1)", "5318e0449fee32b2": "Parasite Eve II (USA) (Disc 2)"}
BOOT_EXE = {"SLUS_010.42": 1, "SLUS_010.43": 2}            # disc 1 / disc 2 boot executables
DISC1_SHA256 = {                                          # first 16 hex of sha256, owned Disc 1
    "SLUS_010.42": "67cad2a0203b4ac0", "STAGE0.HED": "6384d17988675725", "STAGE0.CDF": "4cfa5db8ad446c84",
}
CHUNK_TYPES = {0: "lz-ram", 1: "lz-image", 2: "lz-clut", 3: "raw-ram", 4: "stream-table", 5: "mdec", 6: "sound",
               7: "text"}
FILE_CLASSES = [                                          # (lo, hi, label) over file ids
    (0, 9999, "boot / pictures"), (10200, 10200, "Aya outfit model"), (10300, 10300, "Aya outfit model"),
    (10301, 10399, "weapon"), (10400, 10699, "Aya outfit model"), (11000, 11099, "voice bank"),
    (20000, 29999, "messages / item pictures"), (30000, 39999, "stills"), (40000, 49999, "music"),
    (50000, 59999, "weapon code + sounds"), (100000, 699999, "room"), (800000, 999999, "menu"),
]
# outfit byte (RAM 0x80073BAE) -> file; names from the outfit table players use (byte 1..4) + the fifth slot
OUTFIT_TABLE_RAM = 0x800938CC                             # in the file-0 overlay: 04 03 02 05 06
AYA_OUTFITS = {1: 10400, 2: 10300, 3: 10200, 4: 10500, 5: 10600}
AYA_OUTFIT_NAMES = {1: "purple_jacket_jeans", 2: "blue_jacket_shorts", 3: "tshirt_jeans", 4: "tshirt_jeans_headphones",
                    5: "outfit_5"}
AYA_MODEL_RAM = 0x80115770                               # type-0 destination of every outfit file
AYA_HEADER_RAM = 0x8011C210                              # the EXE's pointer (SLUS_010.42 offset 0x58144)
AYA_RAM_LIMIT = 0x8011D1C0                               # weapon overlay (10301..) loads here: the model must end below
AYA_HEADER_PTR_OFFSET = 0x58144


def file_class(fid: int) -> str:
    for lo, hi, label in FILE_CLASSES:
        if lo <= fid <= hi:
            return label
    return "other"


# ------------------------------------------------------------------------------------------------ HED

@dataclass
class HedRecord:
    id: int
    sector: int
    extra: tuple


def parse_hed(data: bytes) -> tuple[list[HedRecord], list[tuple[int, int]]]:
    """STAGE0.HED -> (flagged records, [(file id, start sector)]). Raises ValueError on a malformed index."""
    if len(data) < 4:
        raise ValueError("HED too short")
    recs, pos = [], 0
    while pos + 0x28 <= len(data) and struct.unpack_from("<I", data, pos)[0] & 0x80000000 \
            and struct.unpack_from("<I", data, pos)[0] != 0xFFFFFFFF:
        v = struct.unpack_from("<10I", data, pos)
        recs.append(HedRecord(v[0] & 0x7FFFFFFF, v[1], tuple(v[2:])))
        pos += 0x28
    pairs = []
    while True:
        if pos + 4 > len(data):
            raise ValueError("HED: no 0xFFFFFFFF terminator")
        fid = struct.unpack_from("<I", data, pos)[0]
        if fid == 0xFFFFFFFF:
            break
        if pos + 8 > len(data):
            raise ValueError("HED: truncated pair")
        sec = struct.unpack_from("<I", data, pos + 4)[0]
        if pairs and sec < pairs[-1][1]:
            raise ValueError(f"HED: sector of file {fid} goes backwards")
        pairs.append((fid, sec))
        pos += 8
    return recs, pairs


def build_hed(recs: list[HedRecord], pairs: list[tuple[int, int]], size: int | None = None) -> bytes:
    """Inverse of parse_hed (zero-padded to `size`, the original file's length)."""
    out = bytearray()
    for r in recs:
        out += struct.pack("<10I", r.id | 0x80000000, r.sector, *r.extra)
    for fid, sec in pairs:
        out += struct.pack("<II", fid, sec)
    out += b"\xff\xff\xff\xff"
    if size is not None:
        if len(out) > size:
            raise ValueError("HED grew past its file")
        out += bytes(size - len(out))
    return bytes(out)


def file_spans(pairs: list[tuple[int, int]], total_sectors: int) -> dict[int, tuple[int, int]]:
    """file id -> (start sector, sector count). Aliases (two ids on one sector) get count 0 for the first."""
    out = {}
    for i, (fid, sec) in enumerate(pairs):
        end = pairs[i + 1][1] if i + 1 < len(pairs) else total_sectors
        out[fid] = (sec, max(0, end - sec))
    return out


# ------------------------------------------------------------------------------------------------ chunks

@dataclass
class Chunk:
    type: int
    flag: int
    used: int          # bytes used in the last sector
    sectors: int
    addr: int
    sector: int        # absolute sector inside the CDF

    @property
    def last(self) -> bool:
        return self.flag == 0xFF

    @property
    def payload_size(self) -> int:
        return (self.sectors - 1) * SECTOR + self.used - 16


def read_chunk_header(cdf: bytes, sector: int) -> Chunk | None:
    o = sector * SECTOR
    if o + 16 > len(cdf):
        return None
    t, f, used, n, addr, z = struct.unpack_from("<BBHIII", cdf, o)
    if t > 7 or f not in (0, 1, 0xFF) or n == 0 or not 16 <= used <= SECTOR:
        return None
    return Chunk(t, f, used, n, addr, sector)


def walk_file(cdf: bytes, start: int, count: int) -> list[Chunk]:
    """The chunk chain of one file; stops at the last-flagged chunk, the file end, or an invalid header."""
    out, s = [], start
    while s < start + count:
        c = read_chunk_header(cdf, s)
        if c is None or s + c.sectors > start + count:
            break
        out.append(c)
        s += c.sectors
        if c.last:
            break
    return out


def payload(cdf: bytes, c: Chunk) -> bytes:
    o = c.sector * SECTOR
    return cdf[o + 16:o + (c.sectors - 1) * SECTOR + c.used]


# ------------------------------------------------------------------------------------------------ LZ codec

class _Bits:
    def __init__(self, src: bytes, pos: int = 0):
        self.src, self.bit, self.n = src, pos * 8, len(src) * 8

    def get(self, k: int) -> int:
        if self.bit + k > self.n:
            raise ValueError("LZ stream runs past its data")
        v = 0
        for _ in range(k):
            v = (v << 1) | ((self.src[self.bit >> 3] >> (7 - (self.bit & 7))) & 1)
            self.bit += 1
        return v


def lz_decode(src: bytes, start: int = 0, limit: int = 1 << 22) -> tuple[bytes, int]:
    """One LZ stream from src[start:] -> (data, offset of the next stream). Bounded by `limit` output bytes."""
    b = _Bits(src, start)
    ring = bytearray(256)
    rp = 1
    out = bytearray()
    while True:
        if b.get(1):
            v = b.get(8)
            ring[rp] = v
            rp = (rp + 1) & 0xFF
            out.append(v)
        else:
            pos = b.get(8)
            if pos == 0:
                return bytes(out), b.bit // 8 + 1
            for _ in range(b.get(4) + 2):
                v = ring[pos]
                pos = (pos + 1) & 0xFF
                ring[rp] = v
                rp = (rp + 1) & 0xFF
                out.append(v)
        if len(out) > limit:
            raise ValueError("LZ output over limit")


def lz_encode(data: bytes) -> bytes:
    """Greedy encoder for lz_decode / the EXE (matches only reference bytes this stream wrote; ring slot 0 is never a
    match source because position 0 is the end marker)."""
    bits: list[int] = []

    def put(v: int, k: int):
        bits.extend((v >> (k - 1 - i)) & 1 for i in range(k))
    heads: dict[bytes, list[int]] = {}
    i, n = 0, len(data)
    while i < n:
        best_len, best_j = 0, -1
        if i + 1 < n:
            for j in reversed(heads.get(data[i:i + 2], ())):
                if j < i - 255:
                    break
                if (1 + j) & 0xFF == 0:
                    continue
                ln = 0
                while ln < 17 and i + ln < n and data[j + ln] == data[i + ln]:
                    ln += 1
                if ln > best_len:
                    best_len, best_j = ln, j
                    if ln == 17:
                        break
        step = best_len if best_len >= 2 else 1
        if best_len >= 2:
            put(0, 1)
            put((1 + best_j) & 0xFF, 8)
            put(best_len - 2, 4)
        else:
            put(1, 1)
            put(data[i], 8)
        for k in range(i, i + step):
            if k + 1 < n:
                lst = heads.setdefault(data[k:k + 2], [])
                lst.append(k)
                if len(lst) > 64:
                    del lst[:len(lst) - 64]
        i += step
    put(0, 1)
    put(0, 8)
    aligned = len(bits) % 8 == 0
    while len(bits) % 8:
        bits.append(0)
    out = bytearray(len(bits) // 8)
    for k in range(len(out)):
        v = 0
        for x in bits[k * 8:k * 8 + 8]:
            v = (v << 1) | x
        out[k] = v
    # the EXE's eager fetch resumes at (bitpos // 8) + 1: a byte-aligned end marker skips one more byte
    return bytes(out) + (b"\0" if aligned else b"")


def decode_image(p: bytes) -> list[dict]:
    """A type-1 chunk payload -> [{x, y, w: 64, h: 256, data: u16 VRAM words (bytes)}]."""
    out, o = [], 0
    while True:
        if o + 8 > len(p):
            raise ValueError("image: entry list runs past the payload")
        x, y, off = struct.unpack_from("<HHI", p, o)
        if x == 0xFFFF:
            break
        if off >= len(p):
            raise ValueError("image: strip offset outside the payload")
        strips, s = [], off
        for _ in range(8):
            d, s = lz_decode(p, s, 8192)
            strips.append(d[:4096].ljust(4096, b"\0"))
        out.append({"x": x, "y": y, "w": 64, "h": 256, "data": b"".join(strips), "offset": off, "end": s})
        o += 8
    return out


def decode_clut(p: bytes) -> dict:
    x, y, h, w = struct.unpack_from("<4H", p, 0)
    d, _ = lz_decode(p, 16, w * h * 2 + 16)
    return {"x": x, "y": y, "w": w, "h": h, "data": d[:w * h * 2]}


# ------------------------------------------------------------------------------------------------ disc

class PE2Disc:
    """STAGE0 of a PE2 disc: from a CHD (gbox.psxdisc) or a directory holding the extracted files."""

    def __init__(self, path):
        path = Path(path)
        self.files: dict[str, bytes] = {}
        if path.is_dir():
            self._get = lambda n: (path / n).read_bytes()
            self.names = sorted(p.name for p in path.iterdir() if p.is_file())
        else:
            from .psxdisc import PSXDisc
            self.disc = PSXDisc(path)
            self._get = self.disc.read
            self.names = sorted(self.disc.files)
        self.disc_no = next((v for k, v in BOOT_EXE.items() if k in self.names), None)
        if self.disc_no is None or "STAGE0.HED" not in self.names:
            raise ValueError(f"{path}: not a Parasite Eve II (USA) disc (no SLUS_010.42/43 + STAGE0.HED)")
        self.hed_bytes = self.read("STAGE0.HED")
        self.records, self.pairs = parse_hed(self.hed_bytes)

    def read(self, name: str) -> bytes:
        if name not in self.files:
            self.files[name] = self._get(name)
        return self.files[name]

    @property
    def cdf(self) -> bytes:
        return self.read("STAGE0.CDF")

    def spans(self) -> dict[int, tuple[int, int]]:
        return file_spans(self.pairs, len(self.cdf) // SECTOR)

    def chunks(self, fid: int) -> list[Chunk]:
        sec, n = self.spans()[fid]
        return walk_file(self.cdf, sec, n)

    def outfit_files(self) -> dict[int, int]:
        """outfit byte -> file id, read from the file-0 overlay's table when it decodes, else the known table."""
        try:
            c = [c for c in self.chunks(0) if c.type == 0][0]
            ov, _ = lz_decode(payload(self.cdf, c), 0)
            o = OUTFIT_TABLE_RAM - c.addr
            return {i + 1: 10000 + 100 * ov[o + i] for i in range(5)}
        except (IndexError, ValueError, KeyError):
            return dict(AYA_OUTFITS)


def sha16(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def inventory(path, list_files: bool = False) -> dict:
    d = PE2Disc(path)
    cdf = d.cdf
    spans = d.spans()
    classes: dict[str, int] = {}
    bad = []
    files = []
    types: dict[str, int] = {}
    for fid, (sec, n) in spans.items():
        classes[file_class(fid)] = classes.get(file_class(fid), 0) + 1
        ch = walk_file(cdf, sec, n)
        if n and not ch and cdf[sec * SECTOR:sec * SECTOR + 4] != b"hMPK":
            bad.append(fid)
        for c in ch:
            types[CHUNK_TYPES[c.type]] = types.get(CHUNK_TYPES[c.type], 0) + 1
        if list_files:
            files.append({"id": fid, "sector": sec, "sectors": n, "class": file_class(fid),
                          "chunks": [f"{CHUNK_TYPES[c.type]}:{c.sectors}" + (f"@{c.addr:08x}" if c.type in (0, 3) else "")
                                     for c in ch]})
    ident = {n: sha16(d.read(n)) for n in ("SLUS_010.42", "STAGE0.HED") if n in d.names}
    rep = {"disc": d.disc_no, "files_on_disc": d.names, "sha256_16": ident,
           "matches_owned_disc1": all(DISC1_SHA256.get(k) == v for k, v in ident.items()) and d.disc_no == 1,
           "hed_records": [(r.id, r.sector) for r in d.records], "hed_files": len(d.pairs),
           "cdf_sectors": len(cdf) // SECTOR, "classes": classes, "chunk_types": types,
           "files_without_chunks": bad, "aya_outfits": d.outfit_files()}
    if list_files:
        rep["files"] = files
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gbox.pe2_inventory", description=__doc__.split("\n")[0])
    ap.add_argument("disc")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--files", action="store_true", help="list every HED file and its chunk chain")
    a = ap.parse_args(argv)
    rep = inventory(a.disc, a.files)
    if a.json:
        print(json.dumps(rep, indent=1))
    else:
        print(f"Parasite Eve II disc {rep['disc']}: {rep['hed_files']} files in STAGE0.CDF ({rep['cdf_sectors']} sectors)")
        print("owned Disc 1 match:", rep["matches_owned_disc1"], rep["sha256_16"])
        for k, v in rep["classes"].items():
            print(f"  {v:4d}  {k}")
        print("chunks:", rep["chunk_types"])
        print("Aya outfit files:", rep["aya_outfits"])
        for f in rep.get("files", []):
            print(f"  {f['id']:7d} @{f['sector']:6d} +{f['sectors']:5d} {f['class']:24s} {' '.join(f['chunks'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
