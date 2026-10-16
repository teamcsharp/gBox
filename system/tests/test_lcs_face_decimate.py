"""The LCS pedestrian cast swap decimates high-poly donors (Dead or Alive 2, ~8k tris) into tiny
streamed pedestrian slots (native peds ~1.3k tris), a ~94% triangle cut that erases the face. The
swap now asks Blender to spare the head/face from the collapse (protect=("head","eye")), so the body
absorbs the reduction instead of the face. These tests pin the command plumbing that carries that
request through re4gc_enemies.decimate -> decimate_gltf.py without disturbing any other writer."""
from pathlib import Path

from gbox.re4gc_enemies import decimate


def _record(monkeypatch, tmp_path, captured):
    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        Path(cmd[cmd.index("--") + 2]).write_bytes(b"glb")
        return type("R", (), {"stdout": "", "stderr": ""})()
    monkeypatch.setattr("gbox.re4gc_enemies.subprocess.run", fake_run)


def test_decimate_passes_protect_arg(monkeypatch, tmp_path):
    captured = []
    _record(monkeypatch, tmp_path, captured)
    decimate(Path("in.glb"), tmp_path / "out.glb", 456.0, blender="/usr/bin/blender", protect=("head", "eye"))
    cmd = captured[0]
    assert cmd[-1] == "head,eye"
    assert (tmp_path / "out.glb").exists()


def test_decimate_without_protect_is_unchanged(monkeypatch, tmp_path):
    captured = []
    _record(monkeypatch, tmp_path, captured)
    decimate(Path("in.glb"), tmp_path / "out.glb", 456.0, blender="/usr/bin/blender")
    cmd = captured[0]
    assert cmd[-1] == "456.0"          # amount stays the final positional argument
    assert "head,eye" not in cmd


def test_decimate_accepts_list_protect(monkeypatch, tmp_path):
    captured = []
    _record(monkeypatch, tmp_path, captured)
    decimate(Path("in.glb"), tmp_path / "out.glb", 100, protect=["head", "eye"])
    assert captured[0][-1] == "head,eye"
