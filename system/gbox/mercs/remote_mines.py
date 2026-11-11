"""The bot's own remote-mine rule (RE6 Switch): rings of four ejected from his body, detonated through the flag.

Operator 2026-11-11: "drop remote bombs anytime that they want ... eject them out of their body in sets of four in a
ring around them ... drop massive quantities of them and then be able to detonate them remotely" - no throw, no
detonator in his hand, no animation. The drops go through `re6_switch_native.bomb_ring_now` (spawn_bomb.c), the
detonation through `re6_switch_mods.detonate` (the player's +0x5A19 bit 0x20 cleared, the detonator's own flag).

The rule runs beside the driver's own bomb mind, never while it is mid-action (`bomb_phase`/`nade`), and keeps its
own ring counters so its cadence does not depend on what the driver's bombs do.
"""
import random

TITLES = {"01002A000CD48000": "gbox.mercs.titles.re6_switch"}
DEFAULTS = {
    "enabled": True,
    "drop_every_s": 22.0,          # a ring this often while a round plays
    "drop_jitter_s": 8.0,          # +/- so the drops are not clockwork ("randomly in the middle of the match")
    "count": 4,                    # "sets of four in a ring around them"
    "radius_cm": 200.0,
    "rings_before_detonate": 3,    # "massive quantities ... then detonate": 12 bombs by default
    "detonate_after_s": 75.0,      # or a forced detonation this long after the first ring of the set
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
        due = rings > 0 and (rings >= int(policy_["rings_before_detonate"]) or
                             (isinstance(first, (int, float)) and now - first >= float(policy_["detonate_after_s"])))
        if due:
            if hold is not None and hold(set()) is False:
                return {**out, "reason": "the bot's keys did not release before the detonation"}
            receipt = re6_switch_native.bomb_detonate_now(ad, snap=snap)
            stats["mine_flag_detonations"] = int(stats.get("mine_flag_detonations", 0)) + 1
            stats["mine_rings_since_detonate"] = 0
            stats["mine_bombs_since_detonate"] = 0
            stats.pop("mine_first_ring_at", None)
            if not receipt.get("verified"):
                stats["mine_detonate_failures"] = int(stats.get("mine_detonate_failures", 0)) + 1
                stats["mine_detonate_reason"] = str(receipt.get("reason") or "")[:200]
            stats["mine_last_detonate_at"] = now
            return {"fire": True, "op": "bomb_detonate", "fired": True,
                    "reason": f"flag detonation of {bombs} lying bombs", "receipt": receipt}
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
            stats.setdefault("mine_first_ring_at", now)
            stats["mine_ring_last_at"] = now
        else:
            stats["mine_ring_failures"] = int(stats.get("mine_ring_failures", 0)) + 1
            stats["mine_ring_reason"] = str(receipt.get("reason") or receipt.get("state") or "")[:200]
        return {"fire": True, "op": "bomb_ring", "fired": True,
                "reason": f"a ring of {receipt.get('placed')} remote bombs around him", "receipt": receipt}

    return step
