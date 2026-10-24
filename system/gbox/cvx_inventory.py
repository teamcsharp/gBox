"""Resident Evil - Code - Veronica X (USA) (Disc 2) (GameCube) - owned-build native inventory.

Owned source (authoritative):
    /mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/
    Resident Evil - Code - Veronica X (USA) (Disc 2).gcz

Verified disc identity (read from the disc header, not the catalog label):
    game code GCDE08, header title "RESIDENT EVIL CVX", 48 FST members.

The build is CRI Middleware: 8 CRI "AFS\\0" archives, 12 .sfd movie streams, 14 .ald audio
banks, 9 .gvr texture banks, plus one .vsd, .idx, .bnr and two card files. The AFS layout
("AFS\\0", uint32 count, then count interleaved (uint32 offset, uint32 size) pairs) is the
standard CRI layout that ``gbox.jgr.afs_entries`` already parses, so this module reuses that
parser instead of adding a second one. ``gbox.formats.lz`` covers the CRI ADX/LZ members
inside those archives.

This module owns the *counted* inventory only: member names, sizes, and the real entry count
of every AFS container read from its own header. Filename-derived guesses (what an ".ald" or
"mry.afs" actually contains) are explicitly NOT asserted here - the AFS member names and
their payloads are the next stage.
"""
from __future__ import annotations

import collections
import json
import struct
from pathlib import Path

from .jgr import afs_entries  # CRI AFS table parser (reused, not re-implemented)

AFS_MAGICS = (b"AFS\x00", b"AFS\x20")
GAME_ID = "dc385be64d1a900b"
TITLE = "Resident Evil - Code - Veronica X (USA) (Disc 2) (GameCube)"
DISC_GAME_CODE = "GCDE08"
DISC_HEADER_TITLE = "RESIDENT EVIL CVX"
SOURCE_PATH = (
    '/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/'
    'Resident Evil - Code - Veronica X (USA) (Disc 2).gcz'
)

# member suffix -> counted role (role names describe the container class only)
ROLE_BY_SUFFIX = {
    ".afs": "afs_container",
    ".sfd": "sfd_movie_stream",
    ".ald": "ald_audio_bank",
    ".gvr": "gvr_texture_bank",
    ".vsd": "vsd_video_bank",
    ".idx": "index_table",
    ".bnr": "banner",
    ".gbn": "card_banner",
    ".gic": "card_icon",
}


def classify_member(name: str) -> str:
    """Counted container class for a disc member name (by suffix, no content claims)."""
    return ROLE_BY_SUFFIX.get(Path(name).suffix.lower(), "other")


def read_at(disc, offset: int, size: int) -> bytes:
    """Read `size` bytes at `offset` from a gbox.gcdisc.GCDisc (ISO or in-place .gcz)."""
    return disc._r(offset, size)


def afs_entry_count(disc, name: str) -> int:
    """Real entry count of a CRI AFS container, read from that archive's own header.

    Raises ValueError when the member is not a CRI AFS archive.
    """
    offset, size = disc.files[name]
    head = read_at(disc, offset, 8)
    if head[:4] not in AFS_MAGICS:
        raise ValueError(f"{name} is not a CRI AFS archive (magic {head[:4]!r})")
    count = struct.unpack_from("<I", head, 4)[0]
    need = 8 + 8 * count
    if need > size:
        raise ValueError(f"{name} AFS header claims {count} entries but the member is {size} bytes")
    table = read_at(disc, offset, need)
    # Multspq2.afs uses the "AFS " (0x20) magic variant; table layout is identical.
    got, _offs, _sizes = afs_entries(b"AFS\x00" + table[4:])
    if got != count:
        raise ValueError(f"{name} AFS header count {count} != parsed {got}")
    return count


def build_manifest(disc, source_path: str = SOURCE_PATH, source_sha256: str = "") -> dict:
    """Counted inventory of the owned CVX disc 2 build."""
    members = []
    for name, (offset, size) in sorted(disc.files.items()):
        members.append({"name": name, "offset": offset, "size": size,
                        "role": classify_member(name)})
    role_counts = collections.Counter(m["role"] for m in members)
    afs_counts = {}
    for m in members:
        if m["role"] == "afs_container":
            afs_counts[m["name"]] = afs_entry_count(disc, m["name"])
    return {
        "game_id": GAME_ID,
        "title": TITLE,
        "source_path": source_path,
        "source_sha256": source_sha256,
        "disc_game_code": DISC_GAME_CODE,
        "disc_header_title": DISC_HEADER_TITLE,
        "member_count": len(members),
        "role_counts": dict(role_counts.most_common()),
        "afs_entry_counts": afs_counts,
        "afs_total_entries": sum(afs_counts.values()),
        "members": members,
    }


def save_manifest(manifest: dict, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return path


def load_manifest(path) -> dict:
    return json.loads(Path(path).read_text())
