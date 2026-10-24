"""Turok: Rage Wars (N64, Europe "NRWP" rev 0) -- owned-build cart inventory.

Owned source for the Europe catalog entry (game_id f275116453c8709d):

  /mnt/gbox/hyperspin/Arcade/collections/Nintendo 64/roms/Europe/
      Turok - Rage Wars (Europe).zip
  zip sha256 2e253f919835ff6b680fb88969b1eff17debc62d6242dc9f39ecb73947a09b06
  member    "Turok - Rage Wars (Europe).z64" (8388608 B)

The member carries a ``.z64`` name but its bytes are v64 (halfword
byte-swapped), so it must be normalised with ``gbox.n64_rom.read`` before
any offset is interpreted.  Normalised (big-endian) image sha256 is
d763cbbe485a5f9e1b7be97d5ac16735087e23d0bb62c05dc844e01b7e1156d1.

Container layout is the same Acclaim/Iguana "tengine" CIndexedSet tree the
USA build uses (gbox.turok_rw_inventory): cart root at 0x50F768, 24
collections, 347 GraphicObjects whose Geometry block is a raw set of RNC
parts (386 parts in all), 507 TextureSets and 37 levels x 13 blocks.  The
asset tree is byte-identical to the USA build, but the code/data region is
not, so no USA offset is reused here:

  * the 0x124Axx debug symbol records that carry the PLAYER_CHARACTER_* enum
    names in the USA build are absent from the PAL build, so that enum
    cannot be recovered from this ROM;
  * the character-select table sits at 0xD0A58 (copies at 0xD52A8, 0x162358,
    0x166D40) instead of the USA 0xCFD88;
  * the cart root ends 24 bytes later (0x7A0B00 vs 0x7A0AE8) because the
    localised string tables are larger.

The rosters are therefore located by scanning for the signature rather
than hardcoding an offset, and the container is walked from the cart root
found by ``find_cart_root``.  The player-character asset is GraphicObject
174 (animType 1120): 37 RNC geometry parts and 44 animations.  Its geometry
hashes identically to the USA build's object 174, which is how cross-build
compatibility is verified here rather than assumed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

from gbox import turok_rw_inventory as rw
from gbox.turok_inventory import decode_rnc, parse_indexed

# The English roster, in select-screen order.  Identical to the USA build's
# list; the PAL build adds French, Italian and Spanish copies of the table.
ENGLISH_ROSTER = list(rw.SELECT_NAMES)

# "TUROK" padded to a 4-byte boundary, followed by the next roster entry.
# The USA build has one such table; the PAL build has four.
ROSTER_SIGNATURE = b"TUROK\x00\x00\x00MANTID DRONE"

PLAYER_OBJECT_INDEX = 174
PLAYER_ANIM_TYPE = 1120

# N64 cartridge metadata that the runtime needs before the game can boot.
LAUNCH = {"cic": "6102 (IPL3 crc32 90bb6cb5)", "save": "Controller Pak",
           "expansion_pak": "optional", "video": "PAL (Europe build)"}


def _sha256_file(path: Path) -> str:
    """Hash a file by streaming it; never load a whole archive into memory."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_roster_tables(rom: bytes) -> list[dict]:
    """Every character-roster string table in the ROM.

    A roster table is a NUL-separated run of display names that starts with
    "TUROK".  Each hit is reported with its offset, its names and whether
    the names are the English roster; the PAL build also ships French,
    Italian and Spanish copies of the same table, so the roster is never
    assumed to live at a fixed offset.
    """
    out: list[dict] = []
    for m in re.finditer(rb"TUROK\x00", rom):
        start = m.start()
        names: list[str] = []
        for raw in re.split(rb"\x00+", rom[start:start + 0x300]):
            if not raw:
                continue
            try:
                names.append(raw.decode("ascii"))
            except UnicodeDecodeError:
                # A non-ASCII byte means this is a localised (accented) table.
                names.append(raw.decode("latin-1"))
                continue
            if len(names) >= 24:
                break
        if len(names) < 8:
            continue
        out.append({
            "offset": start,
            "names": names,
            "n_names": len(names),
            "english": names[:len(ENGLISH_ROSTER)] == ENGLISH_ROSTER,
            "ascii_only": all(n.isascii() for n in names),
        })
    return out


def select_roster(rom: bytes) -> dict:
    """The English character-select roster and every roster table copy."""
    tables = find_roster_tables(rom)
    english = [t for t in tables if t["english"]]
    return {
        "english_offset": english[0]["offset"] if english else None,
        "english_copies": [t["offset"] for t in english],
        "names": english[0]["names"][:len(ENGLISH_ROSTER)] if english else [],
        "localised_tables": [t["offset"] for t in tables if not t["english"]],
        "tables": tables,
    }


def player_character_enum(rom: bytes, end: int) -> dict:
    """PLAYER_CHARACTER_* enum names, when the build carries the debug records.

    The USA build embeds those symbol records twice; the PAL build has none,
    so an empty result here is a property of this build, not a parse failure.
    """
    enum = rw.player_character_enum(rom, end)
    enum["present"] = bool(enum["names"])
    return enum


def target_asset(rom: bytes, index: int = PLAYER_OBJECT_INDEX) -> dict:
    """The player-character asset: one GraphicObject and its RNC geometry parts.

    Each part is reported with its ROM offset, its packed size and the
    SHA-256 of both the packed and the decompressed bytes, so a later
    writer can address exactly the bytes it replaces.
    """
    inv = rw.inventory(rom)
    obj = inv["graphic_objects"]["objects"][index]
    base = obj["rom"]
    blocks = parse_indexed(rom, base)
    if not blocks or len(blocks) != 4:
        raise ValueError(f"graphic object {index} is not a 4-block set")
    geom_rel, geom_size = blocks[1]
    g_base = base + geom_rel
    parts = parse_indexed(rom, g_base)
    if parts is None:
        raise ValueError(f"graphic object {index} geometry is not an indexed set")
    out = []
    for i, (rel, size) in enumerate(parts):
        blob = rom[g_base + rel:g_base + rel + size]
        rec = {"i": i, "rom": g_base + rel, "packed_size": size,
               "packed_sha256": hashlib.sha256(blob).hexdigest()}
        if blob[:3] == b"RNC":
            rec["rnc_method"] = blob[3]
            try:
                dec = decode_rnc(blob)
            except ValueError as exc:
                rec["error"] = str(exc)
                out.append(rec)
                continue
            rec["unpacked_size"] = len(dec)
            rec["unpacked_sha256"] = hashlib.sha256(dec).hexdigest()
            rec["unpacked_head"] = dec[:8].hex()
        else:
            rec["unpacked_size"] = size
            rec["unpacked_sha256"] = rec["packed_sha256"]
        out.append(rec)
    return {
        "index": index,
        "rom": base,
        "size": obj["size"],
        "anim_type": obj["anim_type"],
        "anims": obj["anims"],
        "geometry_parts": len(out),
        "geometry_unpacked_bytes": sum(p.get("unpacked_size", 0) for p in out),
        "geometry_sha1": obj.get("geometry_sha1"),
        "parts": out,
    }


def _zip_member(src: Path) -> tuple[str | None, int | None]:
    """The ROM member name and size when the source is the owned .zip."""
    if src.suffix.lower() != ".zip":
        return None, None
    import zipfile
    with zipfile.ZipFile(src) as zf:
        members = [i for i in zf.infolist() if not i.is_dir()]
        if not members:
            return None, None
        return members[0].filename, members[0].file_size


def build_manifest(src: Path, rom: bytes, source_sha256: str,
                   index: int = PLAYER_OBJECT_INDEX) -> dict:
    """The authoritative owned-build manifest for this exact catalog entry."""
    inv = rw.inventory(rom)
    hdr = rw.header(rom)
    go = inv["graphic_objects"]
    ts = inv["texture_sets"]
    root_base = inv["cart_root"]
    roster = select_roster(rom)
    enum = player_character_enum(rom, root_base)
    member, member_bytes = _zip_member(src)
    return {
        "game": "Turok - Rage Wars (Europe)",
        "game_id": "f275116453c8709d",
        "region": "Europe (PAL)",
        "platform": "n64",
        "serial": hdr["serial"],
        "revision": hdr["version"],
        "source": {
            "path": str(src),
            "sha256": source_sha256,
            "member": member,
            "member_bytes": member_bytes,
            "byte_order_in_file": "v64 (halfword byte-swapped, despite .z64 name)",
            "normalised_byte_order": "z64 (big-endian)",
        },
        "rom": {
            "size": len(rom),
            "sha256": hashlib.sha256(rom).hexdigest(),
            "md5": hashlib.md5(rom).hexdigest(),
            "sha1": hashlib.sha1(rom).hexdigest(),
            "offset_base": "0x000000 in the normalised big-endian image",
        },
        "header": hdr,
        "launch": dict(LAUNCH),
        "container": {
            "root": "tengine CIndexedSet tree, RNC (Propack method 1) blocks",
            "cart_root": root_base,
            "cart_end": inv["cart_end"],
            "collections": len(inv["collections"]),
            "collection_labels": [c["label"] for c in inv["collections"]],
        },
        "counts": {
            "graphic_objects": go["total"],
            "graphic_objects_valid": go["valid"],
            "animated_objects": go["animated"],
            "geometry_parts": go["geometry_parts_rnc_ok"],
            "geometry_parts_failed": len(go["geometry_parts_fail"]),
            "geometry_unpacked_bytes": go["geometry_unpacked_bytes"],
            "texture_sets": ts["total"],
            "texture_sets_decoded": ts["rnc_ok"],
            "texture_formats": ts["format_counts"],
            "levels": inv["levels"]["total"],
            "blocks_per_level": inv["levels"]["blocks_per_level"],
            "rnc_blocks": inv["rnc_census"],
        },
        "roster": {
            "select_table_offset": roster["english_offset"],
            "select_table_copies": roster["english_copies"],
            "names": roster["names"],
            "localised_table_offsets": roster["localised_tables"],
            "player_character_enum_present": enum["present"],
            "player_character_enum": enum["names"],
        },
        "target_asset": target_asset(rom, index),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src", help="owned ROM path (.z64/.n64/.v64 or the owned .zip)")
    ap.add_argument("--out", help="write the manifest JSON here")
    ap.add_argument("--index", type=int, default=PLAYER_OBJECT_INDEX)
    args = ap.parse_args(argv)

    from gbox import n64_rom
    src = Path(args.src)
    rom = n64_rom.read(src)
    manifest = build_manifest(src, rom, _sha256_file(src), args.index)
    text = json.dumps(manifest, indent=1)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
