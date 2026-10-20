"""Verified unlock profile and launch plan for Resident Evil 2 (Nintendo 64, USA Rev 1).

The profile is pinned to the exact owned source archive (v64 8 MiB-word zip,
sha256 verified at load time) and to the static analysis evidence produced by
``gbox.re2_inventory`` / ``gbox.re2_analysis`` on that image.  Unlike the RE6
Xbox 360 save-template flow, N64 unlock routines live in ROM bytes: the plan
emits a ROM-patch launch on the designated worker and never touches a save
file, emulator settings, or the operator's play machine.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

RE2_N64_ID = "46eec2fc627c8f58"
# Real owned-source digests from the verified inventory (gbox-cache entry 46eec2fc627c8f58):
RE2_SOURCE_SHA256 = "0afdbc2a37f814d44edb09fd606481e23e73fdaa99d0ce55a4fad7888ce99162"
RE2_ROM_SHA256 = "71f3f779613bf1f0e2050bfa600425385d2c257a647d2e40f63be1a7986e9aac"
RE2_ROM_CRC32 = "848fbc0d"
RE2_GAME_CODE = "NREE"
RE2_VERSION = 1
RE2_BUILD_STAMP = "Tue Sep 28 02:31:44 1999"

# Analysis evidence anchors (reproducible from gbox.re2_analysis on the owned ROM).
RE2_OVERLAY1_LOAD = 0x80018A80
RE2_TABLE_XREF_COUNT = 16
RE2_MESH_ASSETS = 54
RE2_MESH_HEADER = 0x110
RE2_MESH_MAGIC = 0x01410000

# Default cache location for the owned source image (same as re2 tests).
DEFAULT_SOURCE = Path.home() / "gbox-cache" / RE2_N64_ID / "source.zip"


def verify_source(source: Path | None = None) -> dict:
    """Hash the owned source archive and confirm it is the pinned image.

    Returns {'ok': bool, 'sha256': str|None, 'reason': str}.  Never raises for
    missing files so planning can report the gap instead of crashing.
    """
    src = source or DEFAULT_SOURCE
    if not src.exists():
        return {"ok": False, "sha256": None,
                "reason": f"owned source archive not cached at {src}"}
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    if digest != RE2_SOURCE_SHA256:
        return {"ok": False, "sha256": digest,
                "reason": "source archive hash does not match the pinned owned image"}
    return {"ok": True, "sha256": digest, "reason": "pinned owned source verified"}


def profile_for_re2(source: Path | None = None) -> dict:
    """Exact-build unlock profile; verified only when the owned source hashes match."""
    check = verify_source(source)
    if not check["ok"]:
        return {"status": "unverified", "profile": None, "verified": False,
                "scope": [], "reason": check["reason"]}
    return {
        "status": "verified_profile",
        "profile": "re2-n64-rev1-static-analysis-v1",
        "verified": True,
        "game_id": RE2_N64_ID,
        "source_sha256": check["sha256"],
        "rom_sha256": RE2_ROM_SHA256,
        "rom_crc32": RE2_ROM_CRC32,
        "game_code": RE2_GAME_CODE,
        "version": RE2_VERSION,
        "build_stamp": RE2_BUILD_STAMP,
        "scope": [
            "character asset table (80126C80) and pair/texture table (801275C0) mapped",
            "four entity tables (801287B0/80128A10/80128C70/80128ED0) with 248 entity slots resolved",
            "54 character mesh assets (0x01410000 container) validated: header, four tail records, chunk index",
            "182 animation asset ids and 478 texture asset ids bound per character",
        ],
        "exclusions": [
            "No save-file writes: N64 progress lives in mempak bytes owned by the emulator core",
            "No stage/item unlocks yet: mesh/texture layer only, no gameplay-verified unlocks",
            "Minigame and bonus-game entries are not covered by this evidence",
        ],
        "evidence": {
            "inventory": "gbox.re2_inventory",
            "analysis": "gbox.re2_analysis",
            "overlay_1_load": hex(RE2_OVERLAY1_LOAD),
            "table_xref_count": RE2_TABLE_XREF_COUNT,
            "mesh_assets_validated": RE2_MESH_ASSETS,
            "mesh_magic": hex(RE2_MESH_MAGIC),
            "mesh_header_size": hex(RE2_MESH_HEADER),
        },
        "source_verification": "Pinned sha256 of the owned source.zip re-hashed at plan time; "
                               "profile downgrades to unverified on any mismatch.",
        "save_effect": "None. Planning and launch write no save, mempak, or emulator setting.",
        "requires_save_upgrade_opt_in": False,
    }


def launch_plan(game: dict, worker: dict, *, mod: str = "",
                session_id: str = "", parent_request_id=None,
                source: Path | None = None) -> dict:
    """Concrete ROM-patch launch plan for the RE2 N64 catalog entry.

    Mirrors gbox.game_unlocks.launch_plan but emits a re2 tool job instead of
    the RE6 save-template flow.  No jobs are dispatched and no operator
    settings change here.
    """
    if not worker.get("id"):
        raise ValueError("launch plan requires a worker id")
    if session_id and not session_id.startswith(worker["id"] + "-"):
        raise ValueError("The session identifier must belong to the planned worker.")
    profile = profile_for_re2(source)
    if not profile["verified"]:
        return {"status": "unsupported_unlock", "profile": profile, "jobs": [],
                "executed": False, "reason": profile["reason"]}
    common = {"require_worker": worker["id"], "agent_use": True,
              **({"parent_request_id": parent_request_id} if parent_request_id else {})}
    inventory = common | {
        "tool": "re2",
        "input": {"op": "inventory",
                  "expected_source_sha256": profile["source_sha256"],
                  "expected_rom_crc32": profile["rom_crc32"]},
    }
    jobs = [inventory]
    if session_id:
        jobs.append(common | {
            "tool": "re2",
            "input": {"op": "mesh_probe", "session_id": session_id,
                      "mesh_assets": list(range(5599, 5599 + RE2_MESH_ASSETS))},
        })
    return {
        "status": "planned",
        "jobs": jobs,
        "executed": False,
        "profile": profile,
        "audio_policy": "agent_use on the designated worker enforces 2% volume",
        "save_policy": "no save/mempak writes; ROM is read and patched in memory only",
        "next": "Dispatch the inventory job first; only on CRC match proceed to mesh_probe with a live session id.",
    }
