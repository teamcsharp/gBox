"""Pure RE5 Reunion decisions; no RAM, pad, filesystem or network access.

Guide facts and deliberate tuning are separated in docs/re5-reunion-strategy.md.
The caller supplies verified exposure, prompts, item identity and usable controls.
Priority is a candidate-ordering hint; it never authorizes a shot through a wall.
"""
from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
import math


# RE5 Reunion facts, NOT RE6 counter rules. Award only for an observed melee kill.
MELEE_KILL_SECONDS = 5.0
CLEAR_REMAINING_SECOND_POINTS = 300


@dataclass(frozen=True)
class Policy:
    """Conservative controller tuning, not engine constants or guide guarantees."""

    critical_radius_cm: float = 350.0
    combo_reserve_s: float = 1.0
    pickup_s: float = 0.75
    at_bonus_pickup_s: float = 0.35
    critical_clock_s: float = 15.0
    heal_fraction: float = 0.4
    boss_delay_combo: int = 120
    optional_item_trip_s: float = 5.0


DEFAULT = Policy()
CRITICAL_RADIUS_CM = DEFAULT.critical_radius_cm


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    action: str | None = None


def _number(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def _player(snap):
    value = snap.get("player")
    return value if isinstance(value, Mapping) else {}


def _health(snap):
    player = _player(snap)
    hp, maximum = _number(player.get("hp")), _number(player.get("hp_max"))
    if hp is None or maximum is None or maximum <= 0 or hp < 0:
        return None
    return min(hp / maximum, 1.0)


def _active(snap):
    hp, timer = _number(_player(snap).get("hp")), _number(snap.get("timer"))
    return hp is not None and hp > 1 and timer is not None and timer > 0 and not snap.get("recovery_active")


def _distance(snap, target):
    try:
        a, b = _player(snap)["pos"], target["pos"]
        if len(a) != 3 or len(b) != 3 or any(_number(x) is None for x in (*a, *b)):
            return None
        return math.dist(a, b)
    except (KeyError, TypeError, ValueError):
        return None


def close_exposed_threat(snap: Mapping, *, policy: Policy = DEFAULT) -> bool:
    """Only explicit caller-proven exposure counts; camera proximity alone does not."""
    for enemy in snap.get("enemies") or ():
        if not isinstance(enemy, Mapping) or enemy.get("exposed") is not True:
            continue
        hp, distance = _number(enemy.get("hp")), _distance(snap, enemy)
        if hp is not None and hp > 0 and distance is not None and distance <= policy.critical_radius_cm:
            return True
    return False


def _combo_fits(snap, duration, policy):
    combo = _number(snap.get("combo"))
    if combo is None or combo < 0:
        return False  # unknown is not permission to abandon a possible chain
    if combo == 0:
        return True
    window = _number(snap.get("combo_timer"))
    return window is not None and window > duration + policy.combo_reserve_s


def detour_decision(snap: Mapping, eta, at_bonus=False, *, kind="time", gain_s=None,
                    safe=True, immediate_threat=False, policy: Policy = DEFAULT) -> Decision:
    """eta is estimated travel time until pickup, excluding its interaction.

    The combo reserve covers returning to a kill opportunity. Caller still owns
    route/collision/item validation. ``at_bonus`` never makes a stale ETA valid.
    Healing can sacrifice a combo; optional routes cannot sacrifice nearby safety.
    """
    eta = _number(eta)
    if not _active(snap) or eta is None or eta < 0 or safe is not True:
        return Decision(False, "inactive, unknown ETA, or unsafe route")
    if kind not in ("time", "combo", "heal", "grenade", "mine", "flash"):
        return Decision(False, "unsupported pickup")
    duration = eta + (policy.at_bonus_pickup_s if at_bonus else policy.pickup_s)
    timer = _number(snap.get("timer"))
    if timer <= duration:
        return Decision(False, "clock expires before pickup")
    health = _health(snap)
    if kind == "heal" and health is not None and health <= policy.heal_fraction:
        return Decision(True, "survival takes precedence over the combo", "collect_heal")
    if immediate_threat or close_exposed_threat(snap, policy=policy):
        return Decision(False, "dispatch nearby exposed threat first")
    if health is None or health <= policy.heal_fraction:
        return Decision(False, "heal or establish health before optional travel")
    if gain_s is not None:
        gain = _number(gain_s)
        if gain is None or gain <= duration:
            return Decision(False, "pickup does not repay its measured time cost")
    # A reachable clock extension can save a round that is about to time out.
    if kind == "time" and timer <= policy.critical_clock_s:
        return Decision(True, "reachable time bonus prevents imminent timeout", "collect_time")
    if not _combo_fits(snap, duration, policy):
        return Decision(False, "preserve combo or wait for a known window")
    if kind == "combo":
        combo = _number(snap.get("combo"))
        if combo is None or combo >= 50:
            return Decision(False, "Reunion combo chest adds no bonus at combo 50 or above")
    if kind in ("heal", "grenade", "mine", "flash") and eta > policy.optional_item_trip_s:
        return Decision(False, "optional item is too far from productive combat")
    return Decision(True, "safe pickup fits clock and combo budget", "collect_" + kind)


def detour_allowed(snap: Mapping, eta, at_bonus=False, **kwargs) -> bool:
    return detour_decision(snap, eta, at_bonus, **kwargs).allowed


def melee_allowed(snap: Mapping, *, eta, prompt_verified, lethal, boss=False,
                  boss_melees=0, safe=True, immediate_threat=False, policy: Policy = DEFAULT) -> bool:
    """Allow a verified lethal finisher only when it fits the remaining kill window.

    eta includes approach + animation to kill. Unknown lethality earns no presumed
    +5s. Mandatory escape/recovery QTEs must bypass this optional-melee policy.
    """
    eta = _number(eta)
    if not _active(snap) or prompt_verified is not True or lethal is not True or safe is not True:
        return False
    if eta is None or eta < 0 or eta >= _number(snap.get("timer")):
        return False
    if immediate_threat or close_exposed_threat(snap, policy=policy):
        return False
    if boss and (type(boss_melees) is not int or boss_melees != 0):
        return False  # conservative one-finisher limit; no guessed boss identity
    return _combo_fits(snap, eta, policy)


def target_priority(snap: Mapping, target: Mapping, *, exposed=False, head_exposed=False,
                    immediate_threat=False, group_count=1, policy: Policy = DEFAULT) -> float:
    """Higher means earlier acquisition. Dead/invalid targets return -infinity.

    Explicit ``is_boss`` only: max HP and geometry are not species identification.
    Nearby exposed targets dominate every optional optimization, with strictly
    decreasing priority as distance grows within that critical radius.
    """
    hp, distance = _number(target.get("hp")), _distance(snap, target)
    if hp is None or hp <= 0 or distance is None:
        return -math.inf
    exposed = exposed is True or target.get("exposed") is True
    if exposed and distance <= policy.critical_radius_cm:
        return 100_000.0 + policy.critical_radius_cm - distance
    score = 1000.0 / (1.0 + distance / 100.0)
    if immediate_threat:
        score += 10_000.0
    if exposed:
        score += 2000.0
        if head_exposed is True:
            score += 100.0
        if type(group_count) is int and group_count > 1:
            score += min(group_count - 1, 5) * 20.0
    combo, window = _number(snap.get("combo")), _number(snap.get("combo_timer"))
    urgent = combo is not None and combo > 0 and window is not None and window <= 4.0
    if urgent and exposed:
        score += 3000.0
    # Delay a verified boss only when doing so does not risk survival or the chain.
    health, timer = _health(snap), _number(snap.get("timer"))
    if (target.get("is_boss") is True and not immediate_threat and not urgent
            and health is not None and health > policy.heal_fraction
            and timer is not None and timer > policy.critical_clock_s
            and combo is not None and combo < policy.boss_delay_combo):
        score -= 500.0
    return score


def item_decision(snap: Mapping, available: Collection[str], *, heal_safe=False,
                  explosive_safe=False, mine_placement_safe=False, cluster_count=0,
                  flash_vulnerable=False, approaching_threat=False, policy: Policy = DEFAULT) -> Decision:
    """Recommend only items whose identity, availability and controls caller verified.

    Names: heal, flash, grenade, mine. Heal includes a usable herb/mixture/spray,
    never an uncombined red herb. Safety must include self/team blast clearance.
    No action here means preserve inventory; it does not mean an item was used.
    """
    if not _active(snap):
        return Decision(False, "inactive or recovery owns input")
    items = set(available)
    health = _health(snap)
    if health is not None and health <= policy.heal_fraction:
        if "heal" in items and heal_safe is True:
            return Decision(True, "use verified healing item before optional combat", "heal")
        return Decision(False, "need safe healing opportunity")
    if "flash" in items and flash_vulnerable is True and explosive_safe is True:
        return Decision(True, "verified exposed parasite target", "flash")
    if ("grenade" in items and explosive_safe is True and type(cluster_count) is int
            and cluster_count >= 3):
        return Decision(True, "verified safe cluster can be cleared together", "grenade")
    if ("mine" in items and mine_placement_safe is True and approaching_threat is True
            and not close_exposed_threat(snap, policy=policy)
            and _combo_fits(snap, policy.pickup_s, policy)):
        return Decision(True, "safe prepared approach for incoming enemies", "mine")
    return Decision(False, "preserve items until a verified useful opportunity")


# Only explicit observations are exposed. Presses, disappearance, and clock jumps
# stay separate from successful kills, confirmed pickups and attributed time gain.
_METRICS = {
    "survival": ("deaths", "revives", "heals_confirmed", "damage_taken"),
    "score": ("score",),
    "kills": ("kills", "boss_kills"),
    "combo": ("max_combo", "group_kills"),
    "time": ("elapsed_s", "timer", "time_bonus_pickups", "time_bonus_seconds", "melee_time_seconds"),
    "melee_qte": ("melee_kills", "qte_successes", "qte_presses", "finishers"),
    "items": ("herbs_acquired", "grenades_acquired", "mines_acquired", "grenades_used", "mines_used", "heals"),
    "aim": ("round_shots", "round_hits", "headshot_hits", "headshots", "radius_clears"),
    "proxies": ("kills_seen", "bonus_s", "bonuses_taken", "clock_jumps", "shots_s"),
}


def evaluate_round(observed: Mapping) -> dict:
    """Report supplied round-local facts and missing coverage, never an invented score.

    Caller must pass one round's counters, not lifetime totals. Proxies are retained
    with their names; no presses->kills, clock-jumps->melee or HP->boss conversion.
    Rank is accepted only as an observed result and never derived here from score.
    """
    metrics, missing, invalid = {}, [], []
    for names in _METRICS.values():
        for name in names:
            if name not in observed or observed[name] is None:
                missing.append(name)
                continue
            value = _number(observed[name])
            if value is None or value < 0:
                invalid.append(name)
            else:
                metrics[name] = observed[name]
    groups = {group: {name: metrics[name] for name in names if name in metrics}
              for group, names in _METRICS.items()}
    derived = {}
    shots, hits = metrics.get("round_shots"), metrics.get("round_hits")
    if shots is not None and hits is not None and shots > 0:
        if hits <= shots:
            derived["observed_hit_fraction"] = hits / shots
        else:
            invalid.append("round_hits exceeds round_shots")
    elapsed, kills = metrics.get("elapsed_s"), metrics.get("kills")
    if elapsed is not None and elapsed > 0 and kills is not None:
        derived["observed_kills_per_minute"] = kills * 60.0 / elapsed
    ended = observed.get("end_reason")
    survived = False if ended == "dead" else True if ended in ("results", "clear", "timeout") else None
    # An unranked interrupted round must not appear successful because it scored well.
    rank = observed.get("result_rank")
    rank = rank if survived is True and rank in ("D", "C", "B", "A", "S", "SS") else None
    return {"observed": groups, "derived": derived, "missing": missing, "invalid": invalid,
            "survived": survived, "result_rank": rank,
            "s_rank_observed": rank in ("S", "SS") if rank is not None else None,
            "coverage": {key: len(value) for key, value in groups.items()}}
