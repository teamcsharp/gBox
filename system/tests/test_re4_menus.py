"""RE4 GameCube from boot to a Mercenaries round, from RAM (gbox.re4_menus) and the playbook that walks it
(gbox.re4_merc_bot.play): the title task's work area found on its stack, every menu screen and cursor named, the one
press each screen needs, and a simulated RE4 walked from the title to a round without ever picking New Game, Load,
Options, Assignment Ada, EXIT or another character / stage."""
import struct

import pytest

from gbox import re4_menus as RM
from gbox import re4_merc_bot as B

PG, PSYS_AT, PL = 0x80300000, 0x80301000, 0x80310000
TW, STACK_LO, STACK_TOP = 0x80380000, 0x80390000, 0x80392000
GAME_LOOP = 0x80116640


class FakeRE4:
    """MEM1 of RE4 at 0x80000000 with the title task's work area, reacting to pad presses the way title.cpp does
    (tw routine / step / cursors), until GAME START + Leon + the Village start a round. Records every pick."""

    def __init__(self, routine=4, step=0, menu_cursor=3, unlocked=True):
        self.b = bytearray(0x400000)
        self.picks, self.events = [], []
        self.put(0x80000000, "6s", b"G4BE08")
        for a, sig in RM.SIGNATURES.items():                       # main.dol's code, as RAM holds it
            self.put(a, f"{len(sig)}s", sig)
        self.put(B.P_GLOBAL, ">I", PG)
        self.put(RM.PSYS, ">I", PSYS_AT)
        self.put(PSYS_AT + 4, ">I", 0xFF000000 if unlocked else 0)
        self.put(PG + RM.G_ROOM, ">H", 0x120)                     # the title sets room 0x120
        self.put(PG + B.G_HP, ">h", 1000)
        self.put(B.EMMGR, ">3I", 0x80320000, 1, 0xDE0)
        self.title_task(True)
        self.tw(routine, step)
        self.put(TW + RM.TW_MENU_COUNT, ">II", 5 if unlocked else 3, menu_cursor)
        self.put(TW + RM.TW_EXTRA_CURSOR, "3B", 1, 3, 3)          # EXIT, Krauser, Waterworld: all wrong to start with

    # --- memory ---
    def rd(self, a, n):
        o = a - 0x80000000
        return bytes(self.b[o:o + n])

    def put(self, a, fmt, *v):
        o = a - 0x80000000
        data = struct.pack(fmt, *v)
        self.b[o:o + len(data)] = data

    def u8(self, a):
        return self.b[a - 0x80000000]

    def title_task(self, on):
        t, th = RM.TASKS, RM.TASKS + RM.TASK_THREAD
        self.put(t + RM.TASK_ENTRY, ">I", RM.TITLE_ENTRY if on else GAME_LOOP)
        self.put(th + RM.THREAD_SP, ">I", STACK_TOP - 0x60)
        self.put(th + RM.THREAD_STACK_BASE, ">I", STACK_TOP)
        self.put(STACK_TOP - 0x38, ">II", RM.TITLE_ROUTINES, TW)   # r30 / r31 saved beside each other while it waits

    def tw(self, routine=None, step=None):
        if routine is not None:
            self.put(TW + RM.TW_ROUTINE, "B", routine)
        if step is not None:
            self.put(TW + RM.TW_SUB, "B", step)

    # --- the game's answer to a press (title.cpp's routines, enough of them) ---
    def send(self, rows):
        for r in rows:
            if r.get("down", True):
                self.press(r["key"])

    def press(self, key):
        self.events.append(key)
        routine, step = self.u8(TW), self.u8(TW + 1)
        if routine <= 4:
            if key == "start":
                self.tw(5, 1)
            return
        if routine == 5 and step == 1:
            count, cur = struct.unpack(">II", self.rd(TW + RM.TW_MENU_COUNT, 8))
            if key in ("dup", "ddown"):
                cur = max(0, min(count - 1, cur + (1 if key == "ddown" else -1)))
                self.put(TW + RM.TW_MENU_CURSOR, ">I", cur)
            elif key in ("a", "start"):
                code = (RM.MENU_EXTRAS if count == 5 else RM.MENU_PLAIN)[cur]
                self.picks.append(RM.MENU_NAMES[code])
                if code == RM.MERC_CODE:
                    self.put(PG + RM.G_EXTRA, ">I", RM.EXTRA_MERC)
                    self.tw(6, 4)
                elif code == 4:
                    self.tw(5, 7)                                    # LOAD
            return
        if routine == 5 and step == 7 and key == "b":
            self.tw(5, 1)
            return
        if routine == 6 and step == 4:
            if key in ("dup", "ddown"):
                self.put(TW + RM.TW_EXTRA_CURSOR, "B", 0 if key == "dup" else 1)
            elif key == "a":
                self.picks.append(["GAME START", "EXIT"][self.u8(TW + RM.TW_EXTRA_CURSOR)])
                if self.u8(TW + RM.TW_EXTRA_CURSOR) == 0:
                    self.tw(6, 8)
            return
        if routine == 6 and step == 8:
            cur = self.u8(TW + RM.TW_PLAYER_CURSOR)
            if key in ("dleft", "dright"):
                self.put(TW + RM.TW_PLAYER_CURSOR, "B", (cur + (1 if key == "dright" else -1)) % 5)
            elif key == "a":
                self.picks.append(RM.PLAYERS[cur])
                self.tw(6, 12)
            return
        if routine == 6 and step == 12:
            cur = self.u8(TW + RM.TW_STAGE_CURSOR)
            moves = {"dup": -2, "ddown": 2, "dleft": -1, "dright": 1}
            if key in moves:
                n = cur + moves[key]
                if 0 <= n <= 3 and not (key in ("dleft", "dright") and n // 2 != cur // 2):
                    self.put(TW + RM.TW_STAGE_CURSOR, "B", n)
            elif key == "a":
                self.picks.append(RM.STAGES[cur])
                self.round()

    def round(self):
        """GAME START, the character and the stage: the round starts (task 0 is the game's loop now)."""
        self.title_task(False)
        self.put(PG + RM.G_ROUTINE, "B", 3)
        self.put(PG + RM.G_ROOM, ">H", 0x400)
        self.put(B.P_PLAYER, ">I", PL)
        self.put(B.MERC_TIMER, ">I", 120 * 30)


def test_the_ram_maps_menu_group_reads_the_same_work_area():
    # profiles/gamedata/G4BE08-ram.json "menu": the inspector's view of what re4_menus reads (TW at stack top - 0x34)
    from gbox import ram_map
    g = FakeRE4(routine=6, step=8)
    g.put(TW + RM.TW_PLAYER_CURSOR, "B", 2)
    v = ram_map.load("G4BE08").read(g)
    assert v["menu.task0_entry"] == RM.TITLE_ENTRY and v["menu.title_work"] == TW
    assert (v["menu.title_routine"], v["menu.title_step"]) == (6, 8)
    assert (v["menu.main_items"], v["menu.player_cursor"], v["menu.stage_cursor"]) == (5, 2, 3)
    assert RM.screen(g)["cursor"] == 2 and not {k for k in v.errors if k.startswith("menu.")}


def test_the_title_tasks_work_area_is_found_on_its_stack():
    g = FakeRE4(routine=6, step=8)
    assert RM.tw(g) == TW
    s = RM.screen(g)
    assert s["where"] == "select_player" and s["cursor"] == 3 and s["target"] == RM.LEON
    g.title_task(False)                                             # the game's own loop runs: no title work
    assert RM.tw(g) is None and RM.screen(g)["where"] in RM.ROOM_WHERE


@pytest.mark.parametrize("cur,key", [(0, "ddown"), (1, "ddown"), (2, "a"), (3, "dup"), (4, "dup")])
def test_the_main_menu_goes_to_the_mercenaries_only(cur, key):
    g = FakeRE4(routine=5, step=1, menu_cursor=cur)
    s = RM.screen(g)
    assert s["items"] == ["START", "ASSIGNMENT ADA", "THE MERCENARIES", "LOAD", "OPTIONS"] and s["target"] == 2
    assert RM.step(s) == key


def test_a_main_menu_without_the_mercenaries_is_never_picked_on():
    g = FakeRE4(routine=5, step=1, menu_cursor=0, unlocked=False)
    s = RM.screen(g)
    assert s["items"] == ["START", "LOAD", "OPTIONS"] and s["target"] is None
    assert RM.step(s) is None                     # waits for it to idle back to the title and be built with the unlock


@pytest.mark.parametrize("where,cur,key", [
    ("extra_menu", 1, "dup"), ("extra_menu", 0, "a"),
    ("select_player", 0, "a"), ("select_player", 1, "dleft"), ("select_player", 2, "dleft"),
    ("select_player", 3, "dright"), ("select_player", 4, "dright"),
    ("select_stage", 0, "a"), ("select_stage", 1, "dleft"), ("select_stage", 2, "dup"), ("select_stage", 3, "dup"),
    ("title", None, "start"), ("new_game", None, "b"), ("options", None, "b"), ("load", None, "b"),
    ("ada_menu", 0, "b"), ("starting", None, None), ("players_setup", None, None)])
def test_each_screen_gets_the_one_press_towards_a_round(where, cur, key):
    assert RM.step({"where": where, "cursor": cur, "target": 0}) == key


def test_assignment_ada_is_never_played():
    g = FakeRE4(routine=6, step=4)
    g.put(PG + RM.G_EXTRA, ">I", RM.EXTRA_ADA)
    s = RM.screen(g)
    assert s["where"] == "ada_menu" and RM.step(s) == "b"


def test_results_dead_and_story_rooms():
    base = {"game_routine": 3}
    assert RM._game({"room": 0x400, "timer": 0.0, "hp": 900, "player": {}}, base) == {"where": "results"}
    assert RM._game({"room": 0x400, "timer": 50.0, "hp": 0, "player": {"ptr": 1}}, base) == {"where": "dead"}
    assert RM._game({"room": 0x400, "timer": 50.0, "hp": 900, "player": {"ptr": 1}}, base) == {"where": "playing"}
    # the Result screen after a warm resume (live 2026-10-27): the clock's word reads 17897063.5 s - no round's clock
    assert RM._game({"room": 0x400, "timer": 17897063.5, "hp": 900, "player": {"ptr": 1}}, base) == {"where": "results"}
    assert RM._game({"room": 0x400, "timer": B.CLOCK_MAX_S, "hp": 900, "player": {"ptr": 1}}, base) == {"where": "playing"}
    from gbox.mercs.titles.re4_gc import own_screen
    assert own_screen({"room": 0x400, "timer": 17897063.5, "hp": 900, "player": {"ptr": 1}}) == "results"
    assert own_screen({"room": 0x400, "timer": 50.0, "hp": 900, "player": {"ptr": 1}}) == "playing"
    assert RM._game({"room": 0x100, "timer": 0.0, "hp": 900, "player": {"ptr": 1}}, base) == {"where": "story"}
    loading = {"game_routine": 0}          # the Village loading: clock 0 but not the results
    assert RM._game({"room": 0x400, "timer": 0.0, "hp": 900, "player": {"ptr": 1}}, loading) == {"where": "loading"}
    assert RM.step({"where": "loading"}) is None
    assert RM.step({"where": "results"}) == "a" and RM.step({"where": "dead"}) == "a"
    assert RM.wandered({"where": "story", "room": 0x100}).startswith("in the story")
    assert RM.wandered({"where": "story_starting"}) and RM.wandered({"where": "select_player"}) is None


def test_the_navigator_waits_for_a_press_to_show_in_ram():
    sent, now = [], [0.0]
    nav = RM.Navigator(sent.append, sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    scr = {"where": "select_stage", "cursor": 2, "target": 0}
    assert nav.tick(scr) is None                       # RAM has only just shown it: it may be a passing moment
    now[0] += 0.5
    assert nav.tick(scr) == "dup"
    now[0] += 0.2
    assert nav.tick(scr) is None                       # the cursor has not moved yet: no second press
    now[0] += 2.0
    assert nav.tick(scr) == "dup"                      # it never showed: pressed again after RETRY_S
    moved = dict(scr, cursor=0)
    now[0] += 0.5
    assert nav.tick(moved) is None                     # it moved: the new cursor settles first
    now[0] += 0.5
    assert nav.tick(moved) == "a" and nav.stats["ram_progress"] >= 2


def test_a_moment_between_two_screens_is_never_pressed_on():
    # live 2026-10-20: the Village's first frames ran the room (pG+0x20 3) with the clock still at 0, which reads as
    # the results, and A went in at the start of the round
    sent, now = [], [0.0]
    nav = RM.Navigator(sent.append, sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    for where in ("loading", "results", "playing"):
        assert nav.tick({"where": where}) is None
        now[0] += 0.25
    assert sent == [] and nav.stats["ram_progress"] == 3


# a launch that explicitly keeps the game's own default picks (the bot is random by default since 2026-10-24)
CLASSIC = {"launch": {"mercmode": False}}


def test_play_walks_from_the_title_to_a_round_picking_only_the_mercenaries():
    g = FakeRE4(routine=4, step=0, menu_cursor=3)
    now, hooked = [0.0], []
    steps = iter(range(400))

    def stopped():
        return next(steps, None) is None or B.in_mercenaries(B.snapshot(g))
    stats = {}
    B.play(None, g.send, stopped, sleep=lambda s: now.__setitem__(0, now[0] + s), m=g, stats=stats,
           clock=lambda: now[0], hooks=lambda: hooked.append(g.u8(TW + 1)) or [], game=CLASSIC)
    assert g.picks == ["THE MERCENARIES", "GAME START", "Leon", "Village"]     # nothing else, ever
    assert B.in_mercenaries(B.snapshot(g))
    assert hooked == [8]                                   # the hooks went in at Select Player, once
    assert stats["menu_presses"] >= 8 and stats["hooks"] == "applied" and "menu_moment" in stats
    assert stats["ram_progress"] >= 6                      # the black watch sees RAM moving through the menus


def test_play_ends_the_run_when_the_game_wandered_into_the_story():
    g = FakeRE4(routine=4)
    g.title_task(False)
    g.put(PG + RM.G_ROUTINE, "B", 3)
    g.put(PG + RM.G_ROOM, ">H", 0x101)
    g.put(B.P_PLAYER, ">I", PL)
    now = [0.0]
    stats = B.play(None, g.send, lambda: now[0] > 60, sleep=lambda s: now.__setitem__(0, now[0] + s), m=g,
                   clock=lambda: now[0])
    assert stats["hung"] is True and "story" in stats["wandered"] and not g.events   # no press: relaunched instead


def test_play_ends_the_run_when_ram_cannot_name_the_menus():
    g = FakeRE4(routine=4)
    g.put(RM.TASKS + RM.TASK_ENTRY, ">I", RM.TITLE_ENTRY)
    g.put(STACK_TOP - 0x38, ">II", 0, 0)                   # the title task, but no work area on its stack
    now = [0.0]
    stats = B.play(None, g.send, lambda: now[0] > 700, sleep=lambda s: now.__setitem__(0, now[0] + s), m=g,
                   clock=lambda: now[0], game=CLASSIC)
    assert stats["hung"] is True and "did not name" in stats["wandered"] and not g.events


def test_setup_out_of_a_round_puts_in_only_the_unlock_bits(monkeypatch):
    calls = []
    from gbox import re_mods_tool
    monkeypatch.setattr(re_mods_tool, "RE4", lambda ad: object())
    monkeypatch.setattr(re_mods_tool, "run", lambda ad, op, g=None, **kw: calls.append(op))
    g = FakeRE4(routine=5, step=1)
    monkeypatch.setattr(B, "memory", lambda ad: g)
    assert B.setup(object()) == [] and calls == ["mercenaries_unlock"]
    calls.clear()
    g.round()
    assert B.setup(object()) == [] and calls == [op for op, _ in B.PACKAGE]     # in a round: all of it


def test_matches_any_state_of_the_disc(monkeypatch):
    g = FakeRE4(routine=4)
    monkeypatch.setattr(B, "memory", lambda ad: g)
    assert B.matches(object(), {"platform": "gamecube"})          # the title: still RE4's playbook
    assert not B.matches(object(), {"platform": "dreamcast"})
    g.put(0x80000000, "6s", b"GZLE01")
    assert not B.matches(object(), {"platform": "gamecube"})
