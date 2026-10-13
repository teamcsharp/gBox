"""Turok 2: Seeds of Evil (N64, Europe NT2P rev 0) -- cart inventory.

Same Acclaim/Iguana "tengine" container family as Turok 1 (gbox.turok_inventory):
one tree of CIndexedSet collections, blocks packed with Rob Northen (Propack)
method 1/2 and verified against the RNC CRC-16.  The Turok 1 decoders are
reused unchanged; only the layout differs, so nothing here assumes Turok 1
offsets.

  CIndexedSet = { u32 BE count, u32 BE offsets[count+1] }, offsets relative
  to the set's own base, offsets[0] = header size rounded up to 16.

NT2P rev 0 layout (found by scanning, see ``find_cart_root``):
  cart root at ROM 0xFCBFB4, 21 collections spanning 0xFE6508 bytes.
  0  GraphicObjects   2705 objects, each a 4-block set
                        [ObjectInfo raw, Geometry RNC, Anims raw set, StaticEvents]
  1  RNC set of 1356  (Turok 1 slot: ObjectAttributes)
  2  raw {u32 2, u32 nObjects=2705, u16 animType[nObjects]} (ObjectTypes)
  3  TextureSets      1840 RNC-packed sets
  4  RNC set of 3     (Turok 1 slot: ParticleEffects)
  5  Levels           165 levels x 9 blocks
  16 RNC set of 114 + 17 raw {u32 4, u32 114, u32 types[]} (Binaries/BinaryTypes)
Other collections are recorded by shape only (names unverified).

The multiplayer character-select table names 10 playable characters; the
string block exists twice in the ROM (two resident code images), both
recorded.  Mapping names to GraphicObjects is analysis-stage work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib
from collections import Counter

from gbox.turok_inventory import decode_rnc, parse_indexed, rnc_info

SERIAL = "NT2P"
CART_ROOT_OFFSET = 0xFCBFB4  # NT2P rev 0
CART_ROOT_BLOCKS = 21
COLLECTION_LABELS = {
    0: "GraphicObjects", 1: "ObjectAttributes?", 2: "ObjectTypes",
    3: "TextureSets", 4: "ParticleEffects?", 5: "Levels",
    16: "Binaries?", 17: "BinaryTypes?",
}
GRAPHOBJ_BLOCKS = ["ObjectInfo", "Geometry", "Anims", "StaticEvents"]
TEXTURE_FORMATS = {0: "CI8_RGBA", 1: "CI4_RGBA", 2: "32_RGBA", 3: "CI4_IA",
                   4: "MM16RGBA"}
MP_CHARACTERS = ["Turok", "Adon", "Gant", "Flesh Eater", "Purr Lin",
                 "End Trail", "Fireborn", "Iggy", "Campaigner", "Telset"]


def _is_rnc(b: bytes) -> bool:
    return b[:4] in (b"RNC\x01", b"RNC\x02")


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


def find_cart_root(rom: bytes, start: int = 0) -> int | None:
    """First 4-aligned CIndexedSet with 21 blocks whose block 0 is itself a set of
    4-block sets (GraphicObjects).  Lets other builds be checked, not assumed."""
    for base in range(start & ~3, len(rom) - 8, 4):
        if struct.unpack_from(">I", rom, base)[0] != CART_ROOT_BLOCKS:
            continue
        root = parse_indexed(rom, base)
        if not root or len(root) != CART_ROOT_BLOCKS:
            continue
        go = parse_indexed(rom, base + root[0][0])
        first = parse_indexed(rom, base + root[0][0] + go[0][0]) if go else None
        if first and len(first) == 4:
            return base
    return None


def find_strings(rom: bytes, names: list[str], start: int = 0x1000,
                 end: int | None = None) -> dict:
    """ROM offsets of each name inside [start, end) (default: code, before the cart)."""
    end = len(rom) if end is None else end
    out = {}
    for n in names:
        key, hits, i = n.encode(), [], start
        while (i := rom.find(key, i, end)) >= 0:
            hits.append(i)
            i += 1
        out[n] = hits
    return out


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
            child = parse_indexed(dec, 0)
            e["child_blocks"] = len(child) if child else None
        else:
            s = parse_indexed(rom, base) if size > 8 else None
            e["blocks"] = len(s) if s else None
        out.append(e)
    return out


def inventory(rom: bytes, decode_all: bool = True) -> dict:
    root_base = CART_ROOT_OFFSET
    root = parse_indexed(rom, root_base)
    if not root or len(root) != CART_ROOT_BLOCKS:
        found = find_cart_root(rom)
        if found is None:
            raise ValueError("no 21-block tengine cart root")
        root_base, root = found, parse_indexed(rom, found)
    colls = _collections(rom, root_base, root)

    # ObjectTypes raw table
    ot = root_base + root[2][0]
    sub, n_ot = struct.unpack_from(">II", rom, ot)
    anim_types = struct.unpack_from(f">{n_ot}H", rom, ot + 8)

    # GraphicObjects
    go_base = root_base + root[0][0]
    go = parse_indexed(rom, go_base) or []
    objects, geom_ok, geom_fail, animated = [], 0, [], []
    geom_raw = geom_unpacked = 0
    for i, (rel, size) in enumerate(go):
        ob = parse_indexed(rom, go_base + rel)
        if not ob or len(ob) != 4:
            objects.append({"i": i, "bad": True})
            continue
        o = {"i": i, "rom": go_base + rel, "size": size,
             "anim_type": anim_types[i] if i < n_ot else None}
        for name, (r, s) in zip(GRAPHOBJ_BLOCKS, ob):
            o[name] = s
        gblob = rom[go_base + rel + ob[1][0]: go_base + rel + ob[1][0] + ob[1][1]]
        if decode_all and _is_rnc(gblob):
            try:
                g = decode_rnc(gblob)
                geom_ok += 1
                geom_raw += len(gblob)
                geom_unpacked += len(g)
                o["geometry_unpacked"] = len(g)
                o["geometry_sha1"] = hashlib.sha1(g).hexdigest()
            except ValueError as e:
                geom_fail.append([i, str(e)])
        an_base = go_base + rel + ob[2][0]
        an = parse_indexed(rom, an_base) if ob[2][1] > 8 else None
        o["anims"] = len(an) if an else 0
        if o["anims"]:
            animated.append(i)
        objects.append(o)

    # TextureSets
    ts_base = root_base + root[3][0]
    ts = parse_indexed(rom, ts_base) or []
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
        sub_ts = parse_indexed(dec, 0)
        if not sub_ts:
            ts_fail.append([i, "not an indexed set"])
            continue
        ts_ok += 1
        fmt = dec[sub_ts[0][0]] if sub_ts[0][1] else None
        fmt_counts[TEXTURE_FORMATS.get(fmt, f"?{fmt}")] += 1

    # Levels
    lv_base = root_base + root[5][0]
    lv = parse_indexed(rom, lv_base) or []
    lv_shapes = Counter(len(parse_indexed(rom, lv_base + r) or []) for r, _ in lv)

    # whole-ROM RNC census
    census, i = Counter(), 0
    while (i := rom.find(b"RNC", i)) >= 0:
        if rom[i + 3] in (1, 2):
            census[rom[i + 3]] += 1
        i += 1

    by_anims = sorted((o for o in objects if o.get("anims")),
                      key=lambda o: -o["Anims"])
    return {
        "cart_root": root_base,
        "collections": colls,
        "object_types": {"sub": sub, "n": n_ot,
                         "anim_type_counts": dict(Counter(anim_types).most_common())},
        "graphic_objects": {
            "total": len(go),
            "valid": sum(1 for o in objects if "bad" not in o),
            "geometry_rnc_ok": geom_ok, "geometry_rnc_fail": geom_fail,
            "geometry_packed_bytes": geom_raw,
            "geometry_unpacked_bytes": geom_unpacked,
            "animated": len(animated),
            "largest_anim_sets": [{k: o[k] for k in ("i", "anims", "Anims", "anim_type")}
                                  for o in by_anims[:16]],
            "objects": objects,
        },
        "texture_sets": {"total": len(ts), "rnc_ok": ts_ok, "rnc_fail": ts_fail,
                         "format_counts": dict(fmt_counts)},
        "levels": {"total": len(lv), "blocks_per_level": dict(lv_shapes)},
        "rnc_census": {str(k): v for k, v in sorted(census.items())},
        "mp_characters": {"names": MP_CHARACTERS,
                          "search_range": [0x1000, root_base],
                          "rom_offsets": find_strings(rom, MP_CHARACTERS, 0x1000, root_base)},
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
        "game": "Turok 2: Seeds of Evil", "region": "Europe",
        "source_sha256": src_sha, "header": header(raw), "rom_size": len(raw),
        "rom_md5": hashlib.md5(raw).hexdigest(),
        "rom_sha1": hashlib.sha1(raw).hexdigest(),
        "rom_sha256": hashlib.sha256(raw).hexdigest(),
        "container": "tengine CIndexedSet tree, RNC(Propack) blocks",
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
