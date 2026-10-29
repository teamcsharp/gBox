"""Mercenaries 3D (3DS) driver (gbox.mercs.titles.merc3d_3ds) on a fake guest: screens named by the area stack's flow
states and the classes the game's own DTIs give, the player and the mission counters from RAM."""
import struct

from gbox.mercs.titles import merc3d_3ds as M


class Guest:
    """A sparse little-endian 3DS guest with MT objects: obj(name) builds a vtable whose getDTI names the class."""

    def __init__(self):
        M._NAMES.clear()                             # vtables are per build in the game; each fake reuses addresses
        self.mem = {}
        self.code = 0x00700000                       # stubs, vtables, names (code / ro)
        self.heap = 0x08300000
        self.vts = {}

    def put(self, a, data):
        for i, b in enumerate(data):
            self.mem[a + i] = b

    def u32(self, a, v):
        self.put(a, struct.pack("<I", v & 0xFFFFFFFF))

    def f32(self, a, v):
        self.put(a, struct.pack("<f", v))

    def rd(self, a, n):
        return bytes(self.mem.get(a + i, 0) for i in range(n))

    def _code(self, n):
        a = self.code
        self.code += (n + 15) & ~15
        return a

    def vtable(self, name):
        if name not in self.vts:
            vt, stub, dti, s = self._code(0x40), self._code(12), self._code(0x30), self._code(len(name) + 1)
            self.put(s, name.encode() + b"\0")
            self.u32(dti + 4, s)
            self.u32(stub, 0xE59F0000)
            self.u32(stub + 4, 0xE12FFF1E)
            self.u32(stub + 8, dti)
            self.u32(vt + 0x14, stub)
            self.vts[name] = vt
        return self.vts[name]

    def obj(self, name, size=0x100):
        a = self.heap
        self.heap += (size + 0xFF) & ~0xFF
        self.u32(a, self.vtable(name))
        return a

    def area(self, name, states, current):
        a = self.obj(name, 0x80)
        arr = self.obj("MtArray", 4 * len(states) + 16)
        for i, st in enumerate(states):
            self.u32(arr + 4 * i, self.obj(st, 0x50))
        f = a + M.AREA_FLOW
        self.u32(f, M.FLOW_VT)
        self.u32(f + M.FLOW_STATES, arr)
        self.u32(f + M.FLOW_COUNT, len(states))
        self.u32(f + M.FLOW_CUR, current)
        return a

    def stack(self, *areas):
        sa = self.obj("sGameArea", 0x3900)
        self.u32(M.S_AREA, sa)
        self.u32(sa + M.AREA_DEPTH, len(areas))
        for i, a in enumerate(areas):
            self.u32(sa + M.AREA_STACK + 4 * i, a)

    def player(self, hp=1000.0, pos=(-402.85, 60.97, -3192.98), quat=(0.0, 0.7022, 0.0, 0.7120)):
        sp = self.obj("sPlayer", 0x30)
        node = self.obj("cUnitNode", 0x20)
        p = self.obj("uPl< Chris >", 0x1000)
        self.u32(M.S_PLAYER, sp)
        self.u32(sp + M.SP_FIRST, node)
        self.u32(node + M.NODE_OWNER, p)
        self.put(p + M.P_POS, struct.pack("<3f", *pos))
        self.put(p + M.P_ROT, struct.pack("<4f", *quat))
        self.f32(p + M.P_VIT, hp)
        self.f32(p + M.P_VIT_MAX, 1000.0)
        return p


TITLE = ["cMerceTitleInitState", "cMerceTitleMainState", "cMerceTitleFinalState", "cMerceTitleSystemCheckState",
         "cMerceTitleGoreWarningState", "cMerceTitleCapcomLogoState", "cMerceTitlePressStartState",
         "cMerceTitleDemoState", "cMerceTitleMainMenuState", "cMerceTitleSpecialState", "cMerceTitleOptionMainState",
         "cMerceTitleDummyState"]
MAIN = ["cMerceMainInitState", "cMerceMainMainState", "cMerceMainFinalState", "cMerceMainAutoSaveState",
        "cMerceMainMissionSelectState", "cMerceMainCharacterSelectState", "cMerceMainDuoMenuState",
        "cMerceMainRecordState"]
STAGE = ["cMerceStageInitState", "cMerceStageStartState", "cMerceStageMainState", "cMerceStageEndState",
         "cMerceStageFinalState", "cMerceStageFailedState", "cMerceStageYouAreDeadState"]


def _guest(area, states, current):
    g = Guest()
    g.stack(g.obj("aGame"), g.obj("aMerceArea"), g.area(area, states, current))
    return g


def test_class_names_come_from_the_dti():
    g = Guest()
    p = g.obj("uPl< Chris >")
    assert M.class_name(g, p) == "uPl< Chris >"
    assert M.class_name(g, 0x08F00000) is None                # no vtable there


def test_title_screens_and_their_keys():
    for index, where, key in ((4, "gore_warning", "a"), (5, "loading", None), (6, "press_start", "start"),
                              (7, "demo", "start")):
        scr = M.screen(_guest("aMerceTitle", TITLE, index))
        assert scr["where"] == where and scr["area"] == "aMerceTitle" and scr["state"] == TITLE[index]
        assert M.step(scr) == key


def test_mercenaries_menus():
    M.PICK.reset()
    assert M.screen(_guest("aMerceMain", MAIN, 0))["where"] == "loading"
    assert M.screen(_guest("aMerceMain", MAIN, 3))["where"] == "saving"
    assert M.step(M.screen(_guest("aMerceMain", MAIN, 7))) == "b"           # records: back out


def _select_guest(level=0, open_=1, tab=0, tabs=0, mission=0):
    g = _guest("aMerceMain", MAIN, 4)
    top = M.areas(g)[-1][0]
    arr = struct.unpack("<I", g.rd(top + M.AREA_FLOW + M.FLOW_STATES, 4))[0]
    st = struct.unpack("<I", g.rd(arr + 4 * 4, 4))[0]
    gui = g.obj("uGUI_MissionSelectSub", 0x400)
    g.u32(st + M.STATE_GUI, gui)
    g.put(gui + M.MS_LEVEL, struct.pack("<5i", level, open_, 5, tab, tabs))
    sm = g.obj("sMission", 0x130)
    g.u32(M.S_MISSION, sm)
    g.put(sm + M.M_MISSION, struct.pack("<h", mission))
    return g


def test_main_menu_visits_the_selects_then_starts():
    M.PICK.reset()
    main = M.screen(_guest("aMerceMain", MAIN, 1))
    assert main["where"] == "mercs_main" and M.step(main) == "r"   # never B there: it autosaves and leaves
    M.PICK.mission_done = True
    assert M.step(main) == "l"
    M.PICK.chara_done = True
    assert M.step(main) == "start"
    M.PICK.reset()


def test_repeated_main_menu_step_gets_one_confirm_then_resumes_navigation():
    M.PICK.reset()
    main = M.screen(_guest("aMerceMain", MAIN, 1))
    for _ in range(3):
        assert M.step(main) == "r"
        M.pressed(main, "r")
    assert M.step(main) == "a"                            # dismiss the observed mission-unlock notice
    M.pressed(main, "a")
    assert M.step(main) == "r"                            # still visit the mission selector; no false completion
    assert not M.PICK.mission_done and not M.PICK.chara_done
    M.PICK.reset()


def test_main_notice_recovery_is_bounded_and_resets_after_native_progress():
    M.PICK.reset()
    main = M.screen(_guest("aMerceMain", MAIN, 1))
    confirms = 0
    for _ in range(20):
        key = M.step(main)
        confirms += key == "a"
        M.pressed(main, key)
    assert confirms == 2                                 # no endless A spam when this is not a notice
    assert M.step(main) == "r"
    stage = M.screen(_select_guest())
    M.step(stage)                                       # native menu progress starts a fresh visit
    for _ in range(3):
        assert M.step(main) == "r"
        M.pressed(main, "r")
    assert M.step(main) == "a"
    M.PICK.reset()


def test_old_live_pick_without_notice_fields_can_recover_after_hot_reload():
    M.PICK.reset()
    for name in ("main_key", "main_presses", "main_confirmations"):
        if hasattr(M.PICK, name):
            delattr(M.PICK, name)
    main = {"where": "mercs_main"}
    M.PICK.mission_done = True
    for _ in range(3):
        assert M.step(main) == "l"
        M.pressed(main, "l")
    assert M.step(main) == "a"
    M.pressed(main, "a")
    assert M.step(main) == "l" and not M.PICK.chara_done
    M.PICK.reset()


def test_mission_select_walks_to_a_random_open_level_then_a_tab():
    M.PICK.reset()
    M.PICK.level = 0
    scr = M.screen(_select_guest(level=2, open_=1))                # the cursor on a locked level
    assert scr["where"] == "select_stage" and scr["inside"] is False
    assert scr["target"] == 0 and M.step(scr) == "up"
    scr = M.screen(_select_guest(level=0, open_=1))
    assert M.step(scr) == "a"                                      # opens LV.1
    M.PICK.tab = 2
    scr = M.screen(_select_guest(level=0, open_=1, tab=0, tabs=3))
    assert scr["inside"] is True and scr["target"] == 2 and M.step(scr) == "right"
    scr = M.screen(_select_guest(level=0, open_=1, tab=2, tabs=3))
    assert M.step(scr) == "a"
    M.pressed(scr, "a")
    assert M.PICK.mission_done is True
    M.PICK.reset()


def test_random_draws_stay_inside_what_is_open():
    M.PICK.reset()
    for _ in range(50):
        M.PICK.reset()
        assert M.PICK.level_for(1) == 0
        assert 0 <= M.PICK.tab_for(3) < 3
    M.PICK.reset()


def test_the_round_by_stage_state_and_vitality():
    g = _guest("aS0000", STAGE, 2)
    g.player(hp=1000.0)
    assert M.screen(g)["where"] == "playing"
    g = _guest("aS0000", STAGE, 2)
    g.player(hp=0.0)
    assert M.screen(g)["where"] == "dead"
    assert M.screen(_guest("aS0000", STAGE, 5))["where"] == "results"       # time up, objective not met
    assert M.screen(_guest("aS0000", STAGE, 6))["where"] == "dead"
    assert M.screen(_guest("aS0000", STAGE, 1))["where"] == "loading"


def test_nothing_readable_is_unknown():
    assert M.screen(Guest())["where"] == "unknown"


def test_snapshot_reads_the_player_and_the_mission():
    g = _guest("aS0000", STAGE, 2)
    g.player()
    sm = g.obj("sMission", 0x130)
    g.u32(M.S_MISSION, sm)
    g.f32(sm + M.M_ELAPSED, 63.734)
    g.f32(sm + M.M_LEFT, 86.262)
    g.u32(sm + M.M_SCORE, 1200)
    g.u32(sm + M.M_COMBO, 3)
    g.f32(sm + M.M_COMBO_T, 2.5)
    snap = M.snapshot(g)
    p = snap["player"]
    assert p["hp"] == 1000.0 and p["hp_max"] == 1000.0 and p["class"] == "uPl< Chris >"
    assert abs(p["pos"][0] + 402.85) < 1e-3
    assert abs(p["rot"] - 1.5569) < 1e-3                         # facing +x (live: running "up" moved +x)
    assert snap["timer"] == 86.26 and snap["elapsed"] == 63.73 and snap["score"] == 1200
    assert snap["combo"] == 3 and snap["combo_timer"] == 2.5


def test_driver_hands_rounds_to_the_engine():
    d = M.DRIVER()
    g = _guest("aS0000", STAGE, 2)
    g.player()
    assert d.screen(g, None) == "playing"
    assert d.screen(_guest("aS0000", STAGE, 5), None) == "results"
    assert d.screen(_guest("aMerceMain", MAIN, 4), None) == "results"     # back at the selects: the menus' turn
    assert d.menu_handoff(_guest("aMerceMain", MAIN, 4), {}, "results") is True


def test_warm_probe_is_read_only_and_names_stable_screens():
    out = M.warm_probe(_guest("aMerceTitle", TITLE, 6))
    assert out["ready"] is True and out["screen"] == "press_start" and out["title"] == M.MAP_ID
    assert M.warm_probe(_guest("aMerceTitle", TITLE, 5))["ready"] is False


def test_enemies_walk_sEnemys_unit_list():
    g = _guest("aS0000", STAGE, 2)
    se = g.obj("sEnemy", 0x120)
    g.u32(M.S_ENEMY, se)
    units = []
    nodes = [g.obj("cNode", 0x30) for _ in range(3)]
    for k, n in enumerate(nodes):
        u = g.obj("uEm00Majini", 0x1000)
        g.put(u + M.P_POS, struct.pack("<3f", 100.0 * k, 0.0, 50.0))
        g.f32(u + M.P_VIT, 300.0 - 100 * k)
        g.f32(u + M.P_VIT_MAX, 300.0)
        g.u32(n, M.EN_NODE_VT)
        g.u32(n + M.EN_NODE_UNIT, u)
        g.u32(n + M.NODE_NEXT, nodes[k + 1] if k + 1 < len(nodes) else se + M.SE_SENTINEL)
        units.append(u)
    g.u32(se + M.SE_FIRST, nodes[0])
    es = M.enemies(g)
    assert [e["ptr"] for e in es] == units
    assert es[2]["hp"] == 100.0 and es[1]["pos"] == (100.0, 0.0, 50.0) and es[0]["class"] == "uEm00Majini"


def test_mission_complete_is_the_stage_end_state_only():
    d = M.DRIVER()
    assert d.mission_complete(_guest("aS0000", STAGE, 3), {}) is True          # cMerceStageEndState
    assert d.mission_complete(_guest("aS0000", STAGE, 5), {}) is False         # failed (time up, objective not met)
    assert d.mission_complete(_guest("aS0000", STAGE, 2), {}) is False


def test_mercmode_accepts_a_native_mission_complete_only_for_merc3d():
    import time
    from gbox import mercmode
    now = time.time()
    run = {'session_id': 's1', 'worker_id': 'w', 'autoplay_job': 'j', 'playing_since': now - 100,
           'mercmode': {'title': 'merc3d', 'map_id': '0004000000038B00'}}
    parent = {'id': 'j', 'tool': 'autoplay', 'state': 'running', 'require_worker': 'w',
              'input': {'session_id': 's1', 'op': 'start'}}

    class Store:
        def get(self, kind, key):
            return parent if key == 'j' else None

    body = {'session_id': 's1', 'round_id': 'a' * 32, 'at': now, 'map_id': '0004000000038B00', 'role': 'solo_p1',
            'source': 'native_terminal_reader',
            'witness': {'screen': 'results', 'playing_observed': True, 'player_verified': True, 'tally_ready': True,
                        'timer': 41.5, 'kills': 12, 'mission_complete': True}}
    assert mercmode.accept_boundary(Store(), run, body, parent_job=parent, now=now)['round_id'] == 'a' * 32
    re5 = dict(run, mercmode={'title': 're5', 'map_id': 'BLUS30491'})
    import pytest
    with pytest.raises(ValueError, match='tally'):
        mercmode.accept_boundary(Store(), re5, dict(body, map_id='BLUS30491'), parent_job=parent, now=now)


def test_the_player_comes_from_the_live_node_layout():
    """The exact bytes read live on the i9 (2026-10-27): sPlayer 0x82D7290, its node 0x8567154 = {0x899630, 0x82D72AC,
    0x82D72AC, 0x899644, 0x8566420, 0, ...}; the unit is the word at +0x10."""
    g = _guest("aS0000", STAGE, 2)
    sp, node = 0x082D7290, 0x08567154
    p = g.obj("uPl< Chris >", 0x1000)
    g.u32(M.S_PLAYER, sp)
    g.u32(sp, g.vtable("sPlayer"))
    g.u32(sp + 0x20, node)
    g.put(node, struct.pack("<8I", 0x899630, 0x082D72AC, 0x082D72AC, 0x899644, p, 0, 0, 0))
    g.f32(p + M.P_VIT, 1000.0)
    g.f32(p + M.P_VIT_MAX, 1000.0)
    assert M.player_unit(g) == p
    assert M.snapshot(g)["player"]["class"] == "uPl< Chris >"


def test_missions_are_played_in_order_level_by_level_and_the_game_again(tmp_path):
    """2026-10-28: "level to level to level until it completes the entire game. And then ... again"."""
    from gbox.mercs.titles import merc3d_3ds as M
    pick = M._Pick(path=tmp_path / "progress.json")
    seen = []
    for _ in range(M.LEVELS * 3 + 1):
        level = pick.level_for(M.LEVELS)
        tab = pick.tab_for(3)
        seen.append((level, tab))
        pick.reset()                                         # the round started: on to the next mission
    assert seen[:4] == [(0, 0), (0, 1), (0, 2), (1, 0)]
    assert seen[M.LEVELS * 3] == (0, 0) and pick.cursor[2] == 1   # the whole game, then round again
    again = M._Pick(path=tmp_path / "progress.json")          # a relaunch carries on where it was
    assert again.cursor == pick.cursor
    locked = M._Pick(path=tmp_path / "locked.json")
    locked.cursor = [3, 0, 0]
    assert locked.level_for(2) == 1                           # LV.4 not open yet: the last open level
