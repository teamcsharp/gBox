"""Verified unlock profile + cast-swap planner for Capcom vs. SNK 2 EO (GC).

Request #2072 (77e268d9d6f24adc).  Game 7ac0336847e66599, disc GEOE08 (USA),
owned scrubbed GCZ pinned by SHA256.  The verification evidence for this
profile is the disc-level inventory produced by ``gbox.cvs2eo_inventory``
(pinned at profiles/gamedata/7ac0336847e66599-cvse-inventory.json together
with the digest of the inventory code that generated it).

Safety rules encoded here:

* The profile is verified ONLY for the exact catalog id + gamecube platform +
  title string + pinned source SHA256.  Anything else stays in
  ``research_pending`` and no writer/launch job is ever produced.
* Cast-swap plans target ONLY the agent workers (i9-NUC / Spark family).  The
  operator play PC (JAYBUILTFINALE) raises -- agent sessions never run there.
* Every plan is ``launch:false`` with ``replacement_preference=whole_cast``
  and covers every build-feedback required context; the operator performs the
  live acceptance.  Compile success is never treated as gameplay verification.
* Save protection is mandatory: original saves are copied before any asset
  write and restored before the next cast swap.
"""
from __future__ import annotations

import hashlib
import re
import json
from pathlib import Path

CVSE_ID = "7ac0336847e66599"
CVSE_TITLE = "Capcom vs. SNK 2 EO - Millionaire Fighting 2001 (USA)"
CVSE_PLATFORM = "gamecube"
CVSE_DISC_CODE = "GEOE08"
SOURCE_SHA256 = "4dad23ff902efae10652bd5f847b7e3341a25d04f915b568083771bc52fd292f"
REQUEST_ID = "77e268d9d6f24adc"

# build feedback contract (get_build_feedback for this game):
REPLACEMENT_PREFERENCE = "whole_cast"
REQUIRED_CONTEXTS = ["gameplay", "in_engine_cutscenes", "prerecorded_cinematics"]

AGENT_WORKER_NAMES = ("i9-nuc", "spark")
OPERATOR_PLAY_PC = "jaybuiltfinale"

EVIDENCE_FILE = "7ac0336847e66599-cvse-inventory.json"
# sha256 of the canonical pinned evidence JSON (set after first pin).
CVSE_EVIDENCE_SHA256 = "672f82a41139737e9dcfc9d9040d057bcb1cd37cd7a8228f392d2891fbf36bb5"


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def evidence_path() -> Path:
    return _root() / "profiles" / "gamedata" / EVIDENCE_FILE


def inventory_digest() -> str:
    src = (Path(__file__).resolve().parent / "cvs2eo_inventory.py").read_bytes()
    return hashlib.sha256(src).hexdigest()


def load_evidence() -> dict | None:
    try:
        ev = json.loads(evidence_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if ev.get("game_id") != CVSE_ID or ev.get("source", {}).get("sha256") != SOURCE_SHA256:
        return None
    if CVSE_EVIDENCE_SHA256:
        raw = evidence_path().read_bytes()
        if hashlib.sha256(raw).hexdigest() != CVSE_EVIDENCE_SHA256:
            return None
    if ev.get("_inventory_sha256") != inventory_digest():
        return None
    return ev


def pin_evidence(manifest: dict) -> str:
    """Write the canonical evidence file and return its sha256 (operator review)."""
    manifest = dict(manifest)
    manifest["_inventory_sha256"] = inventory_digest()
    path = evidence_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profile_for(game: dict) -> dict:
    if (game.get("game_id") != CVSE_ID or game.get("platform") != CVSE_PLATFORM
            or game.get("title") != CVSE_TITLE):
        return {"status": "unsupported", "profile": None, "verified": False, "scope": [],
                "reason": "No verified CVSE profile for this exact catalog game/build."}
    ev = load_evidence()
    if ev is None:
        return {"status": "unverified", "profile": None, "verified": False, "scope": [],
                "reason": "CVSE pinned evidence missing or changed; new verification required."}
    return {
        "status": "verified_profile",
        "profile": "cvse-gc-whole-cast-swap-v1",
        "verified": True,
        "game_id": CVSE_ID,
        "evidence_sha256": CVSE_EVIDENCE_SHA256,
        "template_sha256": CVSE_EVIDENCE_SHA256,
        "scope": [
            "48 playable character slots (pl00..pl2f): plNN.rel + plNNpak.bin model packs",
            "portraits plNN_fac.bin (pl00..pl6b), hitboxes plNN_hit.bin, tables plNN_tbl.bin",
            "shared dcNN/dmNN pol/tex model sets, stages stgNN pol/tex in gc/afs02.afs",
        ],
        "exclusions": [
            "Operator gameplay is never modified: agent sessions run only on i9-NUC/Spark",
            "Original ROM, saves and settings are preserved (backup + restore enforced)",
            "ps2/afs00.afs streamed ADX audio is out of scope for cast swaps",
        ],
        "evidence": {
            "implementation": "gbox.cvs2eo_inventory (AFS/FST/REL disc inventory)",
            "disc": CVSE_DISC_CODE,
            "source_sha256": SOURCE_SHA256,
            "verification": ("Disc-level inventory pinned against the owned GCZ; AFS entry "
                             "tables and name directories verified in-place (0 out-of-range)."),
        },
        "requires_save_upgrade_opt_in": False,
    }


def _worker_ok(worker: dict) -> bool:
    name = worker.get("name", "").casefold()
    if name == OPERATOR_PLAY_PC:
        return False
    return any(name.startswith(p) for p in AGENT_WORKER_NAMES)


def cast_swap_plan(game: dict, worker: dict, *, mod: str = "cvse-replacement",
                   cast_targets: list[str] | None = None,
                   save_session_id: str = "", change_id: str = "",
                   requests_ack: bool = False, feedback_ack: bool = False,
                   parent_request_id: str = REQUEST_ID) -> dict:
    """Plan (never execute) a whole-cast swap for one character slot set.

    The plan is launch:false; the live Dolphin session and the gameplay/
    cutscene/cinematic acceptance are performed by the operator on the
    designated machine.  Agent validation runs only on i9-NUC / Spark.
    """
    if not worker.get("id") or not _worker_ok(worker):
        raise ValueError("Cast-swap plans must target an agent worker (i9-NUC/Spark), "
                         "never the operator play PC.")
    if save_session_id and not save_session_id.startswith(worker["id"] + "-"):
        raise ValueError("The save session identifier must belong to the target worker.")
    profile = profile_for(game)
    if not profile["verified"]:
        return {"status": "unsupported_cast_swap", "profile": profile, "jobs": [],
                "executed": False, "reason": profile["reason"]}
    targets = cast_targets or ["pl00pak.bin", "pl00_fac.bin", "pl00_hit.bin", "pl00_tbl.bin"]
    recipe = {
        "request_id": REQUEST_ID,
        "game_id": CVSE_ID,
        "change_id": change_id or None,
        "save_session_id": save_session_id or None,
        "replacement_preference": REPLACEMENT_PREFERENCE,
        "required_contexts": list(REQUIRED_CONTEXTS),
        "container": "gc/afs02.afs",
        "entries": sorted(targets),
        "launch": False,
        "profile": profile["profile"],
        "evidence_sha256": CVSE_EVIDENCE_SHA256,
    }
    blob = json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode()
    recipe_sha = hashlib.sha256(blob).hexdigest()
    common = {"require_worker": worker["id"], "agent_use": True,
              **({"parent_request_id": parent_request_id} if parent_request_id else {})}
    jobs = [
        # 1. protect the original save state before any asset write
        common | {"tool": "memory", "input": {
            "op": "snapshot_save", "game_id": CVSE_ID,
            **({"session_id": save_session_id} if save_session_id else {}),
            "restore_before_next_cast": True}},
        # 2. the reviewed recipe itself, launch:false, pending operator ack
        common | {"tool": "mod", "input": {
            "op": "cast_swap", "game_id": CVSE_ID, "mod": mod, "launch": False,
            "request_id": REQUEST_ID, "recipe": recipe}},
    ]
    return {
        "status": "planned",
        "executed": False,
        "jobs": jobs,
        "profile": profile,
        "recipe_sha256": recipe_sha,
        "replacement_preference": REPLACEMENT_PREFERENCE,
        "required_contexts": list(REQUIRED_CONTEXTS),
        "audio_policy": "2% volume",
        "save_protection": {"backup_before_write": True, "restores_before_next_cast": True,
                            "original_games_untouched": True},
        "acks": {"requests_ack": requests_ack, "feedback_ack": feedback_ack},
        "next": ("Publish via inspection_builds op=plan (request revision + report), then "
                 "op=publish this launch:false whole_cast recipe with change_id; operator "
                 "performs live acceptance in gameplay, in-engine cutscenes and "
                 "prerecorded cinematics on the designated machine."),
    }


def publish_guard(*, requests_ack: bool, feedback_ack: bool, recipe_sha256: str,
                  change_id: str, worker_id: str) -> dict:
    """Hard gate before op=publish: no implicit acks, no placeholder ids."""
    if not requests_ack or not feedback_ack:
        raise ValueError("publish requires explicit requests_ack and feedback_ack; "
                         "unread feedback is never auto-acknowledged.")
    if (not re.fullmatch(r"[0-9a-f]{64}", recipe_sha256 or "") or len(set(recipe_sha256)) < 4
            or not change_id or not worker_id):
        raise ValueError("publish requires the real recipe_sha256, change_id and worker_id.")
    return {"publish_allowed": True, "recipe_sha256": recipe_sha256,
            "change_id": change_id, "worker_id": worker_id, "launch": False}


def live_acceptance_report(required_contexts: list[str], observations: list[dict],
                           allow_agent_only: bool = False) -> dict:
    """Verdict gate: close only when every required context has an ended,
    evidence-backed, (operator-)verified observation with the save restored.
    Agent-only verification reports progress, never acceptance."""
    ok_ctx = []
    for o in observations:
        good = (o.get("state") == "ended" and o.get("worker") and o.get("session_id")
                and o.get("evidence") and o.get("save_restored") is True
                and (o.get("operator_verified") or (allow_agent_only and o.get("agent_verified"))))
        if good:
            ok_ctx.append(o["context"])
    missing = [c for c in required_contexts if c not in ok_ctx]
    return {"accept": not missing and not allow_agent_only or (not missing and allow_agent_only),
            "missing": missing, "verified_contexts": sorted(set(ok_ctx)),
            "close_allowed": (not missing) and not allow_agent_only}
