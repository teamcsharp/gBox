"""The universal behavior axes: one named control set every Mercenaries title answers (docs/research/
universal-mercs-architecture.md, section 4; operator 2026-11-04: a circular behavior graph whose draggable dots -
aggression, weapon switching, grenade usage, mine placement, melee, knife, plus aim speed, magnum behavior and fire
rate - "customize it on the fly to adjust how the bot behaves and plays").

An axis is one dial with one meaning on every title. Each title maps it onto live knobs it already has - the native
mods of gbox.merc_live_controls.MODS and the bot-logic dials of gbox.mercs.bot_logic.KNOBS - through a bounded
transfer, "to an extent": a title that cannot express an axis greys it out (available False, with the reason), and no
axis writes outside a knob's already-vetted bounds. expand() emits exactly the job inputs the per-knob path sends
today (op "bot_logic" with its values, or a native op with its multiplier / on), so the worker side is unchanged and
an axis is live with no restart, like every knob it drives. inventory() derives each axis's current value back from
its first (primary) target, so the status a radial front end reads shows where the dots sit now - whoever moved the
underlying knob (the operator, the tuner through its own file, a profile).

Out of every axis's reach, by design:
  * the hard rules (gbox-bot-no-wall-shots-no-mine-standing): WALL_GOV, CAM_DOWN_GUARD, SHOT_TAIL_S, AIM_LOCK,
    MINE_FOE_CLEAR_CM, PROMPTS - aggression at 1.0 still may not fire at a wall or stand on a mine; those live in the
    bots, not in any knob an axis reaches;
  * the tier-a tuner's constants (gbox.mercs.tuning.PARAMS): an axis that pinned HEAL_CRITICAL or CROWD_R through
    bot-logic would override every trial (tuning.apply applies the operator's bot-logic last - their word wins), so
    the style dials and the survival trials never share a knob. tests/test_mercs_control_axes.py proves both
    exclusions against the live tables.

Not here yet, and why:
  * RE5 PS3 (BLUS30491) has no live-controls title (merc_live_controls.SWITCH maps only the Switch editions) and no
    KNOBS entry, so it needs its own rows before an axis can reach it;
  * the instant-arsenal swap (gbox.mercs.weapon_swap, branch arsenal-instant-swap) is the planned primary for
    weapon_switching and the RE5 magnum once its worker ops ("arsenal", bot_options arsenal=) assimilate to main;
    until then those axes ride the knobs each build already has, and RE5's magnum dot stays grey.

A target's transfer, (at_min, at_max) over the axis's own range:
    ("lin", at_min, at_max)   the knob moves linearly from at_min (axis at its low end) to at_max (axis at its high
                              end); at_min > at_max runs it the other way (more axis = a smaller knob)
    ("gate", threshold)       a boolean knob: on once the axis passes `threshold` of its range
    ("pass",)                 the axis value itself (the axis and the knob share units: fire_rate x, turn_speed x)
Every result is clamped to the knob's own vetted bounds and coerced the way the knob's path coerces it (ints rounded,
floats to 4 places), so the expanded value is byte-for-byte what the worker confirms back.
"""
from __future__ import annotations

import math

GROUP = "Behavior graph"
# name -> (label, low, high, step, default, help). The 0..1 axes are the radial graph's dots; aim_speed and fire_rate
# keep their native multiplier units so the dial reads the same as the knob it drives.
AXES = {
    "aggression":       ("Aggression", 0.0, 1.0, 0.05, 0.6, "push in and unload vs hold back and kite"),
    "aim_speed":        ("Aim speed", 1.0, 10.0, 0.5, 2.0, "how fast he turns onto a target (x the game's own rate)"),
    "fire_rate":        ("Fire rate", 1.0, 80.0, 1.0, 1.0, "the shot time scale (x; 1 = the game's)"),
    "magnum":           ("Magnum behavior", 0.0, 1.0, 0.05, 0.8, "magnum preference and its fire / recoil pace"),
    "weapon_switching": ("Weapon switching", 0.0, 1.0, 0.05, 0.6, "how eagerly he swaps guns for the moment"),
    "grenade_use":      ("Grenade usage", 0.0, 1.0, 0.05, 0.6, "flash / frag / incendiary frequency and throw pace"),
    "mine_place":       ("Mine placement", 0.0, 1.0, 0.05, 0.4, "mine / remote-bomb cadence while relocating"),
    "melee":            ("Melee", 0.0, 1.0, 0.05, 0.5, "quick attacks and melee follow-ups"),
    "knife":            ("Knife", 0.0, 1.0, 0.05, 0.3, "knife preference (no current build wires it)"),
}
# title -> axis -> its targets, primary first: the primary's row decides the axis's availability and shown value.
# A knob belongs to at most one axis (two dots fighting over one knob would make the last drag win silently).
MAPS = {
    "re5": {
        "aggression":       (("behavior.RAMPAGE_R", "lin", 350.0, 800.0),
                             ("behavior.UNLOAD", "gate", 0.4)),
        "aim_speed":        (("mod.turn_speed", "pass"),
                             ("behavior.HEADING_GOV_DEG_S", "lin", 120.0, 360.0)),
        "fire_rate":        (("mod.fire_rate", "pass"),),
        "weapon_switching": (("behavior.CROWD_FIRE", "gate", 0.25),
                             ("behavior.CROWD_FIRE_N", "lin", 8, 2)),
        "grenade_use":      (("behavior.GRENADES", "gate", 0.25),),
        "mine_place":       (("behavior.MINE_EVERY_S", "lin", 60.0, 3.0),
                             ("behavior.MINES", "gate", 0.2)),
    },
    "re6": {
        "aggression":       (("behavior.FIRE_ZONE_R", "lin", 300.0, 2000.0),
                             ("behavior.KITE_R", "lin", 1200.0, 400.0)),
        "aim_speed":        (("behavior.SPIN_DEG_S", "lin", 90.0, 360.0),),
        "fire_rate":        (("mod.fire_rate", "pass"),),
        "magnum":           (("mod.magnum_speed", "lin", 1.0, 6.0),),
        "weapon_switching": (("behavior.AUTO_SWITCH", "gate", 0.2),
                             ("behavior.GRAB_SWAP", "gate", 0.4)),
        "grenade_use":      (("mod.throw_speed", "lin", 1.0, 20.0),
                             ("behavior.NADES", "gate", 0.2),
                             ("behavior.FLASH", "gate", 0.15),
                             ("behavior.FLASH_N", "lin", 8, 2)),
        "mine_place":       (("behavior.BOMB_DROP", "gate", 0.3),),
        "melee":            (("mod.quick_attack", "lin", 1.0, 10.0),
                             ("behavior.PERIODIC_QA", "gate", 0.3),
                             ("behavior.HIT_QS_N", "lin", 0, 10)),
    },
}
# An axis a title cannot express yet: the grey dot's reason.
UNMAPPED = {
    ("re5", "magnum"): "RE5 Switch has no live magnum control on this build; it arrives with the instant-arsenal "
                       "swap (gbox.mercs.weapon_swap).",
    ("re5", "melee"): "RE5 Switch has no live melee dial; prompt melees (hourglass, staggers) stay automatic.",
    ("re5", "knife"): "No current build wires a knife control.",
    ("re6", "knife"): "No current build wires a knife control.",
}


def _v01(axis, value) -> float:
    _label, lo, hi = axis[0], axis[1], axis[2]
    return (float(value) - lo) / (hi - lo) if hi > lo else 0.0


def _transfer(axis, value, spec, row):
    """The knob's value for an axis at `value`, clamped to the row's vetted bounds and coerced the way the knob's own
    path coerces it (bot_logic._coerce / the native op), so verification compares equal numbers."""
    if spec[0] == "gate":
        return _v01(axis, value) >= spec[1]
    t = float(value) if spec[0] == "pass" else spec[1] + _v01(axis, value) * (spec[2] - spec[1])
    lo, hi = row.get("min"), row.get("max")
    if type(lo) in (int, float) and type(hi) in (int, float):
        t = min(max(t, lo), hi)
    return int(round(t)) if row.get("integer") else round(float(t), 4)


def _invert(axis, spec, row):
    """The axis value the primary target's current value reads back as (the dot's position), None when unreadable.
    A boolean primary reads as the midpoint of its on / off band: approximate on purpose - the dot shows which side
    of the gate the bot is on, the knob row below it shows the exact switch."""
    _label, lo, hi = axis[0], axis[1], axis[2]
    val = row.get("value")
    if spec[0] == "gate":
        if type(val) is not bool:
            return None
        th = spec[1]
        v01 = (1.0 + th) / 2 if val else th / 2
    elif spec[0] == "pass":
        if type(val) not in (int, float) or not math.isfinite(val):
            return None
        return round(min(max(float(val), lo), hi), 4)
    else:
        a, b = spec[1], spec[2]
        if type(val) not in (int, float) or not math.isfinite(val) or a == b:
            return None
        v01 = min(max((float(val) - a) / (b - a), 0.0), 1.0)
    return round(lo + v01 * (hi - lo), 4)


def inventory(title, rows) -> list:
    """The axis rows for `title`, derived from the mod. / behavior. rows control_inventory already built: the same
    row shape ({id, label, group, kind, value, available, min, max, step, help}, plus targets and a grey dot's
    reason), ready to sit in front of the per-knob rows. No controls title (another adapter / edition): none."""
    if not title or title not in MAPS and not any(t == title for t, _a in UNMAPPED):
        return []
    index = {r["id"]: r for r in rows if isinstance(r, dict) and not str(r.get("id", "")).startswith("axis.")}
    out = []
    for name, axis in AXES.items():
        label, lo, hi, step, default, help_ = axis
        mapping = MAPS.get(title, {}).get(name)
        row = {"id": "axis." + name, "label": label, "group": GROUP, "kind": "number", "value": None,
               "available": False, "min": lo, "max": hi, "step": step, "default": default, "help": help_,
               "targets": [t[0] for t in (mapping or ())]}
        if not mapping:
            row["reason"] = UNMAPPED.get((title, name)) or f"This game has no live {label.lower()} control yet."
        else:
            primary = mapping[0]
            prow = index.get(primary[0])
            if prow is None or not prow.get("available"):
                row["reason"] = (prow or {}).get("reason") or \
                    f"The worker has not reported {primary[0]} for this round yet."
            else:
                row["available"] = True
                row["value"] = _invert(axis, primary[1:], prow)
        out.append(row)
    return out


def expand(title, axis_id, value, rows):
    """An axis set -> ([(job_input, [{control, value}, ...]), ...], skipped): the ordered job inputs the existing
    per-knob path already sends (native ops first, one "bot_logic" job carrying every behavior target last), each with
    the exact values the worker must confirm back, plus the secondary targets skipped because their row is missing or
    unavailable this round. Raises ValueError exactly where change_input would: an unknown or unmapped axis, a value
    off the axis's range, or a primary target the worker cannot take."""
    name = str(axis_id).split(".", 1)[1] if "." in str(axis_id) else str(axis_id)
    axis = AXES.get(name)
    mapping = MAPS.get(title, {}).get(name) if axis else None
    if axis is None or not mapping:
        raise ValueError(UNMAPPED.get((title, name)) or f"This game has no live {name} axis.")
    _label, lo, hi = axis[0], axis[1], axis[2]
    if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{axis_id}: a number {lo:g}..{hi:g}")
    index = {r["id"]: r for r in rows if isinstance(r, dict) and not str(r.get("id", "")).startswith("axis.")}
    prow = index.get(mapping[0][0])
    if prow is None or not prow.get("available"):
        raise ValueError((prow or {}).get("reason") or
                         f"The worker has not reported {mapping[0][0]} for this round yet.")
    mods, values, behavior_targets, skipped = [], {}, [], []
    for target in mapping:
        tid, spec = target[0], target[1:]
        row = index.get(tid)
        if row is None or not row.get("available"):
            skipped.append(tid)
            continue
        want_bool = spec[0] == "gate"
        if (row.get("kind") == "boolean") is not want_bool:       # a table/knob drift: skip, never send a bad shape
            skipped.append(tid)
            continue
        tv = _transfer(axis, value, spec, row)
        kind, key = tid.split(".", 1)
        if kind == "behavior":
            values[key] = tv
            behavior_targets.append({"control": tid, "value": tv})
        else:
            inp = {"op": key, "on": tv} if row.get("kind") == "boolean" else \
                  {"op": key, "multiplier": tv, "on": tv != 1}
            mods.append((inp, [{"control": tid, "value": tv}]))
    jobs = list(mods)
    if values:
        jobs.append(({"op": "bot_logic", "values": values}, behavior_targets))
    if not jobs:
        raise ValueError(f"{axis_id}: none of its controls are available this round.")
    return jobs, skipped
