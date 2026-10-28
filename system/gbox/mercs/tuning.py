"""Learned per-stage tuning the RE bots read at each round start: tier (a) of the learning loop, no code change.

The server's tuner (gbox/mercs/tuner.py) writes <data>/mercs/learned/<title>/tuning.json from the measured rounds:

    {"schema": "gbox.mercs.tuning/1", "title": "010018100CD46000", "version": "3f2a...",
     "params": {"*": {"re5_switch.HEAL_CRITICAL": 0.3}, "The Mines": {"re5_switch.RELOC_CROWD_N": 5}},
     "avoid": {"The Mines": [[x, z, r_cm], ...]}}

A driver calls apply() once a round starts (its read hook) and, for relocation, steer(). apply sets only the
module constants named in PARAMS, clamped to their bounds, for the round's stage ("*" for every stage, a stage's own
entry over it), and puts every other tunable back to the value the module shipped with. It stamps the round's stats
with tuning_stage / tuning_version / tuning_params, which the Notebook keeps: the tuner reads them back to know a round
really played with a value. Nothing here raises into a bot: a missing or bad file means the shipped values.

The bot also records where a relocation stopped against a wall (note_dead_end -> dead_ends.jsonl next to the file);
the tuner turns places that keep stopping him into avoid spots, and steer() turns a relocation heading away from them.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import threading
import time

SCHEMA = 'gbox.mercs.tuning/1'
FILE, DEAD_ENDS = 'tuning.json', 'dead_ends.jsonl'
# title -> {"module.NAME": (low, high, step)}: the only names a tuning file may set, and their bounds
PARAMS = {
    '010018100CD46000': {
        're5_switch.RELOC_CROWD_N': (4, 6, -1),            # relocate out of a forming crowd sooner
        're5_switch.HEAL_CRITICAL': (0.25, 0.4, 0.05),     # heal under this whoever is near (the deferral's floor)
        're5_switch.BEHIND_R': (300.0, 450.0, 50.0),       # a Majini this near behind wins the threat pick
        're5_switch_mines.BLAST_CM': (800.0, 1200.0, 100.0),   # out of his own bomb's way within this
    },
    '01002A000CD48000': {
        're6_switch.CROWD_R': (260.0, 340.0, 20.0),        # two this near: he steps back while he fires
        're6_switch.KEEP_R': (200.0, 280.0, 20.0),         # one this near: the same
        're6_switch.TABLET_HP': (0.6, 0.8, 0.05),          # a tablet at this much health or less while free
        're6_switch.BOMB_MARGIN_CM': (200.0, 400.0, 50.0),  # the learned blast radius + this: never set off inside
    },
}
PACKAGE = 'gbox.mercs.titles.'
AVOID_MAX, STEER_DEG = 24, (30, -30, 60, -60, 90, -90)
_cache = {}                  # path -> (mtime, data)
_state = {}                  # title -> {'stage', 'version', 'avoid'}
_lock = threading.Lock()


def root(data=None) -> Path:
    """<data>/mercs/learned (the RE6 driver's learn dir parent: gbox.mercs.lessons.ROOT.parent / 'learned')."""
    if data is not None:
        return Path(data)
    from . import lessons
    return Path(lessons.ROOT).parent / 'learned'


def stage_name(names, index):
    """A driver's stage index -> its name (the tuning key), None when unknown."""
    return names[index] if isinstance(index, int) and 0 <= index < len(names) else None


def read(base, title) -> dict | None:
    """The title's tuning file, validated (None when absent or not this schema)."""
    path = Path(base) / title / FILE
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    hit = _cache.get(str(path))
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get('schema') != SCHEMA or data.get('title') != title:
        return None
    _cache[str(path)] = (mtime, data)
    return data


def clamp(title, name, value):
    """The value within the name's bounds (an int for an int bound), or None when the name is not tunable."""
    spec = PARAMS.get(title, {}).get(name)
    if spec is None or type(value) not in (int, float) or not math.isfinite(value):
        return None
    low, high, _step = spec
    value = min(max(value, low), high)
    return int(round(value)) if isinstance(low, int) and isinstance(high, int) else float(value)


def _module(name):
    mod, attr = name.rsplit('.', 1)
    return sys.modules.get(PACKAGE + mod), attr


def apply(title, stage, stats=None, base=None) -> dict:
    """Set the round's tuned constants (the driver's read hook, once a round starts). -> {name: value in force}."""
    try:
        with _lock:
            return _apply(title, stage, stats, base)
    except Exception as exc:                 # noqa: BLE001 - tuning never stops a bot
        if stats is not None:
            stats['tuning_error'] = f'{type(exc).__name__}: {exc}'[:160]
        return {}


def _apply(title, stage, stats, base):
    data = read(root(base), title) or {}
    stage = stage if isinstance(stage, str) and stage else None
    params = data.get('params') if isinstance(data.get('params'), dict) else {}
    wanted = dict(params.get('*') or {})
    if stage and isinstance(params.get(stage), dict):
        wanted.update(params[stage])
    applied = {}
    for name in PARAMS.get(title, {}):
        module, attr = _module(name)
        if module is None or not hasattr(module, attr):
            continue
        shipped = module.__dict__.setdefault('_TUNING_SHIPPED', {})
        mine = module.__dict__.setdefault('_TUNING_SET', {})
        current = getattr(module, attr)
        if attr not in shipped or mine.get(attr) != current:
            shipped[attr] = current          # first use, or the module was reloaded / changed under us
        value = clamp(title, name, wanted.get(name)) if name in wanted else None
        value = shipped[attr] if value is None else value
        setattr(module, attr, value)
        mine[attr] = value
        if value != shipped[attr]:
            applied[name] = value
    avoid = data.get('avoid') if isinstance(data.get('avoid'), dict) else {}
    spots = [s for s in (avoid.get(stage) or avoid.get('*') or [])
             if isinstance(s, list) and len(s) == 3 and all(type(v) in (int, float) for v in s)][:AVOID_MAX]
    _state[title] = {'stage': stage, 'version': data.get('version'), 'avoid': spots}
    if stats is not None:
        stats['tuning_stage'] = stage or 'unknown'
        stats['tuning_version'] = data.get('version') or 'shipped'
        stats['tuning_params'] = ','.join(f'{k.rsplit(".", 1)[1]}={v}' for k, v in sorted(applied.items()))
        stats['tuning_avoid'] = len(spots)
    try:                                     # the operator's live bot logic last: their word wins over the tuner's
        from . import bot_logic
        if str(title).upper() in bot_logic.MAP_IDS:
            ops = bot_logic.apply_saved(title)
            if stats is not None and ops:
                stats['bot_logic'] = ','.join(f'{k}={v}' for k, v in sorted(ops.items()))
    except Exception as exc:                 # noqa: BLE001 - the operator's settings never stop a round
        if stats is not None:
            stats['bot_logic_error'] = f'{type(exc).__name__}: {exc}'[:160]
    return applied


def steer(title, pos, heading, dist) -> float:
    """A relocation heading turned off the learned dead ends: the run's end point `dist` cm along `heading` from
    `pos` (x, z) inside an avoid spot tries 30, 60, 90 deg either way and takes the first clear one; else unchanged."""
    try:
        spots = (_state.get(title) or {}).get('avoid') or ()
        if not spots:
            return heading

        def blocked(h):
            x, z = pos[0] + dist * math.sin(h), pos[1] + dist * math.cos(h)
            return any(math.hypot(x - sx, z - sz) <= r for sx, sz, r in spots)
        if not blocked(heading):
            return heading
        for deg in STEER_DEG:
            h = heading + math.radians(deg)
            if not blocked(h):
                return (h + math.pi) % (2 * math.pi) - math.pi
        return heading
    except Exception:                        # noqa: BLE001
        return heading


def dead_ends(title) -> list:
    """The round's learned dead ends as (x, 0, z) points (a driver's own dead-end list, seeded at round start)."""
    return [(float(x), 0.0, float(z)) for x, z, _r in (_state.get(title) or {}).get('avoid') or ()]


def note_dead_end(title, pos, goal=None, base=None, now=None) -> None:
    """Where a relocation stopped against a wall and the goal it ran for (x, y, z), from the driver's stuck branch:
    one line in dead_ends.jsonl."""
    try:
        line = {'at': time.time() if now is None else now, 'stage': (_state.get(title) or {}).get('stage'),
                'x': round(float(pos[0])), 'z': round(float(pos[1]))}
        if goal is not None and len(goal) >= 3:
            line.update(gx=round(float(goal[0])), gz=round(float(goal[2])))
        path = root(base) / title / DEAD_ENDS
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(line) + '\n')
    except Exception:                        # noqa: BLE001
        pass
