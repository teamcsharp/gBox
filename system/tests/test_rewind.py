"""Select+L2 rewind / Select+R2 fast-forward in every game (#454, #1382): the checkpoint ring, the chord detector, the
fast-forward ramp and the capability reporting, exercised with fake adapters (no emulator, no pad)."""
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import adapters, rewind, tools
from gbox.config import HOST_OS, Config, EmulatorConfig, RewindConfig
from gbox.registry import Unsupported


class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def tick(self, dt: float) -> float:
        self.t += dt
        return self.t


class PathEmulator:
    """Saves like RetroArch: the state goes to the current slot file and save_state reports the verified path."""
    name = "fakearch"
    supported = {"save_state", "load_state", "fast_forward"}
    checkpoint_state = "path"

    def __init__(self, states: Path, state_bytes: int = 0):
        self.states, self.frame, self.saves, self.loads, self.ff = states, 0, [], [], []
        self.states.mkdir(parents=True, exist_ok=True)
        self.slot_file, self.pad, self.block = states / "game.state", state_bytes, None
        self._state_lock = threading.RLock()

    def state_dir(self):
        return self.states

    def save_state(self, slot=None):
        if self.block is not None:
            self.block.wait()
        self.slot_file.write_bytes(f"frame={self.frame}".encode().ljust(self.pad, b"."))
        self.saves.append(self.frame)
        return {"slot": 0, "path": str(self.slot_file), "verified": True}

    def load_state(self, slot=None):
        self.frame = int(self.slot_file.read_bytes().rstrip(b".").split(b"=")[1])
        self.loads.append(self.frame)
        return {"slot": 0}

    def fast_forward(self, on=None):
        self.ff.append(on)
        return {"on": on}


class DirEmulator:
    """Saves like Dolphin: a hotkey writes a private slot file under its state folder a little later."""
    name = "fakedolphin"
    supported = {"save_state", "load_state"}
    checkpoint_state, state_glob = "dir", "*.s08"

    def __init__(self, folder: Path):
        self.folder, self.frame, self.loads = folder, 0, []
        self.folder.mkdir(parents=True, exist_ok=True)
        for name, body in (("OTHER.s08", b"another game, long ago"), ("GAME.s01", b"the operator's slot 1")):
            (folder / name).write_bytes(body)
            os.utime(folder / name, (time.time() - 3600, time.time() - 3600))

    def state_dir(self):
        return self.folder

    def checkpoint_save(self):
        (self.folder / "GAME.s08").write_bytes(f"dolphin frame={self.frame}".encode())
        return {"slot": 8}

    def checkpoint_load(self):
        self.frame = int((self.folder / "GAME.s08").read_bytes().split(b"=")[1])
        self.loads.append(self.frame)
        return {"slot": 8}

    def save_state(self):
        raise AssertionError("the ring must use the private slot, not the operator's")

    load_state = save_state


def ring_for(tmp_path, ad, clock, **kw):
    kw.setdefault("sleep", lambda s: None)
    return rewind.CheckpointRing(ad, tmp_path / "ring", clock=clock, **kw)


@pytest.fixture(autouse=True)
def _no_leftover_sessions():
    yield
    for sid in list(rewind.ACTIVE):
        rewind.stop(sid)


# --- the ring ---------------------------------------------------------------------------------------------------

def test_ring_takes_a_checkpoint_each_interval(tmp_path):
    clock, ad = Clock(), PathEmulator(tmp_path / "states")
    ring = ring_for(tmp_path, ad, clock, interval_s=2.0)
    ad.frame = 7
    assert ring.maybe_take(clock.tick(1.0)) is None and ad.saves == []
    first = ring.maybe_take(clock.tick(1.0))
    assert first["seq"] == 1 and ad.saves == [7] and Path(first["file"]).read_bytes() == b"frame=7"
    ad.frame = 9
    assert ring.maybe_take(clock.tick(1.0)) is None
    assert ring.maybe_take(clock.tick(1.0))["seq"] == 2 and ad.saves == [7, 9]
    assert ring.status()["entries"] == 2 and ring.status()["error"] is None


def test_ring_depth_bound_keeps_the_newest(tmp_path):
    clock, ad = Clock(), PathEmulator(tmp_path / "states")
    ring = ring_for(tmp_path, ad, clock, interval_s=1.0, depth=3)
    for ad.frame in range(1, 6):
        assert ring.maybe_take(clock.tick(1.0)) is not None
    assert [e["seq"] for e in ring.entries] == [3, 4, 5]
    assert sorted(p.name for p in (tmp_path / "ring").glob("ckpt-*.bin")) == ["ckpt-000003.bin", "ckpt-000004.bin", "ckpt-000005.bin"]


def test_ring_disk_cap_drops_the_oldest(tmp_path):
    clock, ad = Clock(), PathEmulator(tmp_path / "states", state_bytes=600 * 1024)
    ring = ring_for(tmp_path, ad, clock, interval_s=1.0, depth=60, max_mb=1)
    for ad.frame in range(1, 4):
        ring.maybe_take(clock.tick(1.0))
    assert [e["seq"] for e in ring.entries] == [3] and ring.size() <= 1 * 2**20


def test_step_back_walks_newest_to_oldest_and_release_drops_the_undone_future(tmp_path):
    clock, ad = Clock(), PathEmulator(tmp_path / "states")
    ring = ring_for(tmp_path, ad, clock, interval_s=1.0)
    for ad.frame in (10, 20, 30):
        ring.maybe_take(clock.tick(1.0))
    ad.frame = 35
    assert ring.step_back()["seq"] == 3 and ad.frame == 30         # the first press: the newest checkpoint
    assert ring.maybe_take(clock.tick(5.0)) is None                 # frozen while the chord is held
    assert ring.step_back()["seq"] == 2 and ad.frame == 20
    assert ring.step_back()["seq"] == 1 and ad.frame == 10
    assert ring.step_back() is None and ad.frame == 10              # nothing older
    assert ad.loads == [30, 20, 10]
    assert ring.release() == 2                                      # 20 and 30 are an undone future
    assert [e["seq"] for e in ring.entries] == [1] and ring.cursor is None
    assert sorted(p.name for p in (tmp_path / "ring").glob("ckpt-*.bin")) == ["ckpt-000001.bin"]
    assert ring.maybe_take(clock.tick(0.5)) is None                 # a full interval after the release
    assert ring.maybe_take(clock.tick(0.5))["seq"] == 4


def test_ring_gives_the_operator_their_slot_file_back(tmp_path):
    clock = Clock()
    ad = PathEmulator(tmp_path / "states")
    ad.slot_file.write_bytes(b"the operator's own save")
    (tmp_path / "states" / "game.state3").write_bytes(b"slot three")
    ring = ring_for(tmp_path, ad, clock, interval_s=1.0, content=tmp_path / "roms" / "game.gdi")
    ad.frame = 4
    entry = ring.maybe_take(clock.tick(1.0))
    assert Path(entry["file"]).read_bytes() == b"frame=4"
    assert ad.slot_file.read_bytes() == b"the operator's own save"          # restored after the ring's save
    assert not any((tmp_path / "ring" / "stash").glob("*"))                 # the copies made before the first save are gone
    ad.frame = 8
    ring.maybe_take(clock.tick(1.0))
    assert ring.step_back()["seq"] == 2 and ad.loads == [8]                 # the load saw the checkpoint...
    assert ad.slot_file.read_bytes() == b"the operator's own save"          # ...and the slot is the operator's again
    ring.release()
    ad.slot_file.write_bytes(b"a newer manual save")                        # the operator saves again
    ad.frame = 12
    ring.maybe_take(clock.tick(2.0))
    assert ad.slot_file.read_bytes() == b"a newer manual save"
    ring.close()
    assert not (tmp_path / "ring").exists() and ad.slot_file.read_bytes() == b"a newer manual save"
    assert (tmp_path / "states" / "game.state3").read_bytes() == b"slot three"


def test_ring_never_saves_while_a_save_or_load_is_in_flight(tmp_path):
    clock, ad = Clock(), PathEmulator(tmp_path / "states")
    ring = ring_for(tmp_path, ad, clock, interval_s=1.0)
    ad.block = threading.Event()
    t = threading.Thread(target=ring.maybe_take, args=(clock.tick(1.0),), daemon=True)
    t.start()
    for _ in range(200):
        if ring.busy.locked():
            break
        time.sleep(0.01)
    assert ring.busy.locked()
    assert ring.maybe_take(clock.tick(10.0)) is None and ad.saves == []     # skipped, not queued
    ad.block.set()
    t.join(5)
    assert len(ring.entries) == 1 and ad.saves == [0]
    with ring.guard():                                                      # an operator save / load in progress
        assert ring.maybe_take(clock.tick(10.0)) is None
    assert ring.maybe_take(clock.t) is not None


def test_ring_backs_off_after_a_failed_save(tmp_path):
    clock = Clock()
    ad = PathEmulator(tmp_path / "states")
    ad.save_state = lambda slot=None: {"slot": 0}                           # no path reported: nothing to copy
    ring = ring_for(tmp_path, ad, clock, interval_s=1.0)
    assert ring.maybe_take(clock.tick(1.0)) is None and "did not report" in ring.status()["error"]
    assert ring.maybe_take(clock.tick(1.0)) is None and ring.failures == 1   # waits longer before trying again
    assert ring.maybe_take(clock.tick(1.0)) is None and ring.failures == 2


def test_dir_adapters_use_their_private_slot(tmp_path):
    ad = DirEmulator(tmp_path / "StateSaves")
    ring = rewind.CheckpointRing(ad, tmp_path / "ring", interval_s=1.0, settle_s=5.0, sleep=lambda s: None)
    ad.frame = 3
    entry = ring.maybe_take(ring.clock() + 1.0)
    assert entry is not None, ring.error
    assert ring.origin == tmp_path / "StateSaves" / "GAME.s08"
    assert Path(entry["file"]).read_bytes() == b"dolphin frame=3"
    ad.frame = 5
    assert ring.step_back() is not None and ad.loads == [3]
    assert (tmp_path / "StateSaves" / "GAME.s01").read_bytes() == b"the operator's slot 1"
    assert (tmp_path / "StateSaves" / "OTHER.s08").read_bytes() == b"another game, long ago"


# --- the chord --------------------------------------------------------------------------------------------------

def test_chord_edge_then_hold_repeats_then_release():
    d = rewind.ChordDetector(repeat_s=0.5)
    assert d.update(False, True, False, 0.0) == []                          # L2 alone: the game's own trigger
    assert d.update(True, True, False, 0.0) == ["rewind_step"]              # Select joins: one step on the edge
    assert d.update(True, True, False, 0.2) == []
    assert d.update(True, True, False, 0.5) == ["rewind_step"]              # held: one more every repeat
    assert d.update(True, True, False, 0.7) == []
    assert d.update(True, True, False, 1.0) == ["rewind_step"]
    assert d.update(True, False, False, 1.1) == ["rewind_end"]
    assert d.update(True, False, False, 1.2) == []                          # Select alone: nothing
    assert d.update(True, True, False, 1.3) == ["rewind_step"]              # a new press steps again at once


def test_chord_fast_forward_and_precedence():
    d = rewind.ChordDetector()
    assert d.update(True, False, True, 0.0) == ["ff_start"] and d.ff_held
    assert d.update(True, False, True, 0.5) == [] and d.ff_held
    assert d.update(False, False, True, 0.6) == ["ff_end"] and not d.ff_held
    assert d.update(True, True, True, 1.0) == ["rewind_step"] and not d.ff_held   # both triggers: rewind wins
    assert d.update(True, False, True, 1.1) == ["rewind_end", "ff_start"]
    assert d.update(False, False, False, 1.2) == ["ff_end"]


def test_chord_from_streamed_pad_events():
    d = rewind.ChordDetector(repeat_s=0.5)
    assert d.feed([{"key": "a", "down": True}, {"key": "select", "down": True}], 0.0) == []
    assert d.feed([{"key": "L2", "down": True}], 0.1) == ["rewind_step"]
    assert d.feed([], 0.6) == ["rewind_step"]
    assert d.feed([{"key": "l2", "down": False}, {"rpc": 1}], 0.7) == ["rewind_end"]
    assert d.feed([{"key": "r2"}], 0.8) == ["ff_start"]                     # down defaults to True, like send_input


def test_fast_forward_ramp_is_2x_then_4x_then_16x():
    ramp = rewind.FastForwardRamp()
    on = [ramp.tick(True, k / 60) for k in range(240)]
    assert sum(on[:90]) == 6                                                # 2x: one fast tick in fifteen
    assert sum(on[90:210]) == 24                                            # 4x: one in five
    assert all(on[210:])                                                    # 16x: every tick
    assert ramp.tick(False, 5.0) is False and ramp.t0 is None               # released: reset
    assert ramp.tick(True, 6.0) is False and ramp.speed(0.0) == 2.0         # a new hold starts at 2x again


# --- a session: chord -> ring / ramp ----------------------------------------------------------------------------

def test_session_poll_steps_the_ring_and_ramps_fast_forward(tmp_path):
    clock, ad = Clock(), PathEmulator(tmp_path / "states")
    ring = ring_for(tmp_path, ad, clock, interval_s=1.0)
    sr = rewind.SessionRewind("w-s", ad, "checkpoint", ring, repeat_s=0.5, clock=clock)
    for ad.frame in (10, 20):
        ring.maybe_take(clock.tick(1.0))
    ad.frame = 25
    assert sr.poll(clock.tick(0.1), (True, True, False)) == ["rewind_step"] and ad.frame == 20
    assert sr.poll(clock.tick(0.1), (True, True, False)) == [] and ad.frame == 20
    assert sr.poll(clock.tick(0.5), (True, True, False)) == ["rewind_step"] and ad.frame == 10
    assert sr.poll(clock.tick(0.1), (False, False, False)) == ["rewind_end"] and ring.cursor is None
    assert [e["seq"] for e in ring.entries] == [1] and sr.steps == 2
    for _ in range(14):
        sr.poll(clock.tick(1 / 60), (True, False, True))
    assert ad.ff == []                                                      # 2x: the first fast tick is the fifteenth
    sr.poll(clock.tick(1 / 60), (True, False, True))
    assert ad.ff == [True]
    sr.poll(clock.tick(1 / 60), (True, False, True))
    assert ad.ff == [True, False]
    sr.poll(clock.tick(1 / 60), (False, False, False))
    assert ad.ff[-1] is False and not sr.ff_on
    assert sr.status()["rewind"] == "checkpoint" and sr.status()["last_step_age_s"] >= 0


def test_session_feed_merges_streamed_events_into_the_sample(tmp_path):
    clock, ad = Clock(), PathEmulator(tmp_path / "states")
    ring = ring_for(tmp_path, ad, clock, interval_s=1.0)
    sr = rewind.SessionRewind("w-s", ad, "checkpoint", ring, clock=clock)
    ad.frame = 3
    ring.maybe_take(clock.tick(1.0))
    ad.frame = 4
    sr.feed([{"key": "select", "down": True}, {"key": "l2", "down": True}])
    assert sr.poll(clock.tick(0.1)) == ["rewind_step"] and ad.frame == 3
    sr.feed([{"key": "l2", "down": False}])
    assert sr.poll(clock.tick(0.1)) == ["rewind_end"]


def test_native_rewind_the_pad_cannot_reach_is_driven_by_the_worker(tmp_path, monkeypatch):
    """Streamed PSX / N64 sessions: rewind is on but the triggers belong to the game (no RetroArch hotkey)."""
    calls = []
    ad = SimpleNamespace(name="retroarch", rewind_on=True, trigger_hotkeys=False, supported={"rewind", "fast_forward"},
                         rewind=lambda seconds: calls.append(seconds), fast_forward=lambda on=None: calls.append(("ff", on)))
    monkeypatch.setattr(rewind, "HOST_OS", "linux")
    st = rewind.start("s-psx", ad, Config(data_dir=tmp_path), threads=False)
    assert st["rewind"] == "native" and st["native_steps"] and st["fast_forward_ramp"]
    sr = rewind.ACTIVE["s-psx"]
    sr.poll(1.0, (True, True, False))
    assert calls == [0.6] and sr.steps == 1
    free = SimpleNamespace(name="retroarch", rewind_on=True, trigger_hotkeys=True, supported={"rewind", "fast_forward"})
    st = rewind.start("s-psp", free, Config(data_dir=tmp_path), threads=False)
    assert st["rewind"] == "native" and st['native_steps'] and st["fast_forward_ramp"]  # one worker owns all aliases


def test_toggle_only_fast_forward_still_ramps(tmp_path):
    toggles = []
    ad = SimpleNamespace(name="old", supported={"fast_forward"}, fast_forward=lambda: toggles.append("t"))
    sr = rewind.SessionRewind("w-s", ad, "native")
    sr._set_ff(True)
    sr._set_ff(True)
    sr._set_ff(False)
    assert toggles == ["t", "t"] and not sr.ff_on


# --- capability reporting ---------------------------------------------------------------------------------------

def test_capabilities_say_native_checkpoint_off_or_unsupported(tmp_path):
    cfg = Config(data_dir=tmp_path, rewind=RewindConfig(interval_s=1.5, depth=7))
    native = SimpleNamespace(name="retroarch", rewind_on=True, supported={"save_state", "load_state", "rewind", "fast_forward"})
    assert rewind.start("s-native", native, cfg, threads=False)["rewind"] == "native"
    assert rewind.capabilities("s-native", {"rewind": "supported"})["rewind"] == "native"

    ad = PathEmulator(tmp_path / "states")
    st = rewind.start("s-ckpt", ad, cfg, {"_rom_path": str(tmp_path / "game.gdi")}, threads=False)
    assert st["rewind"] == "checkpoint" and st["interval_s"] == 1.5 and st["depth"] == 7
    assert rewind.capabilities("s-ckpt", {"rewind": "unsupported", "pause": "supported"}) == {"rewind": "checkpoint", "pause": "supported"}
    assert rewind.ring_dir(cfg, "s-ckpt").is_dir()
    rewind.stop("s-ckpt")
    assert not rewind.ring_dir(cfg, "s-ckpt").exists() and rewind.mode("s-ckpt") is None

    off = rewind.start("s-off", PathEmulator(tmp_path / "s2"), cfg, enabled=False, threads=False)
    assert off["rewind"] == "off" and "switched off" in off["reason"]
    quiet = Config(data_dir=tmp_path, rewind={"checkpoints": False})
    assert rewind.start("s-off2", PathEmulator(tmp_path / "s3"), quiet, threads=False)["rewind"] == "off"
    assert rewind.start("s-off3", PathEmulator(tmp_path / "s4"), quiet, enabled=True, threads=False)["rewind"] == "checkpoint"

    xenia = SimpleNamespace(name="xenia", supported={"pause", "resume"})
    st = rewind.start("s-x", xenia, cfg, threads=False)
    assert st["rewind"] == "unsupported" and "no save state" in st["reason"]
    with pytest.raises(Unsupported, match="no save state"):
        rewind.step("s-x", 5)
    reboots = SimpleNamespace(name="rpcs3", supported={"save_state", "load_state"}, checkpoint_state=False,
                              checkpoint_reason="RPCS3 reloads the game")
    assert rewind.supports(reboots) == "RPCS3 reloads the game"
    blind = SimpleNamespace(name="mystery", supported={"save_state", "load_state"})
    assert "where its save state file is" in rewind.supports(blind)
    assert rewind.capabilities("never-launched", {"rewind": "supported"}) == {"rewind": "supported"}


def test_real_adapters_classify_as_documented(tmp_path):
    cfg = Config(data_dir=tmp_path, runtime_dirs={HOST_OS: str(tmp_path / "rt")})
    emu = EmulatorConfig(adapter="retroarch", executable="x", core="y")
    psp = adapters.RetroArchAdapter(emu, config=cfg, platform="psp")
    assert rewind.start("s-psp", psp, cfg, threads=False)["rewind"] == "native"
    flycast = adapters.RetroArchAdapter(emu, config=cfg, platform="dreamcast")          # NO_REWIND core (#1382's DOA2)
    assert rewind.start("s-dc", flycast, cfg, {"_rom_path": "x.gdi"}, threads=False)["rewind"] == "checkpoint"
    assert rewind.ACTIVE["s-dc"].ring.kind == "path" and flycast.state_dir() == tmp_path / "rt" / "states"
    assert rewind.start("s-gc", adapters.DolphinWinAdapter(cfg, "gamecube"), cfg, threads=False)["rewind"] == "checkpoint"
    assert rewind.ACTIVE["s-gc"].use_ramp and rewind.ACTIVE["s-gc"].ring.kind == "dir"
    ps3 = rewind.start("s-ps3", adapters.RPCS3Adapter(cfg), cfg, threads=False)
    assert ps3["rewind"] == "unsupported" and "RPCS3" in ps3["reason"]
    assert rewind.start("s-sw", adapters.YuzuAdapter(cfg), cfg, threads=False)["rewind"] == "unsupported"
    assert rewind.start("s-steam", adapters.SteamAdapter(), cfg, threads=False)["rewind"] == "unsupported"


def test_retroarch_fast_forward_tracks_on_off_over_its_toggle(tmp_path):
    cfg = Config(data_dir=tmp_path)
    ad = adapters.RetroArchAdapter(EmulatorConfig(adapter="retroarch", executable="x", core="y"), config=cfg, platform="dreamcast")
    sent = []
    ad.cmd = lambda text: sent.append(text)
    assert ad.fast_forward(on=True)["on"] is True and sent == ["FAST_FORWARD"]
    assert ad.fast_forward(on=True) == {"fast_forward": "on"} and sent == ["FAST_FORWARD"]      # already on: nothing sent
    assert ad.fast_forward()["on"] is False and sent == ["FAST_FORWARD"] * 2                  # a plain toggle still toggles
    assert ad.fast_forward(on=False) == {"fast_forward": "off"} and len(sent) == 2


def test_windows_dolphin_ring_hotkeys_and_speed_limit(monkeypatch, tmp_path):
    ad = adapters.DolphinWinAdapter(Config(data_dir=tmp_path), "gamecube")
    ad.proc = SimpleNamespace(pid=123)
    sent = []
    monkeypatch.setattr(adapters, "win_send_keys", lambda pid, events, **kw: sent.extend(events) or {"sent": len(events)})
    lane = ad.lane                                                          # gBox's Hotkeys.ini: F13 lane by default
    assert ad.checkpoint_save() == {"slot": 8} and [e["key"] for e in sent] == ["Control_L", "Shift_R", lane, lane, "Shift_R", "Control_L"]
    sent.clear()
    assert ad.checkpoint_load() == {"slot": 8} and sent == [{"key": "Control_L", "down": True}, {"key": lane, "down": True},
                                                             {"key": lane, "down": False}, {"key": "Control_L", "down": False}]
    sent.clear()
    assert ad.fast_forward(on=True) == {"fast_forward": "on"} and sent == [{"key": lane, "down": True}]
    assert ad.fast_forward(on=True) == {"fast_forward": "on"} and len(sent) == 1
    assert ad.fast_forward(on=False) == {"fast_forward": "off"} and sent[-1] == {"key": lane, "down": False}
    for key in ("F13", "F14", "F15", "Shift_R", "Control_R", "Control_L"):   # the keys the hotkeys need have scan codes
        assert adapters._SCAN[key][0]


def test_sweep_removes_rings_of_sessions_that_are_gone(tmp_path):
    cfg = Config(data_dir=tmp_path)
    stale = rewind.ring_dir(cfg, "old-worker-run")
    stale.mkdir(parents=True)
    (stale / "ckpt-000001.bin").write_bytes(b"x")
    rewind.start("s-new", PathEmulator(tmp_path / "states"), cfg, threads=False)
    assert not stale.exists() and rewind.ring_dir(cfg, "s-new").is_dir()


def test_xinput_reader_is_quiet_without_a_pad():
    pad = rewind.XInputPad()
    assert pad.ok == (HOST_OS == "windows")
    sample = pad.read()
    assert sample is None or (len(sample) == 5 and all(isinstance(v, bool) for v in sample))


# --- the worker: session_op and the session's end --------------------------------------------------------------

def test_session_op_rewinds_through_the_ring_and_guards_saves(monkeypatch, tmp_path):
    cfg = Config(data_dir=tmp_path)
    clock, ad = Clock(), PathEmulator(tmp_path / "states")
    ad.stop_game, ad.proc = lambda: {}, None
    sid = "w-ring"
    monkeypatch.setitem(tools.SESSIONS, sid, (ad, {"game_id": "g"}))
    monkeypatch.setattr(tools, "track_emulator", lambda *a, **k: None)
    rewind.start(sid, ad, cfg, {"_rom_path": str(tmp_path / "game.gdi")}, threads=False)
    ring = rewind.ACTIVE[sid].ring
    ring.clock, ring.sleep, ring.last_take = clock, (lambda s: None), clock()
    for ad.frame in (1, 2, 3):
        assert ring.maybe_take(clock.tick(2.0)) is not None
    ad.frame = 4
    ctx = SimpleNamespace(config=cfg, artifact=lambda *a, **k: None)
    out = tools.session_op(tools.SessionIn(session_id=sid, op="rewind", args={"seconds": 4}), ctx)
    assert out["result"]["kind"] == "checkpoint" and out["result"]["steps"] == 2 and ad.frame == 2
    assert [e["seq"] for e in ring.entries] == [1, 2]                      # the undone future is gone
    seen = []
    real_save = ad.save_state
    ad.save_state = lambda slot=None: seen.append(ring.busy.locked()) or real_save(slot)
    ad.frame = 22
    tools.session_op(tools.SessionIn(session_id=sid, op="save_state", args={}), ctx)
    assert seen == [True]                                                   # the operator's save held the ring's guard
    assert ad.slot_file.read_bytes() == b"frame=22"                         # ...and left their save in the slot
    ad.frame = 9
    assert ring.maybe_take(clock.tick(5.0)) is not None
    assert ad.slot_file.read_bytes() == b"frame=22"                         # the ring borrowed it and gave it back
    assert tools.session_op(tools.SessionIn(session_id=sid, op="stop_game"), ctx)["ended"] is True
    assert sid not in rewind.ACTIVE and not rewind.ring_dir(cfg, sid).exists()


def test_native_sessions_keep_the_emulators_own_rewind(monkeypatch, tmp_path):
    calls = []
    ad = SimpleNamespace(name="retroarch", rewind_on=True, supported={"rewind"}, rewind=lambda seconds=5.0: calls.append(seconds) or {"rewound_s": seconds})
    monkeypatch.setitem(tools.SESSIONS, "w-native", (ad, {}))
    rewind.start("w-native", ad, Config(data_dir=tmp_path), threads=False)
    ctx = SimpleNamespace(config=Config(data_dir=tmp_path))
    out = tools.session_op(tools.SessionIn(session_id="w-native", op="rewind", args={"seconds": 3}), ctx)
    assert out["result"] == {"rewound_s": 3} and calls == [3]
    assert rewind.capabilities("w-native", {"rewind": "supported"})["rewind"] == "native"
