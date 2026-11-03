"""Operator's requested PSO co-op entry: which Episode + Difficulty the autobot starts a game on.

The desktop sidebar writes this selection; the two-player PSO campaign (pso_coop) reads it when it
(re)launches and whenever it is between games (``awaiting_entry``), and points its authentic menu-walk
at the chosen Episode and Difficulty. It never writes game memory and never interrupts a floor already
in play. It also grants no input authority on its own: the existing ``MenuProgress`` gate still requires
the menu observer to independently read the chosen Episode/Difficulty on the Options screen before any
"Start Game" is confirmed. Today the observer's option-screen masks cover Episode 1 / Normal; other
values set the campaign's requested target (and are verified from the native difficulty RAM global
0x805D5550 once a game is entered) but the guarded option-navigation that confirms them needs the menu
observer to gain masks for the other labels - owned by the menu/nav path. See docs/pso-coop-campaign.

This file does not launch an emulator, resume autoplay or modify a memory card.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

FILENAME = "pso-launch-config.json"
# Indices 0..3 are the GameCube PSO difficulties, matching pso_coop.DIFFICULTIES and the native
# difficulty RAM global 0x805D5550 (pso_coop_native.DIFFICULTY).
DIFFICULTIES = ("normal", "hard", "very_hard", "ultimate")
LABELS = {"normal": "Normal", "hard": "Hard", "very_hard": "Very Hard", "ultimate": "Ultimate"}
# "legendary" is NOT a standard PSO GameCube difficulty. The operator's label maps to Ultimate for now
# (the hardest native difficulty); if a "legendary" mod is ever installed this alias is where it changes.
ALIASES = {"normal": "normal", "hard": "hard", "very_hard": "very_hard", "veryhard": "very_hard",
           "very hard": "very_hard", "vhard": "very_hard", "ultimate": "ultimate", "legendary": "ultimate"}


def normalize(episode, difficulty):
    """Return (episode:int 1|2, slug:str, index:int 0..3) or raise ValueError for an unsupported value."""
    try:
        ep = int(episode)
    except (TypeError, ValueError):
        raise ValueError("episode must be 1 or 2")
    if ep not in (1, 2):
        raise ValueError("episode must be 1 or 2")
    slug = ALIASES.get(str(difficulty).strip().lower().replace("-", "_"))
    if slug is None:
        raise ValueError("difficulty must be one of normal, hard, very_hard, ultimate (legendary maps to ultimate)")
    return ep, slug, DIFFICULTIES.index(slug)


def describe(ep, slug, idx, *, source, requested=None):
    requested = str(requested if requested is not None else slug).strip().lower()
    return {"episode": ep, "episode_label": f"Episode {ep}",
            "difficulty": slug, "difficulty_index": idx, "difficulty_label": LABELS[slug],
            "requested_difficulty_input": requested, "legendary": requested == "legendary",
            "source": source}


def defaults():
    """The campaign's own starting point when the operator has set nothing (Episode 1 / Normal)."""
    return describe(1, "normal", 0, source="default")


def read(root):
    """The selection stored in this campaign root, or None (then the campaign auto-cycles as before)."""
    if not root:
        return None
    try:
        data = json.loads((Path(root) / FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        ep, slug, idx = normalize(data.get("episode"), data.get("difficulty"))
    except ValueError:
        return None
    out = describe(ep, slug, idx, source="run", requested=data.get("requested_difficulty_input"))
    for key in ("updated_at", "by"):
        if key in data:
            out[key] = data[key]
    return out


def write(root, episode, difficulty, *, by="operator"):
    """Atomically persist the operator's pick in the campaign root; the bot picks it up by content."""
    ep, slug, idx = normalize(episode, difficulty)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    doc = describe(ep, slug, idx, source="run", requested=str(difficulty))
    doc.update(updated_at=time.time(), by=str(by)[:64])
    path = root / FILENAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)
    return doc


def apply(ledger, root, *, initial=False, stats=None):
    """Point the ledger's requested episode/difficulty at the operator's pick - at a game-entry boundary only.

    A selection is honored at (re)launch (``initial=True``) and whenever the campaign is between games
    (``ledger.awaiting_entry``). It is a no-op mid-run, so a floor already in progress is never disrupted;
    the difficulty the bot is currently verified to be playing is never changed underneath it. Idempotent
    and fail-soft: any error leaves the ledger exactly as it was and the campaign keeps running.
    Returns the applied selection, or None when nothing was applied.
    """
    try:
        if not (initial or getattr(ledger, "awaiting_entry", False)):
            return None
        sel = read(root)
        if sel is None:
            return None
        changed = (getattr(ledger, "target", None) != sel["episode"]
                   or getattr(ledger, "difficulty", None) != sel["difficulty_index"])
        ledger.target = sel["episode"]
        if getattr(ledger, "difficulty", None) != sel["difficulty_index"]:
            ledger.difficulty = sel["difficulty_index"]
            # Re-verify the chosen difficulty from RAM on the next entry (matches the ledger's own
            # convention whenever it changes the requested difficulty).
            if hasattr(ledger, "difficulty_verified"):
                ledger.difficulty_verified = False
        if stats is not None and changed:
            stats["launch_selection"] = {
                "episode": sel["episode"], "difficulty": sel["difficulty"],
                "difficulty_label": sel["difficulty_label"], "legendary": sel.get("legendary", False),
                "applied": "launch" if initial else "between_games"}
        return sel
    except Exception:  # noqa: BLE001 - a selection error must never break play()
        return None
