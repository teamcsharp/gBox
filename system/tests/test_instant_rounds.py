"""Instant rounds (gbox.mercs.round_states + gbox.re4_merc_bot.InstantRounds) and the round transitions around them:
the state library and its bounds, the choice of the next round, a capture at a menu-started round's first frame, a load
verified in RAM (a new round with its own boundary, round map and round_gap_s; the package counted once, the state's
pending equip cleared), the fallbacks (a load RAM never shows: the menus; a load that froze: hung, instant rounds off),
the results-screen hang between rounds (every RE4 MercMode turn ended there on 2026-10-26), phantom rounds after a
Continue, and RE5's shorter menu path (mode blocks, faster cursor steps, round_gap_s)."""
import json
import random
import struct
import time
from pathlib import Path
from types import SimpleNamespace


from gbox import mercs_bot as MB
from gbox import re4_menus as RM
from gbox import re4_merc_bot as B
from gbox import re_games, re_mods_tool
from gbox.mercs import round_map, round_states as RS
from gbox.mercs.curriculum import Coverage
from tests.test_re4_menus import TW, FakeRE4
from tests.test_re4_merc_bot import PG, world

GID = "78ab9efa2e310db4"
GAME = {"game_id": GID, "launch": {"mercmode": {"title": "re4"}}}
CLASSIC = {"game_id": GID, "launch": {"mercmode": False}}


# --- fixtures: a Linux Dolphin over the fake RAM, fake time ---------------------------------------------------------------
def _poke(mem, addr, data: bytes):
    o = addr - 0x80000000
    mem.b[o:o + len(data)] = data


def hook_package(mem):
    """The package's code in RAM, as re_mods_tool.RE4.hooked() checks it (the cave's dispatcher, the main loop's call)."""
    V = re_games.GC
    _poke(mem, V.HOOK_SITE, re_mods_tool._bl(V.HOOK_SITE, V.CAVE))
    _poke(mem, V.CAVE, re_mods_tool.DISPATCHER)


def merc_world(room=0x400, timer_s=3.0, vi=1000, hooks=True):
    m = world([], room=room, timer_s=timer_s)
    _poke(m, 0x80000000, b"G4BE08\x00\x00")
    if hooks:
        hook_package(m)
    m.put(B.VI_COUNT, ">I", vi)
    return m


class FakeDolphin:
    """A Linux Dolphin as instant rounds use it: the demo save slot (jump_save: the RAM's bytes, through StateSaves'
    .s10 like Dolphin), the slot-8 load key (checkpoint_load: RAM <- StateSaves/G4BE08.s08), its RAM for re_mods."""
    name = "dolphin"
    supported = {"send_input", "save_state", "load_state", "read_memory", "write_memory"}

    def __init__(self, mem, root: Path, loads=True, on_load=None):
        self.mem, self.root, self.loads, self.on_load = mem, Path(root), loads, on_load
        self.config = SimpleNamespace(runtime=self.root / "runtime")
        self.saves, self.load_keys, self.events_at_save = [], 0, None

    def state_dir(self):
        return self.root / "StateSaves"

    def jump_save(self, dest):
        self.events_at_save = len(getattr(self.mem, "events", ()))
        data = bytes(self.mem.b)
        self.state_dir().mkdir(parents=True, exist_ok=True)
        slot = self.state_dir() / "G4BE08.s10"
        slot.write_bytes(data)                       # the snapshot is taken (serialized): the file appears
        Path(dest).write_bytes(data)
        slot.unlink()
        self.saves.append(Path(dest))
        return len(data)

    def checkpoint_load(self):
        self.load_keys += 1
        slot = self.state_dir() / "G4BE08.s08"
        if self.loads and slot.is_file():
            self.mem.b[:] = slot.read_bytes()
            if self.on_load is not None:
                self.on_load()
        return {"slot": 8}

    def read_memory(self, a, n):
        return self.mem.rd(a, n)

    def write_memory(self, a, data):
        _poke(self.mem, a, bytes(data))
        return {"verified": True}


class Sim:
    """Fake time for play(): every sleep advances it (and yields a moment of real time to a capture thread), runs the
    Mercenaries clock down `speed` x while a round is up and ticks the VI count while the game runs."""

    def __init__(self, mem, speed=1.0, yield_s=0.0):
        self.m, self.t, self.speed, self.vi_running = mem, 0.0, speed, True
        self.yield_s = yield_s                       # real time per sleep: a capture thread gets to run

    def clock(self):
        return self.t

    def sleep(self, dt):
        self.t += dt
        if self.yield_s:
            time.sleep(self.yield_s)
        m = self.m
        if self.vi_running:
            vi = struct.unpack(">I", m.rd(B.VI_COUNT, 4))[0]
            _poke(m, B.VI_COUNT, struct.pack(">I", vi + max(1, int(dt * 60))))
        if RM.title_running(m):
            return
        frames = struct.unpack(">I", m.rd(B.MERC_TIMER, 4))[0]
        if frames > 0:
            _poke(m, B.MERC_TIMER, struct.pack(">I", max(0, frames - int(round(dt * 30 * self.speed)))))


def library_for(ad, mem, game=GAME):
    key = RS.library_key(game, bytes(mem.rd(0x80000000, 8)), RS.emulator_release(ad))
    return RS.Library(RS.library_root(ad) / key)


def store_state(lib, tmp_path, room, character, timer_s=120.0, pend=(0x37, 150), hooks=True, vi=50):
    """A library state taken at a round's first frame: room, Leon alive, the clock at its start, the package's code in
    RAM (or not), the round's gun pending in the cave."""
    start = merc_world(room=room, timer_s=timer_s, vi=vi, hooks=hooks)
    start.put(B.PEND_EQUIP, ">HH", *pend)
    src = tmp_path / f"{character}-{room:x}.bin"
    src.write_bytes(bytes(start.b))
    idx = RM.STAGE_ROOMS.index(room)
    return lib.add(src, {"room": room, "character": character, "timer": timer_s, "stage": RM.STAGES[idx],
                         "stage_index": idx})


def run_play(ad, mem, sim, stopped, tmp_path, monkeypatch, **kw):
    armed, rows, stats = [], [], dict(kw.pop("stats", None) or {})
    monkeypatch.setattr(B, "arm_round", lambda ad_, st: armed.append(
        (st["rounds"], st.get("hooks"), st.get("menu_presses", 0), st.get("round_start_via"))))

    def boundary(body, live):
        rows.append(body)
        return True
    B.play(ad, kw.pop("send", lambda r: None), stopped, sleep=sim.sleep, m=mem, clock=sim.clock, stats=stats,
           learn_dir=tmp_path / "learned", game=kw.pop("game", GAME), hooks=lambda: [], ram_prompt=False,
           round_boundary=boundary, session_id="w1-s1", **kw)
    return stats, rows, armed


# --- the library ----------------------------------------------------------------------------------------------------------
def test_the_library_is_one_folder_per_build_and_disc_revision(tmp_path):
    ad = FakeDolphin(merc_world(), tmp_path)
    a = RS.library_key({"game_id": GID}, b"G4BE08\x00\x00")
    assert a == f"{GID}-stock-G4BE08r0"
    assert RS.library_key({"game_id": GID, "mod": "hd pack"}, b"G4BE08\x00\x00") == f"{GID}-hd_pack-G4BE08r0"
    assert RS.library_key({"game_id": GID}, b"G4BE08\x00\x01") != a          # another disc revision: another folder
    assert RS.library_key({"game_id": "e42c9b780c07c437"}, b"G4BE08\x00\x00") != a   # another catalog build
    assert RS.library_key({"game_id": GID}, b"G4BE08\x00\x00", "2609a") == a + "-dolphin2609a"   # another Dolphin
    assert RS.library_root(ad) == tmp_path / "runtime" / "round_states"
    head = tmp_path / "G4BE08.s08"                                     # a Dolphin 2609a state's header (the Spark's)
    head.write_bytes(b"G4BE08" + bytes(10) + bytes(8) + b"\x7e\xbb\xad\xba" + b"\x0d\x00\x00\x00" + b"Dolphin 2609a"
                     + b"\x01\x00\x01" + bytes(40))
    assert RS.state_release(head) == "2609a" and RS.state_release(tmp_path / "none") is None


def test_the_library_keeps_two_per_combination_and_its_total_bound(tmp_path, monkeypatch):
    clock = [1000.0]
    lib = RS.Library(tmp_path / "lib", clock=lambda: clock[0])
    (tmp_path / "lib").mkdir()
    stale, fresh = tmp_path / "lib" / "capture-1-aa.tmp", tmp_path / "lib" / "capture-2-bb.tmp"
    for f in (stale, fresh):
        f.write_bytes(b"x")
    old = time.time() - RS.STALE_CAPTURE_S - 60
    import os
    os.utime(stale, (old, old))                                      # a capture its run never filed
    for n in range(3):                                               # a third Leon / Village: the oldest goes
        clock[0] += 10
        src = tmp_path / f"s{n}.bin"
        src.write_bytes(bytes([n]) * 64)
        lib.add(src, {"room": 0x400, "character": "Leon", "timer": 120.0})
    left = lib.entries()
    assert len(left) == RS.MAX_PER_COMBO and lib.count((0x400, "Leon")) == 2
    assert {Path(e["file"]).read_bytes()[0] for e in left} == {1, 2} and not list(tmp_path.glob("s*.bin"))
    assert not stale.exists() and fresh.exists()                     # swept when old; one still being written stays
    monkeypatch.setattr(RS, "MAX_TOTAL", 3)
    for who in ("Ada", "HUNK"):
        clock[0] += 10
        src = tmp_path / f"{who}.bin"
        src.write_bytes(b"x" * 64)
        lib.add(src, {"room": 0x402, "character": who, "timer": 120.0})
    assert len(lib.entries()) == 3 and lib.count((0x402, "HUNK")) == 1   # the newest kept, the oldest dropped
    e = lib.entries()[0]
    assert e["bytes"] == 64 and len(e["sha256"]) == 64 and e["loads"] == e["fails"] == 0


def test_a_changed_state_is_never_loaded_and_failures_drop_it_then_switch_instant_rounds_off(tmp_path):
    clock = [5000.0]
    lib = RS.Library(tmp_path / "lib", clock=lambda: clock[0])
    src = tmp_path / "a.bin"
    src.write_bytes(b"state" * 10)
    e = lib.add(src, {"room": 0x400, "character": "Leon", "timer": 120.0})
    assert lib.valid(e) is None
    Path(e["file"]).write_bytes(b"other")
    assert "sha256" in lib.valid(e)
    lib.record(e, False, "RAM never showed it")
    assert json.loads(Path(e["meta"]).read_text())["fails"] == 1 and lib.tripped() is None
    lib.record(e, False, "RAM never showed it")                     # MAX_FAILS: dropped
    assert not Path(e["file"]).exists() and lib.entries() == []
    lib.record({"file": "x", "meta": str(tmp_path / "none.json")}, False, "third failure in a row")
    assert "3 failed loads" in lib.tripped()                         # TRIP_FAILS in a row: off for TRIP_S
    clock[0] += RS.TRIP_S + 1
    assert lib.tripped() is None
    lib.record({"file": "x", "meta": "x"}, True)
    assert lib.health()["fails_in_a_row"] == 0


# --- which round next -----------------------------------------------------------------------------------------------------
COMBOS = [(room, who) for room in RM.STAGE_ROOMS for who in RM.PLAYERS]


def _lib_with(tmp_path, combos):
    lib = RS.Library(tmp_path / "lib", rng=random.Random(4))
    tmp_path.mkdir(parents=True, exist_ok=True)
    for room, who in combos:
        src = tmp_path / f"{who}{room}.bin"
        src.write_bytes(b"s" * 32)
        lib.add(src, {"room": room, "character": who, "timer": 120.0})
    return lib


def test_the_next_round_is_never_the_last_one_nor_its_character(tmp_path):
    lib = _lib_with(tmp_path, [(0x400, "Leon"), (0x402, "Leon"), (0x403, "Ada")])
    for _ in range(30):
        kind, e = lib.choose(COMBOS, previous=(0x400, "Leon"), grow_p=0.0)
        assert kind == "state" and (e["room"], e["character"]) == (0x403, "Ada")
    kind, combo = lib.choose(COMBOS, previous=(0x403, "Ada"), grow_p=1.0)   # combinations missing: a walk to one
    assert kind == "menus" and combo not in [(0x400, "Leon"), (0x402, "Leon"), (0x403, "Ada")] and combo[1] != "Ada"
    only = _lib_with(tmp_path / "b", [(0x400, "Leon")])
    kind, combo = only.choose(COMBOS, previous=(0x400, "Leon"), grow_p=0.0)   # only Leon stored, Leon just played
    assert kind == "menus" and combo[1] != "Leon"


def test_the_djs_pick_comes_from_the_library_when_it_can_and_the_classic_default_replays(tmp_path):
    lib = _lib_with(tmp_path, [(0x400, "Leon"), (0x404, "Wesker")])
    kind, e = lib.choose(COMBOS, previous=(0x404, "Wesker"), request={"room": 0x404, "character": "Wesker"})
    assert kind == "state" and (e["room"], e["character"]) == (0x404, "Wesker")   # asked for: even right again
    kind, combo = lib.choose(COMBOS, previous=None, request={"room": None, "character": "HUNK"})
    assert kind == "menus" and combo[1] == "HUNK"                  # not stored: the menus take it (and capture it)
    kind, e = lib.choose([(0x400, "Leon")], previous=(0x400, "Leon"))     # a launch without random picks
    assert kind == "state" and e["character"] == "Leon"


# --- a round's end loads the next round ------------------------------------------------------------------------------------
def test_a_round_end_loads_the_next_round_from_the_library_as_a_new_round(tmp_path, monkeypatch):
    monkeypatch.setattr(RS, "GROW_P", 0.0)
    m = merc_world(room=0x400, timer_s=40.0)                         # Leon on the Village (2 s at 20x)
    ad = FakeDolphin(m, tmp_path)
    lib = library_for(ad, m)
    entry = store_state(lib, tmp_path, 0x402, "Ada")                 # Ada / the Castle, taken at its first frame
    sim = Sim(m, speed=20.0)
    stats, rows, armed = run_play(ad, m, sim, lambda: sim.t > 14.0, tmp_path, monkeypatch)
    assert [r["witness"]["screen"] for r in rows] == ["results", "results"]
    assert len({r["round_id"] for r in rows}) == 2                     # one boundary per round, each its own
    assert stats["rounds"] == 2 and stats["instant_loads"] == 1 and ad.load_keys == 1
    assert stats["character"] == "Ada" and stats["stage"] == "Castle" and rows[1]["character"] == "Ada"
    assert stats["hooks"] == "applied (in the loaded state)"           # the package found in RAM: never stacked again
    assert armed[1][:2] == (2, "applied (in the loaded state)")        # ... and the round's own ops (its gun) after it
    assert armed[1][2] == 0 and armed[1][3] == "state"                 # never through the menus: no press before it
    assert m.rd(B.PEND_EQUIP, 4) == bytes(4)                          # the state's own gun is not swapped back in
    assert not (ad.state_dir() / "G4BE08.s08").exists()               # the borrowed slot file is gone again
    assert json.loads(Path(entry["meta"]).read_text())["loads"] == 1
    maps = {p.parent.name: json.loads(p.read_text()) for p in (tmp_path / "round_maps" / "G4BE08").glob("*/*.json")}
    assert set(maps) == {"r400", "r402"}                               # a route map per round
    assert maps["r402"]["round_start_via"] == "state" and maps["r402"]["round_gap_s"] < 2.0
    assert maps["r402"]["instant_state"] == Path(entry["file"]).name
    assert stats["round_start_via"] == "state" and stats["round_gap_s"] < 2.0
    assert "state" in stats["round_gaps"]


def test_a_load_ram_never_shows_falls_back_to_the_menus_once_and_marks_the_state(tmp_path, monkeypatch):
    monkeypatch.setattr(RS, "GROW_P", 0.0)
    monkeypatch.setattr(RS, "RESTORE_AFTER_FAIL_S", 0.0)
    m = merc_world(room=0x400, timer_s=1.0)
    ad = FakeDolphin(m, tmp_path, loads=False)                        # the load key goes nowhere
    lib = library_for(ad, m)
    entry = store_state(lib, tmp_path, 0x402, "Ada")
    sim = Sim(m)
    stats, rows, armed = run_play(ad, m, sim, lambda: sim.t > 14.0, tmp_path, monkeypatch)
    assert len(rows) == 1 and stats["rounds"] == 1                    # the boundary once; no phantom round
    assert stats["instant_fallbacks"] == 1 and "instant_loads" not in stats
    assert "the menus take over" in stats["instant_last"] and "never showed" in stats["instant_last"]
    assert json.loads(Path(entry["meta"]).read_text())["fails"] == 1
    assert stats["menu_presses"] >= 1 and stats["menu_last"] == "results: a"   # the menus walk on from the results
    assert not stats.get("hung") and not (ad.state_dir() / "G4BE08.s08").exists()


def test_a_load_that_freezes_the_game_ends_the_run_as_hung_and_switches_instant_rounds_off(tmp_path, monkeypatch):
    monkeypatch.setattr(RS, "GROW_P", 0.0)
    monkeypatch.setattr(RS, "RESTORE_AFTER_FAIL_S", 0.0)
    m = merc_world(room=0x400, timer_s=1.0)
    sim = Sim(m)
    ad = FakeDolphin(m, tmp_path, on_load=lambda: setattr(sim, "vi_running", False))   # loads, then never runs
    lib = library_for(ad, m)
    entry = store_state(lib, tmp_path, 0x402, "Ada")
    stats, rows, _ = run_play(ad, m, sim, lambda: sim.t > 30.0, tmp_path, monkeypatch)
    assert stats["hung"] is True and stats["wandered"].startswith("instant round: the game froze")
    assert len(rows) == 1 and not Path(entry["file"]).exists()        # that state never loads again
    assert RS.Library(lib.folder, clock=sim.clock).tripped() and stats["instant_rounds"].startswith("off for")
    assert sim.t < 15.0                                              # ended at once, not after a menu stall


def test_while_the_operator_has_the_pad_a_round_end_loads_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(RS, "GROW_P", 0.0)
    m = merc_world(room=0x400, timer_s=1.0)
    ad = FakeDolphin(m, tmp_path)
    store_state(library_for(ad, m), tmp_path, 0x402, "Ada")
    sim = Sim(m)
    stats, rows, _ = run_play(ad, m, sim, lambda: sim.t > 4.0, tmp_path, monkeypatch,
                              stats={"operator_control": True})                 # gbox.pad_takeover: their game
    assert len(rows) == 1 and ad.load_keys == 0 and "instant_loads" not in stats


def test_a_state_without_the_package_gets_it_in_its_round_and_ops_follow_the_package_rule(tmp_path, monkeypatch):
    monkeypatch.setattr(RS, "GROW_P", 0.0)
    m = merc_world(room=0x400, timer_s=1.0)
    ad = FakeDolphin(m, tmp_path)
    store_state(library_for(ad, m), tmp_path, 0x403, "HUNK", hooks=False)
    sim = Sim(m, speed=20.0)
    stats, rows, armed = run_play(ad, m, sim, lambda: sim.t > 4.0, tmp_path, monkeypatch)
    assert stats["instant_loads"] == 1 and armed[-1][:2] == (2, "not in the loaded state")
    applied = []                                                      # arm_round itself: the package only when missing
    monkeypatch.undo()
    monkeypatch.setattr(B, "apply_package", lambda ad_, skip=(): applied.append("package") or [])
    monkeypatch.setattr(B, "apply_round", lambda ad_, equip_now=False: applied.append(("gun", equip_now)) or [])
    st = {"hooks": "not in the loaded state", "rounds_hooked": 3, "rounds_hooked_seen": 3}
    B.arm_round(object(), st)
    assert applied == ["package", ("gun", True)] and st["hooks"] == "applied in round"
    applied.clear()
    B.arm_round(object(), {"hooks": "applied (in the loaded state)", "rounds_hooked": 3, "rounds_hooked_seen": 3})
    assert applied == [("gun", True)]                                 # in the state already: never stacked


# --- capture --------------------------------------------------------------------------------------------------------------
class MercRE4(FakeRE4):
    """The simulated title walked to a round in the room of the stage picked, with the package in RAM and a VI count."""

    def __init__(self, **kw):
        super().__init__(**kw)
        hook_package(self)
        self.round_at = None

    def round(self):
        super().round()
        self.put(PG + RM.G_ROOM, ">H", RM.STAGE_ROOMS[self.u8(TW + RM.TW_STAGE_CURSOR)])
        self.round_at = len(self.events)


def test_a_menu_started_round_is_captured_at_its_first_frame_before_any_press(tmp_path, monkeypatch):
    g = MercRE4(routine=6, step=8)                                   # Select Player
    ad = FakeDolphin(g, tmp_path)
    RM.request(id(ad), "Ada", 1)                                      # the DJ's pick: Ada on the Castle
    sim = Sim(g, speed=1.0, yield_s=0.002)
    lib = library_for(ad, g)
    try:
        stats, rows, armed = run_play(ad, g, sim, lambda: sim.t > 8.0 or bool(lib.entries()) and sim.t > 4.0,
                                      tmp_path, monkeypatch, send=g.send)
    finally:
        RM.REQUESTS.pop(id(ad), None)
    [e] = lib.entries()
    assert (e["room"], e["character"], e["stage"], e["hooks"]) == (0x402, "Ada", "Castle", True)
    assert 119.0 <= e["timer"] <= 120.0                               # the clock at the round's first look
    assert Path(e["file"]).read_bytes()[:6] == b"G4BE08" and stats["instant_captures"] == 1
    assert ad.events_at_save == g.round_at                            # nothing pressed in the round before the snapshot
    assert g.picks[-2:] == ["Ada", "Castle"] and stats["round_start_via"] == "menus"
    assert id(ad) not in RM.REQUESTS                                  # the DJ's round is up: it does not replay


def test_mercmodes_background_round_preparation_captures_before_it_stops(tmp_path, monkeypatch):
    g = MercRE4(routine=6, step=8)
    ad = FakeDolphin(g, tmp_path)
    RM.request(id(ad), "Wesker", 3)                                   # the DJ's pick: Wesker on the Waterworld
    sim = Sim(g, speed=1.0, yield_s=0.002)
    stats = {}
    try:
        B.play(ad, g.send, lambda: sim.t > 20.0, sleep=sim.sleep, m=g, clock=sim.clock, stats=stats, game=GAME,
               learn_dir=tmp_path / "learned", hooks=lambda: [], ram_prompt=False, prepare=True)
    finally:
        RM.REQUESTS.pop(id(ad), None)
    assert stats["prepared"] is True and stats["room"] == 0x404       # stopped on the round's first frame
    [e] = library_for(ad, g).entries()                               # ... after its state went into the library
    assert (e["room"], e["character"]) == (0x404, "Wesker") and ad.load_keys == 0


def test_no_capture_without_the_package_or_the_selects(tmp_path):
    m = merc_world(room=0x402, timer_s=120.0, hooks=False)
    ad = FakeDolphin(m, tmp_path)
    menus = SimpleNamespace(boot=object(), random=True, plan=lambda *a: None)
    inst = B.InstantRounds.for_run(ad, m, GAME, {}, menus)
    s = B.snapshot(m)
    assert "hooks" in inst.maybe_capture(s, {"player": 1, "stage": 1})
    hook_package(m)
    assert "character" in inst.maybe_capture(s, {})
    assert "not this room" in inst.maybe_capture(s, {"player": 1, "stage": 0})
    m.put(B.MERC_TIMER, ">I", 10 * 30)
    assert "first frame" in inst.maybe_capture(B.snapshot(m), {"player": 1, "stage": 1})


def test_instant_rounds_only_where_they_can_work(tmp_path):
    m = merc_world()
    menus = SimpleNamespace(boot=object(), random=True)
    stats = {}
    assert B.InstantRounds.for_run(None, m, GAME, stats, menus) is None and "no session adapter" in stats["instant_rounds"]
    win = FakeDolphin(m, tmp_path)
    win.supported = win.supported | {"local_window"}
    assert B.InstantRounds.for_run(win, m, GAME, stats, menus) is None and "Linux node" in stats["instant_rounds"]
    ad = FakeDolphin(m, tmp_path)
    assert B.InstantRounds.for_run(ad, m, GAME, stats, menus, prepare=True) is not None   # a prepare walk captures
    off = {"game_id": GID, "launch": {"mercmode": {"instant_rounds": False}}}
    assert B.InstantRounds.for_run(ad, m, off, stats, menus) is None and "turned" in stats["instant_rounds"]
    rpcs3 = SimpleNamespace(name="rpcs3", supported={"save_state", "load_state"})
    assert "only Dolphin" in RS.supported(rpcs3)
    _poke(m, 0x80000000, b"GZLE01")
    assert B.InstantRounds.for_run(ad, m, GAME, stats, menus) is None and "G4BE08" in stats["instant_rounds"]
    _poke(m, 0x80000000, b"G4BE08")
    assert B.InstantRounds.for_run(ad, m, GAME, stats, menus) is not None and stats["instant_rounds"].startswith("on:")


# --- the round transitions -------------------------------------------------------------------------------------------------
class FirstFrames(FakeRE4):
    """A stage's first frames run the room with the clock still at 0 (they read as results); the clock is set a
    moment later (the test's sleep). A on the results screen starts the next round; presses in a round are the
    bot's (fire, take) and leave the menus alone."""

    def press(self, key):
        if not RM.title_running(self) and struct.unpack(">I", self.rd(B.MERC_TIMER, 4))[0] > 0:
            return                                                    # a round is running: not a menu press
        super().press(key)

    def round(self):
        super().round()
        self.put(B.MERC_TIMER, ">I", 0)
        self.started = getattr(self, "started", 0) + 1


def test_a_round_that_began_on_a_results_reading_never_ends_the_run_as_hung_at_its_results(tmp_path, monkeypatch):
    # 2026-10-26, ten RE4 MercMode runs: the menus' "nothing moved in RAM" clock ran on through the round; a round that
    # began on a frame reading as results and ended on the results screen showed no change, so its length counted as
    # "nothing moved in RAM for 154 s on results" and the run ended hung (the 5th round of every turn lost)
    monkeypatch.setattr(MB, "MENU_STUCK_S", 2.5)                      # rounds longer than this used to end the run
    g = FirstFrames(routine=6, step=8)
    sim = Sim(g, speed=3.0)
    clock_set = {"done": 0}
    base_sleep = sim.sleep

    def sleep(dt):
        base_sleep(dt)
        if getattr(g, "started", 0) > clock_set["done"] and not RM.title_running(g):
            clock_set["first"] = clock_set.get("first") or sim.t
            if sim.t - clock_set["first"] >= 0.2:                     # the first frames end: the clock runs (4 s)
                g.put(B.MERC_TIMER, ">I", 12 * 30)
                clock_set["done"], clock_set["first"] = g.started, None
    stats = {}
    B.play(None, g.send, lambda: sim.t > 24.0, sleep=sleep, m=g, clock=sim.clock, stats=stats, game=CLASSIC,
           learn_dir=tmp_path / "learned", hooks=lambda: [], ram_prompt=False)
    assert not stats.get("hung"), stats.get("wandered")
    assert stats["rounds"] >= 3 and g.started >= 3                    # results -> next round, again and again


def test_the_menu_watch_starts_again_after_a_round():
    class Menus:
        @staticmethod
        def wandered(scr):
            return None

        @staticmethod
        def step(scr):
            return "a"
    now = [0.0]
    boot = MB.Boot(Menus, None, lambda rows: None, sleep=lambda s: None, clock=lambda: now[0], stats={})
    results = {"where": "results", "cursor": None, "target": None}
    assert boot.tick(0.0, scr={"where": "loading"}) is None
    assert boot.tick(1.0, scr=results) is None                        # a stage's first frames, read as results
    stale = MB.Boot(Menus, None, lambda rows: None, sleep=lambda s: None, clock=lambda: now[0], stats={})
    stale.tick(1.0, scr=results)
    now[0] = 200.0
    assert "nothing moved" in stale.tick(200.0, scr=results)          # what a round looked like to the menus before
    boot.round_played()                                               # play(): the round started
    now[0] = 200.0
    assert boot.tick(200.0, scr=results) is None and boot.loading_since is None
    assert boot.nav.last_sig == MB.Navigator.sig(results)


def _continue_world():
    m = merc_world(room=0x400, timer_s=60.0)
    return m


def test_a_continue_never_makes_a_phantom_round_or_boundary(tmp_path):
    # 2026-10-26 16:51:21-32: Continue restored Leon's health on the death screen (a "retry"), then the reload's first
    # frames read as results: a phantom round of 11 s and 0 m was reported to MercMode
    m = _continue_world()
    sim = Sim(m, speed=0.0)
    script = [(1.0, lambda: m.put(PG + B.G_HP, ">h", 0)),                     # Leon dies, 60 s on the clock
              (3.0, lambda: m.put(PG + B.G_HP, ">h", 1200)),                  # Continue: health back, the same clock
              (5.0, lambda: m.put(B.MERC_TIMER, ">I", 0)),                    # the reload's first frames: 0
              (6.0, lambda: m.put(B.MERC_TIMER, ">I", 120 * 30)),             # the stage again, its clock set
              (8.0, lambda: setattr(sim, "speed", 60.0))]                     # ... and run down to the results
    base = sim.sleep

    def sleep(dt):
        base(dt)
        while script and sim.t >= script[0][0]:
            script.pop(0)[1]()
    rows, stats = [], {}
    B.play(None, lambda r: None, lambda: sim.t > 14.0, sleep=sleep, m=m, clock=sim.clock, stats=stats,
           learn_dir=tmp_path / "learned", hooks=lambda: [], ram_prompt=False,
           round_boundary=lambda body, live: rows.append(body) or True)
    assert [r["witness"]["screen"] for r in rows] == ["dead", "results"]       # two real ends, nothing else
    assert stats["rounds"] == 2


def test_a_clock_jumping_to_zero_is_not_a_round_end():
    m = merc_world(room=0x400, timer_s=90.0)
    now, rows = [0.0], []

    def sleep(dt):
        now[0] += dt
        if now[0] > 0.5:
            m.put(B.MERC_TIMER, ">I", 0)                                       # 90 s -> 0 between two looks
    stats = {}
    B.play(None, lambda r: None, lambda: now[0] > 3.0, sleep=sleep, m=m, clock=lambda: now[0], stats=stats,
           hooks=lambda: [], ram_prompt=False, round_boundary=lambda body, live: rows.append(body) or True)
    assert rows == [] and "not a round's end" in stats["terminal_refused"]


# --- the menus' plan and the DJ's request ----------------------------------------------------------------------------------
def test_a_plan_steers_the_next_selects_and_a_request_is_spent_when_its_round_starts():
    sel = RM.RandomSelections(rng=random.Random(1), key="k-plan")
    RM.REQUESTS.pop("k-plan", None)
    g = FakeRE4(routine=6, step=8)
    sel.plan_next(3, 2)
    assert sel.screen(g)["target"] == 3                                        # HUNK
    g.tw(6, 12)
    assert sel.screen(g)["target"] == 2                                        # the Base
    sel.round_up()
    assert sel.planned is None and sel.previous_player == 3 and sel.previous_stage == 2
    RM.request("k-plan", "Wesker", 0)
    sel.plan_next(1, 1)                                                        # the DJ's pick comes first
    g.tw(6, 8)
    assert sel.screen(g)["target"] == 4
    sel.round_up()
    assert "k-plan" not in RM.REQUESTS                                         # spent: later rounds are random again
    sel.round_up(player=2, stage=3)                                            # a round from a save state names its own
    assert (sel.previous_player, sel.previous_stage) == (2, 3)


# --- round_gap_s -----------------------------------------------------------------------------------------------------------
def test_round_gap_is_the_time_from_one_rounds_end_to_the_next_rounds_first_frame():
    stats = {}
    assert round_map.gap_start(stats, 10.0, "start") is None and stats["round_start_via"] == "start"
    round_map.gap_end(stats, 100.0)
    assert round_map.gap_start(stats, 102.4, "state") == 2.4 and stats["round_gap_s"] == 2.4
    round_map.gap_end(stats, 200.0)
    assert round_map.gap_start(stats, 221.0, "menus") == 21.0 and stats["round_gaps"] == "2.4 state, 21 menus"
    round_map.gap_end(stats, 300.0)
    assert round_map.gap_start(stats, 300.0 + round_map.GAP_MAX_S + 1, "menus") is None   # a parked game, not a gap
    for i in range(20):
        round_map.gap_end(stats, i * 10.0)
        round_map.gap_start(stats, i * 10.0 + 1, "state")
    assert len(stats["round_gaps"].split(", ")) == round_map.GAPS_KEPT


def test_re5_rounds_carry_their_gap_from_the_last_rounds_end():
    from gbox.mercs.titles import re5_ps3 as R
    from tests.test_re5_mercs import world as re5_world
    stats = {}
    first = R.Bot(clock=lambda: 10.0, stats=stats)
    first.observe_round(R.snapshot(re5_world(timer=100.0)), "playing", 10.0)
    assert stats["round_gap_s"] is None
    first.observe_round(R.snapshot(re5_world(timer=0.0)), "results", 100.0)
    second = R.Bot(clock=lambda: 130.0, stats=stats)                           # the engine's next round: a new brain
    second.observe_round(R.snapshot(re5_world(timer=120.0)), "playing", 130.0)
    assert stats["round_gap_s"] == 30.0 and stats["round_start_via"] == "menus"


# --- RE5: a shorter menu path ----------------------------------------------------------------------------------------------
def test_re5_keeps_the_mode_between_rounds_while_the_balance_stays_exact(tmp_path):
    from gbox.mercs.titles import re5_ps3 as R
    c = Coverage(tmp_path / "cov.json", R.MODE_ROSTERS, range(8), random.Random(5))
    modes = []
    for _ in range(72):
        pick = c.choose()
        modes.append(pick["mode"])
        c.started(pick["mode"], pick["character"], pick["stage"])
    switches = sum(a != b for a, b in zip(modes, modes[1:]))
    assert switches <= 9                                                       # in blocks (was ~56% of the gaps)
    per_pair = {}
    for key, n in c.counts.items():
        mode, who, _ = key.split("/")
        per_pair[(mode, who)] = per_pair.get((mode, who), 0) + n
    assert max(per_pair.values()) - min(per_pair.values()) <= 1                # every character as often as the rest


def test_re5_cursor_steps_settle_faster_but_screens_and_confirms_keep_their_waits():
    from gbox.mercs.titles import re5_ps3 as R
    sent, now = [], [0.0]
    nav = MB.Navigator(sent.append, R.step, sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0],
                       cursor=R.NAV_CURSOR)
    scr = {"where": "select_player", "cursor": 0, "target": 3}
    assert nav.tick(scr) is None                                               # a new screen: STABLE_S as always
    now[0] += 0.3
    assert nav.tick(scr) is None
    now[0] += 0.21
    assert nav.tick(scr) == "dright"
    moved = dict(scr, cursor=1)
    now[0] += 0.05
    assert nav.tick(moved) is None
    now[0] += 0.31                                                             # a cursor move settles in 0.3 s
    assert nav.tick(moved) == "dright"
    now[0] += 0.65                                                             # not taken: again after 0.6 s
    assert nav.tick(moved) == "dright"
    at = dict(scr, cursor=3)
    now[0] += 0.35
    assert nav.tick(at) is None                                                # the cursor just arrived: settling
    now[0] += 0.31
    assert nav.tick(at) == "cross"
    now[0] += 0.7
    assert nav.tick(at) is None                                                # a confirm keeps RETRY_S (1.2 s)
    assert nav.poll_s(at, MB.POLL_S) == 0.1 and nav.poll_s({"where": "loading"}, MB.POLL_S) == MB.POLL_S
    plain = MB.Navigator(sent.append, R.step, sleep=lambda s: None, clock=lambda: now[0])
    assert plain.poll_s(at, MB.POLL_S) == MB.POLL_S                            # titles that did not opt in: unchanged
    blind = MB.Navigator(sent.append, lambda scr: "dleft", sleep=lambda s: now.__setitem__(0, now[0] + s),
                         clock=lambda: now[0], cursor=R.NAV_CURSOR)
    walk = {"where": "select_stage", "cursor": None, "target": None}            # no cursor in RAM: a counted walk
    assert blind.tick(walk) is None
    now[0] += 0.51
    assert blind.tick(walk) == "dleft"
    now[0] += 0.65
    assert blind.tick(walk) is None                                            # RAM can't show it moved: RETRY_S
    now[0] += 0.6
    assert blind.tick(walk) == "dleft"
