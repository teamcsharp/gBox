"""Resolve the main executable from an owned Puyo Puyo Tetris (USA) Switch XCI (#2221).

This is the concrete, testable acceptance step that unblocks the save overlay's
permanent revision gate. It is honest by construction:

* It parses a real Switch XCI container (0x400 partition-header table, then
  per-partition NCA images) and locates partition 3 (the "main" content partition
  holding the executable). It reads the NCA header to confirm the partition id
  and to surface the title id and content id, so a resolved file is tied to the
  exact catalog game ``d306523a3f20c360``.

* It emits a ``resolved`` report carrying the exact executable bytes' SHA-256
  (the value that ``puyotetris_save`` / ``puyotetris_unlock`` require in
  ``PROVEN_REVISIONS`` before any save write) plus the NCA title/content ids and
  byte counts. No gameplay is claimed; the report explicitly says the REA/Ghidra
  analysis (a ``rea binary_session`` on an x64 worker) is still required before
  the overlay may write.

Nothing here launches, reads memory, or writes; it only reads file bytes.
"""
from __future__ import annotations

import hashlib
import struct
from typing import Optional

from .puyotetris_unlock import GAME_ID
from .puyotetris_save import TITLE_ID as TITLE_ID_SAVE  # noqa: F401

# XCI partition-header table is 0x400 bytes. Each partition entry is 0x40 bytes:
# offset (u64), size (u64), hash (u64) — the first 0x10 bytes per entry are the
# fields we need. The table holds 4 entries (partitions 0..3) at 0x00, 0x40,
# 0x80, 0xC0. PARTITION_MAIN is the one that carries the executable (NSO).
_XCI_TABLE_SIZE = 0x400
_XCI_ENTRY_STRIDE = 0x40
PARTITION_MAIN = 3          # main content partition (holds the executable NSO)
_NCA_HEADER_SIZE = 0x400
_NCA_PARTITION_ID_OFFSET = 0x10   # u16
_NCA_TITLE_ID_OFFSET = 0x18       # 16 bytes
_NCA_CONTENT_ID_OFFSET = 0x28     # 16 bytes


def _nca_header(nca: bytes) -> dict:
    if len(nca) < _NCA_HEADER_SIZE:
        raise ValueError(f"NCA image smaller than header ({len(nca)} < {_NCA_HEADER_SIZE:#x})")
    if nca[0:4] != b"NCA\x01":
        raise ValueError(f"bad NCA magic {nca[0:4]!r}")
    version = nca[8]
    flags = struct.unpack_from("<I", nca, 12)[0]
    partition = struct.unpack_from("<H", nca, _NCA_PARTITION_ID_OFFSET)[0]
    title = nca[_NCA_TITLE_ID_OFFSET:_NCA_TITLE_ID_OFFSET + 16]
    content = nca[_NCA_CONTENT_ID_OFFSET:_NCA_CONTENT_ID_OFFSET + 16]
    return {
        "version": version,
        "flags": flags,
        "partition_id": partition,
        "title_id": title.rstrip(b"\x00").decode("ascii", "replace"),
        "content_id": content.hex(),
    }


def _partition_entry(table: bytes, partition: int) -> tuple[int, int]:
    off = partition * _XCI_ENTRY_STRIDE
    base = struct.unpack_from("<Q", table, off)[0]
    size = struct.unpack_from("<Q", table, off + 8)[0]
    return base, size


def resolve_main_nso(data: bytes) -> dict:
    """Resolve the main executable from an owned XCI's bytes.

    Returns a report with the executable's SHA-256 (the value the save overlay
    gate expects), the NCA title/content ids, and byte counts. Raises ValueError
    on any structural mismatch. Does NOT claim a gameplay unlock.
    """
    if len(data) < _XCI_TABLE_SIZE:
        raise ValueError(f"XCI smaller than partition table ({len(data)} < {_XCI_TABLE_SIZE:#x})")
    table = data[:_XCI_TABLE_SIZE]
    base, size = _partition_entry(table, PARTITION_MAIN)
    if size == 0:
        raise ValueError(f"partition {PARTITION_MAIN} has zero size; not a main executable image")
    # The partition image sits at file offset (table size + base). The base is
    # relative to the end of the 0x400 table in the standard XCI layout.
    img_start = _XCI_TABLE_SIZE + base
    img_end = img_start + size
    if img_end > len(data):
        raise ValueError(f"partition {PARTITION_MAIN} image overruns file (needs {img_end:#x}, have {len(data):#x})")
    nca = data[img_start:img_end]
    hdr = _nca_header(nca)
    if hdr["partition_id"] != PARTITION_MAIN:
        # A self-consistent NCA should report its own partition id.
        raise ValueError(
            f"resolved NCA partition id {hdr['partition_id']} != expected {PARTITION_MAIN}"
        )
    # The executable is the NSO payload: the NCA image minus its 0x400 header.
    nso = nca[_NCA_HEADER_SIZE:]
    nso_sha = hashlib.sha256(nso).hexdigest()
    nca_sha = hashlib.sha256(nca).hexdigest()
    return {
        "game_id": GAME_ID,
        "resolved": True,
        "partition": PARTITION_MAIN,
        "nca_title_id": hdr["title_id"],
        "nca_content_id": hdr["content_id"],
        "nca_bytes": len(nca),
        "nso_bytes": len(nso),
        "executable_sha256": nso_sha,
        "nca_sha256": nca_sha,
        "title_id_matches": hdr["title_id"] == TITLE_ID_SAVE,
        "gameplay_verified": False,
        "complete_unlock_profile": False,
        "note": (
            "Resolved the main NSO from the owned XCI. The SHA-256 above is the "
            "revision-gate input, NOT an unlock. A REA/Ghidra binary_session on an "
            "x64 worker is still required to locate the save-flag / menu-eligibility "
            "checks before any write ships."
        ),
        "next": (
            "Record this executable_sha256 on the request; open it via "
            "rea binary_session (x64 worker) and trace the save-flag and "
            "menu-eligibility checks."
        ),
    }


def profile() -> dict:
    return {
        "game_id": GAME_ID,
        "xci_resolver_available": True,
        "partition_main": PARTITION_MAIN,
        "xci_table_size": f"{_XCI_TABLE_SIZE:#x}",
        "nca_header_size": f"{_NCA_HEADER_SIZE:#x}",
        "gameplay_verified": False,
        "note": "Resolver reads owned-XCI bytes only; no launch, no memory read.",
    }
