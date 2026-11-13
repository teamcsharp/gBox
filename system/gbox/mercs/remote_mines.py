"""The bot's own remote-mine rule (RE6 Switch): rings of four ejected from his body, detonated through the flag.

Operator 2026-11-11: "drop remote bombs anytime that they want ... eject them out of their body in sets of four in a
ring around them ... drop massive quantities of them and then be able to detonate them remotely" - no throw, no
detonator in his hand, no animation. The drops go through `re6_switch_native.bomb_ring_now` (spawn_bomb.c), the
detonation through `re6_switch_mods.detonate` (the player's +0x5A19 bit 0x20 cleared, the detonator's own flag).

Existing bombs are serviced before grenade/QTE branches. New rings run on a
background worker; each confirmed native placement starts a five-second deadline.
"""
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
    # Every placed bomb has a five-second maximum. More rings never extend it.
    "rings_before_detonate": 1,
    "detonate_after_s": 5.0,
    # Operator 2026-11-11 17:50: "detonating them as they get distance away from them" - the flag never goes while he
    # is inside a lying ring's blast; once he is detonate_safe_cm clear of every centre the set goes.
    "detonate_safe_cm": 1100.0,
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
        out["rings_before_detonate"] = 1
        out["detonate_after_s"] = 5.0
        out["detonate_safe_cm"] = max(1100.0, min(float(out["detonate_safe_cm"]), 2000.0))
    except (TypeError, ValueError):
        out = dict(DEFAULTS)
    return out


def control(ad, prof, bot_getter=None):
    """Native placement evidence starts a five-second deadline; escape begins immediately."""
    from .re6_remote_control import control as make_control
    return make_control(ad, prof, bot_getter)
