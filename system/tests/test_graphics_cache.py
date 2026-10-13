"""#712: the GPU inventory behind the Graphics panel is cached (no nvidia-smi per read, never a console window), and
per-game graphics saves are type-exact, atomic and safe from concurrent writers."""
import json
import sys
import threading

import pytest

from gbox import graphics
from gbox.config import Config


def test_gpu_inventory_is_cached_for_a_minute_and_copies_are_independent(monkeypatch):
    calls, now = [], [10.0]
    monkeypatch.setattr(graphics, "_GPU_CACHE", None)
    monkeypatch.setattr(graphics, "_GPU_EXPIRES", 0.0)
    monkeypatch.setattr(graphics.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(graphics, "_read_gpu", lambda: calls.append(1) or {"name": "RTX", "vram_mb": 8192})
    first = graphics.gpu()
    first["name"] = "changed by a caller"
    assert graphics.gpu()["name"] == "RTX" and len(calls) == 1
    now[0] = 69.9
    graphics.gpu()
    assert len(calls) == 1
    now[0] = 70.0
    graphics.gpu()
    assert len(calls) == 2


def test_nvidia_smi_runs_without_a_console_window(monkeypatch):
    import subprocess
    seen = {}

    def run(argv, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(argv, 0, "NVIDIA GeForce RTX 3070, 8192\n", "")
    monkeypatch.setattr(subprocess, "run", run)
    assert graphics._read_gpu() == {"name": "NVIDIA GeForce RTX 3070", "vram_mb": 8192}
    assert seen["creationflags"] == (0x08000000 if sys.platform == "win32" else 0)


def test_save_rejects_lookalike_types(tmp_path):
    cfg = Config(data_dir=tmp_path)
    with pytest.raises(ValueError):
        graphics.save(cfg, "g", {"vsync": 1})            # 1 == True, but not a boolean
    with pytest.raises(ValueError):
        graphics.save(cfg, "g", {"res_scale": True})     # True == 1 is not a resolution
    assert graphics.save(cfg, "g", {"vsync": False, "res_scale": 200})["res_scale"] == 200


def test_concurrent_saves_keep_every_game_and_leave_valid_json(tmp_path):
    cfg = Config(data_dir=tmp_path)
    games = [f"game{i}" for i in range(16)]
    threads = [threading.Thread(target=graphics.save, args=(cfg, g, {"msaa": "off"})) for g in games]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    saved = json.loads(graphics._file(cfg).read_text())
    assert sorted(saved) == sorted(games)
    assert not graphics._file(cfg).with_suffix(".tmp").exists()
