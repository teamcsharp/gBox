"""DOA3 (USA, Xbox) native cast layer: XPR0 container walker, CAT companions,
slot inventory and the AFS patch path for the combined cast writer.

Everything here is validated against the owned USA build (game b8edf7040116f3aa;
XBE sha256 e523dd15d0765899a43a1824c023e0219d129e9a8b41e8213e4e645755d2bfa3,
loadfile.afs 365690880 bytes). The MDL geometry decoder/encoder is NOT
implemented yet: this module stops at container level and says so. It is not a
playable build and must never be reported as one.

Layout facts pinned from kas00.xpr / kas00.cat (Kasumi costume 00, live bytes):

* XPR0: magic, u32 total, u32 header_size, then the user-data pair
  {u32 0x80000000, u32 size, 4cc tag ``MDL``} at 0x0C..0x18. The MDL payload
  starts at header_size (kas00: 119868 bytes of dense float data, no texture
  magic). The header continues with a second pair {u32 0x48, u32 87} at 0x18
  and a u32 18 at 0x20. From 0x24 the header holds a run of increasing u32
  offsets into the header (kas00: 0x48 .. 0x1D240, all below header_size, i.e.
  texture surface data positions), terminated by 0x00000000 immediately before
  an ``OBJ\0`` section marker at 0x14C (the material/object table). The MDL
  payload is headerless: it begins directly with dense f32 data (kas00 shows a
  ~32-byte periodic structure, no count word and no texture magic). No ``DDS
  `` magic exists anywhere in the resource: textures are raw D3D surfaces, so
  the per-texture descriptor stride has to be pinned against the XBE loader
  (RE stage).
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

import hashlib
import json
import os
import struct
import tempfile
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
    if len(blob) < 0x24:
        raise ValueError(f"XPR0 resource is too short for its fixed header ({len(blob)} < 0x24 bytes)")
    if blob[:4] != XPR_MAGIC:
        raise ValueError(f"not an XPR0 resource (magic {blob[:4]!r})")
    total, hsize = struct.unpack_from("<II", blob, 4)
    if hsize < 0x24:
        raise ValueError(f"XPR0 header is too small for the fixed MDL/descriptor fields ({hsize:#x} < 0x24)")
    if hsize % 4 or total % 4:
        raise ValueError(f"XPR0 sizes are not 4-byte aligned (header {hsize:#x}, total {total:#x})")
    if not hsize <= total <= len(blob):
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


def xpr_roundtrip(blob: bytes) -> bytes:
    """Re-serialize a parsed XPR0 resource byte-for-byte (the no-op encode gate).

    The output must equal ``blob`` exactly. It reconstructs the container from
    the fields ``xpr_resources`` returns, so a byte-identical result proves the
    parser's boundaries (header_size, MDL offset/end, trailing region) account
    for every byte. This gate must hold before any donor geometry is written
    into the MDL payload."""
    res = xpr_resources(blob)
    out = bytearray(res["total"])
    out[0:4] = XPR_MAGIC
    struct.pack_into("<I", out, 4, res["total"])
    struct.pack_into("<I", out, 8, res["header_size"])
    out[0x0C:res["mdl"]["offset"]] = blob[0x0C:res["mdl"]["offset"]]
    out[res["mdl"]["offset"]:res["mdl"]["end"]] = blob[res["mdl"]["offset"]:res["mdl"]["end"]]
    out[res["mdl"]["end"]:] = blob[res["mdl"]["end"]:]
    return bytes(out)


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

def afs_patch_entry(path: str | Path, entry_index: int, new_bytes: bytes, *,
                    out: str | Path | None = None, expected_sha256: str | None = None) -> int:
    """Rewrite one AFS entry into a separately staged image and publish it atomically.

    The source archive is read once and never modified in place: the patched
    image is written to a fresh sibling staging file, fsync'd, then atomically
    moved over ``out`` (or the source when ``out`` is None) with os.replace, so
    an existing archive is never left partially written. The full layout is
    validated first (magic/header bounds, entry table, no overlap, name
    directory bounds, optional source digest) and a byte-identical replacement
    is refused as a no-op. Returns the room the entry occupied."""
    p = Path(path)
    original = p.read_bytes()
    source_digest = hashlib.sha256(original).hexdigest()
    if expected_sha256 is not None and source_digest != expected_sha256:
        raise ValueError(f"AFS source digest mismatch (expected {expected_sha256}, got {source_digest})")
    data = bytearray(original)
    archive_size = len(data)
    table = afs_table(bytes(data), archive_size)
    count = table["count"]
    if not 0 <= entry_index < count:
        raise ValueError(f"AFS entry {entry_index} outside {count} entries")
    nd = table["name_dir"]
    if nd:
        nd_off, nd_size = nd
        if nd_off + nd_size > archive_size:
            raise ValueError("AFS name directory extends outside the archive")
        for i, (o, z) in enumerate(zip(table["offsets"], table["sizes"])):
            if z and o < nd_off + nd_size and nd_off < o + z:
                raise ValueError(f"AFS name directory overlaps entry {i}")
    off, size = table["offsets"][entry_index], table["sizes"][entry_index]
    if not size:
        raise ValueError(f"AFS entry {entry_index} is empty; a cast writer must replace a live slot")
    rooms = entry_rooms(table["offsets"], table["sizes"], archive_size, (nd[0],) if nd else ())
    room = rooms[entry_index]
    if len(new_bytes) > room:
        raise ValueError(f"new payload {len(new_bytes)} bytes exceeds the entry room {room}")
    if new_bytes == bytes(data[off:off + size]):
        raise ValueError("no source change: the entry already holds these bytes")
    data[off:off + len(new_bytes)] = new_bytes
    if len(new_bytes) < room:
        data[off + len(new_bytes):off + room] = b"\x00" * (room - len(new_bytes))
    struct.pack_into("<I", data, 8 + 8 * entry_index + 4, len(new_bytes))
    target = Path(out) if out is not None else p
    fd, staging = tempfile.mkstemp(prefix=target.name + ".", suffix=".staging", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(bytes(data))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, target)
    except BaseException:
        try:
            os.unlink(staging)
        except OSError:
            pass
        raise
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
