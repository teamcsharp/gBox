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
    "near_cm": 400.0,              # "a few metres" around the player
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
    "kind": "flash",               # flash is the verified kind on every title that has the ring
    "count": 10,
    "radius_cm": 600.0,
    "inner_cm": 150.0,
    "ripple_ms": 40.0,
    "min_safe_cm": 250.0,          # never closer than this, whatever the blast book says
    "margin_cm": 250.0,            # extra clearance past the learned safe distance
    "max_radius_cm": 2500.0,       # the native ring's own ceiling
    "not_thinning_s": 8.0,         # pressure this long counts as a crowd that is not thinning
    "kill_window_s": 12.0,         # kills inside this window after a ring are attributed to it
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
        out["enabled"] = bool(out["enabled"])
        out["kind"] = str(out["kind"] or "flash")
    except (TypeError, ValueError):
        out.update({k: DEFAULTS[k] for k in ("enabled", "min_enemies", "cooldown_s", "kind", "radius_cm",
                                             "near_cm", "danger_cm", "periodic_s", "periodic_min_enemies")})
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
    if periodic > 0 and near >= int(policy_.get("periodic_min_enemies") or 2) and \
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
    """[(kind, available)] the launcher ring may draw for this title: the controller's own launcher_kinds() (RE6's
    shell rounds) or its grenade kinds (RE5/RE4, whose launcher fires the same grenades). Operator 2026-11-11 18:30:
    "I want to use the same everything across titles ... the same 360 grenade launcher blasts"."""
    try:
        rows = target.launcher_kinds() if hasattr(target, "launcher_kinds") else target.grenade_kinds()
    except Exception:                                    # noqa: BLE001 - a controller without the report offers none
        return []
    return [(str(r.get("kind")), bool(r.get("available"))) for r in rows or ()
            if isinstance(r, dict) and str(r.get("kind")) in KINDS]


def fire(ad, decision: dict, stats: dict, now: float, *, ring=None) -> dict:
    """Run the native ring once and keep the stats. Never raises for a game-side refusal; reports it."""
    target = ring or controller(ad)
    kind = decision.get("kind") or "flash"
    allow_unverified = False
    if str(kind).lower() == "launcher":
        # Operator 2026-11-11 18:12/18:30: the 360 launcher-shot ring, the same across titles. The rounds are the
        # title's own (RE6's shells, RE5/RE4's grenades); an unavailable row is a research kind (the shells today),
        # so the ring takes allow_unverified: the spawn is what is being measured, a refusal is a receipt, not a crash.
        rounds = launcher_rounds(target)
        if not rounds:
            stats["ring_error"] = "no launcher round kind is reported by this title"
            return {"state": "refused", "reason": stats["ring_error"]}
        preferred = [r for r in rounds if r[0] in LAUNCHER_PREFER]
        kind, available = random.choice(preferred) if preferred else random.choice(rounds)
        allow_unverified = not available
    if str(kind).lower() == "random":
        kind = pick_kind(target, decision)
        if kind is None:
            stats["ring_error"] = ("no grenade kind is available for the ring (none verified on this build, or the "
                                   "flash's one-a-minute gate is closed)")
            return {"state": "refused", "reason": stats["ring_error"]}
    module = type(target).__module__.rsplit(".", 1)[-1]
    try:
        if module == "re4_gc_native":
            receipt = target.grenade_ring(kind)          # RE4's ring picks its own count and radius
        else:
            receipt = target.grenade_ring(kind, count=decision.get("count"), radius_cm=decision.get("radius_cm"),
                                          inner_cm=decision.get("inner_cm"), ripple_ms=decision.get("ripple_ms"),
                                          allow_unverified=allow_unverified)
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

    def step(snap: dict, stats: dict, now: float, hold=None) -> dict:
        policy_ = policy(title_mod, stats)
        observe(stats, snap, now, policy_)
        decision = decide(snap, stats, now, policy_, title=title)
        stats["ring_decision"] = (decision["reason"] if not decision["fire"] else "fire: " + decision["reason"])[:200]
        # The kind is recorded with the ATTEMPT, not only with the receipt: a session that rotates or ends mid-fire used
        # to leave ring_kind_fired empty while rings_attempted had counted the attempt, so the operator's 360 ring
        # looked like it never chose a kind (live 2026-11-11 22:47 RE5 1/ and 23:07 RE6 1/ both lost their outcome).
        if decision.get("fire"):
            stats["ring_kind_fired"] = str(decision.get("kind") or "")
        if not decision["fire"]:
            if title in SCATTER_TITLES:                      # no ring this tick: the scatter barrage's own rule
                return scatter_step(snap, stats, now, hold)
            return decision
        if hold is not None and hold(set()) is False:
            return {**decision, "fire": False, "reason": "the bot's keys did not release before the ring"}
        try:
            receipt = fire(ad, decision, stats, now, ring=ring)
        except Exception as exc:                         # noqa: BLE001 - a ring never ends the round
            stats["ring_error"] = f"{type(exc).__name__}: {exc}"[:200]
            return {**decision, "fire": False, "reason": stats["ring_error"]}
        decision = {**decision, "fired": True, "receipt": receipt}
        stats["ring_last_reason"] = decision["reason"][:200]
        return decision

    def scatter_step(snap, stats, now, hold=None) -> dict:
        sp = scatter_policy(title_mod, stats)
        observe_scatter(stats, snap, now, sp)
        decision = decide_scatter(snap, stats, now, sp, title=title)
        stats["scatter_decision"] = (decision["reason"] if not decision["fire"] else "fire: " + decision["reason"])[:200]
        if not decision["fire"]:
            return decision
        if hold is not None and hold(set()) is False:
            return {**decision, "fire": False, "reason": "the bot's keys did not release before the barrage"}
        try:
            receipt = fire_scatter(ad, decision, stats, now, ring=ring)
        except Exception as exc:                         # noqa: BLE001 - a barrage never ends the round
            stats["scatter_error"] = f"{type(exc).__name__}: {exc}"[:200]
            return {**decision, "fire": False, "reason": stats["scatter_error"]}
        return {**decision, "fired": True, "receipt": receipt}

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
                    "kinds": ("flash",)}         # what "random" draws; a title's scatter_kinds() overrides it


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


def fire_scatter(ad, decision: dict, stats: dict, now: float, *, ring=None) -> dict:
    """The native barrage once, with the stats. Never raises for a game-side refusal."""
    target = ring or controller(ad)
    stats["scatter_last_at"] = now
    if not callable(getattr(target, "grenade_scatter", None)):
        stats["scatter_failures"] = int(stats.get("scatter_failures", 0)) + 1
        stats["scatter_last_failure"] = "this title's native controller has no scatter barrage"
        return {"state": "unavailable", "reason": stats["scatter_last_failure"]}
    options = {"count": decision.get("count"), "toward": decision.get("toward") or None,
               "safe_cm": decision.get("safe_cm")}
    if decision.get("narrowed") and decision.get("kinds"):
        options["kinds"] = tuple(decision["kinds"])
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
