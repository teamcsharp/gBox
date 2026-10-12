"""find_blender must never pick an emulated foreign-arch Blender on Linux.

Live #1175 failure: asset_convert on the aarch64 Spark died with
"Could not open '/lib64/ld-linux-x86-64.so.2'" because shutil.which resolves
/usr/local/bin/blender (EM_X86_64) before /usr/bin/blender (EM_AARCH64).
"""
import os
import time
from pathlib import Path

from gbox import provision


def _write_blender(path: Path, em: int, mtime: float) -> None:
    # ELF header: magic + 14 padding bytes + e_machine (u16 LE at 18:20); find_blender reads 20 bytes
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x7fELF" + bytes(14) + em.to_bytes(2, "little") + b"\x00" * 32)
    os.utime(path, (mtime, mtime))


def test_prefers_native_aarch64_blender_over_newer_x86_64(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(provision, "HOST_OS", "linux")
    monkeypatch.setattr(provision, "ARCH", "aarch64")
    x86 = tmp_path / "new" / "blender"
    arm = tmp_path / "old" / "blender"
    _write_blender(x86, 62, time.time())            # foreign, newest by mtime
    _write_blender(arm, 183, time.time() - 500)     # native, older
    cfg.blender_path = None
    cfg.blender_search = [str(tmp_path)]
    provision._blender_cache.clear()
    assert provision.find_blender(cfg) == str(arm.resolve())


def test_x86_64_host_still_takes_newest_build(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(provision, "HOST_OS", "linux")
    monkeypatch.setattr(provision, "ARCH", "x86_64")
    old = tmp_path / "old" / "blender"
    new = tmp_path / "new" / "blender"
    _write_blender(old, 62, time.time() - 500)
    _write_blender(new, 62, time.time())
    cfg.blender_path = None
    cfg.blender_search = [str(tmp_path)]
    provision._blender_cache.clear()
    assert provision.find_blender(cfg) == str(new.resolve())


def test_skips_foreign_blender_path_on_aarch64(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(provision, "HOST_OS", "linux")
    monkeypatch.setattr(provision, "ARCH", "aarch64")
    foreign = tmp_path / "pinned" / "blender"
    native = tmp_path / "native" / "blender"
    _write_blender(foreign, 62, time.time())
    _write_blender(native, 183, time.time() - 500)
    cfg.blender_path = str(foreign)
    cfg.blender_search = [str(tmp_path)]
    provision._blender_cache.clear()
    assert provision.find_blender(cfg) == str(native.resolve())


def test_native_blender_path_still_short_circuits(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(provision, "HOST_OS", "linux")
    monkeypatch.setattr(provision, "ARCH", "aarch64")
    native = tmp_path / "pinned" / "blender"
    _write_blender(native, 183, time.time())
    cfg.blender_path = str(native)
    cfg.blender_search = [str(tmp_path)]
    provision._blender_cache.clear()
    assert provision.find_blender(cfg) == str(native.resolve())
