"""RE5 weapon tactics. IDs come from the verified BLUS30491 weapon table.

Qualitative tactics and their sources are in docs/re5-weapon-strategy.md. Distances below are bot tuning values,
not claimed game limits or measured blast radii. A weapon preference never establishes line of sight.
"""
from dataclasses import dataclass
import math

from gbox.mercs import weapon_choice


@dataclass(frozen=True)
class Weapon:
    name: str
    family: str
    preferred_cm: float
    automatic: bool = False
    clearance_cm: float = 0.0


WEAPONS = {}


def _group(family, distance, rows, *, automatic=False, clearance=0):
    for wid, name in rows:
        WEAPONS[wid] = Weapon(name, family, distance, automatic, clearance)


_group("handgun", 1800, [(0x02, "M92F"), (0x10, "H&K P8"), (0x11, "SIG P226"),
                          (0x12, "Samurai Edge"), (0x1E, "M93R"), (0x1F, "Px4")])
_group("automatic", 1800, [(0x03, "VZ61"), (0x09, "SIG 556"), (0x13, "H&K MP5"),
                            (0x15, "Gatling gun"), (0x1D, "AK-74")], automatic=True)
_group("shotgun", 800, [(0x04, "Ithaca M37"), (0x16, "Benelli M3"), (0x17, "Jail Breaker"), (0x19, "Hydra")])
_group("rifle", 4000, [(0x05, "S75"), (0x1C, "H&K PSG-1"), (0x20, "Dragunov SVD")])
_group("magnum", 2500, [(0x0B, "S&W M29"), (0x1A, "Lightning Hawk"), (0x1B, "S&W M500")])
_group("thrown", 1000, [(0x06, "hand grenade"), (0x07, "incendiary grenade"), (0x08, "flash grenade")], clearance=500)
_group("mine", 200, [(0x0A, "proximity bomb")], clearance=500)
_group("launcher", 2500, [(0x0C, "grenade launcher")], clearance=500)
_group("rocket", 4000, [(0x0D, "rocket launcher")], clearance=700)
_group("bow", 2000, [(0x0F, "longbow")])
_group('egg',1000,[(0x36,'rotten egg')])
_group("flame", 350, [(0x21, "flamethrower")], automatic=True)
_group("melee", 150, [(0x01, "knife"), (0x0E, "knife (Sheva)"), (0x14, "knife (Excella)"),
                       (0x23, "knife (Wesker)"), (0x22, "stun rod")])
QUICK = {1: "dup", 3: "dleft", 5: "dright", 7: "ddown"}
DIRECT = frozenset({"handgun", "automatic", "shotgun", "rifle", "magnum"})
# Longshots (operator 2026-10-26: "I want the characters able to longshot foes from across the stage"): a Majini this far
# is aimed at with a weapon of these families once it has shown its laser, and fired on only with the dot on him
# (re5_combat). Bot tuning, not decoded projectile ranges. The longbow and scoped guns without a laser ray stay on the
# laserless controller and its own corridor range.
LONGSHOT_CM = {"rifle": 8000.0, "magnum": 5000.0}
ROUND_EFFECTS = {
    "explosive": "area damage", "flame": "burning area damage", "acid": "armor damage and stagger",
    "electric": "area stun", "flash": "blind stun / exposed parasite kill", "nitrogen": "freeze / stagger",
}


def longshot_reach(wid) -> float:
    """How far a laser-sighted shot with the dot on him is taken with this weapon (cm); 0 for weapons without one."""
    weapon = WEAPONS.get(wid)
    return LONGSHOT_CM.get(weapon.family, 0.0) if weapon is not None else 0.0


def quick_key(item):
    """The verified +0x1C UI position, never the inventory storage-record index."""
    grid = item.get("grid")
    return QUICK.get(grid) if type(grid) is int else None


def inventory_key(item):
    return item.get("slot"), item.get("grid"), item.get("type"), item.get("item")


def clearance(snap, impact, radius):
    """Conservative self/partner spacing at the observed impact. Health refill does not prevent knockdown."""
    positions = [(snap.get("player") or {}).get("pos")]
    partner = snap.get("partner") or {}
    positions.append(partner.get("pos") if isinstance(partner, dict) else None)
    if not impact or positions[0] is None:
        return False
    return all(math.dist(pos, impact) >= radius for pos in positions if pos is not None)


def fire_policy(wid, snap, target, impact):
    """Weapon-specific limits; the caller separately rejects measured cover and gates splash on first-hit overlap."""
    weapon = WEAPONS.get(wid)
    if weapon is None:
        return False, "unknown weapon"
    if weapon.family in DIRECT:
        return True, weapon.family
    if weapon.family in {"thrown", "mine", "bow", "egg", "melee", "flame"}:
        return False, "trajectory or contact needs its own controller (mastery_gate; the laser path never fires it)"
    if weapon.family == "launcher" and snap.get("weapon_round_type") not in ROUND_EFFECTS:
        return False, "launcher round type unverified; prefer a direct-fire gun"
    if not clearance(snap, impact, weapon.clearance_cm):
        return False, "impact too close for splash / stagger"
    return True, weapon.family


def bow_fire_policy(wid, *, corridor, aligned, loaded, wall=False):
    """The longbow has no laser. Permit ordinary aimed trigger input only on its own path.

    A linked floor corridor rejects known intervening mesh walls; it does not establish projectile visibility
    through props, dynamic actors or overhead cover. Keep that uncertainty separate from hitscan permission.
    The corridor is a soft preference (operator 2026-11-09: "if I choose to have the bot use ... a bow and arrow, they
    need to be able to spam fire that" - the corridor requirement is what kept the bow silent): without one the arrow
    still flies; only a KNOWN wall between them (wall=True, the caller's own measurement) holds it.
    """
    if wid != 0x0F:
        return False, "not the verified longbow ID"
    if wall:
        return False, "longbow: a known wall between them"
    if not loaded:
        return False, "longbow: no loaded arrow"
    if not aligned:
        return False, "longbow: aligning camera aim"
    return True, ("longbow: ordinary aimed trigger; " + ("corridor only, cover unconfirmed" if corridor else
                                                          "no floor corridor known (a soft preference), cover unconfirmed"))


def laserless_fire_policy(wid, *, corridor, aligned, loaded, wall=False):
    if wid==0x36:
        if wall or not aligned or not loaded:
            return False,'rotten egg: camera alignment and stock required, no known wall between them'
        return True,('rotten egg: ordinary aligned throw; ballistic calibration/cover/impact unconfirmed'
                     + ('' if corridor else '; no floor corridor known (a soft preference)'))
    if wid == 0x0F:
        return bow_fire_policy(wid, corridor=corridor, aligned=aligned, loaded=loaded, wall=wall)
    weapon = WEAPONS.get(wid)
    if not weapon or weapon.family not in DIRECT:
        return False, "laserless controller supports direct guns and the longbow only"
    if not corridor or not aligned or not loaded:
        return False, "laserless gun: corridor, alignment and loaded rounds required"
    return True, "laserless gun: ordinary aimed trigger; corridor only, cover unconfirmed"


def suitability(slot, snap, target):
    weapon = WEAPONS.get(slot.get("item"))
    if slot.get("type") != 1 or not weapon or not slot.get("rounds"):
        return -1000.0
    distance = math.dist(snap["player"]["pos"], target["pos"])
    family = weapon.family
    if family not in DIRECT:
        # The trajectory/round type must be demonstrated before the generic laser controller can use it.
        if family not in {"rocket", "launcher"}:
            return -1000.0
        if family == "launcher" and snap.get("weapon_round_type") not in ROUND_EFFECTS:
            return -1000.0
        if not clearance(snap, target["pos"], weapon.clearance_cm):
            return -1000.0
        return 20.0
    boss = (target.get("hp_max") or 0) >= weapon_choice.BOSS_HP_MIN
    crowd = sum(1 for e in snap.get("enemies", ()) if (e.get("hp") or 0) > 0
                and math.dist(target["pos"], e["pos"]) < weapon_choice.CROWD_RADIUS) >= weapon_choice.CROWD_COUNT
    # The shared, title-agnostic scoring rule (one policy across RE4/RE5/RE6); the
    # preferred-range penalty and loaded/clearance gates remain RE5-specific below.
    score = weapon_choice.family_score(family, distance, boss, crowd)
    score += weapon_choice.shotgun_crowd_bonus(family, crowd, distance)
    if distance > weapon.preferred_cm:
        score -= 10
    return score


CLOSE_LASER_R = 800.0                  # a target this near: a gun without a laser ray (the bow, or one whose ray has not
LASERLESS_PENALTY = 30.0               # shown) gives way to a loaded laser gun in a quick slot (operator 2026-10-26: "at close
                                       # range ... switch to it and keep the rifle for long shots only")


def best_quick_slot(snap, target, blocked=(), laserless=False):
    """Return a materially better, loaded quick-slot weapon, else None. No imaginary inventory RAM equips. laserless:
    the gun in hand has shown no laser ray (re5_combat.Combat.laserless_now) - inside CLOSE_LASER_R a laser gun wins."""
    inventory = snap.get("inventory") or ()
    current = next((w for w in inventory if w.get("hand")), None)
    score = suitability(current, snap, target) if current else -1000
    options = [w for w in inventory if not w.get("hand") and quick_key(w)
               and inventory_key(w) not in blocked]
    current_spec = WEAPONS.get((current or {}).get("item"))
    try:
        close = math.dist(snap["player"]["pos"], target["pos"]) < CLOSE_LASER_R
    except (KeyError, TypeError, ValueError):
        close = False
    if current_spec and current_spec.family == "bow" and current.get("rounds", 0) > 0 and not close:
        return None  # Preserve the character's bow at range; its controller owns aim and trigger pacing.
    if close and (laserless or (current_spec is not None and current_spec.family == "bow")):
        score -= LASERLESS_PENALTY
    if current_spec and current_spec.family in {"rocket", "rifle"}:
        magnums = [w for w in options if w.get("type") == 1 and w.get("rounds", 0) > 0
                   and w.get("item") in (0x0B, 0x1A, 0x1B)]
        if magnums:
            return max(magnums, key=lambda w: suitability(w, snap, target))
    # Spawn templates replace these guns; until the next spawn, avoid choosing another one.
    options = [w for w in options if w.get("item") not in (0x0D, 0x05, 0x1C, 0x20)]
    other = max(options, key=lambda w: suitability(w, snap, target), default=None)
    return other if other and suitability(other, snap, target) > score + 8 else None


# --- weapon mastery: one controller per family (operator 2026-11-09) ----------------------------------------------------
# "Any weapon that I choose to equip the bot with, I need the bot able to masterfully use that. So if I choose to have the
# bot use rotten eggs or a bow and arrow, they need to be able to spam fire that." Each family's controller: how it aims
# (the laser's ray, or the heading and the camera pitch where the weapon has no laser), its button pattern, the band of
# distances it fires in (closer: step back first; farther: close in at a run) and, for explosives, the self-blast
# clearance at the impact (the mines' rule: never inside his own blast). Distances, windows and lofts are bot tuning
# values, not decoded game limits (docs/research/re5-weapon-mastery.md: what to read live per family).
#   mode    laser   the hitscan guns: the Switch bot's laser-ray fight (Bot._decide / _rampage)
#           arrow   the longbow: no laser; heading + pitch to the chest, a fresh ZR press as often as the draw takes one
#           throw   rotten eggs, hand / incendiary / flash grenades: an aimed throw at the crowd's centre
#           splash  grenade launcher, rocket launcher: into the crowd from a safe distance (the dot is the impact when the
#                   laser shows; else the heading)
#           contact knives and the stun rod: in contact, L held, ZR swung
#           stream  the flamethrower: held at short range
#   pattern hold    ZR held while the gate is open (the game repeats a held trigger at the weapon's pace)
#           tap     ZR down one tick, up the next: a fresh edge every second tick while the gate is open, so the weapon's
#                   own (time-scaled) animation is what limits the rate, never a wait in the bot
#           melee   L held, ZR tapped (Type D: "L + ZR swings the knife")
@dataclass(frozen=True)
class Mastery:
    family: str
    mode: str
    min_cm: float
    max_cm: float
    pattern: str
    aim: str = "chest"
    tol_deg: float = 0.0           # the fire window (at least the body's own angular half-width at the range)
    blast_cm: float = 0.0          # self / partner clearance at the impact
    loft_deg_per_m: float = 0.0    # the throw's arc: pitch added per metre to the aim point (tuning, not ballistics)
    loft_max_deg: float = 0.0
    buttons: str = ""


MASTERY = {
    "handgun": Mastery("handgun", "laser", 0.0, 1800.0, "hold",
                       buttons="ZL held; ZR held while the laser dot or ray is on a body (held = the gun's pace x fire_rate)"),
    "automatic": Mastery("automatic", "laser", 0.0, 2500.0, "hold",
                         buttons="ZL held; ZR held through the burst while the ray stays on bodies"),
    "shotgun": Mastery("shotgun", "laser", 0.0, 1000.0, "hold",
                       buttons="ZL held; ZR held point blank into the crowd (the spread cone counts as contact)"),
    "rifle": Mastery("rifle", "laser", 300.0, 8000.0, "hold",
                     buttons="ZL held; ZR with the dot on him; far targets preferred (band cost)"),
    "magnum": Mastery("magnum", "laser", 0.0, 5000.0, "hold",
                      buttons="ZL held; ZR with the dot on him; big targets preferred (band cost)"),
    "bow": Mastery("bow", "arrow", 150.0, 2500.0, "tap", "chest", 4.0, loft_deg_per_m=0.25, loft_max_deg=6.0,
                   buttons="ZL held (the draw stance); ZR down one tick, up the next while aligned on the chest; "
                           "the heading / camera pitch re-made between arrows"),
    "egg": Mastery("egg", "throw", 200.0, 1000.0, "tap", "crowd", 6.0, loft_deg_per_m=2.0, loft_max_deg=25.0,
                   buttons="ZL held (the egg up: motions 22 / 24); ZR down one tick, up the next at the crowd's centre"),
    "thrown": Mastery("thrown", "throw", 500.0, 1200.0, "tap", "crowd", 6.0, blast_cm=500.0, loft_deg_per_m=2.0,
                      loft_max_deg=30.0,
                      buttons="ZL held; ZR down / up at the crowd's centre, never inside the self-blast distance"),
    "launcher": Mastery("launcher", "splash", 500.0, 2500.0, "tap", "crowd", 4.0, blast_cm=500.0, loft_deg_per_m=0.5,
                        loft_max_deg=10.0, buttons="ZL held; ZR down / up into the crowd from beyond its blast"),
    "rocket": Mastery("rocket", "splash", 700.0, 4000.0, "tap", "crowd", 3.0, blast_cm=700.0,
                      buttons="ZL held; ZR down / up into the crowd from beyond its blast"),
    "melee": Mastery("melee", "contact", 0.0, 160.0, "melee", "chest", 25.0,
                     buttons="closes to contact; L held, ZR down one tick, up the next while facing him"),
    "flame": Mastery("flame", "stream", 0.0, 400.0, "hold", "chest", 12.0,
                     buttons="ZL + ZR held while he is within 4 m and in front; closes in otherwise"),
}
# The flash grenade stuns and does not hurt him: no blast clearance, but not at his feet either (it blinds the crowd).
ITEM_MASTERY = {0x08: Mastery("thrown", "throw", 300.0, 1200.0, "tap", "crowd", 6.0, 0.0, 2.0, 30.0,
                              buttons="ZL held; ZR down / up at the crowd's centre (a flash: no self-blast)")}
LASER_FAMILIES = frozenset(f for f, m in MASTERY.items() if m.mode == "laser")
CROWD_AIM_R = 300.0              # the crowd's centre: the target and every living one this near him, on his level
CROWD_LEVEL_DY = 120.0
SPLASH_IMPACT_R = 200.0          # a launcher's dot this near the crowd's centre (or on a body) is on them
CORRIDOR_COST = 1.5              # a target with no floor corridor costs this much more (the bow's soft preference)
RIFLE_CLOSE_COST, RIFLE_RANGE_COST, SHOTGUN_FAR_COST, MAGNUM_BIG_COST = 1.6, 0.8, 1.5, 0.5
# The weapons' own animation motions (player +0x8F8 while that weapon is in hand), for the per-weapon rate mods
# (re5_switch_mods egg_rate / bow_rate) and the bot's no-stick-while-scaled rule. Only measured ids belong here: the egg's
# raise is 22 / 24 (live 2026-10-27 10:42, re5_switch_mods); its throw and the longbow's draw / release are NOT known yet
# - stats weapon_motions_seen (the bot, every tick the trigger is held) collects them live, to fill these sets.
EGG_RAISE_MOTIONS = frozenset({22, 24})
RATE_MOTIONS = {0x36: frozenset(), 0x0F: frozenset()}


def mastery(item):
    """The controller for the weapon in hand, None for no weapon / the proximity bomb (the mine controller's)."""
    if item in ITEM_MASTERY:
        return ITEM_MASTERY[item]
    weapon = WEAPONS.get(item)
    if weapon is None or weapon.family == "mine":
        return None
    return MASTERY.get(weapon.family)


def laser_family(item) -> bool:
    spec = mastery(item)
    return spec is not None and spec.mode == "laser"


def rate_motions(item) -> frozenset:
    return RATE_MOTIONS.get(item, frozenset())


def crowd_point(foot, enemies, radius=CROWD_AIM_R, level_dy=CROWD_LEVEL_DY):
    """The crowd's centre around one target: the mean of his feet and every living one within radius of him on his
    level -> (point, how many)."""
    group = [tuple(e["pos"]) for e in enemies or () if (e.get("hp") or 0) > 0 and e.get("pos")
             and abs(e["pos"][1] - foot[1]) <= level_dy
             and math.hypot(e["pos"][0] - foot[0], e["pos"][2] - foot[2]) <= radius]
    if not any(math.dist(g, foot) < 1.0 for g in group):
        group.append(tuple(foot))
    n = len(group)
    return tuple(sum(g[k] for g in group) / n for k in range(3)), n


def aim_pitch(spec, point, origin) -> float:
    """The pitch (rad, + = up) from the muzzle / hand to the point, plus the controller's loft for the arc."""
    flat = max(math.hypot(point[0] - origin[0], point[2] - origin[2]), 1.0)
    loft = min(spec.loft_deg_per_m * flat / 100.0, spec.loft_max_deg)
    return math.atan2(point[1] - origin[1], flat) + math.radians(loft)


def fire_tol(spec, dist, body_r=36.0) -> float:
    """The yaw window: the controller's own, or the body's half-width at this range, whichever is wider."""
    return max(math.radians(spec.tol_deg), math.atan2(body_r, max(dist, 1.0)))


def blast_ok(snap, impact, spec) -> bool:
    return not spec.blast_cm or clearance(snap, impact, spec.blast_cm)


def mastery_gate(item, *, aligned, loaded, in_band, blast=True, wall=False):
    """Permission for the non-laser controllers: aligned on the aim point, a round / stock in hand, inside the band, the
    impact clear of his own blast, no KNOWN wall between them. A missing floor corridor is not a reason (soft)."""
    spec = mastery(item)
    if spec is None or spec.mode == "laser":
        return False, "the laser path owns this weapon"
    name = WEAPONS[item].name if item in WEAPONS else spec.family
    if wall:
        return False, f"{name}: a known wall between them"
    if not loaded:
        return False, f"{name}: nothing loaded"
    if not in_band:
        return False, f"{name}: outside its band"
    if not blast:
        return False, f"{name}: the impact inside his own blast"
    if not aligned:
        return False, f"{name}: aligning"
    return True, f"{name}: {spec.pattern} ({spec.mode})"


def band_cost(item, dist, hp_max=None, corridor=None) -> float:
    """A target's cost multiplier for the weapon in hand (Bot._kcost): rifles at range, magnums on big targets, the
    shotgun near, the longbow's / throws' soft corridor preference. 1.0: no preference."""
    spec = mastery(item)
    if spec is None:
        return 1.0
    k = 1.0
    if spec.family == "rifle":
        k *= RIFLE_CLOSE_COST if dist < spec.min_cm else RIFLE_RANGE_COST
    elif spec.family == "shotgun" and dist > spec.max_cm:
        k *= SHOTGUN_FAR_COST
    if spec.family in ("magnum", "rifle", "rocket") and (hp_max or 0) >= weapon_choice.BOSS_HP_MIN:
        k *= MAGNUM_BIG_COST
    if spec.mode in ("arrow", "throw") and corridor is False:
        k *= CORRIDOR_COST
    return k
