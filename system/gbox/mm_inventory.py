"""Zelda: Majora's Mask (N64, USA): owned-source inventory for the favorite-queue character replacement.

Reference (read as documentation only, nothing shipped or run): the zeldaret/mm decompilation (CC0)
  baseroms/n64-us/config.yml     dmadata_start 0x1A500
  include/tables/object_table.h  object ids
  tools/disasm/n64-us/variables.txt  gObjectTable 0x801C2740 (mm-us), size 0x1420
  assets/xml/objects/object_link_*.xml  player object layouts
The formats are the OoT engine's, so gbox.oot_writer / gbox.oot_swap parse the same dmadata, Yaz0, Zelda64
object, skeleton and F3DEX2 display-list structures.

ROM model: the dmadata (file table) at 0x1A500 lists {vromStart, vromEnd, romStart, romEnd} per file; romEnd == 0
stores the file raw, otherwise it is a Yaz0 stream of (vromEnd - vromStart) decompressed bytes. Unused table slots
carry romStart 0xFFFFFFFF. gObjectTable ({vromStart, vromEnd} per object id) lives inside the raw `code` file
(dmadata index 5 on the owned build). The owned USA build is the decomp's mm-n64-us-compressed baserom.

CLI: python -m gbox.mm_inventory SRC --out manifest.json
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from . import n64_rom
from .oot_swap import find_skeletons
from .oot_writer import u32, yaz0_decompress

DMA_START = 0x1A500        # baseroms/n64-us/config.yml
OBJECT_GAMEPLAY_KEEP = 0x001
# dmadata order on this build (spec segments): 0 makerom, 1 boot, 2 dmadata, 3 Audiobank, 4 Audioseq, 5 Audiotable,
# 6 kanji, 7 link_animetion, 8-9 empty slots, then the compressed item statics and `code` (Yaz0 on this build).
CODE_SCAN_START = 8       # locate `code` by scanning decompressed files from here for gObjectTable

# The decomp's checksums for the two USA retail builds (baseroms README); the owned zip is the compressed one.
MM_US_MD5 = {
    "f46493eaa0628827dbd6ad3ecd8d65d6": "mm-n64-us",
    "2a0a8acb61538235bc1094d297fb6556": "mm-n64-us-compressed",
}

# Playable forms (object ids from the decomp's include/tables/object_table.h). Tatl the fairy has no dedicated
# object: fairies render from shared data, so she is not listed here.
CHARACTERS = [
    ("link_human", 0x011, "object_link_child", "player, human form"),
    ("link_fierce_deity", 0x010, "object_link_boy", "player, Fierce Deity mask form"),
    ("link_goron", 0x14C, "object_link_goron", "player, Goron mask form"),
    ("link_zora", 0x14D, "object_link_zora", "player, Zora mask form"),
    ("link_deku", 0x154, "object_link_nuts", "player, Deku mask form"),
    ("epona_link", 0x07D, "object_horse_link_child", "mount, ridden by Link"),
]

# All 24 wearable masks (object ids from the decomp's include/tables/object_table.h).
MASKS = [
    ("mask_bu_san", 0x1D9), ("mask_ki_tan", 0x1DA), ("mask_rabit", 0x1DB), ("mask_skj", 0x1DC),
    ("mask_bakuretu", 0x1DD), ("mask_truth", 0x1DE), ("mask_goron", 0x1E1), ("mask_zora", 0x1E2),
    ("mask_nuts", 0x1E3), ("mask_boy", 0x1E4), ("mask_gibudo", 0x1FD), ("mask_json", 0x1FE),
    ("mask_kerfay", 0x1FF), ("mask_bigelf", 0x200), ("mask_kyojin", 0x214), ("mask_romerny", 0x219),
    ("mask_posthat", 0x221), ("mask_zacho", 0x24C), ("mask_stone", 0x24E), ("mask_bree", 0x252),
    ("mask_gero", 0x25C), ("mask_yofukasi", 0x25D), ("mask_meoto", 0x25E), ("mask_dancer", 0x25F),
]


# ---------------------------------------------------------------- identity

def identity(data: bytes) -> dict:
    """N64 header identity of the big-endian ROM bytes."""
    md5 = hashlib.md5(data).hexdigest()
    variant = MM_US_MD5.get(md5)
    return {
        "size": len(data),
        "md5": md5,
        "sha256": hashlib.sha256(data).hexdigest(),
        "title": data[0x20:0x34].decode("ascii", "replace").rstrip("\x00").strip(),
        "crc": [hex(x) for x in struct.unpack_from(">II", data, 0x10)],
        "cic": data[0x3B:0x3C].decode("ascii", "replace"),
        "region_byte": hex(data[0x3E]),
        "variant": variant,
        "is_usa_retail": variant is not None,
    }


# ---------------------------------------------------------------- the ROM

def dmadata(data: bytes) -> list[tuple[int, int, int, int]]:
    """The {vromStart, vromEnd, romStart, romEnd} file table at DMA_START, up to the terminator."""
    out = []
    o = DMA_START
    while o + 16 <= len(data):
        e = struct.unpack_from(">4I", data, o)
        if e == (0, 0, 0, 0):
            break
        out.append(e)
        o += 16
    if not out:
        raise ValueError("empty dmadata (not a Majora's Mask ROM?)")
    return out


OBJECT_ID_MAX = 0x283     # ids 0x000-0x282 (include/tables/object_table.h); {start,start} pairs are EMPTY objects


def locate_object_table(code: bytes, dma_vroms: dict[int, int]) -> int:
    """gObjectTable offset in `code`: entry 0 is {0,0}; gameplay_keep/field_keep/dangeon_keep (ids 1-3) are three
    consecutive dmadata files; every other nonzero entry is a {vromStart <= vromEnd} pair of a dmadata file.
    {start, start} pairs are the EMPTY placeholder objects, and object vroms are NOT strictly increasing along
    object ids (the masks are stored out of order), so only shape is checked."""
    o = 0
    while True:
        o = code.find(b"\x00\x00\x00\x00", o)
        if o < 0 or o + 32 > len(code):
            break
        if u32(code, o + 4) != 0:
            o += 4
            continue
        i1, i2, i3 = (dma_vroms.get(u32(code, o + 8 * k)) for k in (1, 2, 3))
        if None in (i1, i2, i3) or not (i1 + 1 == i2 == i3 - 1):
            o += 4
            continue
        n = 0
        for k in range(1, OBJECT_ID_MAX):
            vs, ve = u32(code, o + 8 * k), u32(code, o + 8 * k + 4)
            if vs == 0 and ve == 0:
                continue
            if ve < vs or (vs != ve and vs not in dma_vroms):
                n = -1
                break
            n += 1
        if n >= 300:
            return o
        o += 4
    raise ValueError("gObjectTable not found in code")


class Rom:
    """A retail MM USA ROM (big-endian .z64): files by dmadata index / object id, decompressed on demand."""

    def __init__(self, data: bytes):
        if data[:4] != b"\x80\x37\x12\x40":
            raise ValueError("need a big-endian .z64 ROM")
        self.data = bytes(data)
        self.dma = dmadata(data)
        self._cache: dict[int, bytes] = {}
        self.code_index = None
        self.obj_table = None

    def file(self, i: int) -> bytes:
        if i in self._cache:
            return self._cache[i]
        vs, ve, rs, re_ = self.dma[i]
        if rs == 0xFFFFFFFF:
            raise KeyError(f"dmadata slot {i} is unused")
        raw = self.data[rs:rs + (ve - vs if re_ == 0 else re_ - rs)]
        self._cache[i] = yaz0_decompress(raw) if raw[:4] == b"Yaz0" else raw
        return self._cache[i]

    def object_table(self) -> int:
        if self.obj_table is None:
            dma_vroms = {e[0]: i for i, e in enumerate(self.dma) if e[2] != 0xFFFFFFFF}
            for i in range(CODE_SCAN_START, min(len(self.dma), 64)):
                try:
                    data = self.file(i)
                except KeyError:
                    continue
                if len(data) < 0x10000:
                    continue
                try:
                    at = locate_object_table(data, dma_vroms)
                except ValueError:
                    continue
                self.code_index, self.obj_table = i, at
                return at
            raise ValueError("gObjectTable not found in any early dmadata file")
        return self.obj_table

    def object(self, obj_id: int) -> bytes:
        assert self.code_index is not None
        vs, _ve = struct.unpack_from(">II", self.file(self.code_index),
                                     self.object_table() + 8 * obj_id)
        if vs == 0:
            raise KeyError(f"object id {obj_id:#x} is not in the table")
        i = next(i for i, e in enumerate(self.dma) if e[0] == vs)
        return self.file(i)


# ---------------------------------------------------------------- object files

def object_sections(obj: bytes) -> dict:
    """The Zelda64 object header: u16 object ids, then the u32 count and count+1 u32 section offsets."""
    ids, o = [], 0
    while o + 2 <= len(obj):
        x = struct.unpack_from(">H", obj, o)[0]
        if x == 0:
            break
        ids.append(x)
        o += 2
    o = (o + 3) & ~3
    for cand in range(o, min(len(obj) - 8, 0x400), 4):
        n = u32(obj, cand)
        if not 2 <= n <= 4096:
            continue
        if u32(obj, cand + 4) < cand + 4 + 4 * (n + 1):
            continue
        offs = [u32(obj, cand + 4 + 4 * i) for i in range(n + 1)]
        if offs[-1] != len(obj) or any(b < a for a, b in zip(offs, offs[1:])):
            continue
        return {"count": n, "index_at": cand, "ids": ids, "offsets": offs, "file_size": len(obj)}
    raise ValueError("no Zelda64 object index in object file")


def tail_skeleton(obj: bytes) -> int | None:
    """MM (ZAPD) player objects keep the Flex skeleton header in the file's last 0x20 bytes, not behind an
    id list: u32 segment-6 pointer to the limb table, u8 limbCount, u8[3] pad, u8 dListCount. Fierce Deity is
    padded to 0x10, so the header is at len-0x18 there, len-0xC for the others. Returns the header offset."""
    from .oot_writer import skeleton
    for off in range(len(obj) - 0x20, len(obj) - 11, 4):
        w, cnt = u32(obj, off), obj[off + 4]
        if w >> 24 != 6 or not 2 <= cnt <= 80 or obj[off + 5:off + 8] != b"\0\0\0":
            continue
        t = w & 0xFFFFFF
        if t % 4 or t + 4 * cnt > off:
            continue
        ptrs = [u32(obj, t + 4 * i) for i in range(cnt)]
        if not all(p >> 24 == 6 and (p & 0xFFFFFF) + 16 <= len(obj) for p in ptrs):
            continue
        sk = skeleton(obj, off)
        if all(lb["child"] == 0xFF or lb["child"] < cnt for lb in sk["limbs"]) and \
                all(lb["sibling"] == 0xFF or lb["sibling"] < cnt for lb in sk["limbs"]):
            return off
    return None


def probe_triangles(rom: Rom, obj: bytes, skel_offs: list[int]) -> dict:
    """Bounded mesh probe: run the first skeleton's limb display lists with segment 6 = the object and segment
    4 = gameplay_keep, counting triangles whose vertices are all loaded and the unique texture sources."""
    from .oot_writer import run_dl, skeleton
    keep = rom.object(OBJECT_GAMEPLAY_KEEP)
    segs = {6: obj, 4: keep}
    tris, tex, walked = 0, set(), 0
    for off in skel_offs[:1]:
        sk = skeleton(obj, off)
        for lb in sk["limbs"]:
            for dl in lb["dls"]:
                if not (dl >> 24 in (0x00, 0x06, 0x04)):
                    continue
                def on_tri(st, t, addr, which):
                    nonlocal tris
                    if all(st["vb"][i] is not None for i in t):
                        tris += 1
                st = run_dl(segs, dl, on_tri)
                walked += 1
                for addr, w0, w1 in st["cmds"]:
                    if w0 >> 24 == 0xFD:
                        tex.add((w1 >> 24) & 0xF)
    return {"triangles": tris, "display_lists_walked": walked, "texture_segments": sorted(tex)}


def character_summary(rom: Rom, key: str) -> dict:
    from .oot_writer import skeleton
    obj_id, fname, role = next((c[1], c[2], c[3]) for c in CHARACTERS if c[0] == key)
    rom.object_table()
    assert rom.code_index is not None
    code = rom.file(rom.code_index)
    vs = struct.unpack_from(">I", code, rom.object_table() + 8 * obj_id)[0]
    idx = next(i for i, e in enumerate(rom.dma) if e[0] == vs)
    _vs, ve, rs, re_ = rom.dma[idx]
    obj = rom.object(obj_id)
    out = {
        "key": key, "object_id": obj_id, "file": fname, "role": role, "dmadata_index": idx,
        "size_compressed": (re_ - rs) if re_ else (ve - vs), "size_raw": ve - vs,
    }
    try:
        sec = object_sections(obj)
        out["object_header"] = {"ids": sec["ids"], "sections": sec["count"], "index_at": sec["index_at"]}
        skels = []
        for off in ([tail_skeleton(obj)] if tail_skeleton(obj) is not None else find_skeletons(obj)):
            s = skeleton(obj, off)
            skels.append({"off": off, "limbs": s["count"], "lod": s["lod"], "dlcount": s["dlcount"]})
        out["skeletons"] = skels
        out["mesh_probe"] = probe_triangles(rom, obj, [s["off"] for s in skels]) if skels else {"triangles": 0}
    except ValueError as e:
        out["object_header"] = None
        out["note"] = f"object sections not parsed yet: {e}"
    return out


# ---------------------------------------------------------------- the manifest

def inventory(source: str | Path, out: str | Path | None = None) -> dict:
    """Resolve the owned archive, hash it, and walk every playable form + mask + the launch layout."""
    source = Path(source)
    data = n64_rom.read(source)
    ident = identity(data)
    rom = Rom(data)
    raw = sum(1 for e in rom.dma if e[3] == 0)
    characters = {key: character_summary(rom, key) for key, *_ in CHARACTERS}
    masks = []
    rom.object_table()
    assert rom.code_index is not None
    for name, oid in MASKS:
        vs, ve, rs, re_ = rom.dma[next(i for i, e in enumerate(rom.dma) if e[0] == struct.unpack_from(
            ">I", rom.file(rom.code_index), rom.object_table() + 8 * oid)[0])]
        masks.append({"key": name, "object_id": oid,
                      "size_compressed": (re_ - rs) if re_ else (ve - vs), "size_raw": ve - vs})
    manifest = {
        "title": "Legend of Zelda, The: Majora's Mask (USA)",
        "platform": "n64",
        "source": {"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
        "rom": ident,
        "dmadata": {"entries": len(rom.dma), "start": DMA_START, "raw_files": raw,
                    "yaz0_files": len(rom.dma) - raw,
                    "unused_slots": sum(1 for e in rom.dma if e[2] == 0xFFFFFFFF)},
        "object_table": {"at": rom.object_table(), "in_code_dma_index": rom.code_index},
        "playable_forms": characters,
        "masks": masks,
        "launch": {"core": "parallel_n64", "rom_md5": ident["md5"], "cic": ident["cic"],
                   "note": "catalog launch prerequisites; the ROM is big-endian .z64, 32 MiB"},
        "writer_notes": [
            "files are appended past the last ROM data uncompressed (romEnd 0) and pointed to via dmadata",
            "a changed object file gets a fresh VROM range; gObjectTable in `code` is repointed",
            "the boot chip is CIC-NUS-6102: the 6102 checksum algorithm differs from oot_writer.crc6105",
            "player animations live inside the playable-form objects (analysis stage locates them)",
        ],
    }
    if out is not None:
        Path(out).write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Majora's Mask (USA, N64) owned-source inventory")
    ap.add_argument("source", help="owned .zip/.7z/.z64 ROM")
    ap.add_argument("--out", help="write the manifest JSON here")
    a = ap.parse_args()
    m = inventory(a.source, a.out)
    print(json.dumps({k: m[k] for k in ("source", "rom", "dmadata", "object_table")}, indent=2))
    for key, c in m["playable_forms"].items():
        sk = [(s["limbs"], "lod" if s["lod"] else "std") for s in c.get("skeletons", [])]
        print(f'{key:20s} obj {c["object_id"]:#x} {c["size_raw"]:>9,d}B raw  '
              f'sections={"?" if c["object_header"] is None else c["object_header"]["sections"]} skels={sk} '
              f'tris~{c.get("mesh_probe", {}).get("triangles", "?")}')
        if c.get("note"):
            print(f'{"":20s} {c["note"]}')
