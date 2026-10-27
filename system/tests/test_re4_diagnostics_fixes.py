"""RE4 Mercenaries fixes from the 2026-10-26 per-round diagnostics (docs/evidence/mercs-diagnostics-2026-10-26.md):
straight runs between waypoints, no false stucks, the round's x80 gun held and verified, body shots at a swing about to
land, every impact learned, every round audited, level maps for the Castle and the Base."""
import json
import math
import struct
from types import SimpleNamespace

import pytest

from gbox import re4_merc_bot as B
from gbox.mercs import impact_lessons as IL
from tests.test_re4_merc_bot import PL, act_state, facing, run, set_pitch, world


def test_turning_on_the_spot_is_never_a_stuck():
    """24 % of today's stucks had the goal behind him: turning on the spot (no run) was counted as blocked - a vault tap,
    a detour and a "wall" learned in front of him, every time."""
    now = [0.0]
    m = world([], room=0x400, leon=(5592.0, 0.0, 12000.0), timer_s=100.0)   # the (5592, 16384) hourglass 44 m ahead
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    facing(m, math.pi)                                                   # facing away: he turns on the spot
    for t in range(1, 40):                                               # 3.9 s; this fake Leon never turns
        now[0] = t * 0.1
        m.put(B.MERC_TIMER, ">I", int((100 - now[0]) * 30))
        act = bot.tick(B.snapshot(m))
        assert "up" not in act.get("hold", set()) and act.get("tap") is None
    assert bot.stats["stuck_events"] == bot.stats["vaults"] == bot.stats["detours"] == 0


def test_with_the_discs_map_a_waypoint_is_skipped_once_the_run_to_the_next_is_clear():
    """Operator 2026-10-26: "Normally when people play Resident Evil, they run linearly in a straight path". Within ARRIVE
    a waypoint is passed as before; with the disc's map one further off is skipped as soon as the run to the next one is
    clear at his shoulders' width - never through a wall, never a vault / ladder waypoint, never without the map."""
    bot = B.Bot(world([]), nav=False)
    bot._round(0x400)
    bot.st = {"walls": [[0.0, 500.0, 2000.0, 500.0, -1000.0, 3000.0, 0.0]]}   # a wall along z 500, x 0 .. 2000
    p = {"pos": (-1000.0, 0.0, 0.0), "rot": 0.0}
    blocked = [(-1000.0, 1000.0), (1000.0, 1000.0)]                     # the next leg runs past the wall's end
    assert not bot._passed(p, blocked, 1000.0)                           # his shoulder would clip it: the corner
    assert bot._passed(p, blocked, B.ARRIVE - 1)                         # at the corner: on to the next, as before
    clear = [(-1000.0, 1000.0), (-1000.0, 3000.0)]                      # open floor straight ahead
    assert bot._passed(p, clear, 1000.0) and bot.stats["waypoints_skipped"] == 1
    assert not bot._passed(p, [(-1000.0, 1000.0, "vault"), (-1000.0, 3000.0)], 1000.0)   # its press comes first
    assert not bot._clear_run({"pos": (-300.0, 0.0, 0.0)}, (-300.0, 2000.0))   # 30 cm off the end: the shoulder hits
    bot.st = None
    assert not bot._passed(p, clear, 1000.0)                             # no disc map: the distance alone, as before


def test_a_verified_x80_round_gun_holds_the_trigger_and_presses_when_holding_fires_nothing():
    """Operator 2026-10-26 16:40: "Why isnt leon shooting with 80x fire speed?" - presses capped him at ~6 a second. With
    the round's gun verified at x80 A is held (the game repeats at the gun's ~1-frame interval); held RAPID_PROOF_S with
    nothing leaving the gun and no health falling, this round taps again."""
    now = [0.0]
    m = world([((0, 0, 1500), True)])
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    bot.stats["rounds"] = 1
    bot.stats["round_loadout"] = {"round": 1, "verified": True, "gun": "Handcannon", "fire_x": 80}
    acts = run(bot, m, now, 0.0, 20)
    first = next(i for i, a in enumerate(acts) if "a" in a.get("hold", set()))
    held = acts[first:]
    assert len(held) >= 8 and all("a" in a["hold"] for a in held)       # held, never let go between shots
    assert bot.stats["trigger_mode"].startswith("hold")
    acts = run(bot, m, now, now[0] + 0.05, 40)                           # nothing fired in RAPID_PROOF_S: presses
    assert bot.rapid["mode"] == "tap" and bot.stats["trigger_mode"].startswith("tap")
    downs = [i for i, (a, b) in enumerate(zip(acts, acts[1:]))
             if "a" not in a.get("hold", set()) and "a" in b.get("hold", set())]
    assert len(downs) >= 5


def test_an_unverified_round_gun_keeps_the_presses():
    now = [0.0]
    m = world([((0, 0, 1500), True)])
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    bot.stats.update(rounds=2, round_loadout={"round": 1, "verified": True})   # last round's: not this one
    assert not bot._rapid_ok()
    bot.stats["round_loadout"] = {"round": 2, "verified": False}
    assert not bot._rapid_ok()


def test_held_fire_shots_are_counted_from_the_fire_motion_restarting():
    bot = B.Bot(world([]), nav=False)
    bot._shot_seen({"r": (0, 6, 2, 0), "mframe": 1.0}, 0.0)            # entering 00 06 02: a shot
    for k, frame in enumerate((2.0, 3.0, 0.5, 1.5, 0.2)):               # the motion restarted twice: two more
        bot._shot_seen({"r": (0, 6, 2, 0), "mframe": frame}, 0.05 * (k + 1))
    assert bot.shots.stats["shots"] == 3 and bot.stats["shots_held"] == 2
    bot._shot_seen({"r": (0, 6, 1, 0), "mframe": 0.1}, 0.4)             # back to aiming: no shot
    assert bot.shots.stats["shots"] == 3


def test_a_swing_about_to_land_is_shot_anywhere_in_his_body_not_only_the_head():
    """27 % of today's hits landed while he was still aiming (the head band, HEAD_LO .. BODY_HI). A swing / grab / rush
    landing within URGENT_BODY_S inside URGENT_BODY_R is shot as soon as the aim is anywhere in his body."""
    now = [0.0]
    m = world([((0, 0, 900), True)])
    act_state(m, 1, (1, 0x26, 1, 0))                                     # a swing under way
    facing(m, 0.0)
    set_pitch(m, math.atan2(B.CHEST_H - B.GUN_H, 900.0))                 # the aim at his chest: under the head band
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    acts = run(bot, m, now, 0.0, int((B.PITCH_AFTER + 0.2) / 0.05))
    assert any("a" in a.get("hold", set()) for a in acts) and bot.stats.get("urgent_body_aims", 0) >= 1
    # a Ganado who only walks there keeps the head band: the same aim holds fire and the stick raises it
    now2 = [0.0]
    m2 = world([((0, 0, 900), True)])
    facing(m2, 0.0)
    set_pitch(m2, math.atan2(B.CHEST_H - B.GUN_H, 900.0))
    calm = B.Bot(m2, clock=lambda: now2[0], nav=False)
    acts = run(calm, m2, now2, 0.0, int((B.PITCH_AFTER + 0.2) / 0.05))
    assert not any("a" in a.get("hold", set()) for a in acts) and any("up" in a.get("hold", set()) for a in acts)


class FakeG:
    """re_mods_tool.RE4's surface the loadout check uses: V (ITEM_MGR, FIRE_RATE_TBL, FIRE_RATE_ORIG) and m (rd / u16)."""

    def __init__(self, held, rates):
        self.mem = bytearray(0x400000)
        self.V = SimpleNamespace(ITEM_MGR=0x802138E0, FIRE_RATE_TBL=0x801ED248,
                                 FIRE_RATE_ORIG=struct.pack(">5f", *[35.0] * 5) * 4)
        self.put(self.V.ITEM_MGR + 0x10, ">H", held)
        self.put(self.V.FIRE_RATE_TBL + 1 * 0x14, ">5f", *rates)
        self.m = SimpleNamespace(rd=self.rd, u16=lambda a: struct.unpack(">H", self.rd(a, 2))[0])

    def rd(self, a, n):
        return bytes(self.mem[a - 0x80000000:a - 0x80000000 + n])

    def put(self, a, fmt, *v):
        data = struct.pack(fmt, *v)
        self.mem[a - 0x80000000:a - 0x80000000 + len(data)] = data


def fake_rm(monkeypatch, g, calls):
    from gbox import re_mods_tool as RM
    monkeypatch.setattr(RM, "RE4", lambda ad: g)
    monkeypatch.setattr(RM, "weapon_classes", lambda gg: {0x37: (1, 0), 0x30: (1, 0)})

    def equip(gg, iid):
        calls.append(("equip", iid))
        g.put(g.V.ITEM_MGR + 0x10, ">H", iid)
        return {"verified": True}

    def mod(gg, iid, rate, damage, reset):
        calls.append(("weapon_mod", iid, rate))
        g.put(g.V.FIRE_RATE_TBL + 0x14, ">5f", *[rate] * 5)
        return {"verified": True}
    monkeypatch.setattr(RM, "equip_item", equip)
    monkeypatch.setattr(RM, "weapon_mod", mod)


def test_the_rounds_loadout_is_read_back_and_repaired_in_the_round(monkeypatch):
    """Live 16:40: the weapon read 'item 0x800' (no gun in his hands) and no rapid fire. LOADOUT_CHECK_S into the round
    the gun in his hands and its class's interval are read back: the drawn gun is equipped, x80 applied again, verified."""
    g, calls = FakeG(B.NO_GUN, [35.0] * 5), []
    fake_rm(monkeypatch, g, calls)
    stats = {"rounds": 2, "character": "Krauser",
             "round_loadout": {"round": 2, "gun": "Handcannon", "gun_id": 0x37, "fire_x": 80,
                               "verified": False, "checks": 0, "fixes": 0}}
    lc = B.LoadoutCheck(object(), stats)
    lc.tick({"weapon": B.NO_GUN}, 0.0)
    assert calls == []                                                    # the records equip it ~5 s in: wait
    lo = lc.tick({"weapon": B.NO_GUN}, B.LOADOUT_CHECK_S + 0.1)
    assert calls == [("equip", 0x37), ("weapon_mod", 0x37, pytest.approx(1.0))] and lo["character"] == "Krauser"
    assert lo["equipped_ok"] and lo["fire_applied"] and lo["verified"] and lo["fire_interval_frames"] == [1.0] * 5
    assert lo["fire_want_frames"] == 1.0 and "verified" in lo["reason"] and lo["fixes"] == 2
    bot = B.Bot(world([]), nav=False)
    bot.stats = stats
    bot.triggers.d["classes"].pop("handcannon", None)                     # (the live prior presses it: per class)
    assert bot._rapid_ok()                                                # the trigger is held from now on
    lc.tick({"weapon": 0x37}, B.LOADOUT_CHECK_S + 10)
    assert len(calls) == 2                                                # verified: read no more


def test_a_loadout_that_cannot_be_repaired_says_why_and_stops_trying(monkeypatch):
    g, calls = FakeG(0x30, [3.0] * 5), []
    fake_rm(monkeypatch, g, calls)
    from gbox import re_mods_tool as RM
    monkeypatch.setattr(RM, "equip_item", lambda gg, iid: calls.append(("equip", iid)) or {"verified": False})
    stats = {"rounds": 1, "round_loadout": {"round": 1, "gun": "Handcannon", "gun_id": 0x37, "fire_x": 80,
                                            "verified": False, "checks": 0, "fixes": 0}}
    lc = B.LoadoutCheck(object(), stats)
    lc.tick({"weapon": 0x30}, 0.0)
    for k in range(12):
        lc.tick({"weapon": 0x30}, B.LOADOUT_CHECK_S + k * B.LOADOUT_EVERY_S)
    lo = stats["round_loadout"]
    assert not lo["verified"] and "in his hands TMP" in lo["reason"] and lo["fixes"] <= B.LOADOUT_FIXES
    assert lo["checks"] == B.LOADOUT_FIXES + 3


def test_select_player_records_the_draw_for_the_round_that_follows(monkeypatch):
    from gbox import re_mods_tool as RM
    monkeypatch.setattr(RM, "run", lambda ad, op, **kw: {"verified": True, "picked": ["Handcannon"],
                                                         "weapon_mod": [True], **({"equipped_now": True} if kw.get("equip_now") else {})})
    stats = {"rounds": 4, "character": "HUNK"}
    assert B.apply_round(object(), stats=stats) == []
    lo = stats["round_loadout"]
    assert lo["round"] == 5 and lo["drawn"] == "at Select Player" and lo["gun_id"] == RM._item_id("Handcannon")
    assert "character" not in lo and lo["fire_x"] == 80 and lo["verified"] is False   # the check names the round's own
    stats["rounds"] = 5
    assert B.apply_round(object(), equip_now=True, stats=stats) == []
    assert stats["round_loadout"]["round"] == 5 and stats["round_loadout"]["equipped_now"] is True


def test_a_hit_while_he_shoots_its_attacker_is_learned_for_the_room(tmp_path):
    """Operator 2026-10-26: "I want the autobot trained from every impact". The round map's hit event names the attack,
    its distance, the angle off his facing and what he was doing; a swing that lands while he stood shooting that very
    Ganado raises the room's evade margin for swings (impact_lessons), so the next one is run out of; an attack he kills
    in its wind-up eases it back."""
    now = [0.0]
    m = world([((0, 0, 900), True)])
    act_state(m, 1, (1, 0x26, 1, 0), ev=B.threats_ram.EV_HIT)            # the hit frames are on
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False, learn_dir=tmp_path, round_maps_dir=tmp_path / "maps")
    bot._round(0x400)
    bot.trace_start("r1")
    run(bot, m, now, 0.0, 3)                                             # fighting him
    m.put(PL + 0xFC, ">4B", 1, 0, 0, 0)                                  # Leon's routine 1: hit
    run(bot, m, now, 0.2, 1)
    assert bot.stats["hits_taken"] == 1
    ev = [e for e in bot.trace.events if e["kind"] == "hit"][-1]
    assert ev["attack"] == "swing" and ev["facing"] == "front" and ev["dist"] == 900 and ev["doing"].startswith("fight")
    assert bot._evade_margin("swing") == pytest.approx(B.EVADE_MARGIN + IL.STEP_EVADE)
    assert ev["evade_margin"] == pytest.approx(B.EVADE_MARGIN + IL.STEP_EVADE)
    bot.impacts.save()
    saved = json.loads((tmp_path / "impact_lessons.json").read_text())["stages"]["r400"]["swing"]
    assert saved["hits"] == 1 and saved["front"] == 1 and saved["params"]["evade_margin"] == pytest.approx(0.2)
    bot.tracker.stats["prevented"] += 2                                  # two attacks killed in their wind-up
    bot._watch(B.snapshot(m)["player"], B.snapshot(m), [], 0.3)
    assert bot._evade_margin("swing") == pytest.approx(0.2 - 2 * IL.DECAY_EVADE)


def test_the_evade_margin_is_bounded():
    lessons = IL.ImpactLessons(None)
    for _ in range(50):
        lessons.adjust("r400", "swing", "evade_margin", IL.STEP_EVADE, B.EVADE_MARGIN, B.EVADE_MARGIN, IL.EVADE_MAX)
    assert lessons.value("r400", "swing", "evade_margin", B.EVADE_MARGIN, B.EVADE_MARGIN, IL.EVADE_MAX) == IL.EVADE_MAX
    for _ in range(200):
        lessons.adjust("r400", "swing", "evade_margin", -IL.DECAY_EVADE, B.EVADE_MARGIN, B.EVADE_MARGIN, IL.EVADE_MAX)
    assert lessons.value("r400", "swing", "evade_margin", B.EVADE_MARGIN, B.EVADE_MARGIN, IL.EVADE_MAX) == B.EVADE_MARGIN


def test_a_hit_named_from_across_the_stage_is_unattributed(tmp_path):
    """29 of today's 131 hits named an attacker over 3000 away or 2 s from landing ('chainsaw at 39771 (eta 15.71)'):
    such a pick cannot have landed - "unattributed", and it moves no margin."""
    now = [0.0]
    m = world([((0, 0, 30000), True)])
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False, learn_dir=tmp_path, round_maps_dir=tmp_path / "maps")
    bot._round(0x400)
    bot.trace_start("r1")
    bot.tracker.last_hit = {"slot": 1, "kind": "near", "dist": 30000, "eta": 15.7}
    bot._impact(B.snapshot(m)["player"], B.snapshot(m), 0.0)
    ev = [e for e in bot.trace.events if e["kind"] == "hit"][-1]
    assert ev["attack"] == "unattributed" and "evade_margin" not in ev


def test_a_round_map_started_before_the_room_was_read_is_filed_under_the_room_played(tmp_path):
    """2026-10-26: an r404 round was filed as r403 - trace_start runs on the round's first frame, the room is read by
    the tick after it."""
    bot = B.Bot(world([]), nav=False, learn_dir=tmp_path, round_maps_dir=tmp_path / "maps")
    bot._round(0x403)
    bot.trace_start("abc")
    assert bot.trace.room == "r403"
    bot._round(0x404)
    assert bot.trace.room == "r404" and bot.trace.out_dir == tmp_path / "maps" / "r404"


def test_every_round_map_carries_its_audit_and_the_stats_the_verdict(tmp_path):
    """Operator 2026-10-26: "I want you troubleshooting each and every one of these runs". Each round's map gets an
    "audit" (verdict + problems) and stats["round_audit"] the verdict, with no one watching."""
    now = [0.0]
    bot = B.Bot(world([]), clock=lambda: now[0], nav=False, learn_dir=tmp_path, round_maps_dir=tmp_path / "maps")
    bot.stats.update(rounds=1, character="Wesker")
    bot._round(0x400)

    def one_round(rid, shots, hits, taken):
        bot.trace_start(rid)
        for k in range(48):                                              # 12 s on one spot, no gun in his hands
            bot.trace.add(100.0 * int(rid[-1]) + k * 0.25, 0.0, 0.0, 0.0, {"phase": "fight", "weapon": "item 0x800 (0x800)"})
        bot.stats.update(shots=bot.stats.get("shots", 0) + shots, hits=bot.stats.get("hits", 0) + hits,
                         misses=bot.stats.get("misses", 0) + shots - hits,
                         hits_taken=bot.stats.get("hits_taken", 0) + taken)
        bot.trace_finish()
        return json.loads(sorted((tmp_path / "maps" / "r400").glob("*.json"))[-1].read_text())["audit"]

    a = one_round("round-1", 20, 4, 15)
    probs = " | ".join(a["problems"])
    assert a["verdict"] == "problems" and bot.stats["round_audit"]["verdict"] == "problems"
    assert "accuracy 20% < 40% (4/20)" in probs and "15 hits taken (> 12)" in probs
    assert "loadout not verified" in probs and "no gun in his hands" in probs and "standstill(s) over 5 s" in probs
    assert "character unchanged" not in probs and a["metrics"]["character"] == "Wesker"
    b = one_round("round-2", 10, 9, 1)                                   # this round's own counters, not the run's
    assert b["metrics"]["shots"] == 10 and b["metrics"]["accuracy"] == 0.9 and b["metrics"]["hits_taken"] == 1
    assert "character unchanged: Wesker again" in " | ".join(b["problems"])
