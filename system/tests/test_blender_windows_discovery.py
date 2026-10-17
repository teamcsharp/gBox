from pathlib import Path
from gbox import provision
from gbox.config import Config


def setup_host(monkeypatch, tmp_path):
    provision._blender_cache.clear()
    monkeypatch.setattr(provision, "HOST_OS", "windows")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "user"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Programs"))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setattr(provision.shutil, "which", lambda _: None)


def test_windows_discovers_installed_blender_with_other_pc_config(monkeypatch, tmp_path):
    setup_host(monkeypatch, tmp_path)
    exe = tmp_path / "Programs" / "Blender Foundation" / "Blender 4.0" / "blender.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"binary")
    cfg = Config(data_dir=tmp_path, blender_search=[str(tmp_path / "other-pc")])
    assert provision.find_blender(cfg) == str(exe)


def test_windows_respects_explicit_blender_before_discovery(monkeypatch, tmp_path):
    setup_host(monkeypatch, tmp_path)
    exe = tmp_path / "chosen.exe"
    exe.write_bytes(b"binary")
    assert provision.find_blender(Config(data_dir=tmp_path, blender_path=str(exe))) == str(exe)
