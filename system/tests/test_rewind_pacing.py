"""#1489: the checkpoint ring must not eat the frame rate (PSO on Flycast dropped to 2 fps with a 27 MB save every 2 s).
The ring measures each save and stretches its interval to stay within a frame-rate budget; Flycast gets a 20 s floor."""
import threading
from pathlib import Path

from gbox import adapters, rewind
from gbox.config import HOST_OS, Config, EmulatorConfig, RewindConfig


class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def tick(self, dt: float) -> float:
        self.t += dt
        return self.t


class SlowSaver:
    """Saves like RetroArch, and each save costs `cost` seconds on the injected timer."""
    name = "slowarch"
    supported = {"save_state", "load_state"}
    checkpoint_state = "path"

    def __init__(self, states: Path, timer: Clock, cost: float):
        self.states, self.timer, self.cost, self.saves = states, timer, cost, 0
        states.mkdir(parents=True, exist_ok=True)
        self.slot_file = states / "game.state"
        self._state_lock = threading.RLock()

    def state_dir(self):
        return self.states

    def save_state(self, slot=None):
        self.timer.tick(self.cost)
        self.saves += 1
        self.slot_file.write_bytes(b"x" * 64)
        return {"slot": 0, "path": str(self.slot_file), "verified": True}

    def load_state(self, slot=None):
        return {"slot": 0}


def _ring(tmp_path, cost, **kw):
    clock, timer = Clock(), Clock(0.0)
    ad = SlowSaver(tmp_path / "states", timer, cost)
    ring = rewind.CheckpointRing(ad, tmp_path / "ring", clock=clock, sleep=lambda s: None, timer=timer, **kw)
    return clock, ad, ring


def test_slow_saves_stretch_the_interval_to_the_frame_budget(tmp_path):
    clock, ad, ring = _ring(tmp_path, cost=1.0, interval_s=2.0, max_duty=0.05)
    assert ring.maybe_take(clock.tick(2.0)) is not None and ad.saves == 1
    st = ring.status()
    assert st["last_save_s"] == 1.0 and st["effective_interval_s"] == 20.0     # 1 s save at a 5 % budget
    for _ in range(9):                                                          # 18 s later: still within the budget wait
        assert ring.maybe_take(clock.tick(2.0)) is None
    assert ad.saves == 1
    assert ring.maybe_take(clock.tick(2.0)) is not None and ad.saves == 2


def test_cheap_saves_keep_the_configured_interval(tmp_path):
    clock, ad, ring = _ring(tmp_path, cost=0.02, interval_s=2.0, max_duty=0.05)
    ring.maybe_take(clock.tick(2.0))
    assert ring.status()["effective_interval_s"] == 2.0
    assert ring.maybe_take(clock.tick(2.0)) is not None and ad.saves == 2


def test_pacing_is_capped_and_can_be_switched_off(tmp_path):
    clock, ad, ring = _ring(tmp_path / "a", cost=30.0, interval_s=2.0, max_duty=0.05)
    ring.maybe_take(clock.tick(2.0))
    assert ring.paced_interval() == rewind.CheckpointRing.MAX_WAIT_S
    clock, ad, ring = _ring(tmp_path / "b", cost=5.0, interval_s=2.0, max_duty=0)
    ring.maybe_take(clock.tick(2.0))
    assert ring.paced_interval() == 2.0


def test_flycast_sessions_get_a_long_checkpoint_floor_and_the_config_budget(tmp_path):
    cfg = Config(data_dir=tmp_path, runtime_dirs={HOST_OS: str(tmp_path / "rt")}, rewind=RewindConfig(max_duty=0.1))
    emu = EmulatorConfig(adapter="retroarch", executable="x", core="y")
    for platform in ("dreamcast", "naomi", "atomiswave"):
        fly = adapters.RetroArchAdapter(emu, config=cfg, platform=platform)
        st = rewind.start(f"s-{platform}", fly, cfg, {"_rom_path": "x.gdi"}, threads=False)
        assert st["rewind"] == "checkpoint" and st["interval_s"] >= adapters.FLYCAST_CHECKPOINT_MIN_S
        assert rewind.ACTIVE[f"s-{platform}"].ring.max_duty == 0.1
        rewind.stop(f"s-{platform}")
    gc = adapters.RetroArchAdapter(emu, config=cfg, platform="gamecube")      # other heavy cores keep the 2 s default
    assert rewind.start("s-gc", gc, cfg, threads=False)["interval_s"] == 2.0
    rewind.stop("s-gc")
