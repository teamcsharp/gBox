"""Thrasher: Skate and Destroy (PS1, USA) - request #6087 control catalog and research ledger.

This module is a *specification*, not a hook. Nothing here reads or writes game
memory: the disc (``PS1 Thrasher - Skate and Destroy (USA).7z`` on the QuickSwap2
share) has not been extracted/decompiled yet, so every control starts as
``research_pending`` and may only be promoted to ``mapped`` through
:func:`promote` with evidence (RAM address + how it was verified). The viewer
(PineBox radio / mod panel) surface can therefore list the full requested
control set today and refuse to dispatch anything that is not mapped.

Note: the report attached to #6087 was captured while Resident Evil: The
Mercenaries 3D was open; its game_id (0ed22ae742e1b56b) is NOT Thrasher. Thrasher
needs its own game_id once catalogued; ``GAME_ID`` stays None until then.
"""
from __future__ import annotations

import re

TITLE = "Thrasher: Skate and Destroy (USA)"
PLATFORM = "playstation"
GAME_ID: str | None = None  # not catalogued yet; do not borrow the Mercenaries 3D id
SOURCE_ARCHIVE = r"\\10.89.1.125\QuickSwap2\Emulation\PS1 Thrasher - Skate and Destroy (USA).7z"
DEMO_PENDING = True  # operator also asked for the demo; no source path given yet

PENDING, MAPPED = "research_pending", "mapped"

# key, label, kind, (min, max) for numeric, RAM/decomp evidence required before mapping
_CONTROLS = [
    ("gravity", "Gravity", "number", (0.1, 4.0), "skater vertical-velocity/gravity constant in the physics step"),
    ("spawn_cop", "Insert cop at random spot", "action", None, "cop actor spawn routine + free actor slot + stage spawn points"),
    ("spawn_two_cops", "Insert 2 cops at random spots", "action", None, "same as spawn_cop; needs actor-table capacity"),
    ("cop_pursuit_speed", "Cop pursuit speed", "number", (0.1, 2.0), "cop chase speed/steering constants"),
    ("cop_cam", "Cycle to cop cam", "action", None, "camera mode selector and cop-target pointer"),
    ("game_speed", "Game speed", "number", (0.25, 4.0), "main-loop frame step / vsync divider"),
    ("reset_score", "Reset score", "action", None, "score word(s) in RAM"),
    ("trick_score_multiplier", "Next trick score x", "number", (1, 100), "trick-award routine that adds to score"),
    ("no_fall", "Cannot fall off board", "toggle", None, "bail/fall state transition trigger"),
    ("jump_distance", "Jump distance x", "number", (0.5, 5.0), "ollie impulse / air-velocity constants"),
    ("trick_speed", "Trick speed x", "number", (0.5, 4.0), "trick animation rate"),
    ("skater_model", "Live skater model swap", "choice", None, "skater model pointer/TMD-or-custom format + loader (see gbox.cast_swap)"),
    ("cop_model", "Live cop model swap", "choice", None, "cop model pointer + format"),
    ("change_level", "Change level", "choice", None, "level id variable + level-load trigger"),
    ("restart_level", "Restart level", "action", None, "level reload trigger"),
    ("place_character", "Place character (2D map)", "position", None, "skater world X/Y/Z and per-level map bounds"),
    ("shirt_logo", "Shirt logo image", "image", None, "shirt texture VRAM region + CLUT; ps1_texture upload path"),
    ("camera_mode", "Camera: follow / pursuit / cinematic", "choice", ("follow", "pursuit", "cinematic"), "camera mode selector"),
    ("perfect_balance", "Perfect balance", "toggle", None, "balance meter variable (grind/manual)"),
    ("add_skaters", "Add random skaters", "action", None, "actor spawn routine for skater class"),
]

# Bot-behaviour knobs requested ("more of certain trick types, exploring the level").
BOT_KNOBS = {
    "trick_bias": {"flip": 0.0, "grab": 0.0, "grind": 0.0, "manual": 0.0, "lip": 0.0},  # weights 0..1
    "explore_vs_objective": 0.5,  # 0 = pure objective speedrun, 1 = pure exploration
    "evade_cops": True,
}
BOT_RESEARCH = [
    "level objective flags/counters in RAM (per level)",
    "cop proximity/state words for evasion",
    "level geometry/collision for navigation",
]


def catalog() -> list[dict]:
    """All requested controls, each with status and what evidence unlocks it."""
    out = []
    for key, label, kind, rng, need in _CONTROLS:
        out.append({"key": key, "label": label, "kind": kind, "range": rng,
                    "status": _state.get(key, {}).get("status", PENDING),
                    "needs": need, "evidence": _state.get(key, {}).get("evidence")})
    return out


_state: dict[str, dict] = {}
_HEX = re.compile(r"^0x[0-9a-fA-F]{6,8}$")


def promote(key: str, address: str, verified_by: str) -> dict:
    """Mark a control mapped. Requires a PS1 RAM address and a verification note."""
    if key not in {c[0] for c in _CONTROLS}:
        raise KeyError(key)
    if not _HEX.match(address or ""):
        raise ValueError("address must look like 0x80xxxxxx")
    if not (verified_by or "").strip():
        raise ValueError("verified_by is required: promotion needs evidence")
    _state[key] = {"status": MAPPED, "evidence": {"address": address, "verified_by": verified_by}}
    return _state[key]


def validate_command(key: str, value=None) -> tuple[bool, str]:
    """Gate for a viewer command: unknown, unmapped or out-of-range -> refused."""
    spec = next((c for c in _CONTROLS if c[0] == key), None)
    if spec is None:
        return False, "unknown control"
    if _state.get(key, {}).get("status") != MAPPED:
        return False, "research_pending: not mapped in RAM yet"
    _, _, kind, rng, _ = spec
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False, "number required"
        if not rng[0] <= value <= rng[1]:
            return False, f"out of range {rng}"
    elif kind == "toggle" and not isinstance(value, bool):
        return False, "bool required"
    elif kind == "choice" and rng and value not in rng:
        return False, f"must be one of {rng}"
    return True, "ok"
