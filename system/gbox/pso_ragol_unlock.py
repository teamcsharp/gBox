"""Return To Ragol V1.0.3 (Phantasy Star Online Episode I&II, GameCube) unlock research gate.

Catalog game_id 5b5792e27be59f59 is the operator's owned "Return To Ragol V1.0.3
(Widescreen)" GameCube build (disc serial GPOE8P, library gc-iso).  This module
pins that exact owned executable identity and records the save-layout facts that
were read from the owned disc, so no future run can bind a patch, a save overlay
or a live memory write to the wrong build.

Deliberately contains NO write targets.  The owned build's item-eligibility
bitmap, level table and memory-card block offsets are still unproven for *this*
executable: the only local decompile is of a different PSO GC build.  Those
offsets are kept in HYPOTHESIS_SAVE_LAYOUT, clearly labelled and never surfaced
on the dispatch surface, so pre_launch can never select a writer for this title.

Until the owned executable is re-derived and a live boot acceptance exists, this
game stays pending_research.
"""
from __future__ import annotations

GAME_ID = "5b5792e27be59f59"
TITLE = "Return To Ragol V1.0.3"
ALT_TITLE = "PHANTASY STAR ONLINE EPISODE I&II"
PLATFORM = "gamecube"
SERIAL = "GPOE8P"
LIBRARY = "gc-iso"

OWNED_ISO = ("/mnt/gbox/quickswap2/Emulation/_emulation/GC ISO/"
             "Return To Ragol V1.0.3 (Widescreen).iso")
OWNED_ISO_SIZE = 1413531648
OWNED_EXECUTABLE = "PsoV3.dol"
OWNED_EXECUTABLE_SIZE = 5236992
OWNED_EXECUTABLE_SHA256 = "60fa76460510de212c817500119ee560bb415cbf7b1c32a8f4911c2e93ead3a5"
OWNED_DISC_FILE_COUNT = 3510

# Category families the standing operator request covers for this title.
CATEGORIES = ("items", "modes", "stages", "costumes", "extras", "hidden_characters")

# The evidence chain a verified profile must attach before promotion.
REQUIRED_EVIDENCE = ("owned_executable_sha256", "owned_build_rederived_layout",
                     "save_backup_receipt", "rollback_receipt",
                     "live_boot_and_selection_acceptance", "second_launch_verification")

# Facts read from the OWNED disc file inventory (not executable offsets).
OWNED_DISC_CONTENT = {
    "quest_stages": 29,        # Quest/quest01..quest29 (+ quest58)
    "challenge_packs": 9,      # Quest/challenge_mlt_stg1..9
    "challenge2_packs": 5,     # Quest/challenge2_mlt_stg1..5
    "title_lists": 5,          # QtOffTitleList_{e,f,g,j,s}.rel
    "challenge_titles": 1,     # QtOffChallenge.rel
    "battle_tables": 4,        # BattleParamEntry{,_on,_lab,_lab_on}.dat
    "item_tables": 2,          # ItemPMT.prs, ItemRTT.prs
    "level_table": 1,          # PlyLevelTbl.cpt
}

# HYPOTHESES ONLY: read from a different PSO GC build (PsoV3.dol sha256
# b02c3091...) that was decompiled on this host.  Not proven for the owned
# executable; never used to derive a write.
HYPOTHESIS_SAVE_LAYOUT = {
    "source_build_sha256": "b02c3091542afc82fc62a1ddbe5f575f70aff6225778be1c12e0652bf47e82c2",
    "verified_for_owned_build": False,
    "item_eligibility_bitmap_offset": 0x1942C,
    "item_eligibility_bitmap_bytes": 0x80,
    "item_count": 999,
    "item_state_field_offset": 0x93,
    "item_state_unlocked": 0x0C,
    "player_save_stride": 0x43C,
    "card_slot_id_offset": 0x0C,
    "ply_level_record": 0x30,
    "ply_level_record_alt": 0x24,
    "card_data_table_decompressed_size": 0x36EC0,
}

SAFETY = (
    "No live memory or save write exists for this title and none may be attempted "
    "before the required evidence chain is complete.",
    "Never test on the operator PC; only an idle authorized worker (i9-NUC or the Spark).",
    "Preserve the original ISO and back up any save before changing it.",
    "A queued task, an artifact report or a code-only PR is not unlock completion.",
)


def profile_gate() -> dict:
    """Honest dispatch-surface record: research pending, nothing verified."""
    return {
        "game_id": GAME_ID,
        "title": TITLE,
        "alt_title": ALT_TITLE,
        "platform": PLATFORM,
        "serial": SERIAL,
        "library": LIBRARY,
        "verified": False,
        "writable": False,
        "status": "pending_research",
        "owned_executable": OWNED_EXECUTABLE,
        "owned_executable_sha256": OWNED_EXECUTABLE_SHA256,
        "owned_executable_size": OWNED_EXECUTABLE_SIZE,
        "owned_disc_content": dict(OWNED_DISC_CONTENT),
        "requires": list(REQUIRED_EVIDENCE),
        "categories": list(CATEGORIES),
        "safety": list(SAFETY),
        "reason": (
            "The owned build's unlock layout is not re-derived yet: the only local "
            "decompile is of a different PSO GC executable, and no owned memory card "
            "or live boot acceptance exists for this build."),
        "next_step": (
            "Depair the owned PsoV3.dol and confirm the item-eligibility bitmap and "
            "level-table records in the Spark Ghidra bridge; then build an isolated "
            "unlock overlay card and register a revision-guarded profile."),
    }
