"""The operator's per-title strategy stack (request #5250, operator 2026-10-28: "enable strategies that the bot
tries to go for and check and uncheck them in a panel ... dragging and dropping and reordering them in an
important stack ... adjust the priority of and the intensity so that way the bot is able to go for all of the
mission objectives while remaining alive").

A per-title ordered list of strategy entries.  Each entry has:
  - name: the strategy identifier (e.g. "survive", "time_bonuses", "combo", ...)
  - enabled: whether the bot pursues this strategy at all
  - intensity: 0.0 .. 1.0 how hard the bot pushes on this strategy
  - order: the stack position (0 = highest priority)

The stack is persisted in gbox-data/mercs/strategy.json so a hot reload or restart keeps it.  The bots read it
every round through ``apply_saved`` (called from tuning.apply at every round's start, after the automatic
tuner: the operator's word wins).

Every value is bounded; a value off its range is clamped, an unknown name refused.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

# (name, label, what it does)
STRATEGIES: dict[str, list[tuple[str, str, str]]] = {
    "re5": [
        ("survive", "Survive the floor", "Stay alive: keep health up, avoid grabs, escape crowds"),
        ("time_bonuses", "Time bonuses", "Navigate from time bonus to time bonus to bank clock"),
        ("combo", "Combo", "Keep the combo chain alive, never let it drop"),
        ("score", "Score", "Maximise score per kill, headshots and melee finishers"),
        ("crowd_clear", "Crowd clear", "Clear space and get out when surrounded (shotgun, magnum, mines)"),
        ("flashbangs", "Flashbangs", "Flash and fight: stun the crowd then pick them off"),
        ("mines", "Mines", "Drop landmines while moving so regrouped crowds get dispatched"),
        ("grenades", "Grenades", "Frag grenades into verified safe clusters"),
        ("pursue", "Pursue", "Chase down runners and ranged enemies"),
        ("melee_qte", "Melee and QTE", "Take melee prompts and QTEs when safe and lethal"),
        ("long_shots", "Long shots", "Pick off distant targets with the rifle or magnum"),
        ("explore", "Explore", "Sweep the map for items, capsules and spawn knowledge"),
        ("taunts", "Taunts", "Style points: taunt when the floor is clear"),
    ],
    "re6": [
        ("survive", "Survive the floor", "Stay alive: keep health up, tablets, avoid grabs"),
        ("time_bonuses", "Time bonuses", "Navigate from time bonus to time bonus to bank clock"),
        ("combo", "Combo", "Keep the combo chain alive, never let it drop"),
        ("score", "Score", "Maximise score per kill, counters and quick shots"),
        ("crowd_clear", "Crowd clear", "Clear space and get out when surrounded"),
        ("flashbangs", "Flashbangs", "Flash and fight: stun the crowd then pick them off"),
        ("mines", "Remote mines", "Remote bombs into clusters and detonate from a grab"),
        ("grenades", "Grenades", "Frag and incendiary grenades into clusters"),
        ("pursue", "Pursue", "Chase down runners and ranged enemies"),
        ("melee_qte", "Melee and QTE", "Quick attacks, counters and QTEs when safe"),
        ("long_shots", "Long shots", "Pick off distant targets"),
        ("explore", "Explore", "Sweep the map for items, capsules and spawn knowledge"),
        ("taunts", "Taunts", "Style points: taunt when the floor is clear"),
    ],
}

PATH = Path(__file__).resolve().parents[2] / "gbox-data" / "mercs" / "strategy.json"
_lock = threading.Lock()


def _title(t) -> str:
    t = str(t or "").strip().lower()
    if t not in STRATEGIES:
        raise ValueError(f"strategy: no strategy stack for {t!r} ({' / '.join(sorted(STRATEGIES))})")
    return t


def _read(path: Path = PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(data: dict, path: Path = PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _default_stack(title: str) -> list[dict]:
    return [
        {"name": name, "label": label, "help": help_text, "enabled": True, "intensity": 0.5}
        for name, label, help_text in STRATEGIES[title]
    ]


def _coerce_intensity(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"strategy: intensity needs a number 0..1") from None
    return min(max(round(v, 2), 0.0), 1.0)


def status(title, path: Path = PATH) -> dict:
    """The current stack for a title, with defaults for anything not yet saved."""
    t = _title(title)
    saved = _read(path).get(t)
    stack = saved if isinstance(saved, list) and saved else _default_stack(t)
    # Reconcile: drop unknown names, add missing defaults, preserve saved order.
    known = {s[0]: s for s in STRATEGIES[t]}
    seen = set()
    out = []
    for entry in stack:
        name = str(entry.get("name") or "")
        if name not in known or name in seen:
            continue
        seen.add(name)
        out.append({
            "name": name,
            "label": known[name][1],
            "help": known[name][2],
            "enabled": bool(entry.get("enabled", True)),
            "intensity": _coerce_intensity(entry.get("intensity", 0.5)),
        })
    for name, label, help_text in STRATEGIES[t]:
        if name not in seen:
            out.append({"name": name, "label": label, "help": help_text,
                        "enabled": True, "intensity": 0.5})
    return {"verified": True, "title": t, "strategies": out}


def handle(title, values=None, reorder=None, reset=None, path: Path = PATH) -> dict:
    """Update the strategy stack.

    values: {name: {"enabled": bool, "intensity": 0..1}} — set now and saved.
    reorder: [names] — the new top-to-bottom order (must be a permutation of the stack).
    reset: true (every entry to defaults) or [names] — back to enabled=True, intensity=0.5.
    """
    t = _title(title)
    with _lock:
        data = _read(path)
        current = {e["name"]: dict(e) for e in status(t, path)["strategies"]}

        if reset is True:
            current = {e["name"]: {**e, "enabled": True, "intensity": 0.5} for e in current.values()}
        elif reset:
            for name in reset:
                if name not in current:
                    raise ValueError(f"strategy: {name!r} is not a {t} strategy")
                current[name].update(enabled=True, intensity=0.5)

        for name, patch in (values or {}).items():
            if name not in current:
                raise ValueError(f"strategy: {name!r} is not a {t} strategy")
            if not isinstance(patch, dict):
                raise ValueError(f"strategy: {name!r} needs an object with enabled and/or intensity")
            if "enabled" in patch:
                current[name]["enabled"] = bool(patch["enabled"])
            if "intensity" in patch:
                current[name]["intensity"] = _coerce_intensity(patch["intensity"])

        order = list(current)
        if reorder is not None:
            if (not isinstance(reorder, list) or len(reorder) != len(current)
                    or set(reorder) != set(current)):
                raise ValueError(f"strategy: reorder must be a permutation of the {len(current)} strategy names")
            order = [str(n) for n in reorder]

        stack = [{**current[name], "order": i} for i, name in enumerate(order)]
        data[t] = stack
        _write(data, path)
    return status(t, path)


def apply_saved(title, path: Path = PATH) -> dict:
    """The saved stack for a title (what the bots read each round). -> {name: {enabled, intensity, order}}."""
    t = _title(title)
    st = status(t, path)
    return {e["name"]: {"enabled": e["enabled"], "intensity": e["intensity"], "order": i}
            for i, e in enumerate(st["strategies"])}


def install(app, store, config, auth):
    """GET/POST /api/mercs/strategy — the PiP panel's strategy stack endpoints."""
    from fastapi import Depends, HTTPException

    @app.get("/api/mercs/strategy")
    def get_strategy(title: str, actor=Depends(auth)):
        try:
            return status(title)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    class StrategyPatch:
        pass

    from pydantic import BaseModel

    class StrategyIn(BaseModel):
        title: str
        values: dict | None = None
        reorder: list[str] | None = None
        reset: bool | list[str] | None = None

    @app.post("/api/mercs/strategy")
    def post_strategy(body: StrategyIn, actor=Depends(auth)):
        try:
            return handle(body.title, values=body.values, reorder=body.reorder, reset=body.reset)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
