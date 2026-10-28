"""The operator's live bot logic (operator 2026-10-28: "the bot automatically plays while I control the Autobot
dynamically on the fly ... a sidebar slides out that allows me to customize the bot logic on the fly"): a whitelist of
each Switch Mercenaries bot's switches and dials, set on the running bot module at once (the bots read these module
constants every tick), saved in gbox-data/mercs/bot-logic.json so a hot reload or a restart keeps them (tuning.apply
reapplies them at every round's start, after the automatic tuner: the operator's word wins). The re5_mods tool's op
bot_logic (values={name: value}, reset=[names] or true) reaches it from the PiP's sidebar.

Every value is bounded; a value off its range is clamped, an unknown name refused."""
from __future__ import annotations

import importlib
import json
import os
import threading
from pathlib import Path

# (name, label, group, kind, low, high, step, what it does)
KNOBS: dict[str, list[tuple]] = {
    "re5": [
        ("CROWD_FIRE", "Crowd fire (shotgun first)", "Crowd control", "bool", 0, 1, 1,
         "3+ within 5 m: the shotgun up, firing at the nearest in front"),
        ("CROWD_FIRE_N", "Crowd size that starts crowd fire", "Crowd control", "int", 2, 8, 1, "Majini within 5 m"),
        ("CROWD_FIRE_CLOSE_R", "One this close starts crowd fire (cm)", "Crowd control", "float", 100, 400, 10, ""),
        ("RAMPAGE_R", "Crowd circle radius (cm)", "Crowd control", "float", 300, 800, 25, ""),
        ("MINES", "Drop mines while moving", "Crowd control", "bool", 0, 1, 1, ""),
        ("MINE_EVERY_S", "Seconds between mines", "Crowd control", "float", 3, 60, 1, ""),
        ("RELOCATE", "Keep moving (relocate off crowds)", "Movement", "bool", 0, 1, 1, ""),
        ("RELOC_CROWD_N", "Crowd size that makes him move", "Movement", "int", 2, 10, 1, ""),
        ("WALL_GOV", "Wall governor (never push into walls)", "Movement", "bool", 0, 1, 1, ""),
        ("QUICK_TURN", "Quick turn on one behind", "Movement", "bool", 0, 1, 1, "stick back + B"),
        ("BEHIND_R", "Behind-him threat range (cm)", "Movement", "float", 150, 600, 25, ""),
        ("HEADING_GOV_DEG_S", "Max turn speed (deg/s)", "Aim", "float", 60, 360, 10, "the camera never whips faster"),
        ("AIM_LOCK", "RAM aim lock", "Aim", "bool", 0, 1, 1, "aims by writing the camera (can snap the view)"),
        ("WINDUP", "Attackers first", "Aim", "bool", 0, 1, 1, "a Majini winding up is shot first"),
        ("WINDUP_R", "Attacker range (cm)", "Aim", "float", 100, 600, 25, ""),
        ("PROMPTS", "Take the game's prompts", "Objectives", "bool", 0, 1, 1, "Y hourglass, ledges, QTEs"),
        ("HEAL_CRITICAL", "Heal at health fraction", "Survival", "float", 0.1, 0.6, 0.05, ""),
    ],
    "re6": [
        ("NADES", "Grenades", "Crowd control", "bool", 0, 1, 1, "frags and incendiaries into clusters"),
        ("FLASH", "Flash and fight", "Crowd control", "bool", 0, 1, 1, "a flash, then the stunned ones"),
        ("FLASH_N", "Crowd size for a flash", "Crowd control", "int", 2, 8, 1, ""),
        ("FLASH_R", "Flash crowd radius (cm)", "Crowd control", "float", 200, 900, 25, ""),
        ("FLASH_GAP_S", "Seconds between flashes", "Crowd control", "float", 0.5, 15, 0.5, "the fight window after one"),
        ("FLASH_BURST_S", "Flurry length (s)", "Crowd control", "float", 0, 5, 0.5, "0 = one flash at a time"),
        ("FLASH_BURST_N", "Swarm size for a flurry", "Crowd control", "int", 3, 10, 1, ""),
        ("BOMB_DROP", "Remote bombs", "Crowd control", "bool", 0, 1, 1, ""),
        ("CROWD_R", "Crowd radius (cm)", "Crowd control", "float", 150, 400, 10, ""),
        ("KITE_R", "Kite distance (cm)", "Movement", "float", 300, 1500, 50, ""),
        ("KEEP_R", "Personal space (cm)", "Movement", "float", 100, 400, 10, ""),
        ("NAV_WALK", "Walk by the nav mesh", "Movement", "bool", 0, 1, 1, ""),
        ("PUSH_CHECK_R", "Escape line check (cm)", "Movement", "float", 200, 800, 25, ""),
        ("SPIN_DEG_S", "Max turn speed (deg/s)", "Aim", "float", 60, 360, 10, ""),
        ("AIM_LOCK", "RAM aim lock", "Aim", "bool", 0, 1, 1, "aims by writing the camera"),
        ("CLOSE_R", "Close-threat range (cm)", "Aim", "float", 300, 1000, 25, "only these are targets"),
        ("CEILING_R", "Aim at ones right above him (cm)", "Aim", "float", 0, 600, 25, "0: never aim up at the floor above"),
        ("BONUS_RUN", "Capsule run (time bonuses)", "Objectives", "bool", 0, 1, 1, ""),
        ("BONUS_SHOOT_R", "Capsule shot range (cm)", "Objectives", "float", 500, 4000, 100, ""),
        ("PROMPTS", "Take the game's prompts", "Objectives", "bool", 0, 1, 1, "climbs and QTEs"),
        ("FIRE_ZONE_R", "Shoot-first radius (cm)", "Crowd control", "float", 0, 2000, 50,
         "an enemy in sight this near: fight before any capsule run"),
        ("AUTO_SWITCH", "Automatic weapon switching", "Weapons", "bool", 0, 1, 1, "off: he keeps the gun in hand and blasts"),
        ("GRAB_SWAP", "Shotgun/magnum after a grab", "Weapons", "bool", 0, 1, 1, ""),
        ("GRAB_DETONATE", "Set the bomb off from a grab", "Weapons", "bool", 0, 1, 1, ""),
        ("SURVIVAL_HP", "Survival mode under health", "Survival", "float", 0.1, 0.7, 0.05, ""),
        ("TABLET_HP", "Tablet at health fraction", "Survival", "float", 0.2, 0.9, 0.05, ""),
        ("TAUNTS", "Taunts", "Style", "bool", 0, 1, 1, ""),
    ],
}
MODULES = {"re5": "gbox.mercs.titles.re5_switch", "re6": "gbox.mercs.titles.re6_switch"}
MAP_IDS = {"010018100CD46000": "re5", "01002A000CD48000": "re6"}
PATH = Path(__file__).resolve().parents[2] / "gbox-data" / "mercs" / "bot-logic.json"
_lock = threading.Lock()


def _title(t) -> str:
    t = str(t or "").strip()
    t = MAP_IDS.get(t.upper(), t.lower())
    if t not in KNOBS:
        raise ValueError(f"bot_logic: no live bot logic for {t!r} (re5 / re6 Switch)")
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


def _coerce(knob: tuple, value):
    name, _, _, kind, lo, hi, step, _ = knob
    if kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "on", "yes")
        return bool(value)
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"bot_logic: {name} needs a number {lo}..{hi}") from None
    v = min(max(v, float(lo)), float(hi))
    return int(round(v)) if kind == "int" else round(v, 4)


def _module(title: str):
    return importlib.import_module(MODULES[title])


def status(title, path: Path = PATH) -> dict:
    t = _title(title)
    mod, saved = _module(t), _read(path).get(t, {})
    shipped = mod.__dict__.setdefault("_BOT_LOGIC_SHIPPED", {})
    knobs = []
    for k in KNOBS[t]:
        name = k[0]
        if not hasattr(mod, name):
            continue
        shipped.setdefault(name, getattr(mod, name))
        knobs.append({"name": name, "label": k[1], "group": k[2], "kind": k[3], "min": k[4], "max": k[5], "step": k[6],
                      "help": k[7], "value": getattr(mod, name), "default": shipped[name], "set": name in saved})
    return {"verified": True, "title": t, "knobs": knobs}


def apply_saved(title, path: Path = PATH) -> dict:
    """The saved values onto the bot module (a hot reload put the shipped ones back). -> {name: value}."""
    t = _title(title)
    mod = _module(t)
    out = {}
    with _lock:
        saved = _read(path).get(t, {})
        for k in KNOBS[t]:
            if k[0] in saved and hasattr(mod, k[0]):
                mod.__dict__.setdefault("_BOT_LOGIC_SHIPPED", {}).setdefault(k[0], getattr(mod, k[0]))
                v = _coerce(k, saved[k[0]])
                setattr(mod, k[0], v)
                out[k[0]] = v
    return out


def handle(title, values=None, reset=None, path: Path = PATH) -> dict:
    """values {name: value}: set now and saved; reset: true (every one) or [names]: back to the shipped value."""
    t = _title(title)
    mod = _module(t)
    knobs = {k[0]: k for k in KNOBS[t]}
    with _lock:
        data = _read(path)
        saved = data.setdefault(t, {})
        shipped = mod.__dict__.setdefault("_BOT_LOGIC_SHIPPED", {})
        names = list(knobs) if reset is True else list(reset or [])
        for name in names:
            if name in knobs and hasattr(mod, name):
                shipped.setdefault(name, getattr(mod, name))
                setattr(mod, name, shipped[name])
                saved.pop(name, None)
        for name, value in (values or {}).items():
            if name not in knobs or not hasattr(mod, name):
                raise ValueError(f"bot_logic: {name!r} is not a live {t} setting")
            shipped.setdefault(name, getattr(mod, name))
            v = _coerce(knobs[name], value)
            setattr(mod, name, v)
            saved[name] = v
        _write(data, path)
    return status(t, path)
