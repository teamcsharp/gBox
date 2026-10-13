"""#1489 live check: real RetroArch + Flycast, real save states, the checkpoint ring's frame-rate budget.

Opt-in (it boots an emulator for ~45 s): set GBOX_FLYCAST_LIVE_ROM to a Dreamcast disc (CHD/GDI) and, optionally,
GBOX_FLYCAST_LIVE_RUNTIME to the worker runtime whose cores and BIOS are borrowed (default: the canonical Linux
runtime). Everything the emulator writes (states, saves, NVRAM, logs, the ring) goes to pytest's tmp_path, so the
worker's real states and any running session are untouched.
"""
import os
import shutil
import time
from pathlib import Path

import pytest

from gbox import adapters, rewind
from gbox.config import HOST_OS, Config

ROM = os.environ.get("GBOX_FLYCAST_LIVE_ROM", "")
REAL = Path(os.environ.get("GBOX_FLYCAST_LIVE_RUNTIME",
                           "/home/ehm_eckx/gBox/system/gbox-data/runtime-linux-aarch64"))
WRITABLE = ("nvmem", "flash", "vmu", ".cfg", ".opt")

pytestmark = pytest.mark.skipif(
    HOST_OS != "linux" or not ROM or not Path(ROM).is_file() or not (REAL / "cores").is_dir()
    or not shutil.which("Xvfb"),
    reason="live Flycast check: set GBOX_FLYCAST_LIVE_ROM (Linux worker with Xvfb and a provisioned runtime)")


def _scratch_runtime(data_dir: Path) -> Path:
    """A runtime dir that reads the real cores/BIOS but writes only to data_dir."""
    rt = data_dir / REAL.name
    rt.mkdir(parents=True)
    for name in ("cores", "retroarch-bin", "cheats", "mint"):
        if (REAL / name).exists():
            (rt / name).symlink_to(REAL / name)
    if (REAL / "retroarch").exists():
        shutil.copytree(REAL / "retroarch", rt / "retroarch", symlinks=True)
    system = rt / "system"
    system.mkdir()
    for entry in (REAL / "system").iterdir():
        if entry.name != "dc":
            (system / entry.name).symlink_to(entry)
            continue
        (system / "dc").mkdir()
        for f in entry.iterdir():                       # Flycast writes its NVRAM/flash next to the BIOS: copy those
            if f.is_file() and any(w in f.name.lower() for w in WRITABLE):
                shutil.copy2(f, system / "dc" / f.name)
            else:
                (system / "dc" / f.name).symlink_to(f)
    return rt


def test_flycast_checkpoints_stay_within_the_frame_rate_budget(tmp_path):
    cfg = Config(data_dir=tmp_path / "gbox-data")
    _scratch_runtime(cfg.data_dir)
    assert str(cfg.runtime).startswith(str(tmp_path))
    game = {"game_id": "live-flycast", "title": Path(ROM).stem, "platform": "dreamcast", "core": "flycast",
            "_rom_path": ROM}
    ad = adapters.for_game(game, cfg)
    assert isinstance(ad, adapters.RetroArchAdapter) and not ad.rewind_on       # Flycast: no native rewind
    assert ad.checkpoint_min_interval_s == adapters.FLYCAST_CHECKPOINT_MIN_S == 20.0
    ad.launch_game(ROM)
    try:
        time.sleep(30)                                  # boot to the title screen
        assert ad.query_runtime().get("state") == "PLAYING"
        interval = max(2.0, ad.checkpoint_min_interval_s)   # what rewind.start() gives a Flycast session
        ring = rewind.CheckpointRing(ad, tmp_path / "ring", interval, depth=5, max_mb=512, content=ROM,
                                     max_duty=0.05)
        costs = []
        for _ in range(3):
            ring._take()
            costs.append(ring.last_cost)
            time.sleep(1)
        status = ring.status()
        print(f"\nFlycast checkpoint saves: {[round(c, 3) for c in costs]} s, ring {status}")
        print(f"old 2 s pacing would stall {max(costs) / 2:.0%} of play; now {max(costs) / status['effective_interval_s']:.1%}")
        assert status["error"] is None and status["taken"] == 3 and status["bytes"] > 0
        assert status["effective_interval_s"] >= 20.0
        assert max(costs) / status["effective_interval_s"] <= 0.05      # saving stays within 5 % of play time
        assert ad.query_runtime().get("state") == "PLAYING"            # the game kept running through the saves
    finally:
        ad.stop_game()
