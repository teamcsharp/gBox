"""RE6 cast roster: put a different extracted character on RE6's player slots and rotate them per round.

RE6 keeps one body archive per native character (`nativeXenon/arc/X360/uPl00LeonUsa.arc`, ...) **and per costume**
(`uPl00LeonAsia.arc`, `uPl00LeonOmake00.arc`, ...). The Mercenaries character select picks one of those native
characters each round, and `gbox.mercs.round_controls.Controls.choose_character` already randomises that choice and
never repeats a family back to back; the select also randomises the costume. So the roster is one mod that replaces
**every** player slot (or every costume of every slot) with a different collection character:

    assignment = re6_cast.plan(entries, seed=7)              # one character per slot, all costumes
    assignment = re6_cast.plan_per_costume(entries, seed=7)  # one character per costume: up to 44 in one mod

Because each native slot/costume now shows a different cast member, the game's own round rotation shows a different
Smash character every round **without a relaunch per round**: the archive is loaded at boot, and the round-to-round
change is the game's native select. A different *build* still needs a relaunch, so this is not real-time in-memory
model swapping.

The scale fit uses the measured `source_proportions` mode (`gbox.re6_models.fit_source_proportions`): the donor surface
is preserved and RE6's bind joints are moved instead, which is the fix for donors the old segment fit stretched.
"""
from __future__ import annotations

import random

#: RE6 player slots the model writer supports, in the order of `re6_models.CHARACTERS` / the select's ids.
TARGETS = ("leon", "helena", "chris", "piers", "jake", "sherry", "ada")
SELECT_IDS = {name: i for i, name in enumerate(TARGETS)}
DEFAULT_NAME = "re6_smash_roster"
POSE = "source_proportions"


class CastError(ValueError):
    """The roster cannot be planned or built; the message names the reason."""


def _roles(meta: dict) -> dict:
    return (meta.get("rig") or {}).get("roles") or {}


def assignable(entries: list[dict], minimum: int = 12) -> list[dict]:
    """Entries a rigid-per-bone writer can fit: a slug, a name and a near-complete humanoid role map."""
    return [e for e in entries
            if isinstance(e, dict) and e.get("slug") and e.get("name") and len(_roles(e)) >= minimum]


def plan(entries: list[dict], *, seed: int | None = None, targets: tuple[str, ...] = TARGETS) -> dict:
    """One cast entry per RE6 slot: a deterministic shuffle of the assignable cast, reusing in order if short."""
    pool = assignable(entries)
    if not pool:
        raise CastError("no assignable character with body roles: extract a cast first")
    order = sorted(pool, key=lambda e: e["slug"])
    random.Random(seed).shuffle(order)
    chosen = [order[i % len(order)] for i in range(len(targets))]
    return {target: chosen[i] for i, target in enumerate(targets)}


def _costumes(target: str) -> list[str]:
    from .re6_models import CHARACTERS
    return list(CHARACTERS[target]["costumes"])


def _per_costume(spec) -> bool:
    """True when an assignment entry maps a costume name to a character (rather than one character for the slot)."""
    return (isinstance(spec, dict) and "slug" not in spec and bool(spec)
            and all(isinstance(v, dict) and v.get("slug") for v in spec.values()))


def normalise(assignment: dict) -> dict:
    """Expand a slot assignment to {target: {costume: character}}; a single character fills every costume."""
    out = {}
    for target, spec in assignment.items():
        if target not in TARGETS or not spec:
            continue
        if _per_costume(spec):
            out[target] = {str(c): m for c, m in spec.items() if m}
        else:
            out[target] = {costume: spec for costume in _costumes(target)}
    return out


def plan_per_costume(entries: list[dict], *, seed: int | None = None, targets: tuple[str, ...] = TARGETS) -> dict:
    """Assign a different collection character to **every costume** of every RE6 slot.

    RE6 keeps one body archive per costume, and its Mercenaries character select also randomises the costume each
    round, so one mod built this way can show up to 44 different characters across the seven slots.
    """
    pool = assignable(entries)
    if not pool:
        raise CastError("no assignable character with body roles: extract a cast first")
    order = sorted(pool, key=lambda e: e["slug"])
    random.Random(seed).shuffle(order)
    pairs = [(target, costume) for target in targets for costume in _costumes(target)]
    out = {target: {} for target in targets}
    for i, (target, costume) in enumerate(pairs):
        out[target][costume] = order[i % len(order)]
    return {target: {c: m for c, m in costumes.items()} for target, costumes in out.items() if costumes}


def costume_rotation(assignment: dict) -> list[dict]:
    """Every (select id, costume, character) row a per-costume roster can show."""
    rows = []
    for target, costumes in normalise(assignment).items():
        for costume, meta in costumes.items():
            rows.append({"select_id": SELECT_IDS[target], "native": target, "costume": costume,
                         "cast": meta["slug"], "name": meta["name"]})
    return rows


def rotation(assignment: dict) -> list[dict]:
    """The select id -> cast row mapping the Mercenaries character rotation walks through."""
    rows = []
    for target in TARGETS:
        if target not in assignment:
            continue
        spec = assignment[target]
        first = next(iter(spec.values())) if _per_costume(spec) else spec
        row = {"select_id": SELECT_IDS[target], "native": target, "cast": first["slug"], "name": first["name"]}
        if _per_costume(spec):
            row["costumes"] = {costume: meta["slug"] for costume, meta in spec.items()}
        rows.append(row)
    return rows


def describe(assignment: dict) -> str:
    return "; ".join(f"{row['name']} as {row['native']}" for row in rotation(assignment))


def build(ctx, base, assignment: dict, *, name: str = DEFAULT_NAME, height: float = 180.0, progress=None) -> dict:
    """Build one mod whose every player slot (and costume) is the assigned collection character."""
    from . import re6_models as M, re6_tool as T
    progress = progress or (lambda *a: None)
    slots = normalise(assignment)
    files, rows, models = {}, [], {}
    total = sum(len(c) for c in slots.values()) or 1
    done = 0
    for target in TARGETS:
        if target not in slots:
            continue
        if target not in M.CHARACTERS:
            raise CastError(f"RE6 has no writer target {target!r}")
        for costume, meta in slots[target].items():
            if costume not in M.CHARACTERS[target]["costumes"]:
                raise CastError(f"{target} has no costume {costume!r}")
            if meta["slug"] not in models:
                models[meta["slug"]] = T.fetch_model(ctx, meta)
            progress(done / total, f"Fitting {meta['name']} to {target} ({costume})")
            result = M.build_swap(base, models[meta["slug"]], _roles(meta), target, costume, meta["slug"],
                                  scale={"pose": POSE, "height": height})
            files.update(result["files"])
            rows.append({"target": target, "costume": costume, "character": meta["slug"],
                         "triangles": result["triangles"], "vertices": result["vertices"],
                         "pose_mode": result.get("pose_mode"),
                         "fitted_height": (result.get("fit") or {}).get("fitted_height"),
                         "proportion_error": (result.get("fit") or {}).get("proportion_error"),
                         "notes": result.get("notes") or []})
            done += 1
    if not files:
        raise CastError("the assignment produced no slot")
    progress(92, f"Writing {name}")
    characters = {target: {costume: meta["slug"] for costume, meta in costumes.items()}
                  for target, costumes in slots.items()}
    written = T.build_mod_folder(ctx.config, name, files, {
        "kind": "cast_roster", "game": "re6",
        "assignment": {target: {costume: {"slug": meta["slug"], "name": meta["name"]}
                                for costume, meta in costumes.items()}
                       for target, costumes in slots.items()},
        "characters": characters,
        "rotation": rotation(slots), "costume_rotation": costume_rotation(slots),
        "pose": POSE, "height": height,
        "note": "each native RE6 character's every costume is a different collection character; the round controls' "
                "character rotation (and the game's costume randomisation) therefore rotates the cast"})
    shown = sorted({meta["slug"] for costumes in slots.values() for meta in costumes.values()})
    return {"mod": name, "slots": rows, "files": len(files), "rotation": rotation(slots),
            "costume_rotation": costume_rotation(slots), "characters": len(shown),
            "characters_shown": shown, "pose": POSE, "height": height, "build": written,
            "choices": [{"select_id": row["select_id"], "character": row["cast"], "name": row["name"]}
                        for row in rotation(slots)]}


def current(assignment: dict, select_id: int | None) -> dict | None:
    """Which cast member a native select id (the round's character) shows; None when unassigned."""
    row = next((r for r in rotation(assignment) if r["select_id"] == select_id), None)
    return row


def plan_from_slugs(entries: list[dict], slugs: list[str], *, seed: int | None = None) -> dict:
    """Explicit cast list -> slots: slugs in order, randomising any slot the list does not name."""
    picked = {e["slug"]: e for e in assignable(entries)}
    missing = [s for s in slugs if s not in picked]
    if missing:
        raise CastError(f"not in the collection as character donors: {', '.join(missing)}")
    chosen = [picked[s] for s in slugs]
    if not chosen:
        return plan(entries, seed=seed)
    chosen = [picked[s] for s in slugs][:len(TARGETS)]
    rest = [e for e in sorted(picked.values(), key=lambda e: e["slug"]) if e["slug"] not in {c["slug"] for c in chosen}]
    random.Random(seed).shuffle(rest)
    ordered = chosen + rest
    return {target: ordered[i % len(ordered)] for i, target in enumerate(TARGETS)}
