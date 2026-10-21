"""RE5 weapon tactics. IDs come from the verified BLUS30491 weapon table.

Qualitative tactics and their sources are in docs/re5-weapon-strategy.md. Distances below are bot tuning values,
not claimed game limits or measured blast radii. A weapon preference never establishes line of sight.
"""
from dataclasses import dataclass
import math


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
_group("flame", 350, [(0x21, "flamethrower")], automatic=True)
_group("melee", 150, [(0x01, "knife"), (0x0E, "knife (Sheva)"), (0x14, "knife (Excella)"),
                       (0x23, "knife (Wesker)"), (0x22, "stun rod")])
QUICK = {1: "dup", 3: "dleft", 5: "dright", 7: "ddown"}
DIRECT = frozenset({"handgun", "automatic", "shotgun", "rifle", "magnum"})
ROUND_EFFECTS = {
    "explosive": "area damage", "flame": "burning area damage", "acid": "armor damage and stagger",
    "electric": "area stun", "flash": "blind stun / exposed parasite kill", "nitrogen": "freeze / stagger",
}


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
    if weapon.family in {"thrown", "mine", "bow", "melee", "flame"}:
        return False, "trajectory or contact needs its own verified controller"
    if weapon.family == "launcher" and snap.get("weapon_round_type") not in ROUND_EFFECTS:
        return False, "launcher round type unverified; prefer a direct-fire gun"
    if not clearance(snap, impact, weapon.clearance_cm):
        return False, "impact too close for splash / stagger"
    return True, weapon.family


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
    boss = (target.get("hp_max") or 0) >= 3000
    crowd = sum(1 for e in snap.get("enemies", ()) if (e.get("hp") or 0) > 0
                and math.dist(target["pos"], e["pos"]) < 250) >= 3
    score = {"handgun": 30, "automatic": 45, "shotgun": 55 if distance <= 800 else 15,
             "rifle": 50 if distance >= 1200 else 25, "magnum": 60 if boss else 48}[family]
    if family == "shotgun" and crowd and distance <= 800:
        score += 10
    if distance > weapon.preferred_cm:
        score -= 10
    return score


def best_quick_slot(snap, target, blocked=()):
    """Return a materially better, loaded quick-slot weapon, else None. No imaginary inventory RAM equips."""
    inventory = snap.get("inventory") or ()
    current = next((w for w in inventory if w.get("hand")), None)
    score = suitability(current, snap, target) if current else -1000
    options = [w for w in inventory if not w.get("hand") and quick_key(w)
               and inventory_key(w) not in blocked]
    current_spec = WEAPONS.get((current or {}).get("item"))
    if current_spec and current_spec.family in {"rocket", "rifle"}:
        magnums = [w for w in options if w.get("type") == 1 and w.get("rounds", 0) > 0
                   and w.get("item") in (0x0B, 0x1A, 0x1B)]
        if magnums:
            return max(magnums, key=lambda w: suitability(w, snap, target))
    # Spawn templates replace these guns; until the next spawn, avoid choosing another one.
    options = [w for w in options if w.get("item") not in (0x0D, 0x05, 0x1C, 0x20)]
    other = max(options, key=lambda w: suitability(w, snap, target), default=None)
    return other if other and suitability(other, snap, target) > score + 8 else None
