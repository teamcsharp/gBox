"""The shared Mercenaries vocabulary (docs/mercenaries_engine.md, section 1): the names every title fills from its RAM
map, marks unknown (null) or leaves to its driver ("driver"), and the signature tags the engines understand.

    from gbox.mercs import vocab
    prof = vocab.profile("G4BE08")       # the map, its mercs block, the resolved names
    prof.field("merc.timer")             # -> the map's field name, None (unknown) or "driver"
    vocab.check(prof)                    # [problems]: required names missing, a name pointing at no field ...
"""
from __future__ import annotations

from dataclasses import dataclass, field

# name -> required. Struct sub-names are "<array>.<sub>"; the array maps to a struct field, a sub-name to its sub-field.
NAMES = {
    "screen": True, "merc.stage": False, "merc.timer": True, "merc.combo": False, "merc.combo_timer": False,
    "merc.score": False, "merc.kills": False,
    "player.pos": True, "player.facing": True, "player.hp": False, "player.hp_max": False, "player.state": True,
    "player.aim_pitch": False, "player.aim_offset": False, "player.weapon": False, "player.ammo": False,
    "enemies": True, "enemies.pos": True, "enemies.facing": False, "enemies.hp": False, "enemies.hp_max": False,
    "enemies.type": False, "enemies.state": True, "enemies.act": False, "enemies.motion": False,
    "enemies.motion_frame": False, "enemies.motion_frames": False, "enemies.motion_speed": False,
    "enemies.motion_events": False, "enemies.target": False,
    "projectiles": False, "projectiles.pos": False, "projectiles.kind": False, "projectiles.owner": False,
    "prompt.kind": False, "prompt.button": False,
    "bonuses": False, "bonuses.pos": False, "bonuses.kind": False, "bonuses.taken": False, "bonuses.hp": False,
    "drops": False, "drops.pos": False, "drops.kind": False,
    "partner.pos": False, "partner.hp": False, "partner.state": False,
}
ARRAYS = ("enemies", "projectiles", "bonuses", "drops")
SCREENS = ("title", "menu", "char_select", "stage_select", "briefing", "loading", "playing", "paused", "results",
           "dead", "lost")
# signature tags (the keys a signature object may carry), by what they describe
ATTACK_KINDS = ("melee", "grab", "throw", "projectile", "explosive", "charge")
MELEE_KINDS = frozenset({"melee", "grab", "charge"})             # can be stepped out of
PHASES = ("approach", "windup", "active", "recover")
ENEMY_FLAGS = ("spawning", "acting", "down", "stunned", "dying", "gone", "hold")
PLAYER_FLAGS = ("control", "aiming", "hit", "held", "down", "action", "dead")
QTE = ("press", "mash", "dodge", "wiggle", "counter", "parry")


@dataclass
class Profile:
    """A title: its RAM map, the map's mercs block, and the vocabulary resolved against the map's fields."""
    map_id: str
    rmap: object
    mercs: dict
    names: dict = field(default_factory=dict)          # vocab name -> map field / sub-field name, None, "driver"

    def field(self, name: str):
        return self.names.get(name)

    @property
    def aim(self) -> dict:
        return dict(self.mercs.get("aim") or {})

    @property
    def units_per_m(self) -> float:
        return float(self.mercs.get("units_per_m") or 1.0)


def resolve(rmap) -> dict:
    """vocab name -> the map's field (top-level names) or sub-field (array sub-names), from the mercs block's vocab;
    a name the block leaves out falls back to the same name in the map when it exists."""
    mercs = (getattr(rmap, "spec", {}) or {}).get("mercs") or {}
    given = mercs.get("vocab") or {}
    out = {}
    for name in NAMES:
        if name in given:
            out[name] = given[name]
            continue
        if "." in name and name.split(".", 1)[0] in ARRAYS:
            out[name] = name.split(".", 1)[1]                    # the sub-field of the same name, if the array has it
        elif name in getattr(rmap, "fields", {}):
            out[name] = name
        else:
            out[name] = None
    return out


def profile(game) -> Profile:
    from .. import ram_map
    rmap = game if hasattr(game, "fields") else ram_map.load(game)
    mercs = (rmap.spec or {}).get("mercs") or {}
    return Profile(rmap.id, rmap, mercs, resolve(rmap))


def check(prof: Profile) -> list[str]:
    """What is wrong with a title's vocabulary: required names left unknown, names pointing at no field."""
    problems = []
    fields = prof.rmap.fields
    for name, required in NAMES.items():
        target = prof.names.get(name)
        if target is None:
            if required:
                problems.append(f"{name}: required, unknown")
            continue
        if target == "driver":
            continue
        if "." in name and name.split(".", 1)[0] in ARRAYS:
            arr = prof.names.get(name.split(".", 1)[0])
            if arr in (None, "driver"):
                continue
            sub = getattr(fields.get(arr), "fields", {}) or {}
            if target not in sub:
                if required:
                    problems.append(f"{name}: {arr} has no sub-field {target!r}")
            continue
        if target not in fields:
            problems.append(f"{name}: no field {target!r} in {prof.map_id}")
    return problems
