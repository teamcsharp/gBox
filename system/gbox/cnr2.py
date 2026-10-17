"""Naruto: Clash of Ninja Revolution 2 (Wii, RNYEDA, Eighting/Tomy 2008) -- disc inventory for character work.

Catalog 00063327fc44eced is a WBFS image.  The disc is extracted once per node with dolphin-tool
(`re4wii.ensure_base` -> cache/modbase/<game_id>/disc/DATA/{sys,files}); the original WBFS is never modified.
The DATA partition ships Eighting's own build tree (.svn dirs, makefile, autofpk.bat, fpkbat/*.bat):

  chr/<code>/NNNN.{brres,brtex,brplt,mot,seq,dah}  loose, uncompressed NW4R files.  0000 = costume 1, 0100 =
                  costume 2; .brres holds the MDL0 model(s) (+ 0001/0002 extra bodies), .brtex the TEX0 textures,
                  .brplt the PLT0 palettes, .mot the motion bank, .seq the move/script data, .dah a text header.
  fpack/chr/<code>/NNNN.fpk  per-costume pack built by fpkbat/fpack_chr_<code>_NNNN.bat ("fpack -a -b"):
                  the costume's seq/brres/mot/brtex/brplt + cam/chr brsca + cpu seq + eft/chr effects, compressed.

FPK layout (big-endian):  0x00 u32 checksum (low 16 bits = byte sum of every entry payload; verified on all
224 shipped packs), 0x04 u32 entry count, 0x08 u32 table offset (0x10), 0x0C u32 file size; entries 0x30
bytes = name[0x20] (NUL padded path), u32 0, u32 data offset, u32 stored size, u32 original size.
Payloads are Eighting PRS streams (`prs_decompress`); an entry with stored == original is stored raw
(the shipped packs only use that for zero-length placeholder entries).

BRRES (NW4R resource archive, documented by BrawlBox/BrawlCrate): "bres" FEFF, u16 pad, u32 size, u16 root
offset, u16 section count; root "root" + size + index group.  Index group: u32 size, u32 count, then
(count + 1) 16-byte entries (u16 id, u16 flag, u16 left, u16 right, u32 name, u32 data), pointers relative to
the group start, entry 0 is the group's root node.  Sub-files (MDL0/TEX0/PLT0/CHR0...) start with magic,
u32 size, u32 version, s32 brres offset, then version-dependent section offsets.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

GAME_IDS = {"00063327fc44eced": "Naruto: Clash of Ninja Revolution 2 (USA)"}
DISC_ID = "RNYEDA"

# MDL0 section order by version (BrawlBox MDL0Node): v8/v9/v10 have 11 groups, v11 adds FurVec/FurPos.
_MDL0_SECTIONS = {
    11: ["Definitions", "Bones", "Vertices", "Normals", "Colors", "UVs", "FurVectors", "FurLayers",
         "Materials", "Shaders", "Objects", "Textures", "Palettes"],
}
_MDL0_SECTIONS_OLD = ["Definitions", "Bones", "Vertices", "Normals", "Colors", "UVs",
                      "Materials", "Shaders", "Objects", "Textures", "Palettes"]


def fpk_index(data: bytes) -> list[dict]:
    """Directory of an Eighting .fpk pack (no decompression)."""
    if len(data) < 16:
        raise ValueError("fpk too short")
    _magic, count, table, size = struct.unpack_from(">4I", data, 0)
    if size != len(data) or table + count * 0x30 > len(data):
        raise ValueError(f"not an fpk (count {count}, table {table:#x}, size {size} vs {len(data)})")
    out = []
    for i in range(count):
        e = table + i * 0x30
        name = data[e:e + 0x20].split(b"\0", 1)[0].decode("ascii")
        zero, off, stored, orig = struct.unpack_from(">4I", data, e + 0x20)
        if off + stored > len(data):
            raise ValueError(f"fpk entry {name} runs past the end")
        out.append({"name": name, "offset": off, "stored": stored, "size": orig, "flag": zero,
                    "compressed": stored != orig})
    return out


def prs_decompress(data: bytes, size: int) -> bytes:
    """Decompress an Eighting PRS stream (the fpack payload codec) to exactly `size` bytes.

    MSB-first flag bits: 1 = one literal byte; 0 0 = short copy (2 length bits, length 2-5,
    8-bit back-offset); 0 1 = long copy (13-bit back-offset, length in the low 3 bits or in a
    following byte).  Port of GNTool PRSUncompressor (tpu / Luigi Auriemma QuickBMS spec).
    Verified byte-equal against the loose disc copies of all 3,599 shipped RNYEDA entries that
    have one (chr/*/0000.brres 307200 B included)."""
    from .formats.lz import prs_msb_decompress       # shared Eighting PRS codec (also con2_inventory)
    return prs_msb_decompress(data, size, strict=False, zero_window=False)


def prs_compress(data: bytes) -> bytes:
    """Compress `data` to an Eighting PRS stream (the fpack payload codec).

    Greedy LZ77 with a 3-byte hash table.  Back-references encode as the inverse of
    `prs_decompress`: flag bits are 1 = literal, 0 0 = short copy (2 length bits + one data byte
    `256 - offset`), 0 1 = long copy (two data bytes `(8192 - offset) << 3 | length_code`, plus a
    third `length - 1` byte when length_code == 0).  Offsets reach 8192, copies reach 256 bytes.
    Round-trips byte-exact through `prs_decompress`; the exact bytes need not match `fpack -a -b`.
    """
    n = len(data)
    out = bytearray()
    flag = 0
    bit = 0
    flag_pos = -1

    def put_flag(b):
        nonlocal flag, bit, flag_pos
        if bit == 0:              # first bit of a new flag byte: reserve its slot up front
            flag_pos = len(out)
            out.append(0)
        flag = (flag << 1) | (1 if b else 0)
        bit += 1
        if bit == 8:
            out[flag_pos] = flag  # flag byte precedes its group's data bytes
            flag = 0
            bit = 0
            flag_pos = -1

    def put_bits(value, count):
        for k in range(count - 1, -1, -1):
            put_flag((value >> k) & 1)

    buckets: dict[bytes, list[int]] = {}
    o = 0
    while o < n:
        match_off = 0
        match_len = 0
        if o + 3 <= n:
            key = data[o:o + 3]
            cands = buckets.get(key)
            if cands:
                max_len = min(0x100, n - o)
                for cand in reversed(cands[-256:]):
                    off = o - cand
                    if off > 0x2000:
                        break
                    l = 0
                    while l < max_len and data[cand + l] == data[o + l]:
                        l += 1
                    if l > match_len:
                        match_len = l
                        match_off = off
                        if l == max_len:
                            break
            buckets.setdefault(key, []).append(o)

        if match_len >= 2:
            if match_len <= 5 and match_off <= 0x100:
                put_flag(0)
                put_flag(0)
                put_bits(match_len - 2, 2)
                out.append(0x100 - match_off)
            else:
                put_flag(0)
                put_flag(1)
                off_field = 0x2000 - match_off
                lc = (match_len - 2) if match_len <= 9 else 0
                field = (off_field << 3) | lc
                out.append(field >> 8)     # 13-bit offset + 3-bit length code = two DATA bytes
                out.append(field & 0xFF)
                if lc == 0:
                    out.append(match_len - 1)
            o += match_len
        else:
            put_flag(1)
            out.append(data[o])
            o += 1

    if bit:
        out[flag_pos] = flag << (8 - bit)  # left-align the partial flag byte (MSB-first)
    return bytes(out)


def fpk_checksum(data: bytes) -> int:
    """The low 16 bits of the header u32: the byte sum of every entry payload (224/224 packs)."""
    total = 0
    for e in fpk_index(data):
        total += sum(data[e["offset"]:e["offset"] + e["stored"]])
    return total & 0xFFFF


def fpk_decompress(data: bytes) -> list[tuple[str, bytes]]:
    """(name, raw bytes) for every entry of an Eighting .fpk pack; PRS entries are decoded,
    stored == original entries pass through unchanged."""
    out = []
    for e in fpk_index(data):
        blob = data[e["offset"]:e["offset"] + e["stored"]]
        out.append((e["name"], blob if not e["compressed"] else prs_decompress(blob, e["size"])))
    return out


def fpk_pack(entries: list[tuple[str, bytes]], compress: bool = True) -> bytes:
    """Rebuild an Eighting .fpk pack from (name, raw bytes) entries.

    Each payload is PRS-compressed and stored raw when that is not smaller (an entry with
    stored == original; the shipped packs only use that for zero-length placeholders, so the
    loader's handling of non-empty raw entries is still to be confirmed in main.dol).  The
    header u32 checksum (byte sum of every stored payload) is recomputed.  Entry order and
    names are preserved by the caller, which is what lets a writer swap one costume's files.
    """
    table = 0x10
    rows = bytearray()
    body = bytearray()
    for name, raw in entries:
        nb = name.encode("ascii")
        if not nb or len(nb) > 0x1F or b"\0" in nb:
            raise ValueError(f"invalid fpk entry name {name!r}")
        blob = prs_compress(raw) if compress else raw
        if len(blob) >= len(raw):
            blob = raw
        rows += nb.ljust(0x20, b"\0") + struct.pack(">4I", 0, table + 0x30 * len(entries) + len(body), len(blob), len(raw))
        body += blob
    total = table + 0x30 * len(entries) + len(body)
    return struct.pack(">4I", sum(body) & 0xFFFF, len(entries), table, total) + bytes(rows) + bytes(body)


def _name(data: bytes, ptr: int) -> str:
    if ptr <= 0 or ptr >= len(data):
        return ""
    return data[ptr:data.index(b"\0", ptr)].decode("ascii", "replace")


def brres_group(data: bytes, at: int) -> list[tuple[str, int]]:
    """(name, absolute data offset) for each entry of the index group at `at`."""
    _size, count = struct.unpack_from(">2I", data, at)
    out = []
    for i in range(1, count + 1):
        e = at + 8 + i * 16
        _id, _flag, _l, _r, name, ptr = struct.unpack_from(">4H2I", data, e)
        out.append((_name(data, at + name), at + ptr))
    return out


def _mdl0(data: bytes, at: int) -> dict:
    size, ver = struct.unpack_from(">2I", data, at + 4)
    names = _MDL0_SECTIONS.get(ver, _MDL0_SECTIONS_OLD)
    offs = struct.unpack_from(f">{len(names)}i", data, at + 0x10)
    groups = {}
    for n, o in zip(names, offs):
        if o > 0 and n != "Definitions":
            groups[n] = [nm for nm, _ in brres_group(data, at + o)]
    return {"version": ver, "size": size, "bones": len(groups.get("Bones", [])),
            "bone_names": groups.get("Bones", []), "objects": len(groups.get("Objects", [])),
            "materials": len(groups.get("Materials", [])), "textures": groups.get("Textures", []),
            "vertex_sets": len(groups.get("Vertices", []))}


def _tex0(data: bytes, at: int) -> dict:
    # TEX0 v1/v3: magic, size, version, brres off, data off, name off, u32 flags, u16 w, u16 h, u32 format, u32 mips
    _s, ver = struct.unpack_from(">2I", data, at + 4)
    w, h, fmt, mips = struct.unpack_from(">2H2I", data, at + 0x1C)
    return {"w": w, "h": h, "format": fmt, "mipmaps": mips, "version": ver}


def brres_index(data: bytes) -> dict:
    """{folder: {name: info}} for a .brres/.brtex/.brplt file; MDL0 entries list bones/objects/textures."""
    if data[:4] != b"bres" or data[4:6] != b"\xfe\xff":
        raise ValueError("not a big-endian BRRES")
    root = struct.unpack_from(">H", data, 0xC)[0]
    if data[root:root + 4] != b"root":
        raise ValueError("BRRES root block missing")
    out: dict[str, dict] = {}
    for folder, fat in brres_group(data, root + 8):
        items = {}
        for name, at in brres_group(data, fat):
            magic = data[at:at + 4].decode("ascii", "replace")
            info: dict = {"magic": magic, "offset": at}
            if magic == "MDL0":
                info.update(_mdl0(data, at))
            elif magic == "TEX0":
                info.update(_tex0(data, at))
            items[name] = info
        out[folder] = items
    return out


def characters(files: Path) -> list[str]:
    """Character codes = chr/<code>/ dirs holding a 0000.brres model (chr/cmn is the shared motion bank)."""
    return sorted(p.parent.name for p in (files / "chr").glob("*/0000.brres"))


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(1 << 22):
            h.update(b)
    return h.hexdigest()


def inventory(disc: Path, codes: list[str] | None = None) -> dict:
    """Manifest of the extracted disc: main.dol hash, per-character costume files, MDL0 rig/texture summary."""
    disc = Path(disc)
    data = disc / "DATA" if (disc / "DATA").is_dir() else disc
    files, sys_ = data / "files", data / "sys"
    boot = sys_ / "boot.bin"
    out: dict = {"disc_id": boot.read_bytes()[:6].decode("ascii", "replace") if boot.is_file() else None,
                 "main_dol_sha256": _sha(sys_ / "main.dol"), "main_dol_size": (sys_ / "main.dol").stat().st_size,
                 "characters": {}}
    for code in codes or characters(files):
        d = files / "chr" / code
        ch: dict = {"files": {}, "costumes": {}}
        for p in sorted(d.iterdir()):
            if p.is_file():
                ch["files"][p.name] = {"size": p.stat().st_size, "sha256": _sha(p)}
        for brres in sorted(d.glob("[0-9][0-9]00.brres")):
            cos = brres.stem
            entry: dict = {}
            try:
                idx = brres_index(brres.read_bytes())
                entry["models"] = {n: {k: v for k, v in i.items() if k != "bone_names"}
                                   for f in idx.values() for n, i in f.items() if i["magic"] == "MDL0"}
                entry["folders"] = {f: len(v) for f, v in idx.items()}
            except (ValueError, struct.error) as e:
                entry["error"] = str(e)
            tex = d / f"{cos}.brtex"
            if tex.is_file():
                try:
                    entry["textures"] = len(brres_index(tex.read_bytes()).get("Textures(NW4R)", {}))
                except (ValueError, struct.error) as e:
                    entry["textures_error"] = str(e)
            fpk = files / "fpack" / "chr" / code / f"{cos}.fpk"
            if fpk.is_file():
                entry["fpk"] = {"size": fpk.stat().st_size, "sha256": _sha(fpk),
                                "entries": [e["name"] for e in fpk_index(fpk.read_bytes())]}
            ch["costumes"][cos] = entry
        out["characters"][code] = ch
    return out


if __name__ == "__main__":  # python -m gbox.cnr2 <extracted disc> [out.json]
    import sys
    m = inventory(Path(sys.argv[1]))
    text = json.dumps(m, indent=1)
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(text)
    print(json.dumps({"characters": len(m["characters"]), "main_dol_sha256": m["main_dol_sha256"]}))
