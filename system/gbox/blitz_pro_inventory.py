"""NFL Blitz Pro (USA) GameCube (GFVE5D) owned-build inventory.

Facts verified against the owned ``NFL Blitz Pro (USA).gcz`` (Dolphin GCZ, sub_type 0, image
1459978240 bytes, file 1228174428 bytes):
- gcz sha256 973a209f08e8abb77daf8bd3ebbb3bd8d5cd2bc873f009bf02d9aa81b16074e5;
  main.dol 3390720 bytes sha256 91e3553184a532f56437bea02126918407669b65013db58114ce7f4fd8802953.
- FST (disc offset, size): blitzpro.tpl 0x360000/153664, opening.bnr, blitzopt.obf,
  blitz04.mpk 0x3891ac/386857088, resimg1.dat 0x17480000/342614592, movies/*.h4m.
  (An earlier note listing blitzpro.tpl as 334 MB was wrong.)
- ``blitz04.mpk`` and ``resimg1.dat`` are BIG-endian ``PAK `` containers.  Header (u32 BE):
  magic "PAK ", version 0x200, size_field, field_0c, field_10, field_14 (= 0x200000), zero pad to 0x40.
    blitz04.mpk : size_field 0x170e3d40, field_0c 0x6c10, field_10 0x4f1c, field_14 0x200000
    resimg1.dat : size_field 0x146be060, field_0c 0x110,  field_10 0xc0,   field_14 0x200000
- The directory of ``blitz04.mpk`` starts at 0x40 with variable-length id records; each record starts
  with a 16-byte field: 4 ASCII digits ("1000", "1002", ...) + 12 NUL bytes.  Observed record starts:
  0x40, 0x220, 0x540, 0x980, 0xe60, 0x1520, 0x18e0, ... (4-byte aligned, 25+ records).
- Inside those records sit part entries: the 8-byte marker 00 00 56 22 cd cd cd cd (u32 0x5622 +
  u32 0xcdcdcdcd) followed by an 8-byte NUL-padded name, e.g. record 1000 has c0130_1 at 0x104 and
  c0130_2 at 0x138; record 1002 has c0132_1 at 0x300.  Marker->marker stride is 0x34.
- WHAT the ids, the 0x5622 marker, field_0c/field_10 or the cNNNN_k names MEAN is still UNPROVEN.
  This is an inventory, not a model reader.  This ``PAK `` is neither the PS2 AKI arena pack
  (gbox.defjam_inventory) nor the GameCube Def Jam .gpl/.act/.skn set (gbox.defjam_vendetta).
  Next: decompile the main.dol PAK loader and decode these fields before classifying any entry.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct

PAK_MAGIC = b"PAK "
PAK_HEADER_SIZE = 0x40
# u32 0x5622 + u32 0xcdcdcdcd, big-endian, as seen in the owned blitz04.mpk directory.
PAK_PART_MARKER = b"\x00\x00\x56\x22\xcd\xcd\xcd\xcd"
PART_NAME_RE = re.compile(rb"c\d{4}_\d")


class FormatError(ValueError):
    pass


def sha256_stream(path, chunk=1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(chunk), b""):
            h.update(c)
    return h.hexdigest()


def pak_header(b: bytes) -> dict:
    """Header fields of a big-endian ``PAK `` container.  Meanings of fields 0x08..0x14 are unproven."""
    if len(b) < 0x18:
        raise FormatError("short PAK header")
    if b[:4] != PAK_MAGIC:
        raise FormatError("not a PAK container")
    ver, size, f3, f4, f5 = struct.unpack_from(">5I", b, 4)
    return {"version": ver, "size_field": size, "field_0c": f3, "field_10": f4, "field_14": f5}


def pak_id_records(b: bytes, limit: int | None = None) -> list[dict]:
    """Id records: 4 ASCII digits + 12 NUL bytes on a 4-byte aligned offset, from 0x40 up."""
    end = min(len(b), limit if limit is not None else len(b))
    out = []
    for m in re.finditer(rb"\d{4}\x00{12}", b[PAK_HEADER_SIZE:end]):
        off = PAK_HEADER_SIZE + m.start()
        if off % 4:
            continue
        out.append({"offset": off, "id": m.group(0)[:4].decode()})
    return out


def pak_part_entries(b: bytes, limit: int | None = None) -> list[dict]:
    """Part entries: the 8-byte 0x5622/0xcdcdcdcd marker plus the 8-byte NUL-padded name after it."""
    end = min(len(b), limit if limit is not None else len(b))
    out = []
    pos = PAK_HEADER_SIZE
    while True:
        i = b.find(PAK_PART_MARKER, pos, end)
        if i < 0:
            break
        raw = b[i + 8:i + 16]
        out.append({"offset": i, "name": raw.split(b"\0")[0].decode("latin-1")})
        pos = i + 1
    return out


def pak_inventory(b: bytes, limit: int | None = None) -> dict:
    """Structured summary of a PAK directory region (ids, part entries, ownership of parts by id)."""
    hdr = pak_header(b)
    ids = pak_id_records(b, limit)
    parts = pak_part_entries(b, limit)
    owner = None
    pending = list(ids)
    for p in parts:
        while pending and pending[0]["offset"] < p["offset"]:
            owner = pending.pop(0)
        p["id"] = owner["id"] if owner else None
    names = sorted({p["name"] for p in parts})
    return {
        "header": hdr,
        "id_count": len(ids),
        "ids": [i["id"] for i in ids],
        "part_count": len(parts),
        "part_names": names,
        "parts": parts,
    }


def part_names(b: bytes, limit: int) -> list[str]:
    """Distinct part names in the leading directory bytes (kept from the first inventory revision)."""
    return sorted({m.group(0).decode() for m in PART_NAME_RE.finditer(b[:limit])})


def pak_entries(b: bytes, limit: int | None = None) -> list[dict]:
    """Backwards-compatible alias for the id record list."""
    return pak_id_records(b, limit)


def summarize_member(data: bytes, limit: int = 1 << 22) -> dict:
    inv = pak_inventory(data, limit)
    return {
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "header": dict(inv["header"]),
        "id_count": inv["id_count"],
        "ids": inv["ids"][:40],
        "part_count": inv["part_count"],
        "part_name_count": len(inv["part_names"]),
        "part_names": inv["part_names"][:40],
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    from .gcdisc import GCDisc

    ap = argparse.ArgumentParser(description="NFL Blitz Pro (GameCube) PAK inventory")
    ap.add_argument("gcz")
    ap.add_argument("--member", default="blitz04.mpk")
    ap.add_argument("--limit", type=int, default=1 << 22)
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    disc = GCDisc(args.gcz)
    data = disc.read(args.member)
    out = summarize_member(data, args.limit)
    out["member"] = args.member
    out["gcz_sha256"] = sha256_stream(args.gcz)
    text = json.dumps(out, indent=2)
    if args.json:
        Path(args.json).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
