"""PSO's quick actions on the operator's own pad: the Select+L1+R1 equipment randomizer.

The operator asked for a chord they can hit *while playing* that randomizes the character's build and equipment. gBox
already owns a chord (``padstate.CHORD``, fired by ``watch_xinput`` when the session's chord keys are all held), so this
module is only the action behind it.

It deliberately does **not** need the character's class. The class-scoped randomizer (``pso_modes``) does, and the
GameCube build does not expose the class to ``pso_controls`` (it returns ``character_class: None`` for GC), so a chord
wired to that would either need a hardcoded class or fail. Instead it takes random *rares* from the owned-disc catalog and
gives + equips them one at a time, reporting what the game actually accepted: PSO refuses an item the character cannot
use, and that refusal is part of the report rather than a failure.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

MAX_COUNT = 4
EQUIPPABLE = ("00", "02", "0101", "0102")      # weapon, armour, shield, unit (the catalog's own code ranges)


def local_rows(path=None) -> list[dict]:
    """The cached owned-disc item database, as a fallback when the server catalog is unavailable."""
    p = Path(path) if path else Path(__file__).resolve().parents[1] / "gbox-data" / "pso" / "items-gc-v3.json"
    if not p.is_file():
        return []
    try:
        rows = json.loads(p.read_text())
    except (OSError, ValueError):
        return []
    return rows if isinstance(rows, list) else []


def candidates(rows, *, count=MAX_COUNT, kinds=EQUIPPABLE) -> list[dict]:
    """The rares the randomizer may pick from: rare, equippable-code items, de-duplicated by code."""
    out, seen = [], set()
    for r in rows:
        code = str(r.get("code") or "")
        if not r.get("rare") or not code.startswith(kinds) or code in seen:
            continue
        seen.add(code)
        out.append(r)
    return out


def randomize_equipment(shop, rows, *, count=MAX_COUNT, rng=None) -> dict:
    """Give and equip up to ``count`` random rares; returns what was accepted and what the game refused.

    ``shop`` needs ``give(code) -> {"verified", "ids"}`` and ``equip_id(item_id) -> bool`` (that is
    :class:`gbox.pso_gc_extras.Extras`), so this is testable without an emulator.
    """
    rng = rng or random
    pool = candidates(rows, count=count)
    if not pool:
        return {"ok": False, "why": "no rare items in the catalog to randomize with", "given": [], "equipped": []}
    picks = rng.sample(pool, min(int(count), len(pool)))
    given, equipped, refused = [], [], []
    for row in picks:
        code = str(row["code"])
        try:
            made = shop.give(code)
        except Exception as exc:                       # noqa: BLE001 - a refused give is data, not a crash
            refused.append({"code": code, "why": str(exc)[:120]})
            continue
        ids = list(made.get("ids") or [])
        if not made.get("verified") or not ids:
            refused.append({"code": code, "why": "the game did not acknowledge the item"})
            continue
        given.append({"code": code, "name": row.get("name"), "id": ids[0]})
        try:
            if shop.equip_id(ids[0]):
                equipped.append(code)
            else:
                refused.append({"code": code, "why": "the game refused to equip it"})
        except Exception as exc:                       # noqa: BLE001
            refused.append({"code": code, "why": str(exc)[:120]})
    return {"ok": bool(given), "given": given, "equipped": equipped, "refused": refused,
            "pool": len(pool), "why": "" if given else "no item was accepted"}


def chord_action(sid, ad, ctx=None, *, count=MAX_COUNT) -> dict:
    """The Select+L1+R1 handler: randomize the live character's equipment and report it.

    Runs on the worker (that is where the adapter is). Never raises into the pad watcher: a chord must not be able to
    kill the session.
    """
    from . import pso_gc_extras
    out = {"chord": "select+l1+r1", "sid": sid, "ok": False}
    try:
        rows = []
        if ctx is not None and getattr(ctx, "server", None):
            try:
                from . import pso_live
                rows = pso_live.catalog(ctx, "gc")
            except Exception:                          # noqa: BLE001 - fall back to the cached catalog
                rows = []
        if not rows:
            rows = local_rows()
        shop = pso_gc_extras.Extras(ad, player_index=0, pin_player=True)
        shop.check()
        out.update(randomize_equipment(shop, rows, count=count))
    except Exception as exc:                           # noqa: BLE001
        out["why"] = f"{type(exc).__name__}: {exc}"[:200]
    return out
