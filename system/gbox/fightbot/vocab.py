"""The fighting engine's vocabulary: what a title's RAM map fills, in the engine's terms (docs/fighting_engine.md).

A map's `fight` block maps these names to its own fields (`"p1.hp": "p1.life"`), marks them unknown (null) or leaves
them to its Title module ("driver"). Enum fields carry `signatures` (ram_map: value -> tags) with the tags below."""
from __future__ import annotations

SCREENS = ("boot", "title", "demo", "menu", "char_select", "loading", "intro", "fight", "round_end", "continue",
           "game_over", "results", "paused", "unknown")
FIGHT_SCREENS = frozenset({"intro", "fight", "round_end"})           # the fight runner keeps going through these

GAME = {
    "screen": "enum + signatures {screen: <one of SCREENS>}, or driver: where the game is",
    "frame": "a value that changes every game frame (a counter, or a millisecond tick: fight.frame_ms)",
    "round": "the round number", "timer": "the round clock, seconds",
}
FIGHTER = {
    "hp": "health now", "hp_max": "health at full",
    "chara": "the character (enum: never identify a fighter by its looks)",
    "pos": "position x, y (up), z in world units", "side": "+1 on the left facing right, -1 on the right",
    "state": "enum + signatures: what the fighter can do now (STATE_TAGS)",
    "move": "the current move / motion id, enum + signatures: the attack tags (ATTACK_TAGS)",
    "move_class": "the move's class from the game's move table, enum + signatures (ATTACK_TAGS / STATE_TAGS)",
    "move_frame": "frames into the current move",
    "attack": "the live attack record (pointer / id, 0 = none): an attack is out",
    "attack_height": "the record's height bits, enum / flags + signatures (height)",
    "attack_start": "the record's first active frame (move-relative)", "attack_end": "its last active frame",
    "hit": "the per-frame hit result, enum + signatures {hit: landed / guarded / parried / held}",
    "input": "the fighter's input as the game read it this frame (game bits): the reaction latency is measured on it",
    "warn": "an attack-onset signal (DOA2: the opponent's attack input): rises a few frames before the hit",
}
REQUIRED = ("screen", "p1.hp", "p2.hp")

# signature tags (on enum values of move / move_class / state / hit / attack_height)
ATTACK_TAGS = {
    "attack": ("strike", "throw", "hold", "special"),
    "phase": ("startup", "active", "recovery"),
    "height": ("high", "mid", "low"),
    "limb": ("punch", "kick"),
    "active": "[first, last] active frames, move-relative",
    "lead_f": "frames from this value's onset to the first active frame (when nothing better is known)",
    "unblockable": "true: guarding doesn't stop it",
}
STATE_TAGS = ("neutral", "guard", "crouch", "air", "hitstun", "stagger", "down", "held", "holding", "throwing",
              "thrown", "ko", "can_act", "attacking", "recovery")
HIT_TAGS = ("landed", "guarded", "parried", "held", "whiffed")
CONFIDENCE = ("candidate", "static", "live")      # as ram_map: proposed by lessons / found in the code / checked live


def names() -> list[str]:
    return list(GAME) + [f"{p}.{n}" for p in ("p1", "p2") for n in FIGHTER]


def tags(field, raw) -> dict:
    """The signature tags of a field's raw value ({} when it has none)."""
    sig = getattr(field, "signatures", None) or {}
    return dict(sig.get(raw) or {}) if raw is not None else {}


def check(rmap) -> dict:
    """What a title's map fills: {filled: {name: field}, driver: [...], unknown: [...], missing: [...], errors: [...]}.
    errors: a vocab entry naming a field the map doesn't have, a required name nobody fills, a tag value outside the
    vocabulary."""
    block = (rmap.spec.get("fight") or {}) if hasattr(rmap, "spec") else {}
    vocab = block.get("vocab") or {}
    out = {"filled": {}, "driver": [], "unknown": [], "missing": [], "errors": []}
    for name in names():
        v = vocab.get(name, "missing")
        if v == "missing":
            out["missing"].append(name)
        elif v is None:
            out["unknown"].append(name)
        elif v == "driver":
            out["driver"].append(name)
        elif v not in rmap.fields:
            out["errors"].append(f"{name}: {v!r} is not a field of {rmap.id}")
        else:
            out["filled"][name] = v
    for name in set(vocab) - set(names()):
        out["errors"].append(f"{name}: not a fighting-engine name")
    for name in REQUIRED:
        if name not in out["filled"] and name not in out["driver"]:
            out["errors"].append(f"{name}: required (a field or driver)")
    for fname, f in rmap.fields.items():
        for raw, t in (getattr(f, "signatures", None) or {}).items():
            for k, allowed in (("attack", ATTACK_TAGS["attack"]), ("phase", ATTACK_TAGS["phase"]),
                               ("height", ATTACK_TAGS["height"]), ("limb", ATTACK_TAGS["limb"]),
                               ("hit", HIT_TAGS), ("screen", SCREENS)):
                if k in t and t[k] not in allowed:
                    out["errors"].append(f"{fname} {raw:#x}: {k}={t[k]!r} (one of {', '.join(allowed)})")
            for k in ("state",):
                for s in ([t[k]] if isinstance(t.get(k), str) else t.get(k) or []):
                    if s not in STATE_TAGS:
                        out["errors"].append(f"{fname} {raw:#x}: state {s!r} (one of {', '.join(STATE_TAGS)})")
    return out
