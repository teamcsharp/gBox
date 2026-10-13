"""#1641: Windows Dolphin's slot-1 save must be verified on disk, and its hotkeys must work while docked."""
import os
import time
from pathlib import Path

import pytest

from gbox import adapters
from gbox.config import Config


def _adapter(tmp_path, monkeypatch):
    ad = adapters.DolphinWinAdapter(Config(), "gamecube")
    ad.proc = type("Proc", (), {"pid": 123})()
    ad.gecko_id = "GGSEA4"
    states = tmp_path / "User" / "StateSaves"
    states.mkdir(parents=True)
    monkeypatch.setattr(ad, "state_dir", lambda: states)
    ad.SAVE_WAIT_S = 2.0
    return ad, states


def test_save_state_returns_verified_native_path(tmp_path, monkeypatch):
    ad, states = _adapter(tmp_path, monkeypatch)
    stale = states / "GMSE01.s01"                     # another game's slot 1 is never reported
    stale.write_bytes(b"x" * 8)

    def keys(pid, events):
        assert [e["key"] for e in events] == ["Shift_R", "F1", "F1", "Shift_R"]
        (states / "GGSEA4.s01").write_bytes(b"S" * 64)
        return {"sent": 4}
    monkeypatch.setattr(adapters, "win_send_keys", keys)
    out = ad.save_state()
    assert out == {"slot": 1, "path": str(states / "GGSEA4.s01"), "verified": True, "bytes": 64}


def test_save_state_ignores_old_file_and_fails_clearly(tmp_path, monkeypatch):
    ad, states = _adapter(tmp_path, monkeypatch)
    old = states / "GGSEA4.s01"
    old.write_bytes(b"O" * 16)
    past = time.time() - 600
    os.utime(old, (past, past))
    ad.SAVE_WAIT_S = 0.5
    monkeypatch.setattr(adapters, "win_send_keys", lambda pid, events: {"sent": 4})
    with pytest.raises(RuntimeError, match="didn't write save slot 1"):
        ad.save_state()


def test_save_state_refuses_undelivered_hotkey(tmp_path, monkeypatch):
    ad, _ = _adapter(tmp_path, monkeypatch)
    monkeypatch.setattr(adapters, "win_send_keys",
                        lambda pid, events: {"sent": 0, "stopped": "another application came to the front"})
    with pytest.raises(RuntimeError, match="not delivered: another application"):
        ad.save_state()


def test_docked_dolphin_hotkeys_do_not_require_focus(tmp_path, monkeypatch):
    exe = tmp_path / "Dolphin-x64" / "gBox Dolphin.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    rom = tmp_path / "tts.iso"
    rom.write_bytes(b"GGSEA4" + bytes(64))
    ad = adapters.DolphinWinAdapter(Config(data_dir=tmp_path), "gamecube")
    ad.port = 55555
    monkeypatch.setattr(ad, "_exe", lambda: exe)
    argv = ad._argv(str(rom))
    assert "Dolphin.General.HotkeysRequireFocus=False" in argv
    assert "Dolphin.Input.BackgroundInput=True" in argv
