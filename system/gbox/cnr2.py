"""Naruto: Clash of Ninja Revolution 2 (Wii, RNYEDA, Eighting/Tomy 2008) -- disc inventory for character work.

Catalog 00063327fc44eced is a WBFS image.  The disc is extracted once per node with dolphin-tool
(`re4wii.ensure_base` -> cache/modbase/<game_id>/disc/DATA/{sys,files}); the original WBFS is never modified.
The DATA partition ships Eighting's own build tree (.svn dirs, makefile, autofpk.bat, fpkbat/*.bat):

  chr/<code>/NNNN.{brres,brtex,brplt,mot,seq,dah}  loose, uncompressed NW4R files.  0000 = costume 1, 0100 =
                  costume 2; .brres holds the MDL0 model(s) (+ 0001/0002 extra bodies), .brtex the TEX0 textures,
                  .brplt the PLT0 palettes, .mot the motion bank, .seq the move/script data, .dah a text header.
  fpack/chr/<code>/NNNN.fpk  per-costume pack built by fpkbat/fpack_chr_<code>_NNNN.bat ("fpack -a -b"):
                  the costume's seq/brres/mot/brtex/brplt + cam/chr brsca + cpu seq + eft/chr effects, compressed.

FPK layout (big-endian):  0x00 u32 unknown (0x3f13 in chr packs), 0x04 u32 entry count, 0x08 u32 table offset
(0x10), 0x0C u32 file size; entries 0x30 bytes = name[0x20] (NUL padded path), u32 0, u32 data offset,
u32 stored (compressed) size, u32 original size.  The payload codec is an Eighting LZ variant not yet decoded
(analysis stage: find the loader/decompressor in main.dol); `fpk_index` only reads the table.

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
