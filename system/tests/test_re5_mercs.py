"""Title #2 of the Mercenaries engine: Resident Evil 5 Gold (PS3 BLUS30491) - the RAM map and the driver, on a small RAM
fixture laid out the way the live game keeps it (found on the Spark's RPCS3, 2026-10-20)."""
import math

import pytest
import struct

from gbox import ram_map
from gbox.mercs import engine, vocab
from gbox.mercs.titles import re5_ps3 as R

SPLAYER, SENEMY, MAIN = 0x3883_69C0, 0x3883_6FE0, 0x3000_0020
PLAYER, GAMESYS, ARRAY = 0x303F_8A00, 0x31EE_C3F0, 0x31F0_2C20
ENEMIES = [0x3070_E630 + 0x21B0 * i for i in range(4)]


class Mem:
    """Sparse big-endian guest memory: rd(addr, n) like the bots' readers."""

    def __init__(self):
        self.b: dict[int, int] = {}

    def put(self, a, data: bytes):
        for i, x in enumerate(data):
            self.b[a + i] = x

    def u32(self, a, v):
        self.put(a, struct.pack(">I", v))

    def rd(self, a, n):
        return bytes(self.b.get(a + i, 0) for i in range(n))

    read = rd


def quat(yaw):
    return struct.pack(">4f", 0.0, math.sin(yaw / 2), 0.0, math.cos(yaw / 2))


def world(player_pos=(0.0, 0.0, 0.0), yaw=0.0, action=0, pitch_raw=0.0, hp=1000, enemies=(), timer=100.0,
          score=900, kills=3, combo=2, combo_t=8.9):
    m = Mem()
    m.u32(R.S_PLAYER, SPLAYER)
    m.u32(SPLAYER + 0x28, PLAYER)
    m.put(PLAYER + 0x30, struct.pack(">3f", *player_pos))
    m.put(PLAYER + 0x40, quat(yaw))
    m.put(PLAYER + 0x845, bytes([action]))
    m.put(PLAYER + 0x1AA0, struct.pack(">f", pitch_raw))
    m.put(PLAYER + 0x14A4, struct.pack(">hh", hp, 1000))
    m.u32(R.S_ENEMY, SENEMY)
    m.u32(SENEMY + 0x28, len(enemies))
    m.u32(SENEMY + 0x34, ARRAY)
    for i, (pos, hp_e, hp_max) in enumerate(enemies):
        m.u32(ARRAY + 4 * i, ENEMIES[i])
        m.put(ENEMIES[i] + 0x30, struct.pack(">3f", *pos))
        m.put(ENEMIES[i] + 0x14A4, struct.pack(">hh", hp_e, hp_max))
    m.u32(R.S_MAIN, MAIN)
    m.u32(MAIN + R.MAIN_GAMESYS, GAMESYS)
    m.put(GAMESYS + 0x3E0, struct.pack(">2f", timer, 120.0))
    m.put(GAMESYS + 0x3F4, struct.pack(">i", kills))
    m.put(GAMESYS + 0x3FC, struct.pack(">i", combo))
    m.put(GAMESYS + 0x404, struct.pack(">f", combo_t))
    m.put(GAMESYS + 0x418, struct.pack(">i", score))
    return m


def test_the_map_follows_the_format_and_fills_the_vocabulary():
    m = ram_map.load("BLUS30491")
    assert m.platform == "ps3" and m.id == "BLUS30491"
    assert ram_map.resolve({"game_id": "e7ca89bbeb67360d"}) == "BLUS30491"
    prof = vocab.profile("BLUS30491")
    assert vocab.check(prof) == []
    assert prof.mercs["driver"] == "gbox.mercs.titles.re5_ps3" and prof.units_per_m == 100
    for name in ("merc.timer", "merc.score", "merc.kills", "merc.combo", "merc.combo_timer", "player.pos",
                 "player.hp", "player.action", "player.aim_pitch", "enemy.ptrs"):
        f = m.fields[name]
        assert f.spec.get("source") == "scan" and "live 2026-10-20" in f.spec.get("evidence", ""), name


def test_the_map_reads_the_fixture_like_the_live_game():
    mem = world(player_pos=(10.0, 550.0, -20.0), action=2, pitch_raw=-0.05, hp=608,
                enemies=[((100.0, 550.0, 300.0), 800, 800)], score=900, kills=3, combo=2)
    v = ram_map.load("BLUS30491").read(mem.rd)
    assert v["merc.timer"] == 100.0 and v["merc.score"] == 900 and v["merc.kills"] == 3 and v["merc.combo"] == 2
    assert v["player.pos"] == [10.0, 550.0, -20.0] and v["player.hp"] == 608 and v["player.hp_max"] == 1000
    assert v.label("player.action") == "aim" and abs(v["player.aim_pitch"] - 0.05) < 1e-6   # + = up after the scale
    assert v["enemy.count"] == 1 and v["enemy.ptrs"] == [ENEMIES[0]]


def test_snapshot_reads_the_singletons():
    mem = world(player_pos=(1.0, 2.0, 3.0), yaw=math.radians(90), enemies=[((5.0, 0.0, 6.0), 700, 700)])
    s = R.snapshot(mem)
    p = s["player"]
    assert p["ptr"] == PLAYER and p["pos"] == (1.0, 2.0, 3.0) and abs(p["rot"] - math.radians(90)) < 1e-6
    assert p["hp"] == 1000 and p["state"] == "stand" and s["enemies"][0]["hp"] == 700
    assert s["timer"] == 100.0 and s["score"] == 900 and s["combo"] == 2 and abs(s["combo_timer"] - 8.9) < 1e-3
    assert R.own_screen(s) == "playing"


def test_screens_from_ram():
    assert R.own_screen(R.snapshot(world(hp=0))) == "dead"
    assert R.own_screen(R.snapshot(world(timer=0.0))) == "results"
    mem = world()
    mem.u32(SPLAYER + 0x28, 0)                      # results / menus: sPlayer holds no player
    assert R.own_screen(R.snapshot(mem)) == "loading"
    assert R.RE5PS3().screen(mem, None) == "loading"


def tick(mem, bot=None):
    bot = bot or R.Bot(clock=lambda: 100.0)
    return bot.tick(R.snapshot(mem)), bot


def test_turns_toward_the_majini_then_aims():
    # heading convention atan2(dx, dz): a Majini at +x is at +90 deg; facing +z (0): turn left (larger heading)
    act, bot = tick(world(enemies=[((1000.0, 0.0, 0.0), 800, 800)]))
    assert act == {"hold": {"rleft"}}
    act, _ = tick(world(yaw=math.radians(-90), enemies=[((-1.0, 0.0, -1000.0), 800, 800)]))   # behind-left
    assert act["hold"] == {"rleft"} or act["hold"] == {"rright"}
    act, _ = tick(world(yaw=math.radians(90), enemies=[((1000.0, 0.0, 0.0), 800, 800)]))
    assert act == {"hold": {"l1"}}                   # facing him: ready the gun


def test_aims_the_pitch_onto_the_head_and_fires():
    e = [((0.0, 0.0, 1000.0), 800, 800)]            # straight ahead; head 160 above his feet, gun 140 above ours
    want = math.atan2(R.HEAD_H - R.GUN_H, 1000.0)
    act, _ = tick(world(action=2, pitch_raw=-(want - 0.3), enemies=e))   # aimed 0.3 rad low: raise it, no fire
    assert "rup" in act["hold"] and "r1" not in act["hold"] and "l1" in act["hold"]
    act, _ = tick(world(action=2, pitch_raw=-(want + 0.3), enemies=e))   # high: lower it
    assert "rdown" in act["hold"] and "r1" not in act["hold"]
    act, bot = tick(world(action=2, pitch_raw=-want, enemies=e))         # on him: fire
    assert act["hold"] >= {"l1", "r1"} and bot.target == 0


def test_skips_crows_rooftops_and_the_dead_and_backs_off_when_on_top():
    e = [((0.0, 0.0, 300.0), 1, 1),                 # a crow: 1 health
         ((0.0, 900.0, 400.0), 800, 800),           # up on a roof
         ((0.0, 0.0, 500.0), 0, 800),               # dead
         ((900.0, 0.0, 0.0), 800, 800)]             # the one to fight: at +x
    act, bot = tick(world(enemies=e))
    assert act == {"hold": {"rleft"}}                # turning toward the live Majini at +x, not the crow ahead
    act, _ = tick(world(enemies=[((0.0, 0.0, 60.0), 800, 800)]))
    assert "ldown" in act["hold"]                    # on top of us: a step back
    act, _ = tick(world(enemies=[((0.0, 0.0, 6000.0), 800, 800)]))
    assert {"lup", "cross"} <= act["hold"]           # far: run to him


def test_hits_and_kills_are_counted_from_health():
    bot = R.Bot(clock=lambda: 1.0)
    bot.tick(R.snapshot(world(action=2, enemies=[((0.0, 0.0, 800.0), 800, 800)])))
    bot.tick(R.snapshot(world(action=2, enemies=[((0.0, 0.0, 800.0), 500, 800)])))
    bot.tick(R.snapshot(world(action=2, enemies=[((0.0, 0.0, 800.0), 0, 800)])))
    assert bot.stats["hits"] == 2 and bot.stats["kills_seen"] == 1


def test_death_presses_are_not_deaths_or_clock_bonuses(monkeypatch):
    monkeypatch.setattr(R, "HOURGLASS_VT", HOURGLASS_VT)
    now = [10.0]
    bot = R.Bot(clock=lambda: now[0], stats={"rounds": 1})
    bot.tick(R.snapshot(with_bonuses(world(timer=60.0), [(0.0, 13.0, 1200.0), (0.0, 13.0, 1800.0)])))
    for t in (12.0, 14.0, 16.0):
        now[0] = t
        assert bot.tick(R.snapshot(world(hp=0, timer=59.0))) == {"tap": "cross"}
    assert bot.stats["deaths"] == 1 and bot.stats["continue_presses"] == 3
    assert bot.stats.get("deaths_continued", 0) == 0
    now[0] = 20.0
    bot.tick(R.snapshot(with_bonuses(world(timer=120.0), [(0.0, 13.0, 1200.0)])))
    assert bot.stats["deaths_continued"] == 1 and bot.stats["rounds"] == 2
    assert bot.stats.get("bonuses_taken", 0) == bot.stats.get("clock_jumps", 0) == 0


def test_a_missing_snapshot_invalidates_bonus_and_health_comparisons(monkeypatch):
    monkeypatch.setattr(R, "HOURGLASS_VT", HOURGLASS_VT)
    bot = R.Bot(clock=lambda: 10.0)
    before = R.snapshot(with_bonuses(world(timer=60.0), [(0.0, 13.0, 1200.0)]))
    bot.observe_round(before, "playing", 10.0)
    bot.observe_round({"player": None}, "loading", 11.0)
    bot.observe_round(R.snapshot(world(timer=120.0)), "playing", 12.0)
    assert bot.stats.get("bonuses_taken", 0) == bot.stats.get("clock_jumps", 0) == 0


def test_health_events_do_not_overwrite_combat_shot_hits():
    bot = R.Bot(stats={"hits": 3})
    bot.combat = object()   # the combat layer owns landed-shot accounting
    bot._score_hits({"enemies": [{"ptr": 1, "hp": 800}]})
    bot._score_hits({"enemies": [{"ptr": 1, "hp": 0}]})
    assert bot.stats["hits"] == 3 and bot.stats["damage_events"] == 1 and bot.stats["kills_seen"] == 1


def test_engine_observes_restart_even_while_prompts_own_the_pad(monkeypatch):
    class Prompts:
        def step(self, now, ok):
            return [["square"]]

    monkeypatch.setattr(engine, "PromptPresser", lambda *a, **kw: Prompts())
    mem, n, stats = world(timer=60.0), [0], {"rounds": 1}
    bot = R.Bot(clock=lambda: float(n[0]), stats=stats)

    def stopped():
        n[0] += 1
        mem.put(PLAYER + R.P_HP, struct.pack(">hh", 0 if n[0] == 2 else 1000, 1000))
        if n[0] == 3:
            mem.put(GAMESYS + 0x3E0, struct.pack(">f", 120.0))
        return n[0] > 3

    engine.play_round({"driver": "gbox.mercs.titles.re5_ps3"}, mem, lambda rows: None, stopped, stats,
                      brain=bot, sleep=lambda s: None, clock=lambda: float(n[0]))
    assert stats["deaths"] == stats["deaths_continued"] == 1 and stats["rounds"] == 2
    assert stats.get("clock_jumps", 0) == 0


def test_play_round_runs_the_driver_until_the_round_ends():
    mem = world(action=2, enemies=[((0.0, 0.0, 1000.0), 800, 800)])
    sent, n = [], [0]

    def stopped():
        n[0] += 1
        if n[0] == 5:                                 # the clock runs out: the results screen
            mem.put(GAMESYS + 0x3E0, struct.pack(">f", 0.0))
        return n[0] > 50
    stats: dict = {}
    why = engine.play_round({"driver": "gbox.mercs.titles.re5_ps3"}, mem, sent.extend, stopped, stats,
                            sleep=lambda s: None, clock=lambda: n[0] * 0.5, tick_s=0.0)
    assert why == "round" and stats["timer"] == 0.0 and stats["score"] == 900
    assert {"key": "l1", "down": True} in sent        # pad names, pressed as a diff


def test_result_tally_refreshes_after_time_expires_and_preserves_totals_during_teardown(monkeypatch, tmp_path):
    for initial, final in ((8050, 8420), (9980, 10020)):
        monkeypatch.setattr(R, "ROSTER", R.Roster())
        memory = world(score=initial, kills=24, combo=6)
        n, stats, logged = [0], {}, []
        def stopped():
            n[0] += 1
            if n[0] == 3:
                memory.put(GAMESYS + R.GS_TIMER, struct.pack(">f", 0.0))
            if n[0] == 4:
                memory.put(GAMESYS + R.GS_SCORE, struct.pack(">i", final))
            if n[0] == 5:
                memory.put(GAMESYS + R.GS_SCORE, struct.pack(">i", 0))
                memory.put(GAMESYS + R.GS_KILLS, struct.pack(">i", 0))
            return n[0] > 20
        bot = R.Bot(stats=stats, learn_dir=tmp_path, clock=lambda: n[0] * 0.5)
        why = engine.play_round({"driver": "gbox.mercs.titles.re5_ps3"}, memory, lambda rows: None,
                                stopped, stats, logged.append, brain=bot, sleep=lambda seconds: None,
                                clock=lambda: n[0] * 0.5)
        assert why == "round" and stats["score"] == final and stats["kills"] == 24 and stats["timer"] == 0.0
        assert stats["rank"] == R.rank_of(final) and f"24k {final}p c6" in stats["char_tally"]
        assert logged[-1]["stats"]["score"] == final


def test_result_refresh_requires_the_observed_round_player_and_valid_terminal_fields(tmp_path):
    stats = {"score": 8050, "kills": 24, "rank": "D", "timer": 1.0}
    bot = R.Bot(stats=stats, learn_dir=tmp_path)
    terminal = R.snapshot(world(score=8420, kills=25, timer=0.0))
    bot.observe_round(terminal, "results", 0.0)
    assert stats["score"] == 8050                  # attaching at a menu is not a known round
    bot.observe_round(R.snapshot(world(score=8050, kills=24, timer=1.0)), "playing", 1.0)
    for invalid in (terminal | {"timer": None}, terminal | {"timer": float("nan")},
                    terminal | {"player": terminal["player"] | {"ptr": PLAYER + 0x1000}}):
        bot.observe_round(invalid, "results", 2.0)
        assert stats["score"] == 8050
    bot.observe_round(terminal | {"score": -1, "kills": None}, "results", 3.0)
    assert stats["score"] == 8050 and stats["kills"] == 24
    bot.observe_round(terminal, "results", 4.0)
    assert stats["score"] == 8420 and stats["kills"] == 25
    bot.observe_round(terminal | {"score": 90000}, "loading", 5.0)
    assert stats["score"] == 8420


def with_camera(mem, eye, at):
    """sBioCamera (static 0x0191CA6C) +0x104 -> uCameraCtrl: eye +0x30, look-at +0x50."""
    cam_mgr, cam = 0x3827_8170, 0x304F_C760
    mem.u32(R.S_CAMERA, cam_mgr)
    mem.u32(cam_mgr + R.CAM_CTRL, cam)
    mem.put(cam + R.CAM_EYE, struct.pack(">3f", *eye))
    mem.put(cam + R.CAM_AT, struct.pack(">3f", *at))
    return mem


def test_aims_on_the_cameras_look_ray_when_there_is_one():
    e = [((0.0, 0.0, 1000.0), 800, 800)]            # head at (0, 160, 1000)
    eye = (0.0, 200.0, -150.0)                       # over the shoulder, behind the player
    act, _ = tick(with_camera(world(action=2, enemies=e), eye, (0.0, 600.0, 400.0)))    # well above his head
    assert "rdown" in act["hold"] and "r1" not in act["hold"]
    act, _ = tick(with_camera(world(action=2, enemies=e), eye, (0.0, -300.0, 400.0)))   # at the ground
    assert "rup" in act["hold"] and "r1" not in act["hold"]
    act, _ = tick(with_camera(world(action=2, enemies=e), eye, (0.0, 160.0, 1000.0)))   # the crosshair on his head
    assert act["hold"] >= {"l1", "r1"}
    # facing +z, +x is on the left (the stick's left turns toward larger headings): a look at -x is right of him
    act, _ = tick(with_camera(world(action=2, enemies=e), eye, (-400.0, 160.0, 1000.0)))
    assert "rleft" in act["hold"] and "r1" not in act["hold"]
    act, _ = tick(with_camera(world(action=2, enemies=e), eye, (400.0, 160.0, 1000.0)))   # left of him: turn right
    assert "rright" in act["hold"] and "r1" not in act["hold"]


def test_continues_after_you_are_dead_and_walks_the_menus():
    bot = R.Bot(clock=lambda: 10.0)
    assert bot.tick(R.snapshot(world(hp=0))) == {"tap": "cross"}
    assert bot.tick(R.snapshot(world(hp=0))) == {"hold": set()}      # not again within 1.5 s
    assert [R.menu_key(n) for n in range(4)] == ["start", "cross", "start", "cross"]


def with_ui(mem, names, line=27):
    """sUnit (static 0x0191D700) with the interface units `names` in one move line (+0x24 + 0x20 * line: +0xC the first
    unit; a unit's +8 the next); a unit is its vtable (UI_VTABLES); a name may come as (name, {offset: u32}) to set
    its fields (cursors, states)."""
    sunit, first = 0x3882_5B20, 0x3009_8D00 + 0x10000 * line
    vt = {v: k for k, v in R.UI_VTABLES.items()}
    mem.u32(R.S_UNIT, sunit)
    mem.u32(sunit + R.UNIT_LINES + R.LINE_STRIDE * line + R.LINE_FIRST, first if names else 0)
    for i, n in enumerate(names):
        n, fields = (n, {}) if isinstance(n, str) else n
        u = first + 0x400 * i
        mem.u32(u, vt[n])
        for off, val in fields.items():
            mem.u32(u + off, val)
        mem.u32(u + R.UNIT_NEXT, u + 0x400 if i + 1 < len(names) else 0)
    return mem


def between_rounds(names):
    mem = world(timer=0.0)
    mem.u32(SPLAYER + 0x28, 0)                       # out of a round: sPlayer holds no player
    return with_ui(mem, names)


def test_the_screens_between_rounds_come_from_the_interface_units():
    assert R.screen(between_rounds(["uIdStartUp21", "uIdTitle00", "uIdTopMenu00"]))["where"] == "select_stage"
    assert R.screen(between_rounds(["uIdStartUp22", "uIdTitle02", "uIdTopMenu00"]))["where"] == "select_player"
    assert R.screen(between_rounds(["uIdNowLoading00"]))["where"] == "loading"
    assert R.screen(between_rounds(["uIdSaving00"]))["where"] == "loading"       # the results, saving the records
    assert R.screen(between_rounds(["uIdTitle00", "uIdTopMenu00"]))["where"] == "menu"   # between the selects / main menu
    assert R.screen(between_rounds(["uIdCursor"]))["where"] == "results"          # the clock at 0, the cursors up
    assert R.screen(between_rounds(["uIdAlert00"]))["where"] == "unknown"         # the boot's logos: no press
    mem = world(enemies=[((0.0, 0.0, 900.0), 800, 800)])
    assert R.screen(with_ui(mem, ["uIdMerce00", "uIdPause00"]))["where"] == "playing"
    assert R.screen(world(hp=0))["where"] == "dead"


def test_it_presses_only_on_the_reunion_screens():
    assert R.step({"where": "results"}) == "start"
    assert R.step({"where": "select_stage"}) in ("dright", "cross")   # a random stage (StagePick)
    assert R.step({"where": "select_player", "cursor": 6, "target": 6}) == "cross"          # Barry picked, on him
    assert R.step({"where": "select_player", "cursor": 2, "target": 6}) == "dright"
    assert R.step({"where": "select_player", "cursor": 7, "target": 6}) == "dleft"
    assert R.step({"where": "select_player"}) is None                                       # no cursor read: wait
    assert R.step({"where": "dead"}) == "cross"
    for where in ("menu", "loading", "unknown", "playing"):
        assert R.step({"where": where}) is None, where                       # never a press on the title's menus
    assert R.wandered({"where": "menu"}) is None


def test_a_grab_is_answered_with_a_wiggle():
    held = world(action=R.P_GRABBED, enemies=[((0.0, 0.0, 60.0), 800, 800)])
    assert R.prompt(held) == "wiggle"
    assert R.prompt(world(action=2)) is None
    drv = R.RE5PS3()
    assert drv.prompt_source(held, {})() == "wiggle"
    assert drv.prompt_keys("wiggle") == [("lleft",), ("lright",), ("lleft",), ("lright",)]
    assert drv.prompt_keys("square") == [("square",)]
    from gbox.mercs import reactions
    assert "wiggle" in reactions.MASH                                             # the engine mashes it, never rests
    assert R.snapshot(held)["player"]["state"] == "grabbed"


def test_explicit_resuscitate_prompt_keeps_zero_hp_recoverable_without_counting_a_death(tmp_path):
    # The detected prompt is supplied here; this fixture makes no claim about an unverified action/flag offset.
    now, stats = [10.0], {"rounds": 1}
    bot = R.Bot(clock=lambda: now[0], stats=stats, learn_dir=tmp_path)
    before = R.snapshot(world(timer=50.0))
    bot.observe_round(before, "playing", now[0])
    dying = R.snapshot(world(hp=0, timer=49.0)) | {"prompt": "mash"}
    assert R.own_screen(dying) == "playing"
    assert bot.tick(dying) == {"hold": set()}
    assert stats["resuscitating"] and stats.get("deaths", 0) == 0
    driver = R.RE5PS3(clock=lambda: now[0])
    assert driver.screen(None, dying) == "playing"
    now[0] += R.HANG_S + 1
    assert driver.screen(None, dying) == "playing"          # explicit live QTE can pause the Mercenaries clock
    recovered = R.snapshot(world(hp=1000, timer=49.0))
    bot.observe_round(recovered, "playing", now[0])
    assert driver.screen(None, recovered) == "playing"
    assert stats["rounds"] == 1 and stats.get("deaths_continued", 0) == 0
    assert not stats["resuscitating"] and stats.get("continue_presses", 0) == 0
    assert R.own_screen(dying | {"prompt": None}) == "dead"
    assert R.own_screen(dying | {"timer": 0.0}) != "playing"


def test_resuscitate_uses_repeated_circle_at_engine_mash_cadence_without_combat(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "prompt", lambda memory: "mash")  # explicit detector result, not a guessed RAM value
    memory, stats, n, sent, sleeps = world(hp=0, timer=50.0), {}, [0], [], []
    bot = R.Bot(stats=stats, clock=lambda: n[0] * 0.08, learn_dir=tmp_path)

    def stopped():
        n[0] += 1
        return n[0] > 5

    engine.play_round({"driver": "gbox.mercs.titles.re5_ps3"}, memory, sent.extend, stopped, stats,
                      brain=bot, sleep=sleeps.append, clock=lambda: n[0] * 0.08)
    assert sent == [{"key": "circle", "down": down} for _ in range(5) for down in (True, False)]
    assert sleeps == [0.045, 0.035] * 5
    assert stats["mash_presses"] == stats["presses_mash"] == stats["resuscitate_presses"] == 5
    assert stats.get("deaths", 0) == stats.get("continue_presses", 0) == 0


def with_prompt(mem, kind, owner, target, *, visible=True, mode=1, index=1, second=False, btn=0x328E1FE0):
    """Verified displayed ButtonMgr unit, independent of manager+0x34's active-array count."""
    ab = 0x3883_8370
    unit = ab + R.QTE_UNITS[bool(second)]
    mem.u32(R.S_ACTION, ab)
    mem.put(ab + R.AB_ENABLED, b"\x01")
    mem.put(ab + R.AB_PLAYER_ENABLED, b"\x01")
    mem.u32(ab + R.AB_PLAYER_INDEX, 0)
    mem.u32(ab + R.AB_INPUT_MODE, 0)
    mem.u32(ab + R.AB_ALTERNATE_CONTROLLER, 0xFFFFFFFF)
    mem.put(R.QTE_INPUT_TABLE, R.QTE_INPUT_SIGNATURE)
    for address, expected in (R.QTE_SIGNATURES | R.QTE_STICK_SIGNATURES).items():
        mem.put(address, expected)
    mem.put(unit + 4, bytes((1, int(visible))))
    mem.u32(unit + 0x0C, btn)
    mem.u32(unit + 0x10, mode)
    mem.u32(unit + 0x18, R.QTE_MASKS[index])
    mem.u32(btn, R.QTE_BUTTON_VT)
    mem.put(btn + 0x0A, b"\x01")
    mem.u32(btn + R.BTN_OWNER, owner)
    mem.u32(btn + R.BTN_KIND, kind)
    mem.u32(btn + 0x18, mode)
    mem.u32(btn + 0x20, index)
    mem.u32(btn + 0x24, 0x37)
    mem.u32(btn + 0x30, 1)
    mem.u32(btn + R.BTN_TARGET, target)
    return mem


def test_a_melee_finisher_on_a_majini_is_pressed_with_square():
    e = [((0.0, 0.0, 150.0), 450, 800)]
    assert R.prompt(with_prompt(world(enemies=e), R.BTN_MELEE, PLAYER, ENEMIES[0])) == "mash:square"
    assert R.prompt(with_prompt(world(enemies=e), R.BTN_MELEE, PLAYER, ENEMIES[0], visible=False)) is None
    assert R.prompt(with_prompt(world(enemies=e), R.BTN_STAGE, PLAYER, 0)) == "mash:square"
    assert R.prompt(with_prompt(world(enemies=e), R.BTN_MELEE, PLAYER, 0x3099_0000)) == "mash:square"
    assert R.prompt(with_prompt(world(enemies=e), 0, ENEMIES[0], 0)) == "mash:square"  # selected enemy-owned QTE
    held = with_prompt(world(action=R.P_GRABBED, enemies=e), 0, ENEMIES[0], 0, visible=False)
    assert R.prompt(held) == "wiggle"                                                             # the grab itself
    act, _ = tick(with_prompt(world(action=2, enemies=e), R.BTN_MELEE, PLAYER, ENEMIES[0]))
    assert act == {"hold": set()}                     # the gun down while the engine presses the finisher (no L1)


def test_verified_melee_square_uses_boss_policy_but_escape_square_keeps_fast_mash(tmp_path):
    from gbox.mercs import reactions
    memory = with_prompt(world(enemies=[((0.0, 0.0, 150.0), 9000, 9000)]),
                         R.BTN_MELEE, PLAYER, ENEMIES[0])
    stats, driver = {}, R.RE5PS3()
    bot = R.Bot(memory, stats=stats, learn_dir=tmp_path)
    source = driver.prompt_source(memory, stats)
    pp = reactions.PromptPresser(source=source, keys=driver.prompt_keys, stats=stats)
    snapshot = R.snapshot(memory)
    assert snapshot["prompt"] == "mash:square" and source() == "square"
    assert pp.step(1.0, ok=lambda key: bot.prompt_ok(key, snapshot, 1.0)) == [("square",)]
    assert not pp.mashing and bot.combat.melees[ENEMIES[0]] == 1
    assert pp.step(2.0, ok=lambda key: bot.prompt_ok(key, snapshot, 2.0)) is None
    assert stats["boss_melee_held"] == 1 and stats["prompt_presses"] == 1
    for kind in (0, R.BTN_STAGE):
        with_prompt(memory, kind, ENEMIES[0], ENEMIES[0])
        assert source() == "mash:square"
        pp.rest_until = 100.0
        for now in (3.0, 3.08):
            assert pp.step(now, ok=lambda key: False) == [("square",)]
            assert pp.mashing                     # escape / traversal requests bypass ordinary melee policy and rest
    with_prompt(memory, R.BTN_MELEE, PLAYER, ENEMIES[0], mode=3, index=14)
    assert source() == "mash:cross+circle"          # a kind alone cannot turn a mandatory chord into melee
    assert pp.step(3.16, ok=lambda key: False) == [("cross", "circle")]
    for mode in (3, 4, 5):
        with_prompt(memory, R.BTN_MELEE, PLAYER, ENEMIES[0], mode=mode, index=1)
        assert source() == "mash:square"          # accumulated / repeated-edge requests must retain fast cadence
        assert pp.step(3.24, ok=lambda key: False) == [("square",)] and pp.mashing


def test_verified_qte_faces_chords_and_second_display_unit_ignore_array_count():
    for mode in (1, 3, 4, 5):
        for index, expected in ((1, "square"), (2, "triangle"), (3, "cross"), (4, "circle"),
                                (5, "l2"), (6, "r2"), (7, "l1"), (8, "r1"),
                                (13, "square+triangle"), (14, "cross+circle"), (15, "square+cross"),
                                (16, "triangle+circle"), (17, "l1+r1"), (18, "l2+r2"), (19, "l1+r1")):
            memory = with_prompt(world(), 0, ENEMIES[0], 0, mode=mode, index=index, second=True)
            memory.u32(0x38838370 + 0x34, 1)             # count1 would fail the old fictitious HUD bit test
            assert R.prompt(memory) == "mash:" + expected
            assert R.RE5PS3().prompt_keys(R.prompt(memory)) == [tuple(expected.split("+"))]


def test_qte_rejects_stale_inactive_mismatched_or_unknown_requests():
    for address, raw in ((R.QTE_INPUT_TABLE, b"bad!"), (next(iter(R.QTE_SIGNATURES)), b"bad!"),
                         (0x328E1FE0, b"bad!"), (0x328E1FE0 + 0x70, struct.pack(">I", 1)),
                         (0x38838370 + R.QTE_UNITS[0] + 5, b"\0"),
                         (0x328E1FE0 + 0x0A, b"\0"), (0x328E1FE0 + 0x0C, b"\1"),
                         (0x38838370 + R.AB_PLAYER_INDEX, struct.pack(">I", 1)),
                         (0x38838370 + R.AB_INPUT_MODE, struct.pack(">I", 1)),
                         (0x38838370 + R.AB_ALTERNATE_CONTROLLER, struct.pack(">I", 0)),
                         (0x38838370 + R.QTE_UNITS[0] + 0x18, struct.pack(">I", 0x4000))):
        memory = with_prompt(world(), 2, PLAYER, 0, mode=5, index=25)
        memory.put(address, raw)
        assert R.prompt(memory) is None
    for mode, index in ((0, 1), (99, 1), (1, 20), (1, 29)):
        assert R.prompt(with_prompt(world(), 2, PLAYER, 0, mode=mode, index=index)) is None
    assert R.RE5PS3().prompt_keys("mash:circle+unknown") == []
    assert R.RE5PS3().prompt_keys("mash:circle+circle") == []


def test_qte_release_mode_clears_existing_fire_and_never_presses_the_requested_chord(tmp_path):
    memory = with_prompt(world(), 2, PLAYER, 0, mode=2, index=14)
    assert R.prompt(memory) == "release:cross+circle"
    driver = R.RE5PS3()
    assert driver.prompt_source(memory, {})() is None
    assert driver.prompt_keys("release:cross+circle") == []
    bot = R.Bot(learn_dir=tmp_path)
    original_tick = bot.tick
    count, sent = [0], []

    def stopped():
        count[0] += 1
        memory.put(0x38838370 + R.QTE_UNITS[0] + 5, bytes((int(count[0] > 1),)))
        return count[0] > 2

    bot.tick = lambda snapshot: {"hold": {"l1", "r1"}} if count[0] == 1 else original_tick(snapshot)
    engine.play_round({"driver": "gbox.mercs.titles.re5_ps3"}, memory, sent.extend, stopped, {},
                      brain=bot, sleep=lambda seconds: None, clock=lambda: float(count[0]))
    assert sent == [{"key": key, "down": down} for down in (True, False) for key in ("l1", "r1")]


def test_live_resuscitate_signature_is_hp_one_selected_circle_edge_mode_and_skips_health(monkeypatch, tmp_path):
    from gbox import re5_mods_tool
    from types import SimpleNamespace
    memory = with_prompt(world(hp=1, action=7), 2, PLAYER, 0, mode=5, index=25)
    memory.put(PLAYER + R.P_DYING_TIMER, struct.pack(">f", 6.74))
    memory.u32(PLAYER + R.P_RECOVER_BUTTON, 0x328E1FE0)
    for mode in (1, 3, 4, 5):
        memory.u32(0x328E1FE0 + 0x18, mode)
        memory.u32(0x38838370 + R.QTE_UNITS[0] + 0x10, mode)
        assert R.prompt(memory) == "mash"                  # recovery callback consumes successful button edges
    snapshot = R.snapshot(memory)
    assert R.own_screen(snapshot) == "playing"
    bot = R.Bot(learn_dir=tmp_path)
    bot.m = SimpleNamespace(adapter=object())
    def unexpected_health(*args, **kwargs):
        raise AssertionError("resuscitation must finish through its input handler before HP is refilled")
    monkeypatch.setattr(re5_mods_tool, "maintain_health", unexpected_health)
    assert bot.tick(snapshot) == {"hold": set()}
    assert snapshot["player"]["hp"] == 1 and bot.stats["resuscitating"]
    memory.u32(PLAYER + R.P_RECOVER_BUTTON, 0)
    assert R.prompt(memory) == "mash:circle"                  # ordinary circle request, not self-resuscitation
    memory.put(PLAYER + R.P_HP, struct.pack(">h", 0))
    assert R.prompt(memory) is None                         # same glyph data cannot authorize input on a corpse


def test_generic_qte_chord_uses_engine_fast_cadence(monkeypatch, tmp_path):
    memory = with_prompt(world(), 0, ENEMIES[0], 0, mode=3, index=14)
    stats, sent, sleeps, count = {}, [], [], [0]
    def stopped():
        count[0] += 1
        return count[0] > 4
    bot = R.Bot(stats=stats, learn_dir=tmp_path)
    engine.play_round({"driver": "gbox.mercs.titles.re5_ps3"}, memory, sent.extend, stopped, stats,
                      brain=bot, sleep=sleeps.append, clock=lambda: count[0] * 0.08)
    assert sent == [{"key": key, "down": down} for _ in range(4) for down in (True, False)
                    for key in ("cross", "circle")]
    assert sleeps == [0.045, 0.035] * 4 and stats["qte_presses"] == 4


def test_verified_self_resuscitation_preempts_a_second_displayed_request(tmp_path):
    memory = with_prompt(world(hp=1, action=7), 2, PLAYER, 0, mode=5, index=25)
    memory.put(PLAYER + R.P_DYING_TIMER, struct.pack(">f", 6.74))
    memory.u32(PLAYER + R.P_RECOVER_BUTTON, 0x328E1FE0)
    memory.u32(0x328E1FE0 + 0x1C, 63)
    with_prompt(memory, 2, PLAYER, 0, mode=1, index=1, second=True, btn=0x328E3000)
    memory.u32(0x328E3000 + 0x1C, 0)
    assert R.prompt(memory) == "mash"                 # a lower numeric priority cannot hide verified self-recovery
    assert R.selected_prompt(memory)["button"] == 0x328E1FE0
    memory.u32(PLAYER + R.P_RECOVER_BUTTON, 0)
    assert R.prompt(memory) == "mash:square"          # ordinary requests retain the normal priority ordering


def test_hidden_recovery_preserves_hp_and_waits_without_inventing_a_prompt(monkeypatch, tmp_path):
    from gbox import re5_mods_tool
    from types import SimpleNamespace
    memory = with_prompt(world(hp=1, action=7), 2, PLAYER, 0, mode=5, index=25, visible=False)
    memory.put(PLAYER + R.P_DYING_TIMER, struct.pack(">f", 6.74))
    memory.u32(PLAYER + R.P_RECOVER_BUTTON, 0x328E1FE0)
    memory.put(0x328E1FE0 + 0x0A, b"\0")       # hidden and inactive during a hit animation
    memory.put(PLAYER + 0x1D0B, b"\1")
    memory.u32(PLAYER + 0x1220, 0x7B)         # transient callback pause does not finish the DYING state
    assert R.recovery_active(memory) and R.RE5PS3().recovery_active(memory)
    snapshot = R.snapshot(memory)
    assert snapshot["recovery_active"] and snapshot["prompt"] is None
    bot = R.Bot(learn_dir=tmp_path)
    bot.m = SimpleNamespace(adapter=object())
    def unexpected_health(*args, **kwargs):
        raise AssertionError("hidden recovery must not be refilled")
    monkeypatch.setattr(re5_mods_tool, "maintain_health", unexpected_health)
    assert bot.tick(snapshot) == {"hold": set()} and bot.stats["resuscitating"]
    now = [0.0]
    driver = R.RE5PS3(clock=lambda: now[0])
    assert driver.screen(memory, snapshot) == "playing"
    now[0] = R.HANG_S + 1
    assert driver.screen(memory, snapshot) == "playing"  # a recovery-paused clock is not a lost game
    memory.put(PLAYER + R.P_HP, struct.pack(">h", 1000))
    assert not R.recovery_active(memory)


def test_recovery_state_requires_current_hp_one_countdown_and_owned_button():
    def dying():
        memory = with_prompt(world(hp=1, action=7), 2, PLAYER, 0, mode=5, index=25, visible=False)
        memory.put(PLAYER + R.P_DYING_TIMER, struct.pack(">f", 6.74))
        memory.u32(PLAYER + R.P_RECOVER_BUTTON, 0x328E1FE0)
        return memory
    for address, raw in ((PLAYER + R.P_HP, struct.pack(">h", 0)),
                         (PLAYER + R.P_HP, struct.pack(">h", 2)),
                         (PLAYER + R.P_DYING_TIMER, struct.pack(">f", 0.0)),
                         (PLAYER + R.P_DYING_TIMER, struct.pack(">f", float("nan"))),
                         (PLAYER + R.P_DYING_TIMER, struct.pack(">f", float("inf"))),
                         (PLAYER + R.P_RECOVER_BUTTON, struct.pack(">I", 0x328E1FE1)),
                         (0x328E1FE0, struct.pack(">I", 0)),
                         (0x328E1FE0 + 4, struct.pack(">I", ENEMIES[0]))):
        memory = dying()
        memory.put(address, raw)
        assert not R.recovery_active(memory)
    assert not R.recovery_active(dying(), PLAYER + 4)
    memory = dying()
    rd = memory.rd
    reads = [0]
    def swap_on_read(address, size):
        if address == 0x328E1FE0 and size == 8:
            reads[0] += 1
            if reads[0] == 1:
                memory.u32(SPLAYER + 0x28, PLAYER + 0x1000)
        return rd(address, size)
    memory.rd = swap_on_read
    assert not R.recovery_active(memory)


def test_qte_stick_modes_require_verified_handlers_and_consistent_nonzero_index():
    for mode, token in R.QTE_STICK_MODES.items():
        memory = with_prompt(world(), 2, PLAYER, 0, mode=mode, index=20)
        assert R.QTE_MASKS[20] == 0 and R.prompt(memory) == token
        memory.u32(0x328E1FE0 + 0x20, 0)
        assert R.prompt(memory) is None              # index0 is explicitly display-only in the evaluator
        memory.u32(0x328E1FE0 + 0x20, 1)
        assert R.prompt(memory) is None              # stale copied mask cannot authorize a stick request
        memory.u32(0x38838370 + R.QTE_UNITS[0] + 0x18, R.QTE_MASKS[1])
        assert R.prompt(memory) == token             # these modes use directions independently of the digital mask
        memory.put(PLAYER + R.P_HP, struct.pack(">h", 0))
        assert R.prompt(memory) is None
    for address in R.QTE_STICK_SIGNATURES:
        memory = with_prompt(world(), 2, PLAYER, 0, mode=7, index=21)
        memory.put(address, b"bad!")
        assert R.prompt(memory) is None
    assert R.RE5PS3().prompt_keys("stick:unknown") == []
    assert R.RE5PS3().prompt_keys("mash:wiggle+circle") == []


def test_qte_wiggle_uses_alternating_real_edges_at_fast_cadence(tmp_path):
    memory = with_prompt(world(), 2, PLAYER, 0, mode=6, index=20)
    stats, sent, sleeps, count = {}, [], [], [0]
    def stopped():
        count[0] += 1
        return count[0] > 4
    bot = R.Bot(stats=stats, learn_dir=tmp_path)
    engine.play_round({"driver": "gbox.mercs.titles.re5_ps3"}, memory, sent.extend, stopped, stats,
                      brain=bot, sleep=sleeps.append, clock=lambda: count[0] * 0.08)
    assert sent == [{"key": key, "down": down} for key in ("lleft", "lright", "lleft", "lright")
                    for down in (True, False)]
    assert sleeps == [0.045, 0.035] * 4 and stats["qte_presses"] == 4


def test_qte_rotation_keeps_adjacent_directions_held_and_releases_on_stop(tmp_path):
    memory = with_prompt(world(), 2, PLAYER, 0, mode=7, index=21)
    count, held, states = [0], set(), []
    def stopped():
        count[0] += 1
        return count[0] > 9
    def send(rows):
        for row in rows:
            if row["down"]:
                held.add(row["key"])
            else:
                held.discard(row["key"])
        states.append(set(held))
    now = lambda: count[0] * 0.081
    bot = R.Bot(learn_dir=tmp_path, clock=now)
    driver = R.RE5PS3()
    assert driver.prompt_source(memory, {})() is None
    assert driver.prompt_keys("stick:rotate") == []
    engine.play_round({"driver": "gbox.mercs.titles.re5_ps3"}, memory, send, stopped, {},
                      brain=bot, sleep=lambda seconds: None, clock=now)
    assert states == [set(keys) for keys in (*R.QTE_ROTATION, R.QTE_ROTATION[0])] + [set()]
    assert all(states[:-1]) and not held              # no neutral frame occurs within the circular sequence


def test_qte_rotation_delays_never_skip_directions_and_axis_requests_hold_until_end(tmp_path):
    memory = with_prompt(world(), 2, PLAYER, 0, mode=7, index=21)
    now = [0.0]
    bot = R.Bot(learn_dir=tmp_path, clock=lambda: now[0])
    assert bot.tick(R.snapshot(memory)) == {"hold": {"lup"}}
    now[0] = 0.01
    assert bot.tick(R.snapshot(memory)) == {"hold": {"lup"}}
    now[0] = 2.0
    assert bot.tick(R.snapshot(memory)) == {"hold": {"lup", "lleft"}}
    for mode, key in ((8, "lup"), (9, "lleft")):
        with_prompt(memory, 2, PLAYER, 0, mode=mode, index=26)
        assert R.RE5PS3().prompt_source(memory, {})() is None
        assert bot.tick(R.snapshot(memory)) == {"hold": {key}}
        now[0] += 2
        assert bot.tick(R.snapshot(memory)) == {"hold": {key}}
    with_prompt(memory, 2, PLAYER, 0, mode=2, index=1)
    assert bot.tick(R.snapshot(memory)) == {"hold": set()}
    assert bot._stick_token is None
    with_prompt(memory, 2, PLAYER, 0, mode=7, index=21)
    assert bot.tick(R.snapshot(memory)) == {"hold": {"lup"}}


HOURGLASS_VT = 0x0159_0000


def with_bonuses(mem, centres, kind=0x00A00C01):
    """sUnit's OM line with a barrel and hourglasses (uOm0100 = HOURGLASS_VT) whose bounding spheres (+0x250: centre,
    28 cm radius) sit at `centres`; +0x194 their kind word."""
    sunit, first = 0x3882_5B20, 0x3040_0000
    mem.u32(R.S_UNIT, sunit)
    mem.u32(sunit + R.UNIT_LINES + R.LINE_STRIDE * R.OM_LINE + R.LINE_FIRST, first)
    units = [(0x0158_8888, (500.0, 0.0, 500.0))] + [(HOURGLASS_VT, q) for q in centres]   # a barrel first
    for i, (vt, q) in enumerate(units):
        u = first + 0x1000 * i
        mem.u32(u, vt)
        mem.put(u + 0x30, struct.pack(">3f", q[0], q[1] - 13.0, q[2]))           # the origin: 13 cm below the centre
        mem.put(u + R.HG_CENTRE, struct.pack(">4f", *q, 28.4))
        mem.u32(u + R.HG_KIND, kind)
        mem.u32(u + R.UNIT_NEXT, u + 0x1000 if i + 1 < len(units) else 0)
    return mem


def test_time_bonuses_are_read_from_the_om_line(monkeypatch):
    monkeypatch.setattr(R, "HOURGLASS_VT", HOURGLASS_VT)
    snap = R.snapshot(with_bonuses(world(), [(0.0, 140.0, 1000.0), (-800.0, 50.0, 0.0)]))
    assert [b["pos"] for b in snap["bonuses"]] == [(0.0, 140.0, 1000.0), (-800.0, 50.0, 0.0)]
    assert snap["bonuses"][0]["r"] == pytest.approx(28.4) and snap["bonuses"][0]["kind_word"] == 0x00A00C01
    monkeypatch.setattr(R, "HOURGLASS_VT", 0)                                     # not known: none read
    assert R.snapshot(with_bonuses(world(), [(0.0, 0.0, 1000.0)]))["bonuses"] == []


def test_a_time_bonus_is_taken_with_its_prompt(monkeypatch):
    monkeypatch.setattr(R, "HOURGLASS_VT", HOURGLASS_VT)
    assert R.BONUS_HUNT is True
    far_majini = [((3000.0, 0.0, 0.0), 800, 800)]                                # 30 m away at +x
    act, bot = tick(with_bonuses(world(enemies=far_majini), [(0.0, 13.0, 100.0)]))   # 1 m ahead, facing it
    assert act == {"tap": "square"} and str(bot.target).startswith("bonus")      # punch it (the prompt is not a
    assert bot.stats["bonus_presses"] == 1                                       # kind-2 cActionButton: press blind)
    mem = with_prompt(with_bonuses(world(enemies=far_majini), [(0.0, 13.0, 100.0)]), R.BTN_STAGE, PLAYER, 0)
    act, bot = tick(mem)
    assert act == {"hold": set()} and R.prompt(mem) == "mash:square"  # engine rapidly answers its displayed prompt
    act, _ = tick(with_bonuses(world(enemies=far_majini), [(-300.0, 13.0, 0.0)])) # 3 m to the right: turn to it first
    assert act == {"hold": {"rright"}}
    close = [((0.0, 0.0, 250.0), 800, 800)]                                       # a Majini 2.5 m away, bonus 6 m off:
    act, bot = tick(with_bonuses(world(action=2, enemies=close), [(0.0, 13.0, 600.0)]))
    assert bot.target == 0                                                        # him first
    act, bot = tick(with_bonuses(world(enemies=close), [(0.0, 13.0, 100.0)]))     # but a bonus 1 m off (in reach):
    assert not str(bot.target).startswith("bonus") and "l1" in act["hold"]  # nearest foe first


def test_a_bonus_that_will_not_take_is_left_alone_for_a_while(monkeypatch):
    monkeypatch.setattr(R, "HOURGLASS_VT", HOURGLASS_VT)
    clock = [100.0]
    bot = R.Bot(clock=lambda: clock[0])
    mem = with_bonuses(world(), [(0.0, 13.0, 40.0)])                             # right at it: punch it blind
    assert bot.tick(R.snapshot(mem)) == {"tap": "square"}
    clock[0] += R.BONUS_GIVE_UP_S + 0.5                                          # punched a while, still here:
    bot.tick(R.snapshot(mem))
    assert bot.bonus_skip                                                        # left alone now
    clock[0] += R.BONUS_SKIP_S + 1
    assert bot.tick(R.snapshot(mem)) == {"tap": "square"}                        # tried again later


def test_bonuses_anywhere_are_walked_to_nearest_first_and_the_clock_jumps_are_counted(monkeypatch):
    monkeypatch.setattr(R, "HOURGLASS_VT", HOURGLASS_VT)
    act, bot = tick(with_bonuses(world(), [(0.0, 13.0, 1200.0)]))                 # 12 m ahead, nobody near, no mesh
    assert {"lup", "cross"} <= act["hold"]                                        # straight at it
    act, b2 = tick(with_bonuses(world(), [(0.0, 13.0, 2500.0), (0.0, 400.0, 900.0)]))   # 25 m off, 9 m up a roof
    assert {"lup", "cross"} <= act["hold"] and b2.target == "bonus 0x30402000"   # the nearer, whatever its level
    assert b2.stats["phase"] == "gather_time" and b2.stats["nearest_eta_s"] > 0
    near = [((0.0, 0.0, 300.0), 800, 800)]                                       # a Majini 3 m ahead: fought first
    act, b3 = tick(with_bonuses(world(action=2, enemies=near), [(0.0, 13.0, 1200.0)]))
    assert b3.target == 0 and b3.stats["phase"] == "clear_nearby"
    behind = [((0.0, 0.0, -300.0), 800, 800)]                                    # one 3 m behind: he walks on
    act, b4 = tick(with_bonuses(world(enemies=behind), [(0.0, 13.0, 1200.0)]))
    assert not str(b4.target).startswith("bonus") and "cross" not in act["hold"]
    monkeypatch.setattr(R, "BONUS_WALK", False)
    act, _ = tick(with_bonuses(world(), [(0.0, 13.0, 1200.0)]))
    assert act == {"hold": set()}                                                 # without routes: out of reach
    bot.tick(R.snapshot(with_bonuses(world(timer=60.0), [])))                     # gone from the line: taken
    assert bot.stats["bonuses_taken"] == 1
    bot.tick(R.snapshot(with_bonuses(world(timer=89.5), [])))                     # the clock +29.5 s: a time bonus
    assert bot.stats["clock_jumps"] == 1 and bot.stats["bonus_s"] == 29.5


def with_inventory(mem, slots, grids=None):
    """The player's inventory (+0x22E0, 0x30 a slot): slots = {k: (id word, rounds, cap, in hand)}."""
    for k, (word, rounds, cap, hand) in slots.items():
        base = PLAYER + R.P_INV + R.INV_SLOT * k
        mem.u32(base + R.INV_ID, word)
        mem.u32(base + R.INV_ROUNDS, rounds)
        mem.u32(base + R.INV_CAP, cap)
        mem.u32(base + R.INV_GRID, (grids or {}).get(k, k))
        mem.u32(base + R.INV_HAND, 1 if hand else 0)
        mem.put(base + R.INV_USED, b"\x01")
    return mem


def test_the_inventory_names_the_weapon_in_hand_and_an_empty_one_is_switched_off():
    mem = with_inventory(world(), {0: (0x112, 30, 30, True), 3: (0x10B, 6, 6, False), 4: (0x202, 150, 150, False),
                                   12: (0x115, 400, 400, False)})
    snap = R.snapshot(mem)
    assert [x["slot"] for x in snap["inventory"]] == [0, 3, 4, 12]  # Every used record, including those past index8.
    assert snap["inventory"][-1]["grid"] is None
    assert R.equipped(snap)["item"] == 0x12 and snap["inventory"][2]["type"] == 2
    act, bot = tick(with_inventory(world(enemies=[((0.0, 0.0, 900.0), 800, 800)]),
                                   {0: (0x112, 30, 30, True), 3: (0x10B, 6, 6, False)}))
    assert bot.stats["weapon"] == "Barry's handgun 30/30" and "l1" in act["hold"]
    act, bot = tick(with_inventory(world(enemies=[((0.0, 0.0, 900.0), 800, 800)]),
                                   {0: (0x112, 0, 0, True), 3: (0x10B, 6, 6, False)}))
    assert act == {"tap": "dleft"} and bot.stats["weapon_switch_attempts"] == 1
    assert bot.stats.get("weapon_switches", 0) == 0          # A tap is not proof that the gun entered the hand.
    act, bot = tick(with_inventory(world(enemies=[((0.0, 0.0, 900.0), 800, 800)]),
                                   {0: (0x112, 0, 30, True), 3: (0x10B, 6, 6, False)}))
    assert act == {"hold": {"l1", "cross"}} and bot.stats["reloads"] == 1          # 0/30: reload


def test_live_inventory_storage_order_is_not_the_dpad_grid():
    mem = with_inventory(world(), {0: (0x10D, 1, 1, True), 1: (0x119, 10, 10, False),
                                  6: (0x304, 1, 1, False), 8: (0x101, 1, 1, False),
                                  12: (0x10B, 6, 6, False)}, grids={0: 3, 1: 5, 6: 1, 8: 9, 12: 7})
    inv = R.inventory(mem, PLAYER)
    assert [(i["slot"], i["grid"]) for i in inv] == [(0, 3), (1, 5), (6, 1), (8, None), (12, 7)]
    assert inv[3]["grid_raw"] == 9
    empty = with_inventory(world(enemies=[((0.0, 0.0, 500.0), 800, 800)]),
                           {0: (0x10D, 0, 0, True), 1: (0x119, 10, 10, False)}, grids={0: 3, 1: 5})
    assert tick(empty)[0] == {"tap": "dright"}
    heal = with_inventory(world(hp=100), {6: (0x304, 1, 1, False)}, grids={6: 1})
    assert tick(heal)[0] == {"tap": "dup"}
    heal.u32(PLAYER + R.P_INV + 6 * R.INV_SLOT + R.INV_GRID, 9)
    assert tick(heal)[0] == {"hold": set()}


def healing_bot(tmp_path, *, held=False, action=0):
    now = [100.0]
    mem = with_inventory(world(hp=100, action=action, enemies=[((0, 0, 180), 800, 800)]),
                         {0: (0x10B, 6, 6, not held), 6: (0x304, 1, 1, held)}, grids={0: 3, 6: 1})
    bot = R.Bot(m=mem, clock=lambda: now[0], learn_dir=tmp_path, lessons=lambda row: None)
    return bot, mem, now


def test_heal_equips_then_confirms_in_hand_then_square_without_combat_switching_away(tmp_path):
    bot, mem, now = healing_bot(tmp_path)
    assert bot.tick(R.snapshot(mem)) == {"tap": "dup"}
    assert bot.stats.get("heals", 0) == 0 and bot.stats["heal_equip_attempts"] == 1
    now[0] += .1
    assert bot.tick(R.snapshot(mem)) == {"hold": set()}  # selection alone is not healing or permission to use Square
    mem.u32(PLAYER + R.P_INV + R.INV_HAND, 0)
    mem.u32(PLAYER + R.P_INV + 6 * R.INV_SLOT + R.INV_HAND, 1)
    now[0] += .1
    assert bot.tick(R.snapshot(mem)) == {"tap": "square"}
    now[0] += .1
    assert bot.tick(R.snapshot(mem)) == {"hold": set()}
    assert bot.stats.get("weapon_switch_attempts", 0) == 0
    assert bot.stats.get("heals", 0) == 0 and bot.stats["heal_use_presses"] == 1


def test_held_spray_uses_square_immediately_even_outside_quick_grid_after_hit(tmp_path):
    bot, mem, now = healing_bot(tmp_path, held=True, action=5)
    mem.u32(PLAYER + R.P_INV + 6 * R.INV_SLOT + R.INV_GRID, 8)
    assert bot.tick(R.snapshot(mem)) == {"tap": "square"}
    now[0] += R.HEAL_USE_EVERY_S + .01
    assert bot.tick(R.snapshot(mem)) == {"tap": "square"}
    assert bot.stats["heal_use_presses"] == 2 and bot.stats.get("heals", 0) == 0


def test_heal_counts_observed_consumption_and_hp_gain_then_returns_to_loaded_gun(tmp_path):
    bot, mem, now = healing_bot(tmp_path)
    bot.tick(R.snapshot(mem))
    mem.u32(PLAYER + R.P_INV + R.INV_HAND, 0)
    mem.u32(PLAYER + R.P_INV + 6 * R.INV_SLOT + R.INV_HAND, 1)
    now[0] += .2
    assert bot.tick(R.snapshot(mem)) == {"tap": "square"}
    mem.put(PLAYER + R.P_HP, struct.pack(">h", 1000))
    mem.put(PLAYER + R.P_INV + 6 * R.INV_SLOT + R.INV_USED, b"\0")
    now[0] += .5
    assert bot.tick(R.snapshot(mem)) == {"tap": "dleft"}
    assert bot.stats["heals"] == bot.stats["heal_items_used"] == 1
    assert bot.healing is None
    now[0] += .1
    bot.tick(R.snapshot(mem))
    assert bot.stats["heals"] == 1


def test_hp_refill_without_item_consumption_is_not_a_claimed_heal(tmp_path):
    bot, mem, now = healing_bot(tmp_path, held=True)
    assert bot.tick(R.snapshot(mem)) == {"tap": "square"}
    mem.put(PLAYER + R.P_HP, struct.pack(">h", 1000))
    now[0] += .5
    assert bot.tick(R.snapshot(mem)) == {"tap": "dleft"}
    assert bot.stats.get("heals", 0) == bot.stats.get("heal_items_used", 0) == 0
    assert "not confirmed" in bot.stats["heal_status"]


def test_relocated_spray_with_external_hp_gain_is_not_consumption_or_healing(tmp_path):
    bot, mem, now = healing_bot(tmp_path, held=True)
    assert bot.tick(R.snapshot(mem)) == {"tap": "square"}
    mem.u32(PLAYER + R.P_INV + 6 * R.INV_SLOT + R.INV_GRID, 7)
    mem.put(PLAYER + R.P_HP, struct.pack(">h", 1000))
    now[0] += .5
    bot.tick(R.snapshot(mem))
    assert bot.stats.get("heals", 0) == bot.stats.get("heal_items_used", 0) == 0
    assert bot.healing is None


def test_unconfirmed_item_selection_and_use_have_bounded_attempts(tmp_path):
    bot, mem, now = healing_bot(tmp_path)
    assert bot.tick(R.snapshot(mem)) == {"tap": "dup"}
    now[0] += R.SWITCH_ACK_S
    assert bot.tick(R.snapshot(mem)) == {"tap": "dup"}
    now[0] += R.HEAL_ATTEMPT_S
    bot.tick(R.snapshot(mem))
    assert bot.healing is None and bot.stats["heal_failures"] == 1
    assert bot.stats["heal_equip_attempts"] == 2 and bot.stats.get("heal_use_presses", 0) == 0
    bot, mem, now = healing_bot(tmp_path, held=True)
    bot.tick(R.snapshot(mem))
    now[0] += R.HEAL_ATTEMPT_S + .1
    assert bot.tick(R.snapshot(mem)) == {"tap": "dleft"}
    assert bot.healing is None and bot.stats.get("heals", 0) == 0


def test_mandatory_qte_preempts_heal_and_sequence_resumes_afterward(tmp_path):
    bot, mem, now = healing_bot(tmp_path, held=True)
    assert bot.tick(R.snapshot(mem)) == {"tap": "square"}
    now[0] += 10
    prompt = R.snapshot(mem); prompt["prompt"] = "mash:circle"
    assert bot.tick(prompt) == {"hold": set()}
    assert bot.stats["heal_use_presses"] == 1
    now[0] += .1
    assert bot.tick(R.snapshot(mem)) == {"tap": "square"}
    hidden = R.snapshot(mem); hidden["recovery_active"] = True
    now[0] += .1
    assert bot.tick(hidden) == {"hold": set()}


def test_empty_recovery_item_is_never_selected_or_used(tmp_path):
    bot, mem, now = healing_bot(tmp_path, held=True)
    mem.u32(PLAYER + R.P_INV + 6 * R.INV_SLOT + R.INV_ROUNDS, 0)
    action = bot.tick(R.snapshot(mem))
    assert action != {"tap": "square"} and bot.healing is None


def test_only_verified_usable_recovery_ids_are_selected(tmp_path):
    for item_id in (0x301, 0x302, 0x303, 0x306, 0x308):
        bot, mem, now = healing_bot(tmp_path, held=True)
        mem.u32(PLAYER + R.P_INV + 6 * R.INV_SLOT + R.INV_ID, item_id)
        assert bot.tick(R.snapshot(mem)) != {"tap": "square"}
        assert bot.healing is None
    for item_id in (0x304, 0x305, 0x307, 0x309):
        bot, mem, now = healing_bot(tmp_path, held=True)
        mem.u32(PLAYER + R.P_INV + 6 * R.INV_SLOT + R.INV_ID, item_id)
        assert bot.tick(R.snapshot(mem)) == {"tap": "square"}
        assert bot.healing["id"] == item_id


def test_ignored_optional_melee_does_not_extend_failed_heal_selection_forever(tmp_path):
    bot, mem, now = healing_bot(tmp_path)
    assert bot.tick(R.snapshot(mem)) == {"tap": "dup"}
    now[0] += R.HEAL_ATTEMPT_S + .1
    snap = R.snapshot(mem); snap["prompt"] = "square"
    assert bot.combat.optional_prompt_blocked(snap)
    bot.tick(snap)
    assert bot.healing is None and bot.stats["heal_failures"] == 1


def test_weapon_switch_waits_for_in_hand_ack_and_failed_switch_leaves_combat_running():
    now = [100.0]
    mem = with_inventory(world(enemies=[((0.0, 0.0, 500.0), 800, 800)]),
                         {0: (0x10D, 1, 1, True), 1: (0x119, 10, 10, False)}, grids={0: 3, 1: 5})
    bot = R.Bot(m=mem, clock=lambda: now[0])
    assert bot.tick(R.snapshot(mem)) == {"tap": "dright"}
    for elapsed in (0.8, 1.6, 3.0, 8.0):
        now[0] = 100.0 + elapsed
        assert "l1" in bot.tick(R.snapshot(mem))["hold"]
    assert bot.stats["weapon_switch_attempts"] == 1
    assert bot.stats["weapon_switch_failures"] == 1 and bot.stats.get("weapon_switches", 0) == 0
    now[0] = 110.0
    assert bot.tick(R.snapshot(mem)) == {"tap": "dright"}
    mem.u32(PLAYER + R.P_INV + R.INV_HAND, 0)
    mem.u32(PLAYER + R.P_INV + R.INV_SLOT + R.INV_HAND, 1)
    now[0] = 110.8
    bot.tick(R.snapshot(mem))
    assert bot.stats["weapon_switches"] == 1 and bot.switch_pending is None
    assert bot.stats["weapon_switch_status"] == "confirmed in hand"


def test_handguns_are_tapped_and_the_gatling_held(monkeypatch):
    on = world(action=2, enemies=[((0.0, 0.0, 900.0), 800, 800)])               # aimed: facing +z, the head level
    monkeypatch.setattr(R, "PITCH_TOL", math.radians(90))
    bot = R.Bot(clock=lambda: 100.0)
    taps = [bot.tick(R.snapshot(with_inventory(on, {0: (0x112, 30, 30, True)}))) for _ in range(3)]
    assert ["r1" in a["hold"] for a in taps] == [True, False, False]              # a press, then let go (TAP_ON/OFF)
    bot = R.Bot(clock=lambda: 100.0)
    holds = [bot.tick(R.snapshot(with_inventory(on, {0: (0x115, 400, 400, True)}))) for _ in range(3)]
    assert all("r1" in a["hold"] for a in holds)                                  # the Gatling: held


def test_gathers_every_bonus_first_then_stands_and_breaks_for_a_late_one(monkeypatch):
    monkeypatch.setattr(R, "HOURGLASS_VT", HOURGLASS_VT)
    bot = R.Bot(clock=lambda: 100.0)
    act = bot.tick(R.snapshot(with_bonuses(world(timer=119.0), [(0.0, 13.0, 1200.0)])))   # start: a bonus 12 m off
    assert bot.spawn == (0.0, 0.0, 0.0) and bot.stats["phase"] == "gather_time"            # movement first, not a stand
    assert {"lup", "cross"} <= act["hold"] and not bot.stood                                # walks to it, high clock
    away = world(player_pos=(0.0, 0.0, 900.0), yaw=math.pi, timer=80.0)                     # 9 m off, nothing to gather
    act = bot.tick(R.snapshot(with_bonuses(away, [])))
    assert bot.stats["phase"] == "stand" and bot.stood and {"lup", "cross"} <= act["hold"]  # back to the stand
    far = [((0.0, 0.0, 3500.0), 800, 800)]                                                 # at the stand, a Majini 35 m off
    act = bot.tick(R.snapshot(with_bonuses(world(timer=80.0, enemies=far, combo=0), [])))
    assert act == {"hold": set()} and bot.stats["phase"] == "stand"                        # he comes to the stand
    act = bot.tick(R.snapshot(with_bonuses(world(timer=55.0, combo=0), [(0.0, 13.0, 2000.0)])))     # a late bonus: break for it
    assert bot.stats["phase"] == "break_for_time" and {"lup", "cross"} <= act["hold"]
    plan = bot.plan()
    assert plan["phase"] == "break_for_time" and plan["target"]["kind"] == "time" and plan["stand"]["r"] == R.STAND_R
    assert set(plan) >= {"route", "note", "nearest_bonus", "enemy_flags"}


def test_a_random_character_each_round_never_the_last_one():
    import random
    r = R.Roster(rng=random.Random(7))
    picks = []
    for _ in range(16):
        i = r.want()
        assert r.want() == i                                                      # stable until the round starts
        picks.append(R.CHARACTERS[i])
        assert r.started() == picks[-1]
    assert all(a != b for a, b in zip(picks, picks[1:])) and set(picks) == set(R.CHARACTERS)
    assert max(r.played.values()) - min(r.played.values()) <= 1                   # everyone in turn, in random order
    fields = r.observe({"kills": 12, "score": 4000, "combo": 7})
    assert fields["character"] == picks[-1] and "12k 4000p c7" in fields["char_tally"]


def strip_mesh():
    """A navmesh strip along +z on two levels: quads 0-1 on the roof (y 0, z 0..800), quad 2 a ladder (straight down at
    z 800: y 0 -> -300), quads 3-4 the ground (y -300, z 800..1600); two triangles a quad."""
    from gbox.mercs.titles import re5_nav as N
    pts = []
    for z, y in ((0, 0), (400, 0), (800, 0), (800, -300), (1200, -300), (1600, -300)):
        pts += [(-100.0, float(y), float(z)), (100.0, float(y), float(z))]
    tris, links = [], []
    for k in range(5):                                   # quad k: points 2k, 2k+1, 2k+2, 2k+3 -> two triangles
        a, b, c, d = 2 * k, 2 * k + 1, 2 * k + 2, 2 * k + 3
        tris += [(a, b, d), (a, d, c)]
    for i in range(len(tris)):
        ls = []
        if i % 2 == 0:
            ls.append((i + 1, 2, 1.0))                   # (a, b, d) | (a, d, c): the edge d-a
            if i > 0:
                ls.append((i - 1, 0, 1.0))               # a-b: the quad before
        else:
            ls.append((i - 1, 0, 1.0))
            if i + 1 < len(tris):
                ls.append((i + 1, 1, 1.0))               # d-c: the next quad
        links.append(ls)
    return N.NavMesh(pts, tris, links)


def test_the_navmesh_routes_over_a_ladder_and_the_bot_takes_it():
    mesh = strip_mesh()
    route = mesh.route((0.0, 0.0, 100.0), (0.0, -300.0, 1500.0))
    assert route and route[-1] == (0.0, -300.0, 1500.0)
    assert any(abs(w[1] + 150.0) < 1 for w in route)                             # down the ladder's middle
    assert mesh.route((0.0, 0.0, 100.0), (5000.0, 0.0, 5000.0)) is None          # off the mesh
    bot = R.Bot(clock=lambda: 50.0)
    tgt = {"ptr": 0x3040_0000, "pos": (0.0, -300.0, 1500.0), "kind": "time", "walk": True}
    p = {"pos": (0.0, 0.0, 100.0), "rot": 0.0, "action": 0}
    act = bot._follow(p, tgt, mesh, False, 50.0)
    assert {"lup", "cross"} <= act["hold"]                                        # facing +z: runs along the roof
    p = {"pos": (0.0, 0.0, 790.0), "rot": 0.0, "action": 0}                        # at the ladder's top
    bot.route = [w for w in bot.route if w[2] >= 780.0]
    assert bot._follow(p, tgt, mesh, False, 50.5) == {"hold": {"lup"}}           # on to the edge
    assert bot._follow(p, tgt, mesh, True, 50.6) == {"tap": "square"}            # the prompt: climb down
    assert bot.stats["climbs"] == 1
    ladder = next(w for w in route if abs(w[1] + 150.0) < 1)
    assert mesh.route((0.0, 0.0, 100.0), (0.0, -300.0, 1500.0), avoid=[ladder]) is None   # the only way down


def test_a_crossing_without_its_prompt_is_avoided(tmp_path):
    mesh = strip_mesh()
    t = [10.0]
    bot = R.Bot(clock=lambda: t[0], learn_dir=tmp_path)
    tgt = {"ptr": 0x3040_0000, "pos": (0.0, -300.0, 1500.0), "kind": "time", "walk": True}
    p = {"pos": (0.0, 0.0, 790.0), "rot": 0.0, "action": 0}
    bot._follow(p, tgt, mesh, False, t[0])
    bot.route = [w for w in bot.route if w[2] >= 780.0]
    assert bot._follow(p, tgt, mesh, False, 10.1) == {"hold": {"lup"}}           # waits at the edge for the prompt
    for k in range(1, 8):
        act = bot._follow(p, tgt, mesh, False, 10.1 + 0.5 * k)
    assert act == {"hold": set()}                           # continuously aligned and stationary, no prompt
    assert bot.stats["crossings_avoided"] == 1 and len(bot.avoid) == 1
    routes = bot.nav_learning.stages[mesh.learning_sig]["routes"]
    assert sum(row["blocked"] for row in routes.values()) == 1
    assert sum(row["arrived"] for row in routes.values()) == 0


def test_a_crossing_is_not_blacklisted_while_turning_or_after_combat_interrupts():
    mesh, bot = strip_mesh(), R.Bot()
    tgt = {"ptr": 1, "pos": (0.0, -300.0, 1500.0), "kind": "time", "walk": True}
    p = {"pos": (0.0, 0.0, 790.0), "rot": math.pi, "action": 0}
    for t in (10.0, 11.0, 12.0, 14.0):
        assert "r1" not in bot._follow(p, tgt, mesh, False, t)["hold"]
    assert not bot.avoid and bot.climb_at is None
    p["rot"] = 0.0
    assert bot._follow(p, tgt, mesh, False, 14.5) == {"hold": {"lup"}}
    assert bot._follow(p, tgt, mesh, False, 24.5) == {"hold": {"lup"}}  # ten seconds spent fighting elsewhere
    assert not bot.avoid
    assert bot._follow(p, tgt, mesh, True, 25.0) == {"tap": "square"}
    assert bot.climb_at is None


def test_navigation_observes_actual_prompt_frames_once_and_clears_loading_continuity(tmp_path):
    mesh = strip_mesh()
    bot = R.Bot(clock=lambda: 10.5, learn_dir=tmp_path)

    def snap(pos):
        return {"player": {"pos": pos, "hp": 1000, "rot": 0.0, "action": 0},
                "timer": 100.0, "nav": mesh, "stage_prompt": True}

    first = snap((50.0, 0.0, 100.0))
    bot.observe_round(first, "playing", 10.0)
    assert bot.tick(first) == {"tap": "square"}
    assert bot.stats["nav_observed_crossings"] == 0             # the press alone proves nothing
    after = snap((-50.0, 0.0, 300.0))
    bot.observe_round(after, "playing", 10.5)
    assert bot.tick(after) == {"tap": "square"}
    assert bot.stats["nav_observed_crossings"] == 1             # engine observer + tick are idempotent
    bot.observe_round({}, "loading", 10.6)
    bot.observe_round(snap((50.0, 0.0, 100.0)), "playing", 11.0)
    assert bot.stats["nav_observed_crossings"] == 1
    assert bot.stats["nav_visited_triangles"] == 2
    bot.save()
    assert (tmp_path / R.NAV_LEARNING_FILE).is_file()


def test_navigation_route_timeout_and_unreachable_are_terminal_observed_outcomes(tmp_path):
    from gbox.mercs.titles.re5_nav import NavMesh
    mesh = NavMesh([(0.0, 0.0, 0.0), (200.0, 0.0, 0.0), (200.0, 0.0, 200.0), (0.0, 0.0, 200.0)],
                   [(0, 1, 2), (0, 2, 3)], [[(1, 2, 1.0)], []])
    bot = R.Bot(learn_dir=tmp_path)
    p = {"pos": (150.0, 0.0, 50.0), "rot": 0.0, "action": 0}
    target = {"ptr": 1, "pos": (50.0, 0.0, 150.0)}
    bot._follow(p, target, mesh, False, 10.0)
    bot._follow(p, target, mesh, False, 11.0 + R.ROUTE_STALE_S)
    row = bot.nav_learning.stages[mesh.learning_sig]["routes"]["0:1"]
    assert row["started"] == 1 and row["timed_out"] == 1 and row["arrived"] == 0
    p["pos"], target = target["pos"], {"ptr": 2, "pos": p["pos"]}
    bot._follow(p, target, mesh, False, 100.0)
    row = bot.nav_learning.stages[mesh.learning_sig]["routes"]["1:0"]
    assert row["unreachable"] == 1 and row["arrived"] == 0
    assert mesh.route(p["pos"], target["pos"]) is None            # observations cannot open a reverse traversal


def test_navigation_geometry_change_discards_cached_route_and_does_not_report_a_crossing(tmp_path):
    from gbox.mercs.titles.re5_nav import NavMesh
    old = strip_mesh()
    new = NavMesh([(x, y + 600.0, z) for x, y, z in old.points], old.tris, old.links, ptr=old.ptr)
    bot = R.Bot(learn_dir=tmp_path)
    bot.observe_round({"player": {"pos": (50.0, 0.0, 100.0)}, "nav": old}, "playing", 1.0)
    bot.route, bot.route_for, bot.route_len = [(1, 2, 3)], 17, {17: 123}
    bot.observe_round({"player": {"pos": (-50.0, 600.0, 300.0)}, "nav": new}, "playing", 1.5)
    assert bot.route is bot.route_for is bot.route_len is None
    assert bot.stats["nav_geometry"] == new.learning_sig and bot.stats["nav_observed_crossings"] == 0


def test_known_unreachable_mesh_route_never_falls_back_to_running_through_a_wall():
    mesh, bot = strip_mesh(), R.Bot()
    p = {"pos": (0.0, 0.0, 100.0), "rot": math.pi / 2, "action": 0}
    tgt = {"ptr": 1, "pos": (5000.0, 0.0, 5000.0), "kind": "time", "walk": True}
    assert bot._follow(p, tgt, mesh, False, 10.0) == {"hold": set()}
    assert bot.stats["route"] == "unreachable on current mesh" and bot.bonus_skip[1] > 10.0


def test_unreachable_bonuses_are_not_chosen_over_a_real_route():
    mesh, bot = strip_mesh(), R.Bot()
    p = {"pos": (0.0, 0.0, 100.0), "rot": 0.0, "action": 0}
    bonuses = [{"ptr": 1, "pos": (5000.0, 0.0, 5000.0), "kind": "time"},
               {"ptr": 2, "pos": (0.0, -300.0, 1500.0), "kind": "time"}]
    assert bot._bonus(p, [], bonuses, 10.0, mesh, 100.0)["ptr"] == 2
    assert bot.stats["unreachable_bonuses"] == 1


def corner_mesh():
    from gbox.mercs.titles.re5_nav import NavMesh
    points = [(x, 0., z) for x, z in ((0., 0.), (200., 0.), (300., 0.), (0., 100.),
                                    (200., 100.), (300., 100.), (200., 300.), (300., 300.))]
    tris = [(0, 1, 4), (0, 4, 3), (1, 2, 5), (1, 5, 4), (4, 5, 7), (4, 7, 6)]
    links = [[] for _ in tris]
    for i, tri in enumerate(tris):
        for edge in range(3):
            shared = {tri[edge], tri[(edge + 1) % 3]}
            for j, other in enumerate(tris):
                if j != i and shared <= set(other):
                    links[i].append((j, edge, 1.))
    return NavMesh(points, tris, links)


def test_nearby_funnel_corner_is_not_skipped_through_the_corridor_wall():
    mesh, bot = corner_mesh(), R.Bot()
    corner, goal = (200., 0., 100.), (250., 0., 250.)
    p = {"pos": (175., 0., 50.), "rot": math.atan2(25., 50.), "action": 0}
    target = {"ptr": 1, "pos": goal}
    bot.route, bot.route_for, bot.route_at, bot.route_since = [corner, goal], 1, 10., 10.
    assert math.dist(p["pos"], corner) < R.WP_REACHED
    assert bot._follow(p, target, mesh, False, 10.1) == {"hold": {"lup"}}
    assert bot.route[0] == corner                              # still turns at the real corner, at walking speed
    p["pos"], p["rot"] = corner, math.atan2(50., 150.)
    assert "lup" in bot._follow(p, target, mesh, False, 10.2)["hold"]
    assert bot.route == [goal]                                # advancing is now supported by the actual floor


def test_route_turns_in_place_before_forward_motion_into_a_narrow_passage():
    bot = R.Bot()
    p = {"pos": (175., 0., 50.), "rot": 0., "action": 0}
    keys = bot._walk(p, math.radians(30.), 10., precise=True)
    assert keys == {"rleft"} and not bot.hist
    assert {"lup", "cross"} <= bot._walk(p, 0., 10.1, precise=True)


def test_repeated_stationary_route_stalls_record_blocked_and_leave_the_target(tmp_path):
    mesh, bot = corner_mesh(), R.Bot(learn_dir=tmp_path)
    p = {"pos": (20., 0., 50.), "rot": math.pi / 2, "action": 0}
    target = {"ptr": 1, "pos": (170., 0., 50.)}
    for now in (10., 10.4, 10.8, 11.3, 11.6, 12.2, 12.6, 13., 13.5):
        action = bot._follow(p, target, mesh, False, now)
    assert action == {"hold": set()}
    assert bot.stats["stuck"] == 2 and bot.stats["routes_blocked"] == 1
    assert bot.route is None and bot.bonus_skip[1] > 13.5
    stage = bot.nav_learning.stages[mesh.learning_sig]
    assert sum(row["blocked"] for row in stage["routes"].values()) == 1
    assert not stage["crossings"] and not bot.avoid            # failure does not invent a permanently blocked edge


def test_combat_gap_does_not_combine_two_independent_route_stalls():
    mesh, bot = corner_mesh(), R.Bot()
    p = {"pos": (20., 0., 50.), "rot": math.pi / 2, "action": 0}
    target = {"ptr": 1, "pos": (170., 0., 50.)}
    for now in (10., 10.4, 10.8, 11.3):
        bot._follow(p, target, mesh, False, now)
    assert bot.route_stall is not None
    for now in (20., 20.4, 20.8, 21.3):
        bot._follow(p, target, mesh, False, now)
    assert bot.stats["stuck"] == 2 and bot.stats.get("routes_blocked", 0) == 0
    assert bot.route_stall is not None and 1 not in bot.bonus_skip


@pytest.mark.parametrize("interruption", ("combat", "qte"))
def test_subsecond_combat_and_engine_owned_qte_frames_break_route_stall_continuity(tmp_path, interruption):
    mesh, now = corner_mesh(), [10.]
    mem = with_inventory(world(player_pos=(20., 0., 50.), action=2,
                               enemies=[((20., 0., 200.), 800, 800)]), {0: (0x10B, 6, 6, True)})
    bot = R.Bot(m=mem, clock=lambda: now[0], learn_dir=tmp_path, lessons=lambda row: None)
    initial = R.snapshot(mem); initial["nav"] = mesh
    bot.observe_round(initial, "playing", now[0])
    p = initial["player"] | {"rot": math.pi / 2}
    target = {"ptr": 1, "pos": (170., 0., 50.)}
    for i in range(10):
        now[0] = 10. + .5 * i
        assert "lup" in bot._follow(p, target, mesh, False, now[0])["hold"]
        now[0] += .25
        snap = R.snapshot(mem); snap["nav"] = mesh
        if interruption == "combat":
            bot.tick(snap)                                 # an actual combat decision, not an inferred elapsed gap
        else:
            snap["prompt"] = "mash:circle"
            bot.observe_round(snap, "playing", now[0])    # the engine presses this prompt and skips bot.tick()
        assert not bot.hist and bot.route_stall is None and bot.route_walk_at is None
    assert bot.stats["stuck"] == bot.stats.get("routes_blocked", 0) == 0
    assert 1 not in bot.bonus_skip


def test_unsupported_portal_rechecks_stop_after_three_attempts_instead_of_idling_at_wall(tmp_path):
    mesh, bot = corner_mesh(), R.Bot(learn_dir=tmp_path)
    # find() permits route endpoint height slack, but this position does not prove supported floor travel.
    p = {"pos": (20., 80., 50.), "rot": math.pi / 2, "action": 0}
    target = {"ptr": 1, "pos": (170., 0., 50.)}
    assert mesh.route(p["pos"], target["pos"]) and not mesh.floor_segment(p["pos"], target["pos"])
    for now in (10., 10.1, 10.2):
        assert bot._follow(p, target, mesh, False, now) == {"hold": set()}
    assert bot.stats["routes_blocked"] == 1 and bot.route is None
    assert bot.bonus_skip[1] > 10.2 and "three route checks" in bot.stats["route"]
    assert not bot.avoid                                   # an unsupported ray is not a newly observed wall edge


def test_distant_unsighted_front_candidate_does_not_starve_time_bonus_navigation(monkeypatch):
    monkeypatch.setattr(R, "HOURGLASS_VT", HOURGLASS_VT)
    m = with_bonuses(world(action=2, combo=0, enemies=[((0.0, 0.0, 1800.0), 800, 800)]), [(0.0, 13.0, 2400.0)])
    bot = R.Bot(m, clock=lambda: 10.0, lessons=lambda e: None)
    act = bot.tick(R.snapshot(m))
    assert bot.stats["phase"] == "gather_time" and {"lup", "cross"} <= act["hold"]


def test_a_stationary_close_attacker_cannot_keep_the_gun_down_forever():
    now = [10.0]
    m = world(action=5, enemies=[((0.0, 0.0, 60.0), 800, 800)])  # still in the hit pose, no usable laser yet
    bot = R.Bot(m, clock=lambda: now[0], lessons=lambda e: None)
    first = bot.tick(R.snapshot(m))
    assert "l1" in first["hold"] and "ldown" not in first["hold"]
    now[0] += R.CLOSE_ESCAPE_S + 0.01
    acquiring = bot.tick(R.snapshot(m))
    assert "l1" in acquiring["hold"] and "ldown" not in acquiring["hold"]
    assert bot.stats["combat"].startswith("readying:") and bot.stats["backoffs"] == 0
    now[0] += 0.5
    assert "l1" in bot.tick(R.snapshot(m))["hold"]
    assert bot.stats["backoffs"] == 0


def boot(names, line=26):
    mem = world(timer=0.0)
    mem.u32(SPLAYER + 0x28, 0)                       # the title's menus: no player
    return with_ui(mem, names, line=line)


def where_and_key(names, line=26):
    scr = R.screen(boot(names, line))
    return scr["where"], R.step(scr)


def test_from_the_title_into_reunion_by_ram():
    title = [("uIdTitle00", {R.TITLE_STEP: R.TITLE_PRESS_START}), "uIdTitle02"]
    assert where_and_key(title, line=0) == ("title", "start")
    assert where_and_key([("uIdTitle00", {R.TITLE_STEP: 0x40}), "uIdTitle02"], line=0) == ("menu", None)  # the logos
    assert where_and_key([("uIdAlert00", {R.ALERT_ID: 0x22})], line=0) == ("alert_signin", "circle")   # Sign in?
    assert where_and_key([("uIdAlert00", {R.ALERT_ID: 0x13})], line=0) == ("alert", None)              # loading it
    assert where_and_key([("uIdAlert00", {R.ALERT_ID: 0x08})], line=0) == ("alert_ok", "cross")        # Load successful
    assert where_and_key([("uIdStartUp00", {R.MENU_CURSOR: 0})]) == ("main_menu", "cross")             # PLAY GAME
    assert where_and_key([("uIdStartUp00", {R.MENU_CURSOR: 2})]) == ("main_menu", "dup")
    assert where_and_key([("uIdStartUp01", {R.MENU_CURSOR: 0})]) == ("play_game", "dup")               # wraps to 7
    assert where_and_key([("uIdStartUp01", {R.MENU_CURSOR: 4})]) == ("play_game", "ddown")
    assert where_and_key([("uIdStartUp01", {R.MENU_CURSOR: 7})]) == ("play_game", "cross")             # EXTRA CONTENT
    extra = {R.MENU_SUB: 1, R.EXTRA_CURSOR: 1}
    assert where_and_key([("uIdStartUp01", extra)]) == ("extra_content", "ddown")
    assert where_and_key([("uIdStartUp01", extra | {R.EXTRA_CURSOR: 3})]) == ("extra_content", "cross")  # REUNION
    assert where_and_key(["uIdStartUp29"], line=1) == ("reunion_title", "cross")                      # START
    assert where_and_key([("uIdStartUp29", {R.MENU_SUB: 1})], line=1) == ("reunion_solo", "cross")    # SOLO
    assert where_and_key(["uIdStartUp21", "uIdTopMenu00"]) in (("select_stage", "cross"), ("select_stage", "dright"))


def test_re5_plays_through_the_deployment_before_the_engine_is_ready():
    from gbox import mercs_bot as MB
    prof = MB.profile_for(None, {"game_id": "e7ca89bbeb67360d"})
    assert prof["menus"] == "gbox.mercs.titles.re5_ps3" and prof["ready"] is True
    assert engine.READY is False                                                   # RE4's A/B still pending
    assert MB.title_engine(prof) is engine and MB.matches(None, {"game_id": "e7ca89bbeb67360d"})
    assert MB.title_engine({"menus": "x"}) is None                                 # a title not marked ready waits


def test_a_frozen_clock_gives_the_round_up_as_lost():
    t = [0.0]
    drv = R.RE5PS3(clock=lambda: t[0])
    mem = world(action=2, timer=88.5, enemies=[((0.0, 0.0, 900.0), 800, 800)])
    assert drv.screen(mem, None) == "playing"
    t[0] = R.HANG_S - 1
    assert drv.screen(mem, None) == "playing"                                       # a long intro, a slow moment
    t[0] = R.HANG_S + 1
    assert drv.screen(mem, None) == "loading"                                       # frozen: RPCS3 hung
    mem.put(GAMESYS + 0x3E0, struct.pack(">f", 88.0))
    assert drv.screen(mem, None) == "playing"                                       # moving again
    t[0], n = 0.0, [0]

    def stopped():
        n[0] += 1
        t[0] += 1.0                                                                 # a second a tick, the clock frozen
        return n[0] > 400
    why = engine.play_round({"driver": "gbox.mercs.titles.re5_ps3"}, world(action=2, timer=50.0), lambda rows: None,
                            stopped, {}, sleep=lambda s: None, clock=lambda: t[0], tick_s=0.0,
                            driver=R.RE5PS3(clock=lambda: t[0]))
    assert why == "lost"                                                            # the deployment then recovers


def u_mesh():
    """A U of 100 cm cells: up x 0..100 (z 0..500), across z 400..500, down x 300..400: (50, 50) and (350, 50) are 3 m
    apart with a wall between them; the way round is 11 m."""
    from gbox.mercs.titles.re5_nav import NavMesh
    cells = [(0, k) for k in range(5)] + [(1, 4), (2, 4)] + [(3, k) for k in range(5)]
    index, points, tris = {}, [], []

    def pt(x, z):
        if (x, z) not in index:
            index[(x, z)] = len(points)
            points.append((100.0 * x, 0.0, 100.0 * z))
        return index[(x, z)]
    for x, z in cells:
        a, b, c, d = pt(x, z), pt(x + 1, z), pt(x + 1, z + 1), pt(x, z + 1)
        tris += [(a, b, c), (a, c, d)]
    links = [[] for _ in tris]
    for i, tri in enumerate(tris):
        for edge in range(3):
            shared = {tri[edge], tri[(edge + 1) % 3]}
            for j, other in enumerate(tris):
                if j != i and shared <= set(other):
                    links[i].append((j, edge, 1.))
    return NavMesh(points, tris, links)


def _pursuit_bot(tmp_path, enemy, action=0, yaw=math.pi / 2, now=None):
    now = now if now is not None else [10.0]
    mem = with_inventory(world(player_pos=(50.0, 0.0, 50.0), yaw=yaw, action=action, enemies=[(enemy, 800, 800)]),
                         {0: (0x10B, 6, 6, True)})
    bot = R.Bot(m=mem, clock=lambda: now[0], learn_dir=tmp_path, lessons=lambda row: None)
    return mem, bot, now


def _snap(mem, mesh, laser=None):
    snap = R.snapshot(mem)
    snap["nav"] = mesh
    if laser is not None:
        snap["laser"] = laser
    return snap


def test_a_majini_behind_a_wall_is_walked_to_not_aimed_at(tmp_path):
    """Live 2026-10-21: 57 of 130 s aiming into walls at Majini behind them. Behind a wall of the mesh he is walked to
    around the corner, the gun down; a pursuit is not a stage route record."""
    mesh = u_mesh()
    mem, bot, _ = _pursuit_bot(tmp_path, (350.0, 0.0, 50.0))
    assert not mesh.floor_segment((50.0, 0.0, 50.0), (350.0, 0.0, 50.0))
    assert mesh.route_length((50.0, 0.0, 50.0), (350.0, 0.0, 50.0)) > 2 * 300.0
    act = bot.tick(_snap(mem, mesh))
    assert bot.stats["phase"] == "pursue" and bot.stats["pursuits"] == 1
    assert act["hold"] and not act["hold"] & {"l1", "r1"}
    assert bot.route and bot.route_for == ("enemy", ENEMIES[0])
    assert not bot.nav_learning.stages.get(mesh.learning_sig, {}).get("routes")
    assert bot.plan()["route"]                                  # the tactical map shows the way to him


def test_an_open_floor_majini_is_fought_from_where_he_stands(tmp_path):
    mesh = corner_mesh()
    mem, bot, _ = _pursuit_bot(tmp_path, (260.0, 0.0, 50.0))
    assert mesh.floor_segment((50.0, 0.0, 50.0), (260.0, 0.0, 50.0))
    act = bot.tick(_snap(mem, mesh))
    assert bot.stats["phase"] != "pursue" and "l1" in act["hold"]


def test_a_dot_stopping_short_of_him_leaves_him_for_a_pursuit(tmp_path):
    mesh = corner_mesh()
    mem, bot, now = _pursuit_bot(tmp_path, (260.0, 0.0, 50.0), action=2)
    wall = {"from": (50.0, 140.0, 50.0), "at": (110.0, 140.0, 50.0)}   # the dot 60 cm off the muzzle: a wall
    for t in (10.0, 10.3):
        now[0] = t
        bot.tick(_snap(mem, mesh, wall))
        assert bot.stats["phase"] != "pursue"          # the combat layer works the dot for BLOCKED_VIEW_S first
    now[0] = 10.6
    act = bot.tick(_snap(mem, mesh, wall))
    assert bot.stats["phase"] == "pursue" and bot.stats["unsighted"] == 1 and "dot wall" in bot.stats["sight"]
    assert bot.unsighted[ENEMIES[0]] > 10.6 and not act["hold"] & {"l1", "r1"}
    on = {"from": (50.0, 140.0, 50.0), "at": (260.0, 150.0, 50.0)}       # out of sight a while, then the dot on him
    now[0] = 12.7
    assert "l1" in bot.tick(_snap(mem, mesh, on))["hold"] and bot.stats["phase"] != "pursue"


def test_a_dot_that_never_reaches_him_is_given_up_after_a_while(tmp_path):
    mesh = corner_mesh()
    mem, bot, now = _pursuit_bot(tmp_path, (260.0, 0.0, 50.0), action=2)
    for t in (10.0, 11.0, 12.0):                              # no laser yet (the gun coming up): no evidence
        now[0] = t
        bot.tick(_snap(mem, mesh))
    elsewhere = {"from": (50.0, 140.0, 50.0), "at": (50.0, 140.0, 800.0)}   # the laser up, the dot off him
    for t in (12.5, 13.0, 13.5, 14.0):                         # 2.0 s of laser-up time off him
        now[0] = t
        bot.tick(_snap(mem, mesh, elsewhere))
        assert bot.stats["phase"] != "pursue"
    now[0] = 14.5
    bot.tick(_snap(mem, mesh, elsewhere))
    assert bot.stats["phase"] == "pursue" and "never" in bot.stats["sight"]


def test_laser_view_names_on_wall_short_and_unknown():
    tgt = {"pos": (1000.0, 0.0, 0.0)}
    o = (0.0, 140.0, 0.0)
    assert R.Bot._laser_view({"laser": {"from": o, "at": (1000.0, 150.0, 0.0)}}, tgt) == "on"
    assert R.Bot._laser_view({"laser": {"from": o, "at": (60.0, 140.0, 0.0)}}, tgt) == "wall"
    assert R.Bot._laser_view({"laser": {"from": o, "at": (400.0, 140.0, 10.0)}}, tgt) == "short"
    assert R.Bot._laser_view({"laser": {"from": o, "at": (0.0, 140.0, 400.0)}}, tgt) is None   # aimed elsewhere
    assert R.Bot._laser_view({"laser": {"from": (0.0, 0.0, 0.0), "at": (0.0, 0.0, 0.0)}}, tgt) == "none"


def test_a_nearly_straight_route_counts_as_open_floor(tmp_path):
    """floor_segment alone called 4 of 5 nearly straight live routes closed; a route that barely bends is open."""
    mesh = corner_mesh()
    mem, bot, _ = _pursuit_bot(tmp_path, (250.0, 0.0, 250.0))
    assert not mesh.floor_segment((50.0, 0.0, 50.0), (250.0, 0.0, 250.0))
    p, e = R.snapshot(mem)["player"], {"ptr": 1, "pos": (250.0, 0.0, 250.0)}
    assert bot._open(p, e, mesh, 10.0)
    assert not bot._open(p, {"ptr": 2, "pos": (350.0, 0.0, 50.0)}, u_mesh(), 10.0)


def test_stage_select_takes_a_random_stage_each_visit():
    # operator 2026-10-22: "have the bot go between the stages randomly during the select"
    import random
    pick = R.StagePick(rng=random.Random(4))
    scr = {"where": "select_stage"}
    sent = []
    for _ in range(40):                                    # the Navigator: step, then pressed() for each key it sends
        key = pick.key(scr)
        sent.append(key)
        pick.pressed(scr, key)
        if key == "cross":
            break
    assert sent[-1] == "cross" and set(sent[:-1]) <= {"dright"} and len(sent) - 1 <= R.StagePick.MAX_MOVES
    assert pick.left is None                               # the next visit draws again
    held = pick.key(scr)                                   # a key the Navigator held back (settle) is not counted
    left = pick.left
    assert pick.key(scr) == held and pick.left == left
    pick.pressed({"where": "select_player"}, "cross")      # presses elsewhere never touch the stage pick
    assert pick.left == left
    draws = {R.StagePick(rng=random.Random(s)).key(scr) for s in range(30)}
    assert draws == {"dright", "cross"}                    # some visits move, some take the stage under the cursor
    assert R.step({"where": "select_stage"}) in ("dright", "cross")


def test_a_running_combo_is_chased_not_waited_for_at_the_stand(monkeypatch):
    monkeypatch.setattr(R, "HOURGLASS_VT", HOURGLASS_VT)
    bot = R.Bot(clock=lambda: 100.0)
    bot.tick(R.snapshot(with_bonuses(world(timer=119.0), [(0.0, 13.0, 1200.0)])))
    bot.tick(R.snapshot(with_bonuses(world(player_pos=(0.0, 0.0, 900.0), yaw=math.pi, timer=80.0), [])))
    far = [((0.0, 0.0, 3500.0), 800, 800)]
    assert bot.tick(R.snapshot(with_bonuses(world(timer=80.0, enemies=far, combo=0), []))) == {"hold": set()}
    act = bot.tick(R.snapshot(with_bonuses(world(timer=80.0, enemies=far, combo=3, combo_t=5.0), [])))
    assert bot.stats["phase"] == "keep_combo" and act["hold"] and "lup" in act["hold"]
    assert R.Bot._combo_running({"combo": 0, "combo_timer": 5.0}) is False
    assert R.Bot._combo_running({"combo": 3, "combo_timer": 0.0}) is False
    assert R.Bot._combo_running({"combo": 3, "combo_timer": None}) is False


def test_an_unreachable_enemy_is_walked_at_while_a_combo_runs_not_left_for_the_stand(tmp_path):
    mesh = u_mesh()
    mem, bot, now = _pursuit_bot(tmp_path, (350.0, 0.0, 50.0))
    bot.spawn = (5000.0, 0.0, 5000.0)                           # a stand far away
    bot.bonus_skip[("enemy", ENEMIES[0])] = now[0] + 60.0        # route failed lately: pursuit has nobody
    act = bot.tick(_snap(mem, mesh))
    assert bot.stats["phase"] == "keep_combo" and bot.stats["combo_chases"] == 1 and act["hold"]
