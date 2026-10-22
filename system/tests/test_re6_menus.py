"""RE6 (Xbox 360) Mercenaries menus interface (gbox.mercs.titles.re6_x360): rounds named from RAM, blind random stage /
character picks, BOOT_KEY never A, and a simulated boot through mercs_bot.Boot that never leaves The Mercenaries."""
import random
import struct

from gbox import mercs_bot as B
from gbox.mercs.titles import re6_x360 as R


class Mem:
    def __init__(self):
        self.b = {}

    def put(self, a, fmt, *v):
        self.b[a] = struct.pack(fmt, *v)

    def rd(self, a, n):
        buf = bytearray(n)
        for base, d in self.b.items():
            lo, hi = max(a, base), min(a + n, base + len(d))
            if lo < hi:
                buf[lo - a:hi - a] = d[lo - base:hi - base]
        return bytes(buf)


def round_mem(hp=900, hp_max=1000):
    m = Mem()
    m.put(R.SPLAYER, ">I", 0x40100000)
    m.put(0x40100000 + R.P1, ">I", 0x40200000)
    m.put(0x40200000 + R.LIFE, ">hh", hp, hp_max)
    return m


def fresh():
    R.ROSTER.__init__(random.Random(1))
    R.STAGE_PICK.__init__(random.Random(2))


def test_a_round_is_named_from_the_players_life():
    fresh()
    first = R.screen(round_mem())
    assert first["where"] == "playing" and first["character"] in R.CHARACTERS
    assert R.screen(round_mem(hp=0))["where"] == "dead"


def test_out_of_a_round_it_is_unknown_and_never_guessed(monkeypatch):
    fresh()
    assert R.screen(Mem())["where"] == "unknown"
    m = Mem()
    m.put(R.SPLAYER, ">I", 0)                      # sPlayer not built yet
    assert R.screen(m)["where"] == "unknown"
    m.put(R.SPLAYER, ">I", 0x40100000)
    m.put(0x40100000 + R.P1, ">I", 0)              # no uPlayer
    assert R.screen(m)["where"] == "unknown"


def test_boot_key_is_never_a_which_would_start_campaign():
    assert R.BOOT_KEY == "start"
    assert R.step({"where": "unknown"}) is None


def test_menu_state_hook_names_screens(monkeypatch):
    fresh()
    monkeypatch.setattr(R, "menu_state", lambda m: {"where": "select_stage", "cursor": None})
    assert R.screen(Mem())["where"] == "select_stage"
    monkeypatch.setattr(R, "menu_state", lambda m: {"where": "select_player", "cursor": 4})
    scr = R.screen(Mem())
    assert scr["target"] in range(len(R.CHARACTERS)) and scr["cursor"] == 4


def test_stage_pick_is_random_rights_then_a_and_counts_only_reported_presses():
    fresh()
    scr = {"where": "select_stage"}
    seen = set()
    for seed in range(40):
        R.STAGE_PICK.__init__(random.Random(seed))
        n = 0
        while R.step(scr) == "dright":
            R.pressed(scr, "dright")
            n += 1
        assert n <= len(R.STAGES) - 1 and R.step(scr) == "a"
        R.pressed(scr, "a")
        assert R.STAGE_PICK.left is None
        seen.add(n)
    assert seen == {0, 1, 2}
    R.STAGE_PICK.__init__(random.Random(0))
    k = R.step(scr)
    left = R.STAGE_PICK.left
    assert R.step(scr) == k and R.STAGE_PICK.left == left      # an unreported press changes nothing


def test_character_moves_with_cursor_from_ram_and_blind():
    fresh()
    assert R.step({"where": "select_player", "cursor": 1, "target": 3}) == "dright"
    assert R.step({"where": "select_player", "cursor": 5, "target": 3}) == "dleft"
    assert R.step({"where": "select_player", "cursor": 3, "target": 3}) == "a"
    scr = {"where": "select_player", "cursor": None, "target": 2}
    n = 0
    while R.step(scr) == "dright":
        R.pressed(scr, "dright")
        n += 1
    assert n == 2 and R.step(scr) == "a"


def test_roster_draws_least_played_never_the_last():
    fresh()
    seen = []
    for _ in range(len(R.CHARACTERS)):
        R.ROSTER.want()
        seen.append(R.ROSTER.started())
    assert sorted(seen) == sorted(R.CHARACTERS)                # everyone once before anyone twice
    assert all(a != b for a, b in zip(seen, seen[1:]))


def test_step_covers_title_results_dead_and_never_wanders_into_a_story():
    assert R.step({"where": "title"}) == "start" and R.step({"where": "results"}) == "start"
    assert R.step({"where": "dead"}) == "a"
    assert R.wandered({"where": "select_stage"}) is None
    assert "left The Mercenaries" in R.wandered({"where": "campaign"})


def test_boot_walks_selects_to_a_round_with_a_random_stage_and_character(monkeypatch):
    fresh()
    sent, state = [], {"where": "select_stage", "n": 0}
    keys = []
    mem = Mem()

    def send(ev):
        if ev[0]["down"]:
            keys.append(ev[0]["key"])
    t = [0.0]

    def clock():
        return t[0]

    def sleep(s):
        t[0] += s
    # a tiny state machine: stage page -> character row -> round
    flow = {"where": "select_stage", "pos": 0}

    def menu_state(m):
        if flow["where"] == "playing":
            return None
        return {"where": flow["where"], "cursor": flow["pos"] if flow["where"] == "select_player" else None}
    monkeypatch.setattr(R, "menu_state", menu_state)
    boot = B.Boot(R, mem, send, sleep=sleep, clock=clock, stats={}, jump_at="select_player")
    for _ in range(400):
        t[0] += 0.3
        n = len(keys)
        scr = R.screen(mem)
        if boot.tick(t[0], scr=scr):
            break
        for k in keys[n:]:
            if flow["where"] == "select_stage" and k == "a":
                flow.update(where="select_player", pos=0)
            elif flow["where"] == "select_player":
                if k == "dright":
                    flow["pos"] += 1
                elif k == "a":
                    mem.__dict__.update(round_mem().__dict__)
                    flow["where"] = "playing"
        if flow["where"] == "playing":
            break
    assert flow["where"] == "playing" and R.screen(mem)["where"] == "playing"
    assert set(keys) <= {"dright", "a"} and keys[-1] == "a"
