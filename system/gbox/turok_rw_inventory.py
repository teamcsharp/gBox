"""Turok: Rage Wars (N64, USA NRWE rev 0) -- cart inventory.

Same Acclaim/Iguana "tengine" CIndexedSet + RNC (Propack method 1) family as
Turok 1/2 (gbox.turok_inventory, gbox.turok2_inventory); the decoders are
reused unchanged and every RNC block is checked against its CRC-16.  The
layout differs from both earlier titles, so nothing here assumes their
offsets:

  CIndexedSet = { u32 BE count, u32 BE offsets[count+1] }, offsets relative
  to the set's own base.

NRWE rev 0 (found by scanning, see ``find_cart_root``):
  cart root at ROM 0x50F768, 24 collections, 0x291318 bytes (ends 0x7A0AE8).
  0  GraphicObjects   347 objects, each a raw 4-block set
                        [ObjectInfo, Geometry, Anims, StaticEvents]
                      Geometry is itself a raw set of RNC parts (386 parts in
                      all, unlike Turok 2 whose Geometry block is one RNC).
  1  RNC set of 169   (Turok 1 slot: ObjectAttributes, name unverified)
  2  RNC {u32 2, u32 347, u16 animType[347]}  (ObjectTypes)
  3  TextureSets      507 RNC sets (CI8_RGBA 272, CI4_RGBA 180, CI4_IA 55)
  5  Levels           37 levels x 13 blocks
  16 69 RNC blocks, 18 38 raw sets (37 x 4 blocks), 21 36 RNC blocks
  ROM 0x2A0000-0x50F768 is high-entropy (~7.3 bits/byte), most likely audio.

GraphicObject 174 (animType 1120) is the largest animated object: 37 RNC
geometry parts (16 large ~10 KB + 21 small ~2 KB) and 44 animations, the
best candidate for the shared player-character object.  That mapping is an
analysis-stage hypothesis, not verified here.

Character select (ROM 0xCFD88, single copy) lists 17 names; the code also
carries the PLAYER_CHARACTER_* enum names (twice, two resident code images),
whose order differs from the select list.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import zlib
from collections import Counter

from gbox.turok_inventory import decode_rnc, parse_indexed, rnc_info

SERIAL = "NRWE"
CART_ROOT_OFFSET = 0x50F768  # NRWE rev 0
CART_ROOT_BLOCKS = 24
COLLECTION_LABELS = {
    0: "GraphicObjects", 1: "ObjectAttributes?", 2: "ObjectTypes",
    3: "TextureSets", 5: "Levels",
}
GRAPHOBJ_BLOCKS = ["ObjectInfo", "Geometry", "Anims", "StaticEvents"]
TEXTURE_FORMATS = {0: "CI8_RGBA", 1: "CI4_RGBA", 2: "32_RGBA", 3: "CI4_IA",
                   4: "MM16RGBA"}
SELECT_TABLE_OFFSET = 0xCFD88
SELECT_NAMES = ["TUROK", "MANTID DRONE", "CAMPAIGNER", "FIREBORN",
                "MANTID SOLDIER", "ADON", "LORD OF THE DEAD", "ELITE GUARD",
                "GUARDIAN", "JUGGERNAUT", "OBLIVION SPAWN", "BASTILLE", "SYRA",
                "SYMBIONT", "TAL SET", "RAPTOR", "MANTID MITES"]
PLAYER_CHARACTER_ENUM_RE = rb"(PLAYER_CHARACTER_[A-Z_]+?)[RT]?(?![A-Z_])"


def _is_rnc(b: bytes) -> bool:
    return b[:4] in (b"RNC\x01", b"RNC\x02")


def _pi(data: bytes, base: int):
    try:
        return parse_indexed(data, base)
    except (struct.error, ValueError, IndexError):
        return None


def header(rom: bytes) -> dict:
    if rom[:4] != b"\x80\x37\x12\x40":
        raise ValueError("not a z64 (big-endian) ROM image")
    return {
        "name": rom[0x20:0x34].decode("ascii", "replace").rstrip(),
        "serial": rom[0x3B:0x3F].decode("ascii", "replace"),
        "version": rom[0x3F],
        "crc1": f"{struct.unpack_from('>I', rom, 0x10)[0]:08x}",
        "crc2": f"{struct.unpack_from('>I', rom, 0x14)[0]:08x}",
        "entry": f"0x{struct.unpack_from('>I', rom, 8)[0]:08x}",
        "ipl3_crc32": f"{zlib.crc32(rom[0x40:0x1000]):08x}",
    }


def find_cart_root(rom: bytes, start: int = 0x1000) -> int | None:
    """First 4-aligned 24-block CIndexedSet whose block 0 is a set of 4-block
    sets (GraphicObjects).  Lets other builds be checked, not assumed."""
    for base in range(start & ~3, len(rom) - 8, 4):
        if struct.unpack_from(">I", rom, base)[0] != CART_ROOT_BLOCKS:
            continue
        root = _pi(rom, base)
        if not root or len(root) != CART_ROOT_BLOCKS:
            continue
        go = _pi(rom, base + root[0][0])
        first = _pi(rom, base + root[0][0] + go[0][0]) if go else None
        if first and len(first) == 4:
            return base
    return None


def select_names(rom: bytes, offset: int = SELECT_TABLE_OFFSET) -> list[str]:
    """NUL-separated character-select strings starting at ``offset``."""
    out = []
    for s in re.split(rb"\x00+", rom[offset:offset + 0x100]):
        if not s:
            continue
        t = s.decode("ascii", "replace")
        if not t.isupper() and t != t.upper():
            break
        out.append(t)
    return out[:len(SELECT_NAMES)]


def player_character_enum(rom: bytes, end: int) -> dict:
    """Every PLAYER_CHARACTER_* enum name in the code range, with copy offsets."""
    hits: dict[str, list[int]] = {}
    # Symbol records end with a tag byte ('R'/'T'); strip one trailing R/T.
    for m in re.finditer(PLAYER_CHARACTER_ENUM_RE, rom[0x1000:end]):
        name = m.group(1).decode()
        hits.setdefault(name, []).append(0x1000 + m.start())
    order = sorted(hits, key=lambda n: hits[n][0])
    return {"names": order, "offsets": {n: hits[n] for n in order}}


def _collections(rom: bytes, root_base: int, root) -> list[dict]:
    out = []
    for i, (rel, size) in enumerate(root):
        base = root_base + rel
        e = {"i": i, "label": COLLECTION_LABELS.get(i, f"unknown_{i}"),
             "rom": base, "size": size, "head": rom[base:base + 4].hex()}
        blob = rom[base:base + size]
        if _is_rnc(blob):
            e.update(rnc_info(blob))
            dec = decode_rnc(blob)  # raises on CRC mismatch
            e["crc_ok"] = True
            e["unpacked"] = len(dec)
            child = _pi(dec, 0)
            e["child_blocks"] = len(child) if child else None
        else:
            s = _pi(rom, base) if size > 8 else None
            e["blocks"] = len(s) if s else None
            if s:
                e["rnc_children"] = sum(
                    1 for r, n in s if _is_rnc(rom[base + r:base + r + 4]))
        out.append(e)
    return out


def inventory(rom: bytes, decode_all: bool = True) -> dict:
    root_base = CART_ROOT_OFFSET
    root = _pi(rom, root_base)
    if not root or len(root) != CART_ROOT_BLOCKS:
        found = find_cart_root(rom)
        if found is None:
            raise ValueError("no 24-block tengine cart root")
        root_base, root = found, _pi(rom, found)
    colls = _collections(rom, root_base, root)

    # ObjectTypes: RNC-packed {u32 sub, u32 n, u16 animType[n]}
    ot_blob = rom[root_base + root[2][0]: root_base + root[2][0] + root[2][1]]
    ot = decode_rnc(ot_blob) if _is_rnc(ot_blob) else ot_blob
    if len(ot) < 8:
        raise ValueError("ObjectTypes block shorter than its 8-byte header")
    sub, n_ot = struct.unpack_from(">II", ot, 0)
    if 8 + 2 * n_ot > len(ot):
        raise ValueError(f"ObjectTypes count {n_ot} overruns {len(ot)} bytes")
    anim_types = struct.unpack_from(f">{n_ot}H", ot, 8)

    # GraphicObjects: Geometry = raw set of RNC parts
    go_base = root_base + root[0][0]
    go = _pi(rom, go_base) or []
    objects, animated = [], []
    parts_ok, parts_fail, geom_packed, geom_unpacked = 0, [], 0, 0
    for i, (rel, size) in enumerate(go):
        ob = _pi(rom, go_base + rel)
        if not ob or len(ob) != 4:
            objects.append({"i": i, "bad": True})
            continue
        o = {"i": i, "rom": go_base + rel, "size": size,
             "anim_type": anim_types[i] if i < n_ot else None}
        for name, (_, s) in zip(GRAPHOBJ_BLOCKS, ob):
            o[name] = s
        g_base = go_base + rel + ob[1][0]
        gparts = _pi(rom, g_base) if ob[1][1] > 8 else None
        o["geometry_parts"] = len(gparts) if gparts else 0
        if decode_all and gparts:
            sizes, h = [], hashlib.sha1()
            for pr, ps in gparts:
                blob = rom[g_base + pr: g_base + pr + ps]
                if not _is_rnc(blob):
                    parts_fail.append([i, "part not RNC"])
                    continue
                try:
                    d = decode_rnc(blob)
                except ValueError as e:
                    parts_fail.append([i, str(e)])
                    continue
                parts_ok += 1
                geom_packed += len(blob)
                geom_unpacked += len(d)
                sizes.append(len(d))
                h.update(d)
            o["geometry_unpacked"] = sizes
            o["geometry_sha1"] = h.hexdigest()
        an = _pi(rom, go_base + rel + ob[2][0]) if ob[2][1] > 8 else None
        o["anims"] = len(an) if an else 0
        if o["anims"]:
            animated.append(i)
        objects.append(o)

    # TextureSets
    ts_base = root_base + root[3][0]
    ts = _pi(rom, ts_base) or []
    fmt_counts, ts_ok, ts_fail = Counter(), 0, []
    for i, (rel, size) in enumerate(ts):
        blob = rom[ts_base + rel: ts_base + rel + size]
        if not decode_all or not _is_rnc(blob):
            continue
        try:
            dec = decode_rnc(blob)
        except ValueError as e:
            ts_fail.append([i, str(e)])
            continue
        sub_ts = _pi(dec, 0)
        if not sub_ts:
            ts_fail.append([i, "not an indexed set"])
            continue
        ts_ok += 1
        fmt = dec[sub_ts[0][0]] if sub_ts[0][1] else None
        fmt_counts[TEXTURE_FORMATS.get(fmt, f"?{fmt}")] += 1

    lv_base = root_base + root[5][0]
    lv = _pi(rom, lv_base) or []
    lv_shapes = Counter(len(_pi(rom, lv_base + r) or []) for r, _ in lv)

    census, i = Counter(), 0
    while (i := rom.find(b"RNC", i)) >= 0:
        if i + 3 < len(rom) and rom[i + 3] in (1, 2):
            census[rom[i + 3]] += 1
        i += 1

    by_anims = sorted((o for o in objects if o.get("anims")),
                      key=lambda o: -o["Anims"])
    return {
        "cart_root": root_base,
        "cart_end": root_base + root[-1][0] + root[-1][1],
        "collections": colls,
        "object_types": {"sub": sub, "n": n_ot,
                         "anim_type_counts": dict(Counter(anim_types).most_common())},
        "graphic_objects": {
            "total": len(go),
            "valid": sum(1 for o in objects if "bad" not in o),
            "geometry_parts_rnc_ok": parts_ok,
            "geometry_parts_fail": parts_fail,
            "geometry_packed_bytes": geom_packed,
            "geometry_unpacked_bytes": geom_unpacked,
            "animated": len(animated),
            "largest_anim_sets": [{k: o[k] for k in
                                   ("i", "anims", "Anims", "anim_type", "geometry_parts")}
                                  for o in by_anims[:16]],
            "player_object_candidate": 174,
            "objects": objects,
        },
        "texture_sets": {"total": len(ts), "rnc_ok": ts_ok, "rnc_fail": ts_fail,
                         "format_counts": dict(fmt_counts)},
        "levels": {"total": len(lv), "blocks_per_level": dict(lv_shapes)},
        "rnc_census": {str(k): v for k, v in sorted(census.items())},
        "characters": {
            "select_table_rom": SELECT_TABLE_OFFSET,
            "select_names": select_names(rom),
            "player_character_enum": player_character_enum(rom, root_base),
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src", help="ROM path (.z64/.n64/.v64 or the owned .zip)")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    from gbox import n64_rom
    raw = n64_rom.read(args.src)
    with open(args.src, "rb") as f:
        src_sha = hashlib.sha256(f.read()).hexdigest()
    m = {
        "game": "Turok: Rage Wars", "region": "USA",
        "source_sha256": src_sha, "header": header(raw), "rom_size": len(raw),
        "rom_md5": hashlib.md5(raw).hexdigest(),
        "rom_sha1": hashlib.sha1(raw).hexdigest(),
        "rom_sha256": hashlib.sha256(raw).hexdigest(),
        "container": "tengine CIndexedSet tree, RNC(Propack m1) blocks",
        "launch": {"cic": "6102 (IPL3 crc32 90bb6cb5)", "save": "Controller Pak",
                   "expansion_pak": "optional"},
        "inventory": inventory(raw),
    }
    txt = json.dumps(m, indent=1)
    if args.out:
        with open(args.out, "w") as f:
            f.write(txt)
        print(f"wrote {args.out}")
    else:
        print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
