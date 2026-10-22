"""Tetris Axis (USA) - Nintendo 3DS unlock research profile (gbox request #2267).

MILESTONE: static evidence only. The owned build was resolved and hashed, the
decompressed EXEFS code segment was mined for the save-data key schema, and
the RomFS content was inventoried by category. NO unlock write target has been
proven yet, so every lock state is reported as ``unknown`` and the Play path
can never apply a guessed write.

The release manager (gbox.game_unlocks) registers this profile for the exact
catalog entry (game_id + platform) so the fast launch path answers with the
evidence and the next step instead of guessing.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

GAME_ID = "d6d1a0582e4c3b0b"
TITLE = "Tetris Axis (USA)"
PLATFORM = "3ds"
GAME_CODE = "ATLE"          # CTR-P-ATLE
REGION = "USA"
ROM_SHA256 = "d47d0bd35cd210567574a302623bb96f6ec40dc8d644f4548dbbed173575dd01"
CODE_SHA256 = "7479e308e142a75139e51379bd3fcf41822a1278f43f58a92de813150007cb66"
ROM_SIZE = 177206272
CODE_SIZE = 3608576
CODE_BASE = 0x100000        # code.bin is the decompressed EXEFS code segment
CACHE_DIR = "/home/ehm_eckx/gBox_alt/gbox-cache/3ds/d6d1a0582e4c3b0b"
INVENTORY_DIR = CACHE_DIR + "/inventory"
ROM_NAME = "Tetris Axis (USA).3ds"

CATEGORIES = ("characters", "hidden_characters", "modes", "levels", "stages",
              "costumes", "items", "extras")

# Lock-state vocabulary for every inventory row.
LOCK_STATES = ("unlocked", "not_present", "unknown")

# --- static evidence: save-data key names in the decompressed code segment ---
# (file offset in code.bin, literal text, role)
SAVE_KEY_STRINGS = (
    (0x131460, "flag_%02d", "per-index progress flag key (level/stage clear)"),
    (0x131440, "Group_00", "group name key"),
    (0x13c104, "Group_01", "group name key"),
    (0x13c110, "Group_flag", "group flag key"),
    (0x13c11c, "Group_ok", "group completion key"),
    (0x13c128, "TextBox_%02d", "menu textbox key"),
    (0x13c138, "Null_%02d_%02d", "layout placeholder key"),
    (0x097c7c, "Group_off", "group disabled-state key"),
    (0x0a63c8, "Group_icon", "group icon key"),
    (0x0dea0c, "Group_Text", "group display-text key"),
    (0x0def38, "Null_rank", "rank row key"),
    (0x0dd36c, "Null_rec", "record row key"),
    (0x123f18, "Text_stage_00", "stage caption key"),
    (0x123ee8, "Text_stage_s", "stage caption key"),
    (0x0b49e4, "Text_noitems", "empty/placeholder key"),
    (0x0ec188, "STAGE %02d", "stage caption format string"),
)

# 3DS save-service strings: the title keeps progress in its own 3DS save
# container (ExSave = extended save), not inside the ROM.
SAVE_SERVICE_STRINGS = (
    (0x2b4311, "_FsSaveFunc"),
    (0x2b4364, "ExSave: Del-miss"),
    (0x2b4378, "ExSave: Cre-miss"),
    (0x2b438c, "ExSave: Mount-miss"),
)

EXTRA_PATHS = {
    "/tutorial/layTutorial.arc", "/tutorial/layShadowEdit.arc",
    "/staff/staff.arc", "/telop/telop.arc", "/now_loading/now_loading.arc",
    "/co02/layESRB.arc", "/co02/layLicence.arc", "/tetris3DS_font.bcfnt",
    "/HuLogo.bcres", "/HuLogoUS.bcres", "/simple.bcsar", "/stream/stream.arc",
}


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rom_path() -> Path:
    return Path(CACHE_DIR) / ROM_NAME


def code_path() -> Path:
    return Path(INVENTORY_DIR) / "code.bin"


def rom_guard(path=None) -> dict:
    """Bind the profile to the owned revision; refuse anything else."""
    p = Path(path) if path else rom_path()
    try:
        digest = _sha256(p)
    except OSError as exc:
        return {"ok": False, "expected": ROM_SHA256, "actual": None,
                "error": str(exc)[:200], "path": str(p)}
    return {"ok": digest == ROM_SHA256, "expected": ROM_SHA256,
            "actual": digest, "path": str(p)}


def _romfs_files():
    try:
        return json.loads((Path(INVENTORY_DIR) / "romfs_files.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _row(category, name, evidence, lock_state="unknown", source="romfs"):
    return {"category": category, "name": name, "evidence": evidence,
            "lock_state": lock_state, "presence": "present_in_owned_rom",
            "source": source}


def inventory() -> dict:
    """Complete per-category content inventory of the owned build.

    Presence is proven (the asset ships in the owned ROM); the *lock* state is
    not, because no lock check has been traced yet - hence ``unknown``.
    """
    files = _romfs_files()
    entries = []
    notes = []
    if not files:
        notes.append("RomFS listing unavailable in this environment; inventory is empty")
        return {"categories": list(CATEGORIES), "entries": entries, "notes": notes,
                "romfs_file_count": 0}

    by_dir = {}
    for f in files:
        by_dir.setdefault(f["path"].strip("/").split("/")[0], []).append(f)

    # stages: one row per stage pack directory (sp00..sp17)
    for d in sorted(k for k in by_dir if re.match(r"^sp\d+$", k)):
        group = by_dir[d]
        entries.append(_row("stages", d,
                            "romfs:/%s (%d files, %d bytes)" % (
                                d, len(group), sum(int(x.get("size", 0)) for x in group))))

    for f in files:
        p = f["path"]
        name = p.rsplit("/", 1)[-1]
        size = int(f.get("size", 0))
        if p.startswith("/co04/NW/") and name.startswith("co04_ch_"):
            entries.append(_row("characters", name[:-6],
                                "romfs:%s (%d bytes)" % (p, size)))
        elif p.startswith("/co04/NW/") and name.startswith("mii_"):
            entries.append(_row("costumes", name[:-6],
                                "romfs:%s (%d bytes)" % (p, size)))
        elif "item" in name.lower():
            entries.append(_row("items", name[:-4],
                                "romfs:%s (%d bytes)" % (p, size)))
        elif p in EXTRA_PATHS or name in {
                "tetris3DS_font.bcfnt", "HuLogo.bcres", "HuLogoUS.bcres",
                "simple.bcsar", "HuErrUS.csv", "HuErrUS.txt"}:
            entries.append(_row("extras", name.rsplit(".", 1)[0],
                                "romfs:%s (%d bytes)" % (p, size)))
        elif name.startswith("lay") and name.endswith(".arc"):
            entries.append(_row("modes", name[:-4],
                                "romfs:%s (%d bytes)" % (p, size)))

    notes.append("levels: not separately identified - the sp00..sp17 packs may "
                 "themselves be level groups; needs the lock-check trace")
    notes.append("hidden_characters: no asset set separate from /co04/NW was "
                 "found; the title ships Mii customization instead - lock state "
                 "unknown until the menu-eligibility check is traced")
    notes.append("items: item_%02d format strings exist in code "
                 "(0x0a3d64, 0x0f7994) but the per-item ids are unresolved")
    notes.append("modes: derived from mode-specific lay*.arc UI layouts; the "
                 "menu code that gates them is not yet traced")
    return {"categories": list(CATEGORIES), "entries": entries, "notes": notes,
            "romfs_file_count": len(files)}


def unlock_ops() -> list:
    """No write target is proven yet - deliberately empty.

    Any future writer must first resolve the save-container layout, the
    per-index flag key table and the unlock threshold values, and must pass
    rom_guard before touching a save.
    """
    return []


def write_targets() -> list:
    return []


def verification_plan(session_id: str) -> dict:
    """Bounded live-acceptance steps; read-back is mandatory."""
    return {
        "game_id": GAME_ID, "session_id": session_id,
        "steps": [
            "1. rom_guard(rom) must report ok before anything else",
            "2. locate the title's 3DS save container on the worker and back it up",
            "3. dump the save and map flag_%02d / Group_ok / Group_flag keys",
            "4. write only the proven fields, then read the save back byte-identical",
            "5. fresh boot, select and play each inventoried character and mode",
            "6. second launch confirms persistence, then rollback to the backup",
        ],
        "read_back_required": True,
        "rollback": "Restore the step-2 save backup; never mutate the owned ROM.",
        "audio_policy": "2% volume on the agent session; never JAYBUILTFINALE",
    }


def live_acceptance_plan(session_id: str) -> dict:
    return {
        "game_id": GAME_ID, "session_id": session_id,
        "preconditions": ["rom_guard ok", "save backup taken",
                          "list_workers/list_sessions for a live authorized agent session"],
        "jobs": [], "rollback_jobs": [],
        "success_criterion": "every inventoried character and mode is selectable "
                              "and playable after a fresh boot, confirmed by "
                              "read-back plus in-game selection",
        "executed": False,
    }


def profile_gate() -> dict:
    """Compact gate for gbox.game_unlocks (no write path is reachable)."""
    return {
        "reason": "Tetris Axis (USA) unlock profile is static-evidence only: the "
                  "owned build is hashed and the content inventory plus the "
                  "save-key schema are mapped, but no lock check and no save "
                  "field have been proven, so nothing may be written yet.",
        "evidence": {
            "rom_sha256": ROM_SHA256, "code_sha256": CODE_SHA256,
            "gamecode": GAME_CODE, "region": REGION,
            "save_key_strings": [s for _o, s, _r in SAVE_KEY_STRINGS],
            "save_service_strings": [s for _o, s in SAVE_SERVICE_STRINGS],
        },
        "blockers": [
            "lock-check function not yet located (no xref into flag_%02d / Group_ok)",
            "3DS save container layout and field offsets unresolved",
            "per-mode and per-character eligibility thresholds unknown",
            "no runtime (live) verification yet",
        ],
        "next": "Open code.bin in Ghidra (ARM:LE:32:default) on an x64 worker "
                "(i9-NUC, not JAYBUILTFINALE) with job_ghidra_bridge, xref "
                "flag_%02d and Group_ok, dump the title's 3DS save from the "
                "Spark test worker, then map the flag table and threshold "
                "values before any writer is written.",
    }


def profile() -> dict:
    inv = inventory()
    gate = profile_gate()
    return {
        "game_id": GAME_ID, "title": TITLE, "platform": PLATFORM,
        "gamecode": GAME_CODE, "region": REGION,
        "rom_sha256": ROM_SHA256, "code_sha256": CODE_SHA256,
        "rom_size": ROM_SIZE, "code_size": CODE_SIZE,
        "rom_guard": rom_guard(),
        "scope": list(CATEGORIES),
        "inventory": inv,
        "save_key_strings": [{"offset": o, "vaddr": o + CODE_BASE, "text": s, "role": r}
                              for o, s, r in SAVE_KEY_STRINGS],
        "save_service_strings": [{"offset": o, "vaddr": o + CODE_BASE, "text": s}
                                 for o, s in SAVE_SERVICE_STRINGS],
        "unlock_ops": unlock_ops(),
        "verified": [],
        "gameplay_verified": False,
        "complete_unlock_profile": False,
        "state": "static_evidence_only",
        "reason": gate["reason"],
        "known_gap": "Static inventory of the owned build is complete by "
                     "category, but every lock state is unknown: no lock check, "
                     "no save-field offset and no runtime acceptance yet.",
        "blockers": gate["blockers"],
        "next": gate["next"],
        "requires_live_readback": True,
    }


def pre_launch(ctx, mod: str = "") -> dict:
    """Launch hook: research-pending only, never a write."""
    gate = profile_gate()
    return {"state": "research_pending", "applied": False,
            "reason": gate["reason"], "scope": list(CATEGORIES),
            "evidence": gate["evidence"], "blockers": gate["blockers"],
            "next": gate["next"]}
