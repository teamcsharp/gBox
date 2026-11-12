"""The bot's own remote-mine rule (RE6 Switch): rings of four ejected from his body, detonated through the flag.

Operator 2026-11-11: "drop remote bombs anytime that they want ... eject them out of their body in sets of four in a
ring around them ... drop massive quantities of them and then be able to detonate them remotely" - no throw, no
detonator in his hand, no animation. The drops go through `re6_switch_native.bomb_ring_now` (spawn_bomb.c), the
detonation through `re6_switch_mods.detonate` (the player's +0x5A19 bit 0x20 cleared, the detonator's own flag).

The rule runs beside the driver's own bomb mind, never while it is mid-action (`bomb_phase`/`nade`), and keeps its
own ring counters so its cadence does not depend on what the driver's bombs do.
"""
import math
import random

TITLES = {"01002A000CD48000": "gbox.mercs.titles.re6_switch"}
#: Why the other playable editions have no remote-mine lane yet (operator 2026-11-11 18:30: the same features across
#: titles; the honest per-title report is the mod sidebar's source, the same shape as grenade_status).
UNSUPPORTED = {
    "010018100CD46000": ("RE5 Switch", "the proximity bomb's uWp0a class DTI is not derived yet (the RE5 image is not "
                                      "on the control plane), so no native free drop is claimed"),
    "010099A00BC1E000": ("RE4 Switch", "no mine system is built on the RE4 native harness yet (its blasts are the "
                                      "flash and hand grenades)"),
}


def status(game_id: str | None = None) -> list:
    """The remote-mine lane per title for the mod sidebar: the RE6 native ring/detonate is verified; the other
    editions say why they have none yet."""
    rows = [{"game_id": g, "title": t, "available": True, "reason": ""} for g, t in TITLES.items()]
    for g, (t, why) in UNSUPPORTED.items():
        rows.append({"game_id": g, "title": t, "available": False, "reason": why})
    return [r for r in rows if game_id is None or r["game_id"] == game_id]
#: Operator 2026-11-11 18:02: "Whenever the bot deploys a flashbang in Resident Evil Six, also have them send out a
#: ring of remote mines in the area up to 15, and then have those be detonated ... to spread out the enemies and get
#: rid of being surrounded." A flash stamped this recently (stats["ring_flash_at"]) earns the combo ring.
FLASH_COMBO_S, FLASH_COMBO_MINES = 1.0, 15
#: The surround rule's own numbers: 4 within 400 cm earns the big ring at most every 10 s (the operator's "surrounded
#: by enemies ... dropping massive amounts of remote mines").
SURROUND_N, SURROUND_R_CM, SURROUND_S = 4, 400.0, 10.0
DEFAULTS = {
    "enabled": True,
    "drop_every_s": 7.5,           # a ring this often while a round plays (operator 2026-11-11 17:49: "mines are just
                                   # dropping out from around them every five to ten seconds randomly")
    "drop_jitter_s": 2.5,          # +/- so the drops land anywhere in the 5-10 s window ("randomly in the match")
    "count": 6,                    # six a ring: "dropping even more remote mines"
    "radius_cm": 200.0,
    "rings_before_detonate": 4,    # "massive quantities ... then detonate": 24 bombs by default
    "detonate_after_s": 75.0,      # or a forced detonation this long after the first ring of the set
    # Operator 2026-11-11 17:50: "detonating them as they get distance away from them" - the flag never goes while he
    # is inside a lying ring's blast; once he is detonate_safe_cm clear of every centre the set goes.
    "detonate_safe_cm": 350.0,
}


def policy(stats=None) -> dict:
    """The defaults with a ``stats['remote_mines']`` override (tests/tools), bounds enforced."""
    out = dict(DEFAULTS)
    override = (stats or {}).get("remote_mines") if isinstance(stats, dict) else None
    if isinstance(override, dict):
        for key, value in override.items():
            if key in out and value is not None:
                out[key] = value
    try:
        out["enabled"] = bool(out["enabled"])
        out["drop_every_s"] = max(5.0, min(float(out["drop_every_s"]), 300.0))
        out["drop_jitter_s"] = max(0.0, min(float(out["drop_jitter_s"]), 120.0))
        out["count"] = max(1, min(int(out["count"]), 16))
        out["radius_cm"] = max(50.0, min(float(out["radius_cm"]), 600.0))
        out["rings_before_detonate"] = max(1, min(int(out["rings_before_detonate"]), 16))
        out["detonate_after_s"] = max(5.0, min(float(out["detonate_after_s"]), 300.0))
        out["detonate_safe_cm"] = max(50.0, min(float(out["detonate_safe_cm"]), 2000.0))
    except (TypeError, ValueError):
        out = dict(DEFAULTS)
    return out


def control(ad, prof, bot_getter=None):
    """The engine's hook for RE6: a ring of four on a jittered cadence, then the flag detonation of the set."""
    if str((prof or {}).get("map_id") or "") not in TITLES:
        return None
    from .titles import re6_switch_native

    def step(snap: dict, stats: dict, now: float, hold=None, **_) -> dict:
        out = {"fire": False, "op": "remote_mines", "reason": ""}
        policy_ = policy(stats)
        if not policy_["enabled"]:
            return {**out, "reason": "the remote-mine rule is switched off (REMOTE_MINES)"}
        player = (snap or {}).get("player") or {}
        if not player.get("pos"):
            return {**out, "reason": "no player in a live round"}
        bot = bot_getter() if callable(bot_getter) else None
        if bot is not None and (getattr(bot, "bomb_phase", None) is not None or
                                getattr(bot, "nade", None) is not None):
            return {**out, "reason": "the driver's own bomb or grenade action is in progress"}
        rings = int(stats.get("mine_rings_since_detonate") or 0)
        bombs = int(stats.get("mine_bombs_since_detonate") or 0)
        first = stats.get("mine_first_ring_at")
        # The player's own blast is the first gate (operator 2026-11-11 17:50: "detonating them as they get distance
        # away from them"): the nearest lying ring's centre decides; never the flag under his feet.
        centres = [c for c in (stats.get("mine_ring_centres") or []) if isinstance(c, (list, tuple)) and len(c) == 3]
        try:
            ppos = [float(v) for v in player.get("pos")]
            clear_cm = min((math.dist(ppos, [float(c[0]), float(c[1]), float(c[2])]) for c in centres), default=None)
        except (TypeError, ValueError):
            clear_cm = None
        safe_cm = float(policy_.get("detonate_safe_cm") or 350.0)
        clear = clear_cm is None or clear_cm >= safe_cm
        set_due = rings > 0 and (rings >= int(policy_["rings_before_detonate"]) or
                                 (isinstance(first, (int, float)) and now - first >= float(policy_["detonate_after_s"])))
        due = set_due and clear
        if due:
            if hold is not None and hold(set()) is False:
                return {**out, "reason": "the bot's keys did not release before the detonation"}
            receipt = re6_switch_native.bomb_detonate_now(ad, snap=snap)
            stats["mine_flag_detonations"] = int(stats.get("mine_flag_detonations", 0)) + 1
            stats["mine_rings_since_detonate"] = 0
            stats["mine_bombs_since_detonate"] = 0
            stats["mine_ring_centres"] = []
            stats.pop("mine_first_ring_at", None)
            if not receipt.get("verified"):
                stats["mine_detonate_failures"] = int(stats.get("mine_detonate_failures", 0)) + 1
                stats["mine_detonate_reason"] = str(receipt.get("reason") or "")[:200]
            stats["mine_last_detonate_at"] = now
            return {"fire": True, "op": "bomb_detonate", "fired": True,
                    "reason": f"flag detonation of {bombs} lying bombs", "receipt": receipt}
        if set_due and not clear:
            return {**out, "reason": (f"the player is {clear_cm:.0f} cm from the nearest lying ring: the flag waits "
                                      f"{safe_cm:.0f} cm")}
        # The operator's surrounded rule (2026-11-11 18:44: "surrounded by enemies ... needs to be dropping massive
        # amounts of remote mines and running for his life"): a real surround earns the big ring on its own cadence,
        # whatever the flash state. It runs before the flash combo so a surround never waits for a flash that is not
        # coming.
        near = 0
        try:
            ppos = [float(v) for v in player.get("pos")]
            near = sum(1 for e in (snap or {}).get("enemies") or ()
                       if isinstance(e, dict) and (e.get("hp") or 0) > 0 and e.get("pos")
                       and math.dist(ppos, [float(e["pos"][0]), float(e["pos"][1]), float(e["pos"][2])])
                       <= SURROUND_R_CM)
        except (TypeError, ValueError, IndexError):
            near = 0
        if (near >= SURROUND_N and now - float(stats.get("mine_surround_at") or 0) >= SURROUND_S
                and stats.get("mine_surround_at") != now):
            if hold is not None and hold(set()) is False:
                return {**out, "reason": "the bot's keys did not release before the surround ring"}
            receipt = re6_switch_native.bomb_ring_now(ad, count=FLASH_COMBO_MINES,
                                                      radius_cm=float(policy_["radius_cm"]))
            stats["mine_surround_at"] = now
            stats["mine_surround_rings"] = int(stats.get("mine_surround_rings", 0)) + 1
            stats["mine_next_drop_at"] = now + float(policy_["drop_every_s"]) + \
                random.uniform(-float(policy_["drop_jitter_s"]), float(policy_["drop_jitter_s"]))
            if receipt.get("state") == "confirmed":
                placed = int(receipt.get("placed") or 0)
                stats["mine_rings_dropped"] = int(stats.get("mine_rings_dropped", 0)) + 1
                stats["mine_ring_bombs"] = int(stats.get("mine_ring_bombs", 0)) + placed
                stats["mine_rings_since_detonate"] = rings + 1
                stats["mine_bombs_since_detonate"] = bombs + placed
                try:
                    stats.setdefault("mine_ring_centres", []).append(tuple(float(v) for v in player.get("pos")))
                    del stats["mine_ring_centres"][:-16]
                except (TypeError, ValueError):
                    pass
                stats.setdefault("mine_first_ring_at", now)
                stats["mine_ring_last_at"] = now
            else:
                stats["mine_ring_failures"] = int(stats.get("mine_ring_failures", 0)) + 1
                stats["mine_ring_reason"] = str(receipt.get("reason") or receipt.get("state") or "")[:200]
            return {"fire": True, "op": "bomb_ring", "fired": True,
                    "reason": (f"surrounded ({near} within {SURROUND_R_CM:.0f} cm): a ring of "
                               f"{receipt.get('placed')} remote bombs"), "receipt": receipt}
        # The flashbang combo (operator 2026-11-11 18:02): the flash just went -> a 15-mine ring right away (the flash
        # spreads the crowd, the ring clears the surround), then the standard distance-gated detonation.
        flash_at = stats.get("ring_flash_at")
        if (isinstance(flash_at, (int, float)) and now - flash_at <= FLASH_COMBO_S
                and stats.get("mine_flash_combo_at") != flash_at):
            if hold is not None and hold(set()) is False:
                return {**out, "reason": "the bot's keys did not release before the flash combo ring"}
            receipt = re6_switch_native.bomb_ring_now(ad, count=FLASH_COMBO_MINES,
                                                      radius_cm=float(policy_["radius_cm"]))
            stats["mine_flash_combo_at"] = flash_at
            stats["mine_flash_combos"] = int(stats.get("mine_flash_combos", 0)) + 1
            stats["mine_next_drop_at"] = now + float(policy_["drop_every_s"]) + \
                random.uniform(-float(policy_["drop_jitter_s"]), float(policy_["drop_jitter_s"]))
            if receipt.get("state") == "confirmed":
                placed = int(receipt.get("placed") or 0)
                stats["mine_rings_dropped"] = int(stats.get("mine_rings_dropped", 0)) + 1
                stats["mine_ring_bombs"] = int(stats.get("mine_ring_bombs", 0)) + placed
                stats["mine_rings_since_detonate"] = rings + 1
                stats["mine_bombs_since_detonate"] = bombs + placed
                try:
                    stats.setdefault("mine_ring_centres", []).append(tuple(float(v) for v in player.get("pos")))
                    del stats["mine_ring_centres"][:-16]
                except (TypeError, ValueError):
                    pass
                stats.setdefault("mine_first_ring_at", now)
                stats["mine_ring_last_at"] = now
            else:
                stats["mine_ring_failures"] = int(stats.get("mine_ring_failures", 0)) + 1
                stats["mine_ring_reason"] = str(receipt.get("reason") or receipt.get("state") or "")[:200]
            return {"fire": True, "op": "bomb_ring", "fired": True,
                    "reason": f"the flash combo: a ring of {receipt.get('placed')} remote bombs", "receipt": receipt}
        next_drop = stats.get("mine_next_drop_at")
        if isinstance(next_drop, (int, float)) and now < next_drop:
            return {**out, "reason": f"{next_drop - now:.1f} s to the next ring"}
        if hold is not None and hold(set()) is False:
            return {**out, "reason": "the bot's keys did not release before the ring"}
        receipt = re6_switch_native.bomb_ring_now(ad, count=int(policy_["count"]),
                                                  radius_cm=float(policy_["radius_cm"]))
        stats["mine_next_drop_at"] = now + float(policy_["drop_every_s"]) + \
            random.uniform(-float(policy_["drop_jitter_s"]), float(policy_["drop_jitter_s"]))
        if receipt.get("state") == "confirmed":
            placed = int(receipt.get("placed") or 0)
            stats["mine_rings_dropped"] = int(stats.get("mine_rings_dropped", 0)) + 1
            stats["mine_ring_bombs"] = int(stats.get("mine_ring_bombs", 0)) + placed
            stats["mine_rings_since_detonate"] = rings + 1
            stats["mine_bombs_since_detonate"] = bombs + placed
            try:
                stats.setdefault("mine_ring_centres", []).append(tuple(float(v) for v in player.get("pos")))
                del stats["mine_ring_centres"][:-16]
            except (TypeError, ValueError):
                pass
            stats.setdefault("mine_first_ring_at", now)
            stats["mine_ring_last_at"] = now
        else:
            stats["mine_ring_failures"] = int(stats.get("mine_ring_failures", 0)) + 1
            stats["mine_ring_reason"] = str(receipt.get("reason") or receipt.get("state") or "")[:200]
        return {"fire": True, "op": "bomb_ring", "fired": True,
                "reason": f"a ring of {receipt.get('placed')} remote bombs around him", "receipt": receipt}

    return step
