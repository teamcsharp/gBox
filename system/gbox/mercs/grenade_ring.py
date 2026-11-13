"""When the bot fires the grenade ring by itself - one rule for every Mercenaries title.

The ring (``grenade_ring`` on each title's native controller) spawns ten grenades around the player that bloom
outward and detonate. The operator (2026-10-31, 2026-11-10) wants the bot to fire it without being asked:

* when it is **surrounded**: several enemies within a few metres;
* when it faces a **boss or heavy class** (``gbox.mercs.enemy_identity`` tiers);
* when a crowd is **not thinning** (pressure that stays for seconds).

It must **never fire inside the learned blast reach of the player** (the last blasts the title's own BlastBook
measured: ``bomb_radius_cm`` / ``bomb_safe_cm`` in the live stats grow the ring's radius instead of trusting a
constant), at most once every ``cooldown_s``, and it keeps ``rings_deployed`` / ``ring_kills`` in the live stats.

The rule lives here once; a title contributes one line - ``engine.play_round`` builds ``control(ad, prof)`` and
calls it on every playing tick. Its tunables are the title module's ``RING``, ``RING_N``, ``RING_EVERY_S`` and
``RING_KIND`` constants (the PiP's bot-logic sidebar can set them) over this module's defaults.
"""
from __future__ import annotations

import importlib
import math
import random
import time

from . import enemy_identity

DEFAULTS = {
    "enabled": True,
    "min_enemies": 4,              # a crowd this size inside near_cm is "surrounded"
    # 800 (not 400): the ring places its grenades at radius_cm 600, so a lone enemy at 5 m - well inside the blast -
    # counted as nobody and the 90 s blast never fired (live 2026-11-11 23:46: RE6 ring armed, "nothing worth a ring: 0
    # within 400 cm" while the ring was due). Every enemy the ring could catch now counts toward it.
    "near_cm": 800.0,
    # the operator 2026-11-11: "at least once every two minutes ... deploying a grenade ring around them in the middle
    # of a group of enemies" - a ring is owed when this long has passed with a group on him, whatever the crowd tests
    # above say; the kind is drawn from the controller's honestly available kinds ("random ammunition types")
    # The operator 2026-11-11 17:50: "they need to be ejecting a ring of grenades or grenade launcher shots in a 360
    # blast from their area every minute and a half at least" (it was every two minutes).
    "periodic_s": 90.0,
    "periodic_min_enemies": 2,
    # a boss / dangerous class counts this far out (coached moment, request 5482 note 7, 2026-11-10: two 1500-health
    # uEm1370 and a uEm3000 coming at 5.5-6.5 m with a J'avo pack while he faced a pillar - "failing to deal with a
    # threat"; inside near_cm alone the ring never went out)
    "danger_cm": 800.0,
    "cooldown_s": 20.0,            # at most one ring this often
    # The operator 2026-11-11: "a 360 grenade launcher blast ... every minute and a half". This DEFAULTS entry is what
    # decide() puts in the decision, so while it read "flash" the periodic ring fired a flash/random throw instead of
    # the launcher the operator asked for (live 2026-11-11 23:34: ring_kind=random on RE5 with ring_armed true). A
    # title can still override it with its own RING_KIND.
    "kind": "launcher",
    "count": 10,
    "radius_cm": 600.0,
    "inner_cm": 305.0,             # 10 ft: the operator 2026-11-12, "eject them like 10 feet from the player"
    "ripple_ms": 40.0,
    "min_safe_cm": 305.0,          # never closer than 10 ft, whatever the blast book says
    "margin_cm": 250.0,            # extra clearance past the learned safe distance
    "max_radius_cm": 2500.0,       # the native ring's own ceiling
    "not_thinning_s": 8.0,         # pressure this long counts as a crowd that is not thinning
    "kill_window_s": 12.0,         # kills inside this window after a ring are attributed to it
    # The operator 2026-11-12: "also if a chainsaw boss approaches the character. Do a 360 grenade launcher 10 round
    # nitrous blast freezing the immediate enemies in the vicinity. If a boss is preparing to hit the character with a
    # kill animation, defend them with a 360 grenade nitrous blast." A chainsaw boss inside defend_cm, any boss inside
    # defend_close_cm, or a boss winding up inside defend_windup_cm earns the defensive ring at once (the kind is the
    # verified freezing round when available, otherwise an explicitly recorded
    # flash fallback. Flash stun is a different effect from nitrogen freezing.
    "defend": True,
    "defend_cm": 1000.0,           # a CHAINSAW boss this close: the kill animation is coming, ring now
    "defend_close_cm": 450.0,      # any boss this close: ring now
    "defend_windup_cm": 1500.0,    # a boss winding up an attack: ring now
}
HISTORY_MAX_S = 20.0
#: No ring in the first seconds of a round (operator's titles live 2026-11-11: the RE5 auto-ring's first attempt at
#: the round's start froze the session on a loading screen twice, 15:52 and 16:35 - the bot's own ring during the
#: spawn/load window). The ring's crowd/pressure triggers wait this long; the flash minute and the blast rules stand.
RING_START_GUARD_S = 6.0
HISTORY_ROUNDS = 32
# Switch only (operator 2026-11-10: "we should only be focusing on switch versions"): the rule runs on the three
# Switch Mercenaries titles. A PS3/GameCube/Wii session keeps whatever its own bot already did.
RING_TITLES = frozenset({"010018100CD46000", "01002A000CD48000", "010099A00BC1E000"})

# (started, count) samples per round for the "not thinning" test, keyed by the round's evidence id.
_HISTORY: dict = {}


def policy(title_module=None, stats=None) -> dict:
    """The defaults, then the title module's operator-set constants, then a ``stats['ring']`` override (tests/tools).

    Bounds are enforced here so a bad saved value can never turn the ring into a zero-radius or one-per-second tic.
    """
    out = dict(DEFAULTS)
    # A flash ring is a flash (RE5 Switch, the operator 2026-11-10: "only be able to flashbang once a minute or on a
    # slider"; "never let the bot get stunned by their own flash grenades"): the title's FLASH_MIN_GAP_S holds it too, and
    # with the title's FLASH_PLACE its first grenade goes off no nearer him than FLASH_PLACE_MIN_CM.
    if title_module is not None and not isinstance(title_module, dict):
        out.update(flash_rules(title_module))
        clear = getattr(title_module, "FLASH_PLACE_MIN_CM", None)
        if getattr(title_module, "FLASH_PLACE", False) and isinstance(clear, (int, float)):
            out["inner_cm"] = max(float(out["inner_cm"]), float(clear))
    for source in (title_module, (stats or {}).get("ring") if isinstance(stats, dict) else None):
        if source is None:
            continue
        for key, name in (("enabled", "RING"), ("min_enemies", "RING_N"), ("cooldown_s", "RING_EVERY_S"),
                          ("kind", "RING_KIND"), ("radius_cm", "RING_RADIUS_CM"),
                          ("periodic_s", "RING_PERIODIC_S")):
            value = source.get(key) if isinstance(source, dict) else getattr(source, name, None)
            if value is not None:
                out[key] = value
    try:
        out["min_enemies"] = max(1, min(int(out["min_enemies"]), 32))
        out["cooldown_s"] = max(1.0, min(float(out["cooldown_s"]), 600.0))
        out["periodic_s"] = max(0.0, min(float(out["periodic_s"]), 600.0))
        out["periodic_min_enemies"] = max(1, min(int(out["periodic_min_enemies"]), 32))
        out["radius_cm"] = max(0.0, min(float(out["radius_cm"]), float(out["max_radius_cm"])))
        out["near_cm"] = max(50.0, min(float(out["near_cm"]), 2000.0))
        out["danger_cm"] = max(out["near_cm"], min(float(out["danger_cm"]), 2000.0))
        out["defend"] = bool(out["defend"])
        out["defend_cm"] = max(100.0, min(float(out["defend_cm"]), 3000.0))
        out["defend_close_cm"] = max(50.0, min(float(out["defend_close_cm"]), 3000.0))
        out["defend_windup_cm"] = max(out["defend_cm"], min(float(out["defend_windup_cm"]), 4000.0))
        out["enabled"] = bool(out["enabled"])
        out["kind"] = str(out["kind"] or "launcher")
    except (TypeError, ValueError):
        out.update({k: DEFAULTS[k] for k in ("enabled", "min_enemies", "cooldown_s", "kind", "radius_cm",
                                             "near_cm", "danger_cm", "periodic_s", "periodic_min_enemies",
                                             "defend", "defend_cm", "defend_close_cm", "defend_windup_cm")})
    return out


def flash_rules(title_module) -> dict:
    """The title's flash rules for the ring and the scatter (RE6 / RE5 Switch, the operator 2026-11-10: "at most one
    flash per minute" and "flashes should only come in tight situations"): flash_gap_s (FLASH_MIN_GAP_S), and with
    FLASH_TIGHT the tight test - flash_tight_n flashable ones (no boss / dangerous class) within flash_tight_cm."""
    out = {}
    gap = getattr(title_module, "FLASH_MIN_GAP_S", None)
    if isinstance(gap, (int, float)) and not isinstance(gap, bool) and gap > 0:
        out["flash_gap_s"] = float(gap)
    if getattr(title_module, "FLASH_TIGHT", False):
        out["flash_tight_n"] = int(getattr(title_module, "FLASH_TIGHT_N", 4))
        out["flash_tight_cm"] = float(getattr(title_module, "FLASH_TIGHT_R", 300.0))
    if getattr(title_module, "SCATTER_FLASH_ONLY", False):
        out["flash_only"] = True
    return out


def last_flash(stats: dict) -> float | None:
    """The last flash from any source (wall clock): a gated path's stamp or a native receipt."""
    vals = [stats.get(k) for k in ("flash_stamp_at", "native_flash_confirmed_at")]
    vals = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return max(vals) if vals else None


def flash_held(snap: dict, stats: dict, policy_: dict, title: str | None) -> str | None:
    """Why a flash (a flash ring, an all-flash barrage) may not go now - the minute since the last flash, or no tight
    situation (fewer than flash_tight_n flashable ones within flash_tight_cm) - counted like the bot's own skips; None:
    it may."""
    gap, last = policy_.get("flash_gap_s"), last_flash(stats)
    if isinstance(gap, (int, float)) and last is not None and time.time() - last < gap:
        stats["flash_gap_skips"] = int(stats.get("flash_gap_skips", 0)) + 1
        return f"a flash went off {time.time() - last:.0f} s ago: one every {gap:.0f} s (FLASH_MIN_GAP_S)"
    n = policy_.get("flash_tight_n")
    if n:
        r = float(policy_.get("flash_tight_cm") or 300.0)
        tight = [e for _d, e in enemies_near(snap, r) if not dangerous(e, title)]
        if len(tight) < int(n):
            stats["flash_untight_skips"] = int(stats.get("flash_untight_skips", 0)) + 1
            return f"not tight: {len(tight)} flashable within {r:.0f} cm (FLASH_TIGHT wants {int(n)})"
    return None


def stamp_flash(stats: dict, path: str, reason: str) -> None:
    """A flash ring / barrage went off: the shared clock and its reason (FlashGate's stats names)."""
    stats["native_flash_confirmed_at"] = stats["flash_stamp_at"] = time.time()
    stats["flash_reason_last"] = f"{path}: {reason}"[:120]
    for key, k in (("flash_reasons", "surrounded"), ("flash_paths", path)):
        d = stats.get(key)
        if not isinstance(d, dict):
            d = stats[key] = {}
        d[k] = d.get(k, 0) + 1


def _player(snap: dict) -> tuple:
    player = (snap or {}).get("player")
    if isinstance(player, dict):
        pos = player.get("pos")
        if isinstance(pos, (list, tuple)) and len(pos) == 3:
            return player, tuple(float(v) for v in pos)
    return None, None


def enemies_near(snap: dict, near_cm: float) -> list:
    """[(distance_cm, enemy)] for the living enemies within near_cm of the player, nearest first."""
    player, pos = _player(snap)
    if player is None or not all(math.isfinite(v) for v in pos):
        return []
    out = []
    for enemy in (snap or {}).get("enemies") or []:
        if not isinstance(enemy, dict) or (enemy.get("hp") or 0) <= 0:
            continue
        epos = enemy.get("pos")
        if not isinstance(epos, (list, tuple)) or len(epos) != 3:
            continue
        try:
            distance = math.dist(pos, (float(epos[0]), float(epos[1]), float(epos[2])))
        except (TypeError, ValueError):
            continue
        if math.isfinite(distance) and distance <= near_cm:
            out.append((distance, enemy))
    return sorted(out, key=lambda row: row[0])


def _history(round_id, now: float) -> list:
    if not round_id:
        round_id = "unbound"
    rows = _HISTORY.setdefault(round_id, [])
    rows.append((now, 0))
    del rows[:-int(HISTORY_MAX_S * 10)]
    while len(_HISTORY) > HISTORY_ROUNDS:
        _HISTORY.pop(next(iter(_HISTORY)))
    return rows


def _not_thinning(round_id, near: int, now: float, policy_: dict) -> bool:
    """Pressure that neither grew nor fell away for not_thinning_s: a crowd the bot is not clearing."""
    rows = _HISTORY.get(round_id or "unbound")
    if not rows:
        return False
    floor = max(2, int(policy_["min_enemies"]) - 2)
    if near < floor:
        return False
    recent = [r for r in rows if now - r[0] <= float(policy_["not_thinning_s"])]
    if len(recent) < 2 or now - rows[0][0] < float(policy_["not_thinning_s"]):
        return False
    return all(count >= floor for _, count in recent)


def dangerous(enemy, title: str | None = None) -> bool:
    """A boss or a dangerous class for this title (gbox.mercs.enemy_identity's tiers), never a guess."""
    if not isinstance(enemy, dict):
        return False
    try:
        tier = enemy_identity.tier(title, enemy.get("class"), enemy.get("hp_max"))
    except Exception:                                     # noqa: BLE001 - an unknown title is not a boss
        return False
    return tier in ("boss", "dangerous")


def boss_row(enemy, title: str | None = None) -> bool:
    """A BOSS for the defensive ring: the row's own flag/tier first (a title that names it - RE4's stage set list),
    then enemy_identity's tier (RE5/RE6 by class, or by the title's own health thresholds)."""
    if not isinstance(enemy, dict):
        return False
    if enemy.get("boss") is True or str(enemy.get("tier") or "").lower() == "boss":
        return True
    try:
        return enemy_identity.tier(title, enemy.get("class"), enemy.get("hp_max")) == "boss"
    except Exception:                                     # noqa: BLE001
        return False


def chainsaw_row(enemy, title: str | None = None) -> bool:
    """A boss whose attack is a one-blow chainsaw kill (the kill animation the operator rings the nitrous for)."""
    if not isinstance(enemy, dict):
        return False
    if enemy.get("chainsaw") is True:
        return True
    if str(enemy.get("key") or "").lower() in ("salvador", "bella", "super_salvador"):
        return True
    try:
        ident = enemy_identity.identity(title, enemy.get("class"))
    except Exception:                                     # noqa: BLE001
        ident = None
    if not isinstance(ident, dict):
        return False
    text = " ".join([str(ident.get("name") or ""), *[str(a) for a in ident.get("aliases") or ()]]).lower()
    return any(word in text for word in ("chainsaw", "salvador", "bella", "ubistvo"))


#: Prefer the verified freezing shell; use an explicitly recorded defensive
#: flash fallback while a title's native shell path remains unavailable.
FREEZE_KINDS = ("shell1304",)


def defend_kind(target) -> tuple:
    """(kind, available) of the defensive ring's round: the freezing round where the title carries it, else the flash."""
    rounds = launcher_rounds(target)
    for kind, available in rounds:
        if kind in FREEZE_KINDS:
            return kind, available
    flash = [available for kind, available in rounds if kind == "flash"]
    return "flash", bool(flash and flash[0])


def observe(stats: dict, snap: dict, now: float, policy_: dict | None = None) -> dict:
    """Per-tick bookkeeping: the crowd history and the kills attributed to the last ring."""
    policy_ = policy_ or policy(stats=stats)
    # The per-round clock. round_evidence_id is the native round's identity when the driver publishes one (RE5/RE6);
    # a driver that publishes none (RE4's snapshot has no such key) used to fall back to "", so ring_round_id never
    # changed and ring_round_at was never set - the every-90-s periodic could never fire (live 2026-11-11 22:28: RE4's
    # rounds 1 and 2 ran with an empty ring_round_at). Fall back to the round counter the engine always counts.
    round_id = str(stats.get("round_evidence_id") or stats.get("rounds") or stats.get("round") or "round")
    if stats.get("ring_round_id") != round_id:
        stats["ring_round_id"] = round_id
        stats["ring_round_at"] = now
    player, pos = _player(snap)
    near = len(enemies_near(snap, float(policy_["near_cm"]))) if pos else 0
    rows = _history(round_id, now)
    if rows:
        rows[-1] = (now, near)
    stats["ring_near"] = near
    pending = stats.get("ring_pending")
    if isinstance(pending, dict):
        if now - float(pending.get("at") or 0) > float(policy_["kill_window_s"]):
            stats.pop("ring_pending", None)               # the window closed: later kills are not this ring's
        else:
            kills = snap.get("kills") if isinstance(snap, dict) else None
            if isinstance(kills, int) and isinstance(pending.get("kills"), int) and kills > pending["kills"]:
                stats["ring_kills"] = int(stats.get("ring_kills", 0)) + (kills - pending["kills"])
                pending["kills"] = kills
    return {"near": near, "round": round_id}


def decide(snap: dict, stats: dict, now: float, policy_: dict | None = None, *, title: str | None = None) -> dict:
    """Fire or not, with the reason. Pure apart from the read-only crowd history."""
    policy_ = policy_ or policy(stats=stats)
    player, pos = _player(snap)
    near_rows = enemies_near(snap, float(policy_["near_cm"])) if pos else []
    near = len(near_rows)
    round_id = stats.get("round_evidence_id") or ""
    danger_rows = enemies_near(snap, float(policy_.get("danger_cm", policy_["near_cm"]))) if pos else []
    risky = [row for row in danger_rows if dangerous(row[1], title)]
    safe_cm = max(float(stats.get("bomb_safe_cm") or 0.0), float(policy_["min_safe_cm"]))
    radius = max(float(policy_["radius_cm"]), safe_cm + float(policy_["margin_cm"]))
    out = {"fire": False, "kind": policy_["kind"], "radius_cm": round(radius, 1), "near": near,
           "dangerous": len(risky), "reason": "", "count": int(policy_["count"]),
           "inner_cm": float(policy_["inner_cm"]), "ripple_ms": float(policy_["ripple_ms"]),
           "safe_cm": round(safe_cm, 1)}
    if not policy_["enabled"]:
        return {**out, "reason": "the ring is switched off (RING)"}
    if stats.get("operator_control") is True:
        return {**out, "reason": "the operator has the pad"}
    screen = stats.get("screen") or (snap or {}).get("screen")
    if screen not in (None, "playing", "unknown"):
        return {**out, "reason": f"the round is not being played ({screen})"}
    if player is None:
        return {**out, "reason": "no player in this snapshot"}
    hp = player.get("hp")
    if isinstance(hp, (int, float)) and hp <= 0:
        return {**out, "reason": "the player is not alive"}      # the live "player is not alive" ring error, pre-empted
    round_at = stats.get("ring_round_at")
    if isinstance(round_at, (int, float)) and now - round_at < RING_START_GUARD_S:
        return {**out, "reason": (f"the round is {now - round_at:.1f} s old: the ring waits "
                                  f"{RING_START_GUARD_S:.0f} s after the start")}
    if radius > float(policy_["max_radius_cm"]):
        return {**out, "reason": (f"the learned blast reach ({safe_cm:.0f} cm) is wider than the ring can place "
                                  f"grenades ({float(policy_['max_radius_cm']):.0f} cm)")}
    last = stats.get("ring_last_at")
    if isinstance(last, (int, float)) and now - last < float(policy_["cooldown_s"]):
        return {**out, "reason": f"{float(policy_['cooldown_s']) - (now - last):.1f} s of the ring cooldown left"}
    # DEFEND (operator 2026-11-12): a chainsaw boss approaching, a boss on him, or a boss winding up a kill animation
    # earns the 360 freezing ring NOW - that is what it is for. It is checked before every crowd test (a boss can be
    # the only enemy in the snapshot) and it overrides the flash's minute (the ring places its blasts at the kind's own
    # floor, away from him, so it cannot stun him - the minute exists for the flash the bot throws at a crowd).
    if policy_.get("defend", True) and pos:
        bosses = [(d, e) for d, e in enemies_near(snap, float(policy_["defend_windup_cm"])) if boss_row(e, title)]
        if bosses:
            d_cm, boss = min(bosses, key=lambda row: row[0])
            saw = chainsaw_row(boss, title)
            windup = boss.get("windup") is True or boss.get("winding") is True or boss.get("attack") is True
            limit = float(policy_["defend_cm"] if saw else policy_["defend_close_cm"])
            if d_cm <= limit or (windup and d_cm <= float(policy_["defend_windup_cm"])):
                stats["ring_defends_owed"] = int(stats.get("ring_defends_owed", 0)) + 1
                # the outer blasts must reach HIM, not only ring the bot's own feet: the ring's radius grows to the
                # boss (a 10-round ring at 6 m would freeze the crowd and leave the chainsaw at 10 m untouched)
                reach = max(float(out["radius_cm"]), min(float(d_cm) + 300.0, float(policy_["max_radius_cm"])))
                return {**out, "fire": True, "kind": "nitrous", "defend": True, "flash_ok": True,
                        "radius_cm": round(reach, 1),
                        "reason": (f"DEFEND: {'a chainsaw boss' if saw else 'a boss'} {d_cm:.0f} cm off"
                                   f"{' winding up' if windup else ''}: the 360 {int(policy_['count'])}-round "
                                   f"freezing ring")}
    if out["kind"] == "flash":
        held = flash_held(snap, stats, policy_, title)
        if held is not None:
            return {**out, "reason": held}
        if policy_.get("flash_tight_n"):                   # tight: the surround alone (a boss ignores a flash)
            tight = [e for _d, e in enemies_near(snap, float(policy_["flash_tight_cm"])) if not dangerous(e, title)]
            return {**out, "fire": True, "reason": f"surrounded: {len(tight)} within "
                                                   f"{float(policy_['flash_tight_cm']):.0f} cm"}
    if risky:
        return {**out, "fire": True,
                "reason": f"{len(risky)} boss/dangerous within {policy_.get('danger_cm', policy_['near_cm']):.0f} cm"}
    if near >= int(policy_["min_enemies"]):
        return {**out, "fire": True, "reason": f"surrounded: {near} within {policy_['near_cm']:.0f} cm"}
    if _not_thinning(round_id, near, now, policy_):
        return {**out, "fire": True, "reason": f"a crowd of {near} is not thinning"}
    # the operator 2026-11-11: at least one ring every two minutes while a group is on him, whatever the tests above
    # said; the kind is drawn from the controller's honestly available kinds ("random ammunition types")
    periodic = float(policy_.get("periodic_s") or 0.0)
    # One enemy is enough once the timer is due: the operator asked for the blast every 90 s "throughout the match", and
    # a round that churns in under the guard/while only a straggler is near it used to skip the blast entirely (live
    # 2026-11-11: RE4 cycling rounds 9-12 with no ring telemetry at all).
    if periodic > 0 and near >= max(1, int(policy_.get("periodic_min_enemies") or 1)) and \
            (not isinstance(last, (int, float)) or now - last >= periodic):
        held = flash_held(snap, stats, policy_, title)
        # The kind stays the title's (RING_KIND, the launcher): this branch used to hardcode "random", so the 90 s ring
        # the operator asked for as a 360 grenade-launcher blast fired a random-ammunition throw instead (live
        # 2026-11-11 23:34: ring_kind=random on RE5 with ring_armed true).
        return {**out, "fire": True, "kind": out.get("kind") or RING_KIND, "flash_ok": held is None,
                "reason": (f"periodic: one ring at least every {periodic:.0f} s with a group on him: "
                           f"{near} within {policy_['near_cm']:.0f} cm")}
    return {**out, "reason": f"nothing worth a ring: {near} within {policy_['near_cm']:.0f} cm"}


def controller(ad):
    """The title's native controller - the same instance the PiP's worker uses, so its lock serializes both."""
    from . import interventions
    return interventions.native_controller(ad)


KINDS = ("flash", "hand", "incendiary", "shell1302", "shell1303", "shell1304")
#: The launcher's own round classes (RE6 grenade launcher uWp1080, items 0x133-0x135). The ring's kind "launcher"
#: draws one at random: the parameterised class spawn takes the shell's DTI, the game's projectile registration inside
#: it carries the round, and the shell's own launcher path explodes it (the wrapper's detonate refuses a shell with 0).
SHELL_KINDS = ("shell1302", "shell1303", "shell1304")
#: The launcher's rounds in the game's item order: 0x133 the Grenade round, 0x134 the Acid round, 0x135 the Nitrogen
#: round (the freeze). Operator 2026-11-11 19:49: "a 360 grenade launcher ring of Nitrogen at these enemies in order
#: to freeze everyone around them" - the Nitrogen is the crowd-control round the ring prefers when the title offers it.
LAUNCHER_PREFER = ("shell1304",)


def pick_kind(target, decision: dict) -> str | None:
    """One of the controller's honestly available kinds, at random (the operator's random grenade type).

    The controller's own `grenade_kinds()` is the source (never a title table): only `available: True` rows are in the
    pool, and a flash whose one-a-minute gate the decision closed is removed. None: nothing may be fired.
    """
    try:
        rows = target.grenade_kinds()
    except Exception:                                    # noqa: BLE001 - a controller without the report offers none
        rows = []
    kinds = [row.get("kind") for row in rows or ()
             if isinstance(row, dict) and row.get("kind") in KINDS and row.get("available") is True]
    if decision.get("flash_ok") is False:
        kinds = [kind for kind in kinds if kind != "flash"]
    return random.choice(kinds) if kinds else None


def launcher_rounds(target) -> list:
    """[(kind, available)] the launcher ring may draw for this title: the controller's own launcher_kinds()
    or its verified grenade fallback. RE5's native launcher shells have a separate lifecycle. Operator 2026-11-11 18:30:
    "I want to use the same everything across titles ... the same 360 grenade launcher blasts"."""
    try:
        try:
            rows = target.launcher_kinds()
        except (AttributeError, NotImplementedError):
            rows = target.grenade_kinds()      # a title with no launcher of its own fires its grenades
    except Exception:                                    # noqa: BLE001 - a controller without the report offers none
        return []
    return [(str(r.get("kind")), bool(r.get("available"))) for r in rows or ()
            if isinstance(r, dict) and str(r.get("kind")) in KINDS]


def fire(ad, decision: dict, stats: dict, now: float, *, ring=None, native_guard=None, flash_only=False) -> dict:
    """Run the native ring once and keep the stats. Never raises for a game-side refusal; reports it."""
    target = ring or controller(ad)
    kind = decision.get("kind") or "launcher"
    allow_unverified = False
    if str(kind).lower() == "launcher":
        # Automatic combat uses verified title capabilities. An unverified shell
        # probe previously locked RE6's native mailbox and RE4 inherited the
        # foreign shell list entirely. Explicit research requests remain separate.
        rounds = [row for row in launcher_rounds(target) if row[1]]
        if not rounds:
            try:
                rounds = [(r['kind'], True) for r in target.grenade_kinds()
                          if r.get('available') is True and r.get('kind') in KINDS]
            except (AttributeError, RuntimeError):
                rounds = []
            if rounds:
                stats['ring_launcher_fallback_note'] = 'launcher shell unverified; using a verified native grenade'
        if decision.get('flash_ok') is False:
            rounds = [row for row in rounds if row[0] != 'flash']
        if not rounds:
            stats["ring_error"] = "no verified native round kind is available for this title"
            return {"state": "refused", "reason": stats["ring_error"]}
        preferred = [r for r in rounds if r[0] in LAUNCHER_PREFER]
        kind, available = random.choice(preferred) if preferred else random.choice(rounds)
        allow_unverified = False
    if str(kind).lower() == "random":
        kind = pick_kind(target, decision)
        if kind is None:
            stats["ring_error"] = ("no grenade kind is available for the ring (none verified on this build, or the "
                                   "flash's one-a-minute gate is closed)")
            return {"state": "refused", "reason": stats["ring_error"]}
    if str(kind).lower() in ("nitrous", "freeze"):
        # Prefer a verified freezing shell. RE5 also has nitrogen ammunition;
        # its native ring still needs an independently verified shell path.
        # A defensive flash fallback is recorded as flash, never as freezing.
        kind, available = defend_kind(target)
        if not available:
            # An unverified shell cannot be used by the automatic defensive
            # rule. Keep its refusal and the actual fallback kind observable.
            stats["ring_defend_shell_refused"] = str(kind)
            kind, available = "flash", True
        allow_unverified = not available
        stats["ring_defend_kind"] = kind
        stats["ring_kind_fired"] = kind
    if flash_only and kind != 'flash':
        return {'state': 'refused', 'reason': 'background ring only supports a verified native flash'}
    module = type(target).__module__.rsplit(".", 1)[-1]
    try:
        if module == "re4_gc_native":
            receipt = target.grenade_ring(kind)          # RE4's ring picks its own count and radius
        else:
            receipt = target.grenade_ring(kind, count=decision.get("count"), radius_cm=decision.get("radius_cm"),
                                          inner_cm=decision.get("inner_cm"), ripple_ms=decision.get("ripple_ms"),
                                          allow_unverified=allow_unverified, **(native_guard or {}))
    except Exception as exc:                             # noqa: BLE001 - a refused ring is a stat, not a crash
        stats["ring_last_at"] = now
        stats["ring_error"] = f"{type(exc).__name__}: {exc}"[:200]
        # The FIRST failure survives every later "controller awaits recovery" line: it is the one that carries the
        # native mailbox state and the request offset (live 2026-11-11 19:07: the shell spawn's own error was
        # overwritten by the lock it caused).
        stats.setdefault("ring_first_failure", f"{type(exc).__name__}: {exc}"[:300])
        stats["rings_attempted"] = int(stats.get("rings_attempted", 0)) + 1
        return {"state": "failed", "reason": stats["ring_error"]}
    stats["ring_last_at"] = now
    stats["rings_attempted"] = int(stats.get("rings_attempted", 0)) + 1
    stats.pop("ring_error", None)
    confirmed = isinstance(receipt, dict) and receipt.get("state") == "confirmed"
    if confirmed:
        stats["rings_deployed"] = int(stats.get("rings_deployed", 0)) + 1
        stats["ring_kind_fired"] = receipt.get("kind", kind)
        if decision.get("defend"):
            stats["ring_defends"] = int(stats.get("ring_defends", 0)) + 1
        if receipt.get("launcher_fallback"):
            # The launcher-less loadout's fallback is a receipt fact, not a hidden one: the operator sees the flash
            # ring answering while the launcher is missing (live 2026-11-11 19:27: the shell ring's AttributeError).
            stats["ring_launcher_fallback"] = int(stats.get("ring_launcher_fallback", 0)) + 1
            stats.setdefault("ring_launcher_fallback_note", receipt["launcher_fallback"])
        stats["ring_last_detonated"] = receipt.get("detonated")
        if receipt.get("kind", kind) == "flash":
            stamp_flash(stats, "ring", decision.get("reason") or "")   # a flash like any other: its window, the gap
        kills = stats.get("kills")
        stats["ring_pending"] = {"at": now, "kills": kills if isinstance(kills, int) else None}
    else:
        stats["ring_last_failure"] = str((receipt or {}).get("reason") or "the ring did not confirm")[:200]
    return receipt if isinstance(receipt, dict) else {"state": "failed", "reason": "no receipt"}


def _scaled(snap: dict, units_per_cm: float) -> dict:
    """The snapshot in CENTIMETRES for this rule: a title whose RAM positions are millimetres (RE4 Switch, 10 per cm)
    passes units_per_cm, every other title 1.0. Without it an 8 m boss read 8000 "cm" and every threshold in this
    file (all cm) saw nothing - which is why RE4's own ring counted only enemies inside 0.8 m."""
    if not isinstance(snap, dict) or not units_per_cm or float(units_per_cm) == 1.0:
        return snap
    k = float(units_per_cm)
    out = dict(snap)
    player = out.get("player")
    if isinstance(player, dict):
        pos = player.get("pos")
        if isinstance(pos, (list, tuple)) and len(pos) == 3:
            out["player"] = {**player, "pos": [float(v) / k for v in pos]}
    enemies = out.get("enemies")
    if isinstance(enemies, list):
        rows = []
        for e in enemies:
            if isinstance(e, dict) and isinstance(e.get("pos"), (list, tuple)) and len(e["pos"]) == 3:
                rows.append({**e, "pos": [float(v) / k for v in e["pos"]]})
            else:
                rows.append(e)
        out["enemies"] = rows
    return out


def control(ad, prof, *, ring=None):
    """The engine's one-line hook: build the per-round step that decides, fires and keeps the stats.

    None for a session whose title is not one of the Switch Mercenaries ids: the rule is Switch work (2026-11-10).
    """
    if str((prof or {}).get("map_id") or "") not in RING_TITLES:
        return None
    title_mod = None
    try:
        title_mod = importlib.import_module((prof or {}).get("menus") or "")
    except Exception:                                    # noqa: BLE001 - a title without its own module: defaults
        title_mod = None
    title = (prof or {}).get("map_id")
    try:
        units = float((prof or {}).get("units_per_cm") or 1.0)
    except (TypeError, ValueError):
        units = 1.0
    reactions = None
    if title == '010099A00BC1E000':
        from .re4_reactive_ring import Reactions
        reactions = Reactions()
    # RE5's native flash path already reanchors each blast to the live player.
    # Its multi-call batch can run beside ordinary movement/aiming. No other
    # title or damaging round is admitted to this background path.
    from .async_flash_ring import Flight
    flight = Flight() if title == '010018100CD46000' and (ring is None or getattr(ring, 'async_flash_ring', False)) else None
    re5_reactions = None
    if flight is not None:
        from .re5_reactive_ring import Reactions
        re5_reactions = Reactions()

    def react(snap, stats, now):
        """Before prompt handling: fresh RE5 hit/QTE edges never wait for the periodic timer."""
        event = re5_reactions.observe(snap, stats, now)
        result = flight.poll(snap, stats)
        if result is not None:
            if result.get('reactive') and result.get('receipt') is not None:
                receipt = result['receipt']
                stats['reactive_ring_receipt'] = {k: receipt.get(k) for k in
                    ('state', 'verified', 'kind', 'requested', 'detonated', 'reason', 'self_damage')}
                stats['reactive_ring_receipt']['event'] = result.get('reactive_event')
            return result
        if event is None:
            return None
        policy_ = policy(title_mod, stats)
        if not policy_['enabled']:
            re5_reactions.consume(event, stats, 'ring disabled')
            return None
        # A native mine or an already requested flash owns the same native
        # mailbox. Keep only the fresh event; no blocked worker or pad pause.
        if stats.get('bot_grenade_state') == 'requested' or stats.get('native_mine_pending'):
            stats['reactive_ring_wait'] = 'another native defensive action is pending'
            return {'fire': False, 'pending': True, 'reason': stats['reactive_ring_wait']}
        decision = decide(snap, stats, now, policy_, title=title)
        if decision['radius_cm'] > policy_['max_radius_cm'] or (snap.get('player') or {}).get('hp', 0) <= 1:
            re5_reactions.consume(event, stats, 'native flash requires a living player and supported clearance')
            return None
        decision.update(re5_reactions.decision(event))
        result = flight.submit(snap, stats, decision, now,
            lambda d, s, t, guard: fire(ad, d, s, t, ring=ring, native_guard=guard, flash_only=True))
        if result.get('pending'):
            re5_reactions.consume(event, stats, 'submitted')
            stats['reactive_ring_requests'] = int(stats.get('reactive_ring_requests') or 0) + 1
        return result

    def step(snap: dict, stats: dict, now: float, hold=None) -> dict:
        if re5_reactions is not None:
            result = react(snap, stats, now)
            if result is not None:
                return result
        if flight is not None:
            result = flight.poll(snap, stats)
            if result is not None:
                return result
        view = _scaled(snap, units)                      # the rule speaks cm; RE4's RAM speaks mm
        policy_ = policy(title_mod, stats)
        observe(stats, view, now, policy_)
        decision = decide(view, stats, now, policy_, title=title)
        event = reactions.observe(view, stats, now) if reactions is not None else None
        if event is not None and policy_['enabled'] and decision['radius_cm'] <= policy_['max_radius_cm']:
            # Damage and a new grab must not wait behind the periodic 90-second
            # ring, its start delay, or its crowd/flash cooldown. Native build,
            # allocation, player-life and blast-clearance checks still apply.
            decision = {**decision, **event, 'fire': True, 'flash_ok': True,
                        'reactive': True, 'ripple_ms': 0.0}
        stats["ring_decision"] = (decision["reason"] if not decision["fire"] else "fire: " + decision["reason"])[:200]
        # The kind is recorded with the ATTEMPT, not only with the receipt: a session that rotates or ends mid-fire used
        # to leave ring_kind_fired empty while rings_attempted had counted the attempt, so the operator's 360 ring
        # looked like it never chose a kind (live 2026-11-11 22:47 RE5 1/ and 23:07 RE6 1/ both lost their outcome).
        if decision.get("fire"):
            stats["ring_kind_fired"] = str(decision.get("kind") or "")
        if not decision["fire"]:
            if title in SCATTER_TITLES:                      # no ring this tick: the scatter barrage's own rule
                return scatter_step(view, stats, now, hold)
            return decision
        if flight is not None:
            if stats.get('bot_grenade_state') == 'requested':
                return {'fire': False, 'reason': 'a native flash request is already pending'}
            return flight.submit(snap, stats, decision, now,
                lambda d, s, t, guard: fire(ad, d, s, t, ring=ring, native_guard=guard, flash_only=True))
        if hold is not None and hold(set()) is False:
            return {**decision, "fire": False, "reason": "the bot's keys did not release before the ring"}
        try:
            receipt = fire(ad, decision, stats, now, ring=ring)
        except Exception as exc:                         # noqa: BLE001 - a ring never ends the round
            stats["ring_error"] = f"{type(exc).__name__}: {exc}"[:200]
            return {**decision, "fire": False, "reason": stats["ring_error"]}
        decision = {**decision, "attempted": True, "fired": receipt.get('state') == 'confirmed', "receipt": receipt}
        if decision.get('reactive'):
            stats['reactive_ring_receipt'] = {k: receipt.get(k) for k in
                ('state', 'verified', 'kind', 'requested', 'detonated', 'reason', 'self_damage')}
        stats["ring_last_reason"] = decision["reason"][:200]
        return decision

    def scatter_step(snap, stats, now, hold=None) -> dict:
        sp = scatter_policy(title_mod, stats)
        observe_scatter(stats, snap, now, sp)
        decision = decide_scatter(snap, stats, now, sp, title=title)
        stats["scatter_decision"] = (decision["reason"] if not decision["fire"] else "fire: " + decision["reason"])[:200]
        if not decision["fire"]:
            return decision
        if flight is not None:
            if stats.get('bot_grenade_state') == 'requested':
                return {'fire': False, 'reason': 'a native flash request is already pending'}
            return flight.submit(snap, stats, decision, now,
                lambda d, s, t, guard: fire_scatter(ad, d, s, t, ring=ring, units=units,
                                                   native_guard=guard, flash_only=True), operation='scatter')
        if hold is not None and hold(set()) is False:
            return {**decision, "fire": False, "reason": "the bot's keys did not release before the barrage"}
        try:
            receipt = fire_scatter(ad, decision, stats, now, ring=ring, units=units)
        except Exception as exc:                         # noqa: BLE001 - a barrage never ends the round
            stats["scatter_error"] = f"{type(exc).__name__}: {exc}"[:200]
            return {**decision, "fire": False, "reason": stats["scatter_error"]}
        return {**decision, "fired": receipt.get('state') == 'confirmed', "receipt": receipt}

    if flight is not None:
        step.observe = flight.observe
        step.close = flight.close
        step.react = react
    return step


# --- the scatter barrage (RE6 Switch, operator 2026-11-10 ~07:00) ----------------------------------------------------
# "i want the bot able to spray a scatter shot of grenades from his postion at threats at will ... a rapid barrage of
# random grenades ... without equipping it on his character ... whenever the going gets tough": re6_switch_native
# .grenade_scatter (a cone of native grenades from him toward the threats, nothing equipped), fired when he is
# surrounded, was hurt in the last hurt_s with a threat within near_cm, a boss / dangerous class is within reach_cm,
# or a pack of min_pack within reach_cm is not thinning - at most every cooldown_s (the title's SCATTER_EVERY_S), never
# its explosive kinds inside the learned reach (bomb_safe_cm goes to the controller). stats scatters_fired,
# scatter_rounds, scatter_kills (inside kill_window_s after one), scatter_failures, scatter_decision.
SCATTER_TITLES = frozenset({"01002A000CD48000", "010018100CD46000", "010099A00BC1E000"})   # RE6, RE5 and RE4 Switch
SCATTER_DEFAULTS = {"enabled": True, "cooldown_s": 12.0, "count": 8, "near_cm": 500.0, "reach_cm": 1500.0,
                    "floor_dy_cm": 150.0, "hurt_s": 3.0, "min_pack": 3, "surround_n": 4, "surround_cm": 400.0,
                    "kill_window_s": 8.0, "toward_n": 6, "after_ring_s": 6.0,   # (no barrage right after a ring)
                    # The launcher's rounds first, Nitrogen (shell1304) ahead of the rest: the operator's "the same
                    # everything across titles - the same 360 grenade launcher blasts". While this read ("flash",) the
                    # barrage that fires when the ring does not was a flash throw (live 2026-11-11 23:48: RE6 ring
                    # deployed with kind=flash although every title declares RING_KIND 'launcher'). A title's
                    # scatter_kinds() still overrides this set.
                    "kinds": ("shell1304", "shell1303", "shell1302", "hand", "incendiary", "flash")}


def scatter_policy(title_module=None, stats=None) -> dict:
    out = dict(SCATTER_DEFAULTS)
    for source in (title_module, (stats or {}).get("scatter") if isinstance(stats, dict) else None):
        if source is None:
            continue
        for key, name in (("enabled", "SCATTER"), ("cooldown_s", "SCATTER_EVERY_S"), ("count", "SCATTER_N")):
            value = source.get(key) if isinstance(source, dict) else getattr(source, name, None)
            if value is not None:
                out[key] = value
        if not isinstance(source, dict):
            out.update(flash_rules(source))
    hook = getattr(title_module, "scatter_kinds", None) if title_module is not None else None
    if callable(hook):
        try:                                              # the title's native verified set (checkpoint C extends it)
            out["kinds"] = tuple(str(k) for k in hook())
        except Exception:                                 # noqa: BLE001 - no native module: the flash is the default
            pass
    try:
        out["enabled"] = bool(out["enabled"])
        out["cooldown_s"] = max(1.0, min(float(out["cooldown_s"]), 600.0))
        out["count"] = max(1, min(int(out["count"]), 16))
        out["kinds"] = tuple(k for k in (out.get("kinds") or ("flash",)) if isinstance(k, str) and k) or ("flash",)
    except (TypeError, ValueError):
        out.update({k: SCATTER_DEFAULTS[k] for k in ("enabled", "cooldown_s", "count", "kinds")})
    return out


def observe_scatter(stats: dict, snap: dict, now: float, policy_: dict | None = None) -> None:
    """Per tick: when his health last fell (the "hurt" trigger) and the kills inside the window after a barrage."""
    policy_ = policy_ or scatter_policy(stats=stats)
    player, _pos = _player(snap)
    hp = (player or {}).get("hp")
    if isinstance(hp, int):
        prev = stats.get("scatter_hp_prev")
        if isinstance(prev, int) and hp < prev:
            stats["scatter_hurt_at"] = now
        stats["scatter_hp_prev"] = hp
    pending = stats.get("scatter_pending")
    if isinstance(pending, dict):
        if now - float(pending.get("at") or 0) > float(policy_["kill_window_s"]):
            stats.pop("scatter_pending", None)
        else:
            kills = snap.get("kills") if isinstance(snap, dict) else None
            if isinstance(kills, int) and isinstance(pending.get("kills"), int) and kills > pending["kills"]:
                stats["scatter_kills"] = int(stats.get("scatter_kills", 0)) + (kills - pending["kills"])
                pending["kills"] = kills


def decide_scatter(snap: dict, stats: dict, now: float, policy_: dict | None = None, *, title: str | None = None) -> dict:
    """Fire the barrage or not, with the reason (pure apart from the crowd history the ring's observe keeps)."""
    policy_ = policy_ or scatter_policy(stats=stats)
    player, pos = _player(snap)
    kinds = tuple(policy_.get("kinds") or ("flash",))
    out = {"fire": False, "count": int(policy_["count"]), "toward": [], "reason": "", "kinds": list(kinds),
           "safe_cm": float(stats.get("bomb_safe_cm") or 0.0)}
    if not policy_["enabled"]:
        return {**out, "reason": "the barrage is switched off (SCATTER)"}
    if stats.get("operator_control") is True:
        return {**out, "reason": "the operator has the pad"}
    screen = stats.get("screen") or (snap or {}).get("screen")
    if screen not in (None, "playing", "unknown"):
        return {**out, "reason": f"the round is not being played ({screen})"}
    if player is None:
        return {**out, "reason": "no player in this snapshot"}
    ring_last = stats.get("ring_last_at")
    if isinstance(ring_last, (int, float)) and now - ring_last < float(policy_["after_ring_s"]):
        return {**out, "reason": "a ring just went out"}
    last = stats.get("scatter_last_at")
    if isinstance(last, (int, float)) and now - last < float(policy_["cooldown_s"]):
        return {**out, "reason": f"{float(policy_['cooldown_s']) - (now - last):.1f} s of the barrage cooldown left"}
    rows = [(d, e) for d, e in enemies_near(snap, float(policy_["reach_cm"]))
            if abs(float(e["pos"][1]) - pos[1]) <= float(policy_["floor_dy_cm"])]   # on his floor: never the void
    if not rows:
        return {**out, "reason": "no threat on his floor within reach"}
    # Checkpoint D1 - the one flash clock. A barrage whose every round is a flash is held by FLASH_MIN_GAP_S exactly
    # like the ring; a mixed barrage leaves the flash out inside the gap instead of refusing outright (so a verified
    # non-flash kind can still answer the tough moment).
    gap = policy_.get("flash_gap_s")
    last = last_flash(stats)
    if "flash" in kinds and isinstance(gap, (int, float)) and gap and last is not None \
            and time.time() - last < gap:
        held = f"a flash went off {time.time() - last:.0f} s ago: one every {gap:.0f} s (FLASH_MIN_GAP_S)"
        stats["flash_gap_skips"] = int(stats.get("flash_gap_skips", 0)) + 1
        remaining = tuple(k for k in kinds if k != "flash")
        if not remaining:
            return {**out, "reason": held}
        out.update(kinds=list(remaining), flash_held=held, narrowed=True)
    if policy_.get("flash_only"):                         # every round of it a flash: the flash rules hold it
        held = flash_held(snap, stats, policy_, title)
        if held is not None:
            return {**out, "reason": held}
        if policy_.get("flash_tight_n"):
            out["toward"] = [(float(e["pos"][0]), float(e["pos"][2])) for _d, e in rows[:int(policy_["toward_n"])]]
            return {**out, "fire": True, "flash": True,
                    "reason": f"surrounded: {int(policy_['flash_tight_n'])}+ within {float(policy_['flash_tight_cm']):.0f} cm"}
    if all(k == "flash" for k in out["kinds"]):           # a barrage that is all flash stamps the clock when it goes
        out["flash"] = True
    out["toward"] = [(float(e["pos"][0]), float(e["pos"][2])) for _d, e in rows[:int(policy_["toward_n"])]]
    near = sum(1 for d, _e in rows if d <= float(policy_["near_cm"]))
    surround = sum(1 for d, _e in rows if d <= float(policy_["surround_cm"]))
    hurt = stats.get("scatter_hurt_at")
    if surround >= int(policy_["surround_n"]):
        return {**out, "fire": True, "reason": f"surrounded: {surround} within {policy_['surround_cm']:.0f} cm"}
    if isinstance(hurt, (int, float)) and now - hurt <= float(policy_["hurt_s"]) and near:
        return {**out, "fire": True,
                "reason": f"hurt {now - hurt:.1f} s ago with {near} within {policy_['near_cm']:.0f} cm"}
    risky = [e for _d, e in rows if dangerous(e, title)]
    if risky:
        return {**out, "fire": True, "reason": f"{len(risky)} boss/dangerous within {policy_['reach_cm']:.0f} cm"}
    round_id = stats.get("round_evidence_id") or ""
    if len(rows) >= int(policy_["min_pack"]) and _not_thinning(round_id, len(rows), now,
                                                             {**DEFAULTS, "min_enemies": int(policy_["min_pack"]) + 2}):
        return {**out, "fire": True, "reason": f"a pack of {len(rows)} is not thinning"}
    return {**out, "reason": f"nothing tough: {len(rows)} within {policy_['reach_cm']:.0f} cm"}


def fire_scatter(ad, decision: dict, stats: dict, now: float, *, ring=None, units: float = 1.0,
                 native_guard=None, flash_only=False) -> dict:
    """The native barrage once, with the stats. Never raises for a game-side refusal."""
    target = ring or controller(ad)
    stats["scatter_last_at"] = now
    if not callable(getattr(target, "grenade_scatter", None)):
        stats["scatter_failures"] = int(stats.get("scatter_failures", 0)) + 1
        stats["scatter_last_failure"] = "this title's native controller has no scatter barrage"
        return {"state": "unavailable", "reason": stats["scatter_last_failure"]}
    toward = decision.get("toward") or None
    if toward and units and float(units) != 1.0:
        # `toward` is in the TITLE's own units (RE4: mm): the decision was made on the cm view, so put the points back
        toward = [(float(x) * float(units), float(z) * float(units)) for x, z in toward]
    options = {"count": decision.get("count"), "toward": toward,
               "safe_cm": decision.get("safe_cm")}
    if decision.get("narrowed") and decision.get("kinds"):
        options["kinds"] = tuple(decision["kinds"])
    if flash_only:
        if decision.get('flash_ok') is False or ('kinds' in options and 'flash' not in options['kinds']):
            return {'state': 'refused', 'reason': 'background scatter requires an allowed verified flash'}
        options['kinds'] = ('flash',)
    options.update(native_guard or {})
    try:
        receipt = target.grenade_scatter("random", **options)
    except Exception as exc:                             # noqa: BLE001
        stats["scatter_failures"] = int(stats.get("scatter_failures", 0)) + 1
        stats["scatter_last_failure"] = f"{type(exc).__name__}: {exc}"[:200]
        return {"state": "failed", "reason": stats["scatter_last_failure"]}
    if isinstance(receipt, dict) and receipt.get("state") == "confirmed":
        fired = receipt.get("kinds")
        if not isinstance(fired, (list, tuple)):
            fired = ["flash"] if decision.get("flash") else []
        if decision.get("flash") or "flash" in [str(k) for k in fired]:
            stamp_flash(stats, "scatter", decision.get("reason") or "")   # one clock: the title's own rules wait too
        stats["scatters_fired"] = int(stats.get("scatters_fired", 0)) + 1
        stats["scatter_rounds"] = int(stats.get("scatter_rounds", 0)) + int(receipt.get("detonated") or 0)
        kills = stats.get("kills")
        stats["scatter_pending"] = {"at": now, "kills": kills if isinstance(kills, int) else None}
    else:
        stats["scatter_failures"] = int(stats.get("scatter_failures", 0)) + 1
        stats["scatter_last_failure"] = str((receipt or {}).get("reason") or "the barrage did not confirm")[:200]
    return receipt if isinstance(receipt, dict) else {"state": "failed", "reason": "no receipt"}


def reset() -> None:
    """Forget the crowd history (tests, and a title change)."""
    _HISTORY.clear()
