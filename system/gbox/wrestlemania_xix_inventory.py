"""WWE WrestleMania XIX (GameCube) - owned-revision inventory and unlock-surface gate.

Revision characterised (verified against the owned ISO, read-only):
  ISO        /home/ehm_eckx/modbase/WWE_WrestleMania_XIX_USA.nkit.iso
  iso sha256 325a041a1c3cdabce322d90a0b0b7b405050568bc2357707e6bb13c31fdb2fa3
  main.dol   sha256 627b899760d0b820c049ad29f96a613da1c43d35dd4a1456e581cc620bae9fb7
  game code  GW9E78, 4222 files in the image.

This module never writes to the game, the ISO, a save or the memory card.  It
records what the owned revision actually contains and refuses to claim a
verified unlock surface.
"""

from __future__ import annotations

import hashlib
import re
import struct

GAME_ID = "0afbb206f442bb11"
PLATFORM = "gamecube"
GAME_CODE = "GW9E78"
GAME_TITLE = "WWE WrestleMania XIX (USA)"
ISO_PATH = "/home/ehm_eckx/modbase/WWE_WrestleMania_XIX_USA.nkit.iso"
ISO_SHA256 = "325a041a1c3cdabce322d90a0b0b7b405050568bc2357707e6bb13c31fdb2fa3"
DOL_SHA256 = "627b899760d0b820c049ad29f96a613da1c43d35dd4a1456e581cc620bae9fb7"

# Category prefixes actually present in com_dt.mpc of this ISO (25 groups,
# 116 records).  Names are the real record names, e.g. "char", "rule", "tbl".
CATEGORIES = ["al", "bg", "char", "cmn", "cmot", "cnt", "com", "comb", "cs", "fa",
              "ha", "mb", "pa", "pl", "r", "root", "rr", "rule", "rw", "sd", "sl",
              "sm", "ss", "tbl", "x"]

LOCK_SURFACE = {
    "located": False,
    "candidate_containers": ["com_dt.mpc", "static.mpc"],
    "candidate_entries": ["char", "rule", "rw", "ss"],
    "reason": ("main.dol carries no ASCII unlock/roster flag string and the ISO image "
               "holds no unlock/save-named file, so for the AKI engine the lock state is "
               "expected to live in the memory-card save, not in the shipped containers."),
}


def parse_container(blob):
    """Parse an AKI .mpc container (verified on com_dt.mpc of this ISO).

    Header: 4 big-endian u32 words (0x57c, 0xb7c60, 0x20, 0x5a0).  Records are
    12 bytes starting at 0x24: name[4], w1(u32), w2(u32).  When the top byte of
    w2 is 0xFF the record is a file: w1 is the data offset, w2 & 0xFFFFFF the
    size.  Other records are directory/index nodes (w1/w2 kept raw).  A record
    with w2 == 0 terminates the table.
    """
    header = list(struct.unpack_from(">4I", blob, 0))
    start = 0x24
    entries = []
    off = start
    while off + 12 <= len(blob):
        name = blob[off:off + 4].decode("ascii", "replace").rstrip("\x00")
        w1, w2 = struct.unpack_from(">II", blob, off + 4)
        if w2 == 0:
            break
        if w2 >> 24 == 0xFF:
            entries.append({"name": name, "kind": "file", "size": w2 & 0xFFFFFF,
                            "offset": w1})
        else:
            entries.append({"name": name, "kind": "dir", "w1": w1, "w2": w2})
        off += 12
    return {"header": header, "table_start": start, "record_count": len(entries),
            "entries": entries}


def category_of(name):
    m = re.match(r"^[A-Za-z]+", name)
    return m.group(0) if m else name


def _disc(iso_path):
    try:
        from .gcdisc import GCDisc
    except ImportError:  # loaded outside the gbox package
        from gbox.gcdisc import GCDisc
    return GCDisc(iso_path)


def inventory(iso_path=ISO_PATH):
    """Read-only inventory of the owned revision."""
    disc = _disc(iso_path)
    com = parse_container(disc.read("com_dt.mpc"))
    cats = {}
    for e in com["entries"]:
        cats.setdefault(category_of(e["name"]), []).append(e["name"])
    return {"game_id": GAME_ID, "platform": PLATFORM, "game_code": disc.game_id,
            "iso_path": iso_path, "iso_sha256": ISO_SHA256, "dol_sha256": DOL_SHA256,
            "com_dt_mpc": com,
            "categories": {k: sorted(v) for k, v in sorted(cats.items())},
            "lock_surface": LOCK_SURFACE}


def profile_gate():
    """Honest gate: inventory only, no writer is reachable from the Play path."""
    return {"verified": False, "writer": None,
            "reason": ("WrestleMania XIX lock state is not located for the owned revision; "
                       "only the container/category inventory is proven."),
            "lock_surface": LOCK_SURFACE,
            "next_step": ("Locate the AKI save-struct unlock bitfield (Ghidra on main.dol, "
                          "save/load record writer) and identify which com_dt.mpc tables "
                          "drive the on-load roster/feature gates."),
            "artifact": "artifacts/wrestlemania_xix_gc_inventory.json"}
