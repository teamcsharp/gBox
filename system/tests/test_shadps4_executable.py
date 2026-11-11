"""shadps4.executable() must survive a Windows lock (WinError 5) on the exe.

Request #3755: launch_game failed at stage "prepare" because Path.is_file() /
Path.resolve() on a locked or ACL-blocked shadPS4.exe raised PermissionError
instead of either falling back or producing an actionable ToolUnavailable.
"""
from pathlib import Path

import pytest

from gbox import shadps4
from gbox.config import Config
from gbox.registry import ToolUnavailable


class _FakeEmu:
    def __init__(self, executable=None):
        self.executable = executable


class _FakeConfig:
    def __init__(self, runtime, executable=None):
        self.runtime = runtime
        self.emulators = {"ps4": _FakeEmu(executable)} if executable is not None else {}


def _winerror(exc):
    try:
        exc.winerror = 5
    except AttributeError:
        pass
    return exc


def test_locked_exe_denies_stat_but_launches(tmp_path, monkeypatch):
    """is_file() raises PermissionError (locked/AV-scanned exe): a clear
    ToolUnavailable with the lock diagnosis replaces the raw WinError 5."""
    exe = tmp_path / "shadps4" / "shadPS4.exe"
    exe.parent.mkdir(exist_ok=True)
    exe.write_bytes(b"MZ")
    real_is_file = Path.is_file

    def deny(self, *args, **kwargs):
        if self.name == "shadPS4.exe":
            raise _winerror(PermissionError(5, "Access is denied", str(self)))
        return real_is_file(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", deny)
    with pytest.raises(ToolUnavailable) as raised:
        shadps4.executable(_FakeConfig(tmp_path))
    assert "denies access" in str(raised.value)
    assert "antivirus" in str(raised.value)


def test_locked_exe_denies_resolve_falls_back_to_path(tmp_path, monkeypatch):
    """A running image can refuse the handle that Path.resolve() opens
    (GetFinalPathNameByHandle) while execution is still permitted: return the
    unresolved absolute path so the launch can proceed."""
    exe = tmp_path / "shadps4" / "shadPS4.exe"
    exe.parent.mkdir(exist_ok=True)
    exe.write_bytes(b"MZ")
    real_resolve = Path.resolve

    def deny(self, *args, **kwargs):
        if self.name == "shadPS4.exe":
            raise _winerror(PermissionError(5, "Access is denied", str(self)))
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", deny)
    found = shadps4.executable(_FakeConfig(tmp_path))
    assert found == exe and found.is_file()


def test_missing_exe_still_reports_not_installed(tmp_path):
    with pytest.raises(ToolUnavailable, match="not installed"):
        shadps4.executable(_FakeConfig(tmp_path))


def test_healthy_exe_resolves(tmp_path):
    exe = tmp_path / "shadps4" / "shadPS4.exe"
    exe.parent.mkdir(exist_ok=True)
    exe.write_bytes(b"MZ")
    assert shadps4.executable(_FakeConfig(tmp_path)) == exe.resolve()
