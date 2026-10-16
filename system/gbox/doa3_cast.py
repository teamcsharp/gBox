"""DOA3 (USA, Xbox) native cast layer: XPR0 container walker, CAT companions,
slot inventory and the AFS patch path for the combined cast writer.

Everything here is validated against the owned USA build (game b8edf7040116f3aa;
XBE sha256 e523dd15d0765899a43a1824c023e0219d129e9a8b41e8213e4e645755d2bfa3,
loadfile.afs 365689880 bytes). The MDL geometry decoder/encoder is NOT
implemented yet: this module stops at container level and says so. It is not a
playable build and must never be reported as one.

Layout facts pinned from kas00.xpr / kas00.cat (Kasumi costume 00, live bytes):

* XPR0: magic, u32 total, u32 header_size, then the user-data pair
  {u32 0x80000000, u32 size, 4cc tag ``MDL``} at 0x0C..0x18. The MDL payload
  starts at header_size (kas00: 119868 bytes of dense float data, no texture
  magic). The header continues with a second pair {u32 0x48, u32 87} at 0x18
  and a u32 18 at 0x20; the words after that are NOT resolved to a record
  stride yet (12- and 20-byte interpretations both fail internal consistency
  on live bytes) and are exposed raw. No ``DDS `` magic exists anywhere in the
  resource: textures are raw D3D surfaces without an external marker, so the
  D3D resource table has to be pinned against the XBE loader (RE stage).
* CAT: u32 version (1) then size/count words (kas00: 0x14, 1472, 0x9A40,
  0x4F5C0, 0x100, 1, 0x18) and ASCII section markers (``LNK\\0`` plus digits,
  e.g. at 0x9A40). The trailing 12-byte table near EOF looks like
  {id, size, next_id} records but its alignment/chain rules differ between
  costumes (kas00 vs kas01 scans disagree), so it is left for the RE stage.
* AFS entries must be rewritten inside their room (size rounded up to the
  archive alignment, bounded by the next entry's offset / name directory),
  which ``doa3_inventory.entry_rooms`` computes.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

from .doa3_inventory import GAME_ID, ROSTER, afs_table, entry_rooms

XBE_SHA256 = "e523dd15d0765899a43a1824c023e0219d129e9a8b41e8213e4e645755d2bfa3"
XPR_MAGIC = b"XPR0"
USER_TYPE = 0x80000000
MDL_TAG = b"MDL\x00"
LNK_MARKER = b"LNK\x00"
MAX_HEADER_WORDS = 4096

# Display-name mapping for the nickname families that carry a fighter code is
# NOT derivable from the archive: karate, ninja, koryu, suiken, gokei, chin,
# sambo, bosnin, hika need the XBE select table (RE stage). Reported as pending.
DISPLAY_MAPPING_PENDING = ("karate", "ninja", "koryu", "suiken", "gokei",
                           "chin", "sambo", "bosnin", "hika", "tengu")


# --------------------------------------------------------------------- XPR0

def xpr_resources(blob: bytes) -> dict:
    """Walk an XPR0 packed resource: the verified header fields, the MDL
    payload range and the raw descriptor words that follow the second pair.

    The descriptor words are intentionally not interpreted as records: their
    stride is still unresolved (see the module docstring)."""
    if len(blob) < 0x20 or blob[:4] != XPR_MAGIC:
        raise ValueError(f"not an XPR0 resource (magic {blob[:4]!r})")
    total, hsize = struct.unpack_from("<II", blob, 4)
    if not 12 <= hsize <= total <= len(blob):
        raise ValueError(f"XPR0 sizes invalid: header {hsize}, total {total}, file {len(blob)}")
    rtype, rsize = struct.unpack_from("<II", blob, 12)
    if rtype != USER_TYPE:
        raise ValueError(f"XPR0 first resource is not user data (type {rtype:#x})")
    tag = blob[20:24]
    if tag != MDL_TAG:
        raise ValueError(f"XPR0 user resource tag is {tag!r}, not {MDL_TAG!r}")
    mdl_end = hsize + rsize
    if mdl_end > total:
        raise ValueError("XPR0 MDL payload extends outside the resource")
    second_type, second_size = struct.unpack_from("<II", blob, 0x18)
    descriptor_count = struct.unpack_from("<I", blob, 0x20)[0]
    # The descriptor region length (stride) is unresolved; expose a bounded
    # window of raw words and note truncation instead of guessing a record size.
    cap = min(MAX_HEADER_WORDS, max(64, 8 * descriptor_count))
    words_end = min(hsize, 0x24 + 4 * cap)
    words = [struct.unpack_from("<I", blob, o)[0] for o in range(0x24, words_end, 4)]
    return {"magic": XPR_MAGIC.decode(), "total": total, "header_size": hsize,
            "mdl": {"type": rtype, "size": rsize, "tag": tag.decode("latin-1").rstrip("\x00"),
                    "offset": hsize, "end": mdl_end},
            "second_pair": {"type": second_type, "size": second_size},
            "descriptor_count": descriptor_count,
            "descriptor_words": words,
            "trailing_size": total - mdl_end}


def xpr_mdl(blob: bytes) -> bytes:
    """The raw MDL payload of an XPR0 costume resource (undecoded)."""
    res = xpr_resources(blob)
    return blob[res["mdl"]["offset"]:res["mdl"]["end"]]


# --------------------------------------------------------------------- CAT

def cat_sections(blob: bytes) -> dict:
    """CAT companion header and section markers.

    The body format past the header is not decoded yet; this returns the
    verified header words and every ``LNK`` section marker offset so later
    stages have named anchors. The trailing near-EOF table is deliberately
    not parsed: its record alignment is inconsistent across costumes."""
    if len(blob) < 0x20:
        raise ValueError("CAT companion is too small")
    head = struct.unpack_from("<8I", blob, 0)
    if head[0] != 1:
        raise ValueError(f"CAT version is {head[0]}, not 1")
    markers = []
    start = 0
    while True:
        at = blob.find(LNK_MARKER, start)
        if at < 0:
            break
        markers.append(at)
        start = at + len(LNK_MARKER)
    return {"version": head[0], "header": list(head[1:]), "size": len(blob),
            "lnk_markers": markers}


# ----------------------------------------------------------------- slots

def slot_inventory(manifest: dict) -> dict:
    """Cast slot rows from a doa3_inventory manifest.

    One row per fighter family with its costume coverage; display names stay
    pending until the XBE select table is mapped (RE stage). Coverage gaps are
    listed explicitly so a cast build can report them."""
    slots = []
    for fam in manifest.get("fighter_families", []):
        complete = fam.get("complete_costumes", [])
        codes = sorted({c[:3] for c in fam.get("costumes", {})})
        slots.append({
            "nick": fam.get("nick"), "code": fam.get("code") or (codes[0] if codes else None),
            "family": fam.get("nick"), "motion_banks": fam.get("mot", []),
            "costumes": sorted(fam.get("costumes", {})), "complete_costumes": complete,
            "costume_count": len(complete), "hidden": fam.get("nick") in ("tengu", "bosnin"),
            "display_name": None,
        })
    gaps = []
    for s in slots:
        if s["display_name"] is None and s["nick"] in DISPLAY_MAPPING_PENDING:
            gaps.append({"kind": "display_name_pending",
                         "slot": s["nick"],
                         "detail": "needs the XBE select table (RE) to map to a roster fighter"})
        if not s["complete_costumes"]:
            gaps.append({"kind": "no_complete_costumes", "slot": s["nick"],
                         "detail": f"family has no complete xpr+cat costume pair "
                                   f"(costumes seen: {s['costumes']})"})
    roster = manifest.get("roster_expected") or ROSTER
    return {"game_id": manifest.get("game_id", GAME_ID),
            "title": manifest.get("title"), "slots": slots,
            "slot_count": len(slots), "costume_total": sum(s["costume_count"] for s in slots),
            "roster_expected": roster,
            "coverage_gaps": gaps,
            "display_mapping": "pending", "unlock_all": "pending"}


# ----------------------------------------------------------------- AFS writer path

def afs_patch_entry(path: str | Path, entry_index: int, new_bytes: bytes) -> int:
    """Rewrite one AFS entry in place inside its room (content at the same
    offset, zero-padded to the room; the entry table size word is updated).

    Returns the room the entry occupied. Refuses anything larger than the
    room; the archive is left untouched on failure."""
    p = Path(path)
    data = bytearray(p.read_bytes())
    table = afs_table(bytes(data), len(data))
    count = table["count"]
    if not 0 <= entry_index < count:
        raise ValueError(f"AFS entry {entry_index} outside {count} entries")
    off, size = table["offsets"][entry_index], table["sizes"][entry_index]
    if not size:
        raise ValueError(f"AFS entry {entry_index} is empty; a cast writer must replace a live slot")
    rooms = entry_rooms(table["offsets"], table["sizes"], len(data), table["name_dir"] or ())
    room = rooms[entry_index]
    if len(new_bytes) > room:
        raise ValueError(f"new payload {len(new_bytes)} bytes exceeds the entry room {room}")
    data[off:off + len(new_bytes)] = new_bytes
    if len(new_bytes) < room:
        data[off + len(new_bytes):off + room] = b"\x00" * (room - len(new_bytes))
    struct.pack_into("<I", data, 8 + 8 * entry_index + 4, len(new_bytes))
    p.write_bytes(bytes(data))
    return room


def cast_writer_status() -> dict:
    """The honest current state of the combined DOA3 cast writer."""
    return {
        "game_id": GAME_ID,
        "writer": "gbox.doa3_cast",
        "afs_patch_path": True,
        "xpr0_parser": True,
        "cat_parser": True,
        "mdl_geometry_decode": False,
        "mdl_geometry_encode": False,
        "donor_retarget": False,
        "playable": False,
        "message": "container parsing and the AFS patch path are in place; MDL geometry "
                   "decode/encode, donor retarget and the routed cast build are the next stages",
    }


def _cli_slot_report(manifest_path: str | Path) -> str:
    m = json.loads(Path(manifest_path).read_text())
    inv = slot_inventory(m)
    lines = [f"{inv['title']}: {inv['slot_count']} fighter families, "
             f"{inv['costume_total']} complete costumes"]
    for s in inv["slots"]:
        lines.append(f"  {s['nick']:10s} code={s['code'] or '-':5s} costumes={s['costume_count']}"
                     f" display={s['display_name'] or 'pending'}")
    for g in inv["coverage_gaps"]:
        lines.append(f"  GAP {g['kind']}: {g['slot']} - {g['detail']}")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - diagnostic only
    import argparse
    ap = argparse.ArgumentParser(description="DOA3 cast slot inventory report")
    ap.add_argument("manifest")
    print(_cli_slot_report(ap.parse_args().manifest))
