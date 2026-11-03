"""Per-boss WEAK-POINT ADVISOR for the PSO Episode I & II (GameCube, 3OE2) autoplay bot.

Operator goal: "with each boss, research and integrate the strategy for how they are
intended to be beaten ... they need to shoot and hit the exposed sections and cause
damage." This module tells the nav/combat loop WHICH boss is active, WHICH phase it is
in, and WHERE the currently-exposed weak section is (a world position to aim at), plus
the recommended technique element, action and the hazard to dodge.

It is a strict ADVISOR:
  * READ-ONLY on RAM (only ad.read_memory, via gbox.semantic.Extractor).
  * sends NO inputs and never writes memory.
  * never raises into the bot loop - any uncertainty returns {"active": False}.

Detection is built on the SAME verified model pso_campaign.py already uses: the
semantic profile `pso-gc-plus-us` enumerates the live entity table at 0x8050D460
(256 null-terminated object pointers; class name = C string at obj+0x0, position f32
x/y/z at obj+0x38/0x3C/0x40, HP u16 at obj+0x32C / max +0x2B8). Bosses are gated on the
FLOOR id (build-agent-confirmed: Ep1 11=Dragon 12=De Rol Le 13=Vol Opt 14=Dark Falz),
and on a boss floor the live "enemy"-kind entities ARE the boss and its sub-parts/adds
(regular enemies do not spawn in the boss arenas), so the weak-point target is picked
from those entities per the boss's intended strategy - no exact boss class string needed.

Public API (the nav agent wires this into its combat loop):
    from gbox.pso_boss_strategy import boss_target, boss_telemetry
    adv = boss_target(ad)
    if adv["active"]:
        aim_at(adv["weakpoint_pos"])        # {"x","z","y"} world position
        if adv["element"]: cast(adv["element"])   # "zonde"/"barta"/"foie" or None
        dodge(adv["hazard"])                # a short hazard tag or None

See WEAKPOINT_SPEC for the verified per-boss weak-point spec, and CONFIRMATION_NOTES
for what is byte-verified vs. still needs a live boss to pin down.
"""
import math

# Canonical 3OE2 globals (reused from the verified control modules so addresses stay in
# sync). All confirmed by the build agent (ad4e76ee1bfcb3a45) + live reads 2026-11-02/03.
from .pso_gc_live import PHASE, FLOOR, ENTITY_TABLE          # 0x804FE120, 0x805D5FC0, 0x8050D460
from .pso_coop_native import EPISODE, TRAVELLING, DIFFICULTY  # 0x805D6060, 0x805D49B8, 0x805D5550

DISC_ID = b"GPOE8P"                   # at 0x80000000; the only guard the advisor needs (read-only)
PROFILE_ID = "pso-gc-plus-us"
FREE_PLAY_PHASE = 14

# (episode, floor) -> boss name. episode here is the 1-based value (RAM EPISODE+1).
# Ep1 floors confirmed by the build agent; Ep2 floors from the standard PSO area-id table
# and corroborated by pso_campaign.FINAL_FLOORS (Ep1=14 DarkFalz, Ep2=13 OlgaFlow). The Ep2
# floors are flagged NEEDS_LIVE_CONFIRM in CONFIRMATION_NOTES.
BOSS_FLOORS = {
    (1, 11): "Dragon",
    (1, 12): "De Rol Le",
    (1, 13): "Vol Opt",
    (1, 14): "Dark Falz",
    (2, 14): "Barba Ray",
    (2, 15): "Gol Dragon",
    (2, 12): "Gal Gryphon",
    (2, 13): "Olga Flow",
}

# The intended strategy per boss (researched: operator spec + PSO/StrategyWiki + PSO-World
# forums; the Dark Falz elemental weaknesses F1 Zonde / F2 Barta / F3 Foie are confirmed).
#   aim    : which exposed section the bot should aim at.
#   element: recommended technique element to cast ("zonde"/"barta"/"foie"), or None (melee/any).
#   hazard : short tag the bot should dodge.
#   pick   : how to choose the weak-point entity among the live boss entities:
#            "main"    -> the main body (largest HP pool).
#            "nearest" -> the exposed/surfaced segment closest to the player.
#            a callable name resolved in _ANALYZERS for multi-phase bosses.
WEAKPOINT_SPEC = {
    "Dragon":      dict(aim="head", element=None, hazard="fire_breath_cone|burrow_eruption",
                        pick="main", note="Hit the HEAD when grounded; dodge the fire-breath cone and the "
                                          "underground burrow then eruption."),
    "De Rol Le":   dict(aim="exposed_body_segment", element=None, hazard="dive",
                        pick="nearest", note="Platform fight: hit the exposed body segments / main body "
                                             "when it surfaces; dodge its dives."),
    "Vol Opt":     dict(aim="monitors_then_core", element=None, hazard="electric_floor",
                        pick="volopt", note="Phase 1 destroy the wall monitors/pillars; Phase 2 hit the "
                                            "core's exposed glowing panel/eye; avoid electrified floor tiles."),
    "Dark Falz":   dict(aim="exposed_core", element="zonde", hazard="grab|aoe",
                        pick="darkfalz", note="3 forms: F1 weak to Zonde, F2 (beam-grab linking a player) weak "
                                              "to Barta, F3 (Hard+) weak to Foie; hit the exposed core/body; "
                                              "dodge grabs and the AoE.",
                        elements=["zonde", "barta", "foie"]),
    "Barba Ray":   dict(aim="exposed_body_head", element=None, hazard="dive|projectiles",
                        pick="nearest", note="De-Rol-Le-like: hit the exposed body/head when it surfaces; "
                                             "dodge dives and projectiles."),
    "Gol Dragon":  dict(aim="head", element=None, hazard="elemental_breath|burrow_eruption",
                        pick="main", note="Dragon-like: hit the HEAD; dodge the elemental breath."),
    "Gal Gryphon": dict(aim="body_when_close", element=None, hazard="charge_ram|projectiles",
                        pick="nearest", note="Flying beast: hit it when grounded/close; dodge its charge/ram "
                                             "and projectiles."),
    "Olga Flow":   dict(aim="exposed_core", element=None, hazard="adds|aoe",
                        pick="olga", note="2 phases plus adds (Gael/Giel): hit the exposed core/body weak "
                                          "points; clear/avoid the adds and the AoE."),
}

CONFIRMATION_NOTES = {
    "entity_model": "CONFIRMED (build agent + live 2026-11-02): entity table 0x8050D460, 256 u32 null-terminated "
                    "pointers; class = C string at obj+0x0 (read live: TObjPlayer/TObjDoorKey/TObjContainerItem); "
                    "pos f32 x/y/z at +0x38/+0x3C/+0x40; room u16 +0x28. Enumerated via gbox.semantic profile "
                    "'pso-gc-plus-us' (same path pso_campaign uses).",
    "globals": "CONFIRMED: floor *(0x805D5FC0), episode *(0x805D6060) [0=Ep1,1=Ep2], travelling *(0x805D49B8), "
               "phase *(0x804FE120)==14 free-play, difficulty *(0x805D5550).",
    "ep1_boss_floors": "CONFIRMED by build agent: 11 Dragon, 12 De Rol Le, 13 Vol Opt, 14 Dark Falz.",
    "ep2_boss_floors": "NEEDS_LIVE_CONFIRM: 12 Gal Gryphon, 13 Olga Flow, 14 Barba Ray, 15 Gol Dragon (standard "
                       "PSO area-id table; corroborated by pso_campaign.FINAL_FLOORS[2]=13).",
    "enemy_hp_offset": "NEEDS_LIVE_CONFIRM: HP u16 at +0x32C / max +0x2B8 is verified for TObjPlayer and a Forest "
                       "wolf, but the build agent flags boss structs may differ. The advisor VALIDATES hp "
                       "(0<=hp<=hp_max, hp_max>0) and, when invalid, treats the entity as alive and uses "
                       "position only - it never gates on an unverified HP read.",
    "weakpoint_subparts": "NEEDS_LIVE_CONFIRM: whether Vol Opt monitors, Dark Falz forms, De Rol Le/Barba Ray "
                          "segments and Olga adds appear as separate entity-table entries or as child objects. "
                          "The advisor assumes separate 'enemy'-kind entries on the boss floor and picks among "
                          "them; the exact sub-part class strings + any phase/state byte need a live boss. The "
                          "build agent offered to disassemble a boss update fn (via obj+0x18 vtable+0xC) once a "
                          "live boss pointer is captured - that will pin the true weak-point/phase fields.",
    "dark_falz_forms": "Element weaknesses CONFIRMED (PSO-World/StrategyWiki): F1 Zonde, F2 Barta, F3 Foie (F3 "
                       "Hard+ only). Current-form detection is a HEURISTIC (main-body HP fraction + difficulty) "
                       "pending a live form/state offset.",
}

_MIN_FINITE, _MAX_FINITE = 0.0, 1e5


# --------------------------------------------------------------------------- memory helpers (read-only, fail-soft)
def _read_u32(read, address):
    import struct
    return struct.unpack(">I", read(address, 4))[0]


def _extractor(ad):
    """A cached semantic Extractor for the live session (reuses its class-name cache)."""
    from .semantic import Extractor, load_profiles
    cached = getattr(ad, "_pso_boss_extractor", None)
    if cached is not None and cached.read == ad.read_memory:
        return cached
    profile = next((p for p in load_profiles() if p.get("id") == PROFILE_ID), None)
    if profile is None:
        raise LookupError("pso-gc-plus-us profile missing")
    ext = Extractor(profile, ad.read_memory)
    try:
        ad._pso_boss_extractor = ext
    except Exception:
        pass
    return ext


def _finite(v):
    return isinstance(v, (int, float)) and math.isfinite(v) and abs(v) < _MAX_FINITE


def _pos(e):
    x, y, z = e.get("x"), e.get("y"), e.get("z")
    if _finite(x) and _finite(y) and _finite(z):
        return {"x": float(x), "z": float(z), "y": float(y)}
    return None


def _alive(e):
    """Living = HP valid and > 0, OR HP unreadable/invalid for this struct (assume alive)."""
    hp, mx = e.get("hp"), e.get("hp_max")
    if isinstance(hp, int) and isinstance(mx, int) and 0 <= hp <= mx and mx > 0:
        return hp > 0
    return True                      # HP offset unverified for bosses: never declare a boss dead on a bad read


def _hp_fraction(e):
    hp, mx = e.get("hp"), e.get("hp_max")
    if isinstance(hp, int) and isinstance(mx, int) and 0 <= hp <= mx and mx > 0:
        return hp / mx
    return None


def _planar(a, b):
    return math.hypot(a["x"] - b["x"], a["z"] - b["z"])


# --------------------------------------------------------------------------- weak-point pickers / phase analyzers
def _pick_main(bosses, player):
    """The main body: the largest HP pool (ties -> first). Falls back to nearest when no HP."""
    graded = [b for b in bosses if isinstance(b["entity"].get("hp_max"), int) and b["entity"]["hp_max"] > 0]
    if graded:
        return max(graded, key=lambda b: b["entity"]["hp_max"])
    return _pick_nearest(bosses, player)


def _pick_nearest(bosses, player):
    if player is None:
        return bosses[0]
    return min(bosses, key=lambda b: _planar(b["pos"], player))


def _analyze_generic(name, bosses, player, difficulty):
    spec = WEAKPOINT_SPEC[name]
    chooser = _pick_main if spec["pick"] == "main" else _pick_nearest
    target = chooser(bosses, player)
    return dict(phase=spec["aim"], target=target, element=spec["element"],
                action=f"aim_{spec['aim']}", hazard=spec["hazard"], confidence="heuristic")


def _analyze_volopt(name, bosses, player, difficulty):
    # Phase 1 = several wall monitors/pillars present -> shoot the nearest living monitor.
    # Phase 2 = the core cube is what remains -> aim its exposed glowing panel (its body pos).
    if len(bosses) >= 3:
        return dict(phase="phase1_monitors", target=_pick_nearest(bosses, player), element=None,
                    action="aim_monitors", hazard="electric_floor", confidence="heuristic")
    return dict(phase="phase2_core", target=_pick_main(bosses, player), element=None,
                action="aim_core_panel", hazard="electric_floor", confidence="heuristic")


def _analyze_darkfalz(name, bosses, player, difficulty):
    target = _pick_main(bosses, player)
    frac = _hp_fraction(target["entity"])
    # Form -> element (confirmed weaknesses). Current form is a heuristic from main-body HP
    # fraction; F3 only exists on Hard+ (difficulty >= 1). Nav may also cycle all elements.
    if frac is None:
        form, element = "form1", "zonde"
    elif frac > 0.66:
        form, element = "form1", "zonde"
    elif frac > 0.33 or difficulty == 0:
        form, element = "form2", "barta"
    else:
        form, element = "form3", "foie"
    return dict(phase=form, target=target, element=element, action="aim_exposed_core",
                hazard="grab|aoe", confidence="heuristic",
                extra={"elements": WEAKPOINT_SPEC[name]["elements"]})


def _analyze_olga(name, bosses, player, difficulty):
    # Phase 2 (+ Gael/Giel adds) tends to present more live entities. Target the main body;
    # nav clears/avoids the adds. HP-based phase label is best-effort.
    phase = "phase2_with_adds" if len(bosses) >= 2 else "phase1_core"
    return dict(phase=phase, target=_pick_main(bosses, player), element=None,
                action="aim_exposed_core", hazard="adds|aoe", confidence="heuristic")


_ANALYZERS = {"volopt": _analyze_volopt, "darkfalz": _analyze_darkfalz, "olga": _analyze_olga}


# --------------------------------------------------------------------------- public API
def _inactive(reason=None):
    out = {"active": False, "boss": None, "phase": None, "weakpoint_pos": None, "weakpoint": None,
           "element": None, "action": None, "hazard": None, "episode": None, "floor": None,
           "confidence": None,
           # flat telemetry mirrors (the telemetry endpoint keeps only flat scalars)
           "boss_active": False, "boss_name": None, "boss_phase": None,
           "boss_weakpoint_locked": False, "boss_weakpoint_x": None, "boss_weakpoint_z": None}
    if reason:
        out["reason"] = reason
    return out


def boss_target(ad):
    """Advisor for the autoplay bot's combat loop. Read-only, never raises.

    Returns a dict:
      active            : bool - a boss is loaded AND at least one live boss entity is present.
      boss              : canonical boss name (BOSS_FLOORS) or None.
      phase             : phase/aim label (e.g. 'phase1_monitors', 'form1', 'head') or None.
      weakpoint_pos     : {"x","z","y"} world position to AIM AND SHOOT at, or None.
      weakpoint         : the chosen boss entity row (ptr/class/hp/hp_max/x/y/z) or None.
      element           : recommended technique element 'zonde'|'barta'|'foie' or None (melee/any).
      action            : short action hint, e.g. 'aim_head' / 'aim_monitors'.
      hazard            : short hazard tag to dodge (may be '|'-joined), or None.
      episode, floor    : the live episode (1/2) and floor id.
      confidence        : 'heuristic' (phase inferred) - see CONFIRMATION_NOTES.
      boss_active/boss_name/boss_phase/boss_weakpoint_locked/boss_weakpoint_x/boss_weakpoint_z
                        : FLAT scalar telemetry mirrors.
    On any uncertainty (not in free-play, travelling, not a boss floor, no live boss entity,
    or any read error) it returns active=False.
    """
    try:
        read = ad.read_memory
        if read(0x80000000, len(DISC_ID)) != DISC_ID:
            return _inactive("not_pso_gc_plus_us")
        if _read_u32(read, PHASE) != FREE_PLAY_PHASE:
            return _inactive("not_free_play")
        if _read_u32(read, TRAVELLING):
            return _inactive("travelling")
        episode = _read_u32(read, EPISODE) + 1
        floor = _read_u32(read, FLOOR)
        name = BOSS_FLOORS.get((episode, floor))
        if name is None:
            return _inactive("not_a_boss_floor")
        try:
            difficulty = _read_u32(read, DIFFICULTY)
        except Exception:
            difficulty = 0
        if difficulty not in range(4):
            difficulty = 0

        ents = _extractor(ad).entities()
        player = next((_pos(e) for e in ents if e.get("kind") == "player" and _pos(e)), None)
        bosses = []
        for e in ents:
            if e.get("kind") != "enemy":
                continue
            pos = _pos(e)
            if pos is None or not _alive(e):
                continue
            bosses.append({"entity": e, "pos": pos})
        if not bosses:
            return _inactive("boss_floor_no_live_boss_entity") | {"episode": episode, "floor": floor}

        spec = WEAKPOINT_SPEC[name]
        analyzer = _ANALYZERS.get(spec["pick"], None)
        result = analyzer(name, bosses, player, difficulty) if analyzer else _analyze_generic(name, bosses, player, difficulty)
        target, pos = result["target"], result["target"]["pos"]
        e = target["entity"]
        weak = {"ptr": e.get("ptr"), "class": e.get("class"), "hp": e.get("hp"),
                "hp_max": e.get("hp_max"), "x": pos["x"], "z": pos["z"], "y": pos["y"]}

        out = {"active": True, "boss": name, "phase": result["phase"], "weakpoint_pos": pos,
               "weakpoint": weak, "element": result["element"], "action": result["action"],
               "hazard": result["hazard"], "episode": episode, "floor": floor,
               "confidence": result["confidence"], "boss_entity_count": len(bosses),
               "note": spec["note"],
               # flat telemetry mirrors
               "boss_active": True, "boss_name": name, "boss_phase": result["phase"],
               "boss_weakpoint_locked": True, "boss_weakpoint_x": round(pos["x"], 2),
               "boss_weakpoint_z": round(pos["z"], 2)}
        if result.get("extra"):
            out.update(result["extra"])
        return out
    except Exception:
        return _inactive("read_error")


def boss_telemetry(ad):
    """Only the FLAT scalar telemetry keys for the telemetry endpoint."""
    adv = boss_target(ad)
    return {k: adv[k] for k in ("boss_active", "boss_name", "boss_phase",
                                "boss_weakpoint_locked", "boss_weakpoint_x", "boss_weakpoint_z")}
