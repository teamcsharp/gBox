"""Dolphin on Windows: gBox's own hotkeys (save / load state, reset, speed limit) reach the docked game.

2026-10-13, Twin Snakes on JAYBUILTFINALE: a swap failed with "state_transfer failed: RuntimeError: the emulator didn't
write a save state" and Reset said "dolphin has no reset". The runtime's User/StateSaves had stayed empty since Dolphin
was installed: docked in gBox, Dolphin's render window is a child window, and on Windows Dolphin counts it focused only
when it is the foreground window (which a child never is), so every hotkey was dropped. Nothing here starts Dolphin.
"""
import threading
import time
from types import SimpleNamespace

import pytest

from gbox import adapters, tools
from gbox.config import Config


@pytest.fixture
def dolphin(tmp_path, monkeypatch):
    exe = tmp_path / "Dolphin-x64" / "gBox Dolphin.exe"
    (exe.parent / "User" / "StateSaves").mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setattr(adapters.DolphinWinAdapter, "_lanes", {})
    ad = adapters.DolphinWinAdapter(Config(data_dir=tmp_path / "data"), "gamecube")
    monkeypatch.setattr(ad, "_exe", lambda: exe, raising=False)
    monkeypatch.setattr(ad, "_gecko_setup", lambda user, rom: None, raising=False)
    ad.proc = SimpleNamespace(pid=4242, poll=lambda: None)
    sent = []
    monkeypatch.setattr(adapters, "win_send_keys", lambda pid, events: sent.extend(events) or {"sent": len(events)})
    return ad, exe, sent


def keys(sent):
    return [(e["key"], e["down"]) for e in sent]


def test_launch_writes_gbox_hotkeys_and_lifts_the_focus_gate(dolphin):
    ad, exe, _ = dolphin
    argv = ad._argv("GGSEA4 Twin Snakes.iso")
    assert "Dolphin.General.HotkeysRequireFocus=False" in argv
    ini = (exe.parent / "User" / "Config" / "Hotkeys.ini").read_text()
    assert ini.startswith("[Hotkeys]\nDevice = DInput/0/Keyboard Mouse\n")
    k = lambda name: f"`DInput/0/Keyboard Mouse:{name}`"
    lines = dict(line.split(" = ", 1) for line in ini.splitlines()[1:])
    assert lines["Save State/Save State Slot 1"] == f"{k('F13')} & {k('RCONTROL')} & {k('RSHIFT')} & !{k('LCONTROL')}"
    assert lines["Load State/Load State Slot 1"] == f"{k('F13')} & {k('RCONTROL')} & !{k('RSHIFT')} & !{k('LCONTROL')}"
    assert lines["General/Reset"] == f"{k('F13')} & {k('RSHIFT')} & !{k('RCONTROL')} & !{k('LCONTROL')}"
    assert lines["Emulation Speed/Disable Emulation Speed Limit"] == f"{k('F13')} & !{k('RCONTROL')} & !{k('RSHIFT')} & !{k('LCONTROL')}"
    # hotkeys work without focus, so nothing a person presses is bound: no Esc (Stop), F1-F12, Tab...
    assert set(lines) == {"Device", *adapters.DolphinWinAdapter.HOTKEYS}
    for word in ("ESCAPE", "`F1`", ":F1`", "TAB", "RETURN"):
        assert word not in ini


def test_two_dolphins_on_one_pc_get_their_own_lane(dolphin, tmp_path, monkeypatch):
    ad, exe, _ = dolphin
    ad._argv("a.iso")
    other = adapters.DolphinWinAdapter(Config(data_dir=tmp_path / "data"), "gamecube")
    monkeypatch.setattr(other, "_exe", lambda: exe, raising=False)
    monkeypatch.setattr(other, "_gecko_setup", lambda user, rom: None, raising=False)
    other._argv("b.iso")                                   # e.g. a reset's replacement, started beside the running copy
    assert (ad.lane, other.lane) == ("F13", "F14")
    assert "Keyboard Mouse:F14" in (exe.parent / "User" / "Config" / "Hotkeys.ini").read_text()
    other.proc = SimpleNamespace(pid=1, poll=lambda: None)
    ad.proc = SimpleNamespace(pid=2, poll=lambda: 0)        # the first Dolphin has exited: its lane is free again
    third = adapters.DolphinWinAdapter(Config(data_dir=tmp_path / "data"), "gamecube")
    assert third._claim_lane() == "F13"
    other._release_lane()
    assert "F14" not in adapters.DolphinWinAdapter._lanes


def test_save_state_presses_the_lane_chord_and_returns_the_file_dolphin_wrote(dolphin):
    ad, exe, sent = dolphin
    state = exe.parent / "User" / "StateSaves" / "GGSEA4.s01"

    def dolphin_writes():                                  # Dolphin writes on its own thread, a moment later
        time.sleep(0.2)
        state.write_bytes(b"DOLPHIN-STATE" * 1000)
    threading.Thread(target=dolphin_writes, daemon=True).start()
    out = ad.save_state()
    assert keys(sent) == [("Control_R", True), ("Shift_R", True), ("F13", True), ("F13", False), ("Shift_R", False),
                          ("Control_R", False)]
    assert out == {"slot": 1, "path": str(state), "bytes": 13000, "verified": True}


def test_save_state_that_never_lands_fails_loudly_instead_of_claiming_slot_1(dolphin, monkeypatch):
    ad, exe, _ = dolphin
    old = exe.parent / "User" / "StateSaves" / "GGSEA4.s01"
    old.write_bytes(b"yesterday")
    import os
    os.utime(old, (time.time() - 3600, time.time() - 3600))   # an old state is not this save
    monkeypatch.setattr(ad, "STATE_WAIT_S", 0.5)
    with pytest.raises(RuntimeError, match="did not write a save state"):
        ad.save_state()


def test_reset_is_dolphins_reset_hotkey_and_ends_fast_forward(dolphin):
    ad, _, sent = dolphin
    assert callable(getattr(type(ad), "reset", None))      # tools.session_op / session_rpc: Dolphin has a reset now
    ad.fast_forward(on=True)
    sent.clear()
    assert ad.reset()["reset"] is True
    assert keys(sent) == [("F13", False), ("Shift_R", True), ("F13", True), ("F13", False), ("Shift_R", False)]
    assert ad.ff_on is False


def test_a_hotkey_during_fast_forward_keeps_it_held(dolphin):
    ad, _, sent = dolphin
    ad.fast_forward(on=True)
    sent.clear()
    ad.load_state()
    assert keys(sent) == [("Control_R", True), ("F13", True), ("F13", False), ("Control_R", False), ("F13", True)]


def test_state_transfer_exports_the_verified_dolphin_file(dolphin, monkeypatch):
    ad, exe, _ = dolphin
    ad.name = "dolphin"
    state = exe.parent / "User" / "StateSaves" / "GGSEA4.s01"
    threading.Thread(target=lambda: (time.sleep(0.2), state.write_bytes(b"S" * 4096)), daemon=True).start()
    monkeypatch.setitem(tools.SESSIONS, "w-dolphin", (ad, {"game_id": "ts", "_rom_path": "tts_sonic_full_cast.iso"}))
    artifacts = []
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=exe.parent), server="", headers={},
                          artifact=lambda *a, **k: artifacts.append((a, k)))
    out = tools.state_transfer(tools.StateXIn(session_id="w-dolphin", op="export"), ctx)["result"]
    assert out["file"] == "GGSEA4.s01" and out["bytes"] == 4096 and out["selection"] == "verified_adapter_path"
    assert out["slot_verified"] is True and artifacts and artifacts[0][0][0] == "GGSEA4.s01"


def test_session_op_reset_reaches_dolphin(dolphin, monkeypatch):
    ad, _, sent = dolphin
    monkeypatch.setitem(tools.SESSIONS, "w-dolphin", (ad, {"game_id": "ts"}))
    out = tools.session_op(tools.SessionIn(session_id="w-dolphin", op="reset"), SimpleNamespace())
    assert out["result"]["reset"] is True and out["ended"] is False and ("Shift_R", True) in keys(sent)
    assert tools.session_rpc("w-dolphin", "reset", {})["reset"] is True


def test_checkpoint_ring_now_that_it_saves_takes_at_most_one_state_every_20_s(dolphin):
    ad, _, _ = dolphin
    assert ad.checkpoint_min_interval_s >= 20


def test_function_keys_13_to_15_have_their_directinput_scan_codes():
    assert [adapters._SCAN[k] for k in ("F13", "F14", "F15")] == [(0x64, 0), (0x65, 0), (0x66, 0)]
    assert adapters._SCAN["Control_R"] == (0x1D, 1) and adapters._SCAN["Control_L"] == (0x1D, 0)


@pytest.mark.parametrize("cls,key", [(adapters.MgbaAdapter, "ctrl+r"), (adapters.MameAdapter, "F3")])
def test_standalone_emulators_with_a_reset_key_reset_in_place(cls, key, tmp_path, monkeypatch):
    ad = cls.__new__(cls)
    pressed = []
    monkeypatch.setattr(ad, "_xdo", lambda *a: pressed.append(a), raising=False)
    assert ad.reset()["reset"] is True and pressed == [("key", key)]
