"""The fighting engine (gbox.fightbot) against a simulated fighting game: frame-exact holds, learning, feints, latency."""
import random
import struct

import pytest

from gbox import ram_map
from gbox.fightbot import book as B
from gbox.fightbot import engine as E
from gbox.fightbot import lessons as L
from gbox.fightbot import runner as R
from gbox.fightbot import vocab
from gbox.fightbot.title import Answer, Title

BASE = 0x1000
MOVES = {   # P2's attacks: move -> (height, limb, first active, last active)
    0x10: ("high", "punch", 9, 11), 0x11: ("mid", "kick", 11, 13), 0x12: ("low", "kick", 12, 14),
    0x20: ("mid", "punch", 10, 12)}            # 0x20 has no signature: the engine only sees an untagged move
F = 0x1
BITS = {"y": F, "up": 0x20, "down": 0x10, "left": 0x80, "right": 0x40}


def spec():
    sig = {f"0x{m:X}": {"attack": "strike", "height": h, "limb": l, "active": [s, e], "source": "manual",
                        "confidence": "static"} for m, (h, l, s, e) in MOVES.items() if m != 0x20}
    fighter = lambda p, o: {                                                     # noqa: E731
        f"{p}.hp": {"address": hex(BASE + 0x10 + o * 2), "type": "u16", "source": "manual"},
        f"{p}.move": {"address": hex(BASE + 0x20 + o * 2), "type": "u16", "format": "hex", "source": "manual",
                      "signatures": sig},
        f"{p}.move_frame": {"address": hex(BASE + 0x28 + o * 2), "type": "u16", "source": "manual"},
        f"{p}.input": {"address": hex(BASE + 0x30 + o * 2), "type": "u16", "source": "manual",
                       "flags": {"0x1": "F", "0x10": "down", "0x20": "up", "0x40": "right", "0x80": "left"}},
        f"{p}.pos": {"address": hex(BASE + 0x40 + o * 16), "type": "f32", "count": 3, "source": "manual"},
        f"{p}.chara": {"address": hex(BASE + 0x60 + o), "type": "u8", "source": "manual"}}
    vocab_ = {"screen": "game.screen", "frame": "game.frame"}
    for p in ("p1", "p2"):
        vocab_.update({f"{p}.{n}": f"{p}.{n}" for n in ("hp", "move", "move_frame", "input", "pos", "chara")})
    return {"format": "gbox-ram-map/1", "id": "TESTFIGHT", "platform": "test", "endian": "little",
            "fight": {"title": "tests", "fps": 60, "vocab": vocab_},
            "fields": {"game.frame": {"address": hex(BASE), "type": "u32", "source": "manual"},
                       "game.screen": {"address": hex(BASE + 4), "type": "u8", "source": "manual",
                                       "enum": {"0": "title", "1": "fight"},
                                       "signatures": {"0": {"screen": "title"}, "1": {"screen": "fight"}}},
                       **fighter("p1", 0), **fighter("p2", 1)}}


class Game:
    """One frame per step(): the pad reaches P1's input word a frame later; P2 attacks on a schedule; a hold with F
    and the right directions on any active frame parries (P2 takes 20), else P1 takes 15 on the first active frame."""
    NEED = {"high": {"up", "left"}, "mid": {"left"}, "low": {"down", "left"}}      # P1 on the left: back = left

    def __init__(self, schedule):
        self.ram = bytearray(0x200)
        self.schedule = dict(schedule)          # frame -> move
        self.frame, self.pad, self.p1_hp, self.p2_hp = 0, (), 200, 200
        self.move, self.mf, self.done, self.screen = 0, 0, True, 1
        struct.pack_into("<3f", self.ram, 0x40, 0.0, 0.0, 0.0)
        struct.pack_into("<3f", self.ram, 0x50, 1.5, 0.0, 0.0)
        self.events = []
        self.write()

    def read(self, a, n):
        return bytes(self.ram[a - BASE:a - BASE + n])

    def write(self):
        struct.pack_into("<IB", self.ram, 0, self.frame, self.screen)
        struct.pack_into("<HH", self.ram, 0x10, self.p1_hp, self.p2_hp)
        struct.pack_into("<HH", self.ram, 0x20, 0x1, self.move)                  # p1.move, p2.move
        struct.pack_into("<HH", self.ram, 0x28, 0, self.mf)                      # p1.move_frame, p2.move_frame

    def step(self):
        held = {k for k in self.pad}
        struct.pack_into("<H", self.ram, 0x30, sum(BITS[k] for k in held))     # the game reads last frame's pad
        self.frame += 1
        if self.frame in self.schedule:
            self.move, self.mf, self.done = self.schedule[self.frame], 0, False
        elif self.move:
            self.mf += 1
        if self.move and not self.done:
            h, _, s, e = MOVES[self.move]
            if s <= self.mf <= e:
                dirs = held - {"y"}
                if "y" in held and dirs == self.NEED[h]:
                    self.p2_hp -= 20
                    self.done = True
                    self.events.append(("parried", self.frame, self.move))
                elif self.mf == s:
                    self.p1_hp -= 15
                    self.done = True
                    self.events.append(("hit", self.frame, self.move))
            if self.mf > 30:
                self.move, self.mf = 0, 0
        self.write()


class Holds(Title):
    map_id = "TESTFIGHT"
    reach = 3.0

    def answers(self, attack, w):
        back = self.back(w)
        out = [Answer("hold_high", ("up", back, "y"), frames=4, lead=1),
               Answer("hold_mid", (back, "y"), frames=4, lead=1),
               Answer("hold_low", ("down", back, "y"), frames=4, lead=1)]
        if attack.height:                       # the signature says where it hits: that hold first
            out.sort(key=lambda a: a.name != f"hold_{attack.height}")
        return out

    def input_bits(self, answer, w):
        return sum(BITS[k] for k in answer.keys)


def setup(schedule, book=None, lessons=None):
    rmap = ram_map.RamMap(spec())
    title = Holds(rmap)
    game = Game(schedule)
    stats = {}
    eng = E.Engine(title, book=book or B.Book(rng=random.Random(3)), lessons=lessons, stats=stats,
                   rng=random.Random(3))
    return title, game, eng, stats


def run(title, game, eng, frames):
    for _ in range(frames):
        game.step()
        w = title.read(game.read)
        game.pad = eng.tick(w)


def test_menu_rules_in_the_map_walk_a_cursor_then_confirm():
    s = spec()
    s["fields"]["game.cursor"] = {"address": hex(BASE + 0x70), "type": "u8", "source": "manual"}
    s["fields"]["game.menu"] = {"address": hex(BASE + 0x71), "type": "u8", "source": "manual"}
    s["fields"]["game.screen"]["signatures"]["2"] = {"screen": "menu"}
    s["fight"]["menus"] = {"title": {"press": "start"},
                           "menu": [{"when": {"field": "game.menu", "eq": 3}, "cursor": "game.cursor", "target": 2,
                                     "next": "down", "prev": "up", "confirm": "b"},
                                    {"when": {"field": "game.menu", "eq": 4}, "wait": True},
                                    {"press": "a"}]}
    title = Holds(ram_map.RamMap(s))
    assert "game.cursor" in title.fields and "game.menu" in title.fields
    game = Game({})
    game.screen = 2
    game.write()

    def key(menu, cursor):
        game.ram[0x71], game.ram[0x70] = menu, cursor
        return title.menu(title.read(game.read))
    assert [key(3, 0), key(3, 2), key(3, 5), key(4, 0), key(1, 0)] == ["down", "b", "up", None, "a"]
    game.screen = 0
    game.write()
    assert title.read(game.read).screen == "title" and title.menu(title.read(game.read)) == "start"
    game.screen = 1
    game.write()
    assert title.menu(title.read(game.read)) is None                       # the fight: no menu rules
    s["fight"]["menus"]["menu"] = [{"cursor": "game.cursor", "targets": [1, 3], "next": "down", "prev": "up",
                                    "confirm": "b"}]                      # a new fighter each visit
    title = Holds(ram_map.RamMap(s))
    game.screen = 2
    game.write()
    assert key(0, 1) == "b" and key(0, 3) == "up"                         # first visit: target 1
    game.screen = 1
    game.write()
    title.menu(title.read(game.read))                                      # left the screen ...
    game.screen = 2
    game.write()
    assert key(0, 1) == "down" and key(0, 3) == "b"                       # ... and came back: target 3


def test_vocab_check_reports_what_a_map_fills():
    rep = vocab.check(ram_map.RamMap(spec()))
    assert rep["errors"] == [] and rep["filled"]["p2.move"] == "p2.move"
    assert "p1.state" in rep["missing"] and "screen" in rep["filled"]
    bad = spec()
    bad["fields"]["p2.move"]["signatures"]["0x10"]["height"] = "overhead"
    bad["fight"]["vocab"]["p1.hp"] = "p1.life"
    errors = vocab.check(ram_map.RamMap(bad))["errors"]
    assert any("overhead" in e for e in errors) and any("p1.life" in e for e in errors)


def test_world_reads_signatures_into_attacks():
    title, game, _, _ = setup({1: 0x11})
    game.step()
    game.step()
    w = title.read(game.read)
    assert w.screen == "fight" and w.frame == 2 and w.p1.side == 1 and w.distance == pytest.approx(1.5)
    att = w.p2.attack
    assert (att.kind, att.height, att.limb, att.start, att.end, att.frame) == ("strike", "mid", "kick", 11, 13, 1)
    assert att.to_active() == 10 and att.cls() == "strike:mid:kick"


def test_holds_land_on_the_active_frames_with_input_latency_measured():
    title, game, eng, stats = setup({10: 0x10, 60: 0x11, 110: 0x12})
    run(title, game, eng, 200)
    assert [e[0] for e in game.events] == ["parried"] * 3                       # high, mid, low: all held
    assert stats["attacks"] == 3 and stats["answers"] == 3 and stats["hits_taken"] == 0
    assert stats["damage_dealt"] == 60 and stats["answered_ok"] == 3
    assert stats["lat_input_f"] == 1                                           # the game showed the keys a frame later
    # pressed (first active - lead 1 - lag 1) after the onset, shown by the game a frame later: 9-2+1, 11-2+1, 12-2+1
    assert list(eng.lat_reaction) == [8, 10, 11] and stats["lat_reaction_f"] == 10


def test_an_untagged_move_is_learned_by_what_pays():
    sched = {10 + i * 50: 0x20 for i in range(12)}                             # a mid punch the map doesn't tag
    title, game, eng, stats = setup(sched)
    run(title, game, eng, 10 + 12 * 50)
    assert stats["attacks"] == 0                                               # no signature, no warn: not seen at all
    title, game, eng, stats = setup(sched)
    title.map.fields["p2.move"].signatures[0x20] = {"attack": "strike"}        # an attack, height and frames unknown
    run(title, game, eng, 10 + 12 * 50)
    ev = [e[0] for e in game.events]
    assert ev.count("parried") >= 8                                            # tried the holds, then kept the paying one
    assert eng.book.best("0:32") == "hold_mid" and eng.book.hit_frame("0:32") == 9    # and learned when it hits


def test_a_move_that_never_meets_anything_is_left_alone_as_a_feint():
    bk = B.Book(rng=random.Random(1))
    for _ in range(2):
        bk.record("1:16", "strike:high:punch", "hold_high", 0, met=False)
    assert bk.feint("1:16")
    bk.hit("1:16")
    assert not bk.feint("1:16")                                                # it hit once: real


def test_hits_taken_log_the_attackers_state_just_before(tmp_path):
    lessons = L.Run(tmp_path, "TESTFIGHT", "r1")
    title, game, eng, stats = setup({10: 0x12}, lessons=lessons)
    title.answers = lambda attack, w: [Answer("hold_wrong", ("up", "y"), frames=4, lead=1)]   # always wrong
    run(title, game, eng, 100)
    assert stats["hits_taken"] == 1 and stats["damage_taken"] == 15
    rows = [r for r in map(__import__("json").loads, (tmp_path / "TESTFIGHT/runs/r1.jsonl").read_text().splitlines())]
    hit = next(r for r in rows if r["kind"] == "hit_taken")
    assert hit["attacker"]["move"] == 0x12 and hit["in_move_frames"] == 11 and hit["answered"] is True
    ans = next(r for r in rows if r["kind"] == "answer")
    assert ans["answer"] == "hold_wrong" and ans["reward"] == -15 and ans["outcome"] == "taken"
    assert L.analyze(tmp_path, "TESTFIGHT") == []                             # the move is tagged: no candidate


def test_lessons_rank_p2_move_classes_by_the_hits_that_follow(tmp_path):
    run = L.Run(tmp_path, "TESTFIGHT", "c1")
    for i in range(10):                                        # class 3: an attack that hits 12 frames in, 8 of 10
        run.log("p2_move", 100 * i, move=0x40 + i % 2, move_class=3)
        if i < 8:
            run.log("hit_taken", 100 * i + 12, hp_lost=10)
        run.log("p2_move", 100 * i + 50, move=0, move_class=0)  # class 0: walking / idle, never followed by a hit
    rows = L.classes(tmp_path, "TESTFIGHT")
    assert rows[0] == {"move_class": 3, "starts": 10, "hits": 8, "hit_rate": 0.8, "frames_to_hit": [12, 12, 12]}
    assert rows[1]["move_class"] == 0 and rows[1]["hits"] == 0


def test_book_persists_and_prefers_a_paying_class_answer_for_new_moves(tmp_path):
    path = tmp_path / "book.json"
    bk = B.Book(path, rng=random.Random(0))
    for _ in range(3):
        bk.record("3:7", "strike:low", "hold_low", 30)
    bk.save()
    bk2 = B.Book(path, rng=random.Random(0))
    assert bk2.choose("9:99", "strike:low", ["hold_high", "hold_low"]) == "hold_low"   # never met, its class pays
    assert bk2.choose("9:99", "strike:mid", ["hold_high", "hold_low"]) == "hold_high"  # nothing known: untried first


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_runner_ticks_once_per_game_frame_and_returns_when_the_fight_ends():
    title, game, eng, stats = setup({5: 0x10})
    clock, sent = Clock(), []
    polls = {"n": 0}

    def frame(mem):                       # the game advances one frame every 33 polls (~16 ms at 0.5 ms polls)
        polls["n"] += 1
        if polls["n"] % 33 == 0:
            game.step()
            if game.frame == 40:
                game.screen = 0
                game.write()
        return Title.frame(title, mem)
    title.frame = frame
    held = set()

    def send(rows):
        sent.append(rows)
        for r in rows:
            (held.add if r["down"] else held.discard)(r["key"])
        game.pad = tuple(held)
    out = R.fight(title, game.read, R.Sender(send), eng, lambda: False, clock=clock, sleep=clock.sleep, stats=stats)
    assert out == "title" and stats["frames"] == 40 and stats["frames_skipped"] == 0          # frames 0..39
    assert game.events == [("parried", 14, 0x10)]
    downs = [r for rows in sent for r in rows if r["down"]]
    assert [r["key"] for r in downs][:3] == ["left", "up", "y"]               # directions down before the button


def test_runner_reports_a_stalled_frame_clock():
    title, game, eng, stats = setup({})
    clock = Clock()
    out = R.fight(title, game.read, R.Sender(lambda rows: None), eng, lambda: False, clock=clock,
                  sleep=clock.sleep, stats=stats, stall_s=1.0)
    assert out == "stalled"


def test_sender_sends_only_changes_and_threaded_sends_the_newest():
    sent = []
    s = R.Sender(sent.append)
    s.hold({"y", "left"})
    s.hold({"y", "left"})
    s.hold({"left"})
    s.hold(())
    assert sent == [[{"key": "left", "down": True}, {"key": "y", "down": True}], [{"key": "y", "down": False}],
                    [{"key": "left", "down": False}]]
    import threading
    gate, got = threading.Event(), []

    def slow(rows):
        got.append(rows)
        gate.wait(2)
    t = R.Sender(slow, threaded=True)
    t.hold({"a"})
    import time
    for _ in range(100):
        if got:
            break
        time.sleep(0.01)
    t.hold({"b"})
    t.hold({"c"})                                                              # b is never sent: c is newer
    gate.set()
    t.close()
    for _ in range(100):
        if len(got) >= 3:
            break
        time.sleep(0.01)
    keys = [[(r["key"], r["down"]) for r in rows] for rows in got]
    assert keys[0] == [("a", True)] and ("b", True) not in [k for rows in keys for k in rows]


def bare_world(frame, p2_attack=None, p1_attack=None):
    from gbox.fightbot.world import Fighter, World
    return World(frame=frame, t=0, screen="fight", p1=Fighter(side=1, attack=p1_attack, chara=1),
                 p2=Fighter(side=-1, attack=p2_attack, chara=2))


def test_an_answer_that_does_not_come_out_falls_back(tmp_path):
    """SC2: a GI only comes out when P1 is free; no GI move within confirm_f frames -> guard instead."""
    from gbox.fightbot.world import Attack
    title = Holds(ram_map.RamMap(spec()))
    guard = Answer("guard", ("b",), frames=10)
    title.answers = lambda attack, w: [Answer("gi", ("left", "b"), frames=2, lead=5, confirm_f=3, fallback=guard)]
    came_out = {"v": False}
    title.confirm = lambda answer, w: came_out["v"]
    eng = E.Engine(title, B.Book(rng=random.Random(0)))
    att = Attack(kind="strike", height="mid", start=20, frame=0, move=7)
    keys = [eng.tick(bare_world(f, Attack(**{**att.__dict__, "frame": f}))) for f in range(20)]
    assert keys[14] == ("left", "b")                              # pressed 20 - lead 5 - lag 1 frames in
    assert keys[17] == ("b",) and eng.stats["fallbacks"] == 1     # not out 3 frames later: the guard
    came_out["v"] = True
    eng2 = E.Engine(title, B.Book(rng=random.Random(0)))
    keys = [eng2.tick(bare_world(f, Attack(**{**att.__dict__, "frame": f}))) for f in range(20)]
    assert eng2.stats.get("fallbacks", 0) == 0 and keys[14] == ("left", "b")


def test_hold_off_keys_stay_up_while_p1s_own_attack_is_out():
    from gbox.fightbot.world import Attack
    title = Holds(ram_map.RamMap(spec()))
    eng = E.Engine(title, B.Book(rng=random.Random(0)))
    eng._start(Answer("punish", ("a", "b"), frames=5, kind="punish", hold_off=("b",)), bare_world(0), None)
    own = Attack(kind="strike", start=3, end=6, frame=2)
    assert eng.tick(bare_world(1, p1_attack=own)) == ("a",)        # G would cancel the startup
    assert eng.tick(bare_world(2, p1_attack=Attack(kind="strike", start=3, end=6, frame=7))) == ("a", "b")


def test_long_active_windows_are_timed_on_where_they_landed_before():
    from gbox.fightbot.world import Attack
    title = Holds(ram_map.RamMap(spec()))
    bk = B.Book(rng=random.Random(0))
    for _ in range(3):
        bk.hit("2:9", "strike:mid", frames=31)                    # active 24-34, but it connects at 31
    eng = E.Engine(title, bk)
    att = Attack(kind="strike", height="mid", start=24, end=34, frame=0, move=9)
    keys = [eng.tick(bare_world(f, Attack(**{**att.__dict__, "frame": f}))) for f in range(32)]
    first = next(i for i, k in enumerate(keys) if k)
    assert first == 31 - 1 - 1                                    # contact 31 - lead 1 - lag 1, not 24 - 2
