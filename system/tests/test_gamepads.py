"""Regression checks for excluding 3D mice without disabling Xbox input."""
from types import SimpleNamespace

import pytest

from gbox import adapters, gamepads
from gbox.config import Config, EmulatorConfig
from gbox.registry import ToolUnavailable


@pytest.mark.parametrize("features,expected", [
    ("  SDL3:\tSDL3 input: yes\n  SDL2: no\n", "sdl3"),
    ("  SDL3: no\n  SDL2:\tSDL2 input: yes\n", "sdl2"),
])
def test_supported_sdl_driver(monkeypatch, features, expected):
    gamepads._driver.cache_clear()
    monkeypatch.setattr(gamepads.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=features))
    assert gamepads.retroarch_driver("retroarch-test.exe") == expected


def test_no_hybrid_xinput_fallback(monkeypatch):
    gamepads._driver.cache_clear()
    monkeypatch.setattr(gamepads.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="SDL3: no\nSDL2: no\nXInput: yes\n"))
    with pytest.raises(ToolUnavailable, match="exclude SpaceMouse"):
        gamepads.retroarch_driver("retroarch-test.exe")


def test_exclusions_are_scoped_and_keep_xbox():
    original = {"PATH": "unchanged", "SDL_GAMECONTROLLER_IGNORE_DEVICES": "0x1234/0x5678"}
    env = gamepads.emulator_environment(original)
    assert env["SDL_JOYSTICK_DIRECTINPUT"] == "0"
    assert env["SDL_XINPUT_ENABLED"] == "1"
    blocked = env["SDL_GAMECONTROLLER_IGNORE_DEVICES"].split(",")
    assert {"0x256f/0xc635", "0xbeef/0x046d", "0x046d/0xc626", "0x1234/0x5678"} <= set(blocked)
    assert not any(device.startswith("0x045e/") for device in blocked)
    assert "SDL_JOYSTICK_DIRECTINPUT" not in original
    assert env["PATH"] == original["PATH"]


def test_windows_session_uses_sdl_and_correct_select_hotkey(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, "HOST_OS", "windows")
    monkeypatch.setattr(gamepads, "retroarch_driver", lambda exe: "sdl3")
    monkeypatch.setattr(adapters.provision, "retroarch_exe", lambda cfg: "retroarch-test.exe")
    from gbox import graphics
    monkeypatch.setattr(graphics, "get", lambda *a: {})
    monkeypatch.setattr(graphics, "retroarch_opts", lambda *a: {})
    adapter = adapters.RetroArchAdapter(EmulatorConfig(adapter="retroarch", executable="retroarch-test.exe", core="core"),
                                       config=Config(data_dir=tmp_path), platform="psp")
    cfg = adapter._write_cfg().read_text()
    assert 'input_joypad_driver = "sdl3"' in cfg
    assert 'input_autodetect_enable = "true"' in cfg
    assert 'input_enable_hotkey_btn = "4"' in cfg
    assert 'input_rewind_axis = "+4"' in cfg
