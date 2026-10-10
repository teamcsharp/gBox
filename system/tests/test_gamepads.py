"""Regression checks for excluding 3D mice without disabling Xbox input."""
from types import SimpleNamespace

import pytest

from gbox import adapters, gamepads
from gbox.config import Config, EmulatorConfig
from gbox.registry import ToolUnavailable


@pytest.mark.parametrize("features,expected", [
    ("  SDL3:\tSDL3 input: yes\n  SDL2: no\n", "sdl3"),
    ("  SDL3: no\n  SDL2:\tSDL2 input: yes\n", "sdl2"),
    ("  SDL3:\tSDL3 input: yes\n  SDL2:\tSDL2 input: yes\n", "sdl2"),   # both: SDL2 (mature profiles; SDL3 inverted a stick)
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
    assert env["SDL_DIRECTINPUT_ENABLED"] == "0"
    assert env["SDL_XINPUT_ENABLED"] == "1"
    assert env["SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"] == "1"
    blocked = env["SDL_GAMECONTROLLER_IGNORE_DEVICES"].split(",")
    assert {"0x256f/0xc635", "0xbeef/0x046d", "0x046d/0xc626", "0x1234/0x5678"} <= set(blocked)
    assert not any(device.startswith("0x045e/") for device in blocked)
    assert "SDL_JOYSTICK_DIRECTINPUT" not in original
    assert env["PATH"] == original["PATH"]


def test_yuzu_rebinds_only_player_one_and_keeps_original(tmp_path):
    ini = tmp_path / "qt-config.ini"
    old = "0" * 32
    new = "0300938d5e040000ff02000000007200"
    body = (f'[Controls]\r\nplayer_0_button_a="engine:sdl,port:0,guid:{old},button:1"\r\n'
            f'player_0_lstick="axis_x:0,guid:{old},axis_y:1,guid:{old}"\r\n'
            f'player_1_button_a="engine:sdl,port:1,guid:{old},button:1"\r\n')
    ini.write_bytes(body.encode())
    assert gamepads.bind_yuzu_player_one(ini, new)
    updated = ini.read_bytes().decode()
    assert updated.count(f"guid:{new}") == 3
    assert f"player_1_button_a=\"engine:sdl,port:1,guid:{old}" in updated
    assert ini.with_name("qt-config.ini.gbox-original").read_bytes().decode() == body
    assert not gamepads.bind_yuzu_player_one(ini, new)


def test_yuzu_xinput_bridge_bindings_are_scoped_and_backed_up(tmp_path):
    ini = tmp_path / "qt-config.ini"
    body = ('[Controls]\r\nplayer_0_button_a="engine:sdl,port:0,button:1"\r\n'
            'player_0_lstick="engine:sdl,port:0,axis_x:0"\r\n'
            'player_1_button_a="engine:keyboard,code:42"\r\n')
    ini.write_bytes(body.encode())
    assert gamepads.bind_yuzu_xinput_bridge(ini)
    updated = ini.read_bytes().decode()
    assert 'player_0_button_a="engine:keyboard,code:67,toggle:0"\r\n' in updated
    assert 'player_0_lstick="engine:analog_from_button,' in updated
    assert 'player_1_button_a="engine:keyboard,code:42"' in updated
    assert ini.with_name("qt-config.ini.gbox-sdl").read_bytes().decode() == body
    assert not gamepads.bind_yuzu_xinput_bridge(ini)


def test_yuzu_mouse_click_enables_handheld_touch_without_changing_ui_mode(tmp_path):
    ini = tmp_path / "qt-config.ini"
    body = ('[Controls]\r\nmouse_enabled=true\r\ntouchscreen_enabled=false\r\n'
            'use_docked_mode\\default=true\r\nuse_docked_mode=true\r\n'
            '[UI]\r\nuse_docked_mode=true\r\n')
    ini.write_bytes(body.encode())
    assert gamepads.enable_yuzu_mouse_touch(ini)
    updated = ini.read_bytes().decode()
    assert '[Controls]\r\nmouse_enabled=false\r\ntouchscreen_enabled=true\r\n' in updated
    assert 'use_docked_mode\\default=false\r\nuse_docked_mode=false\r\n' in updated
    assert '[UI]\r\nuse_docked_mode=true\r\n' in updated
    assert ini.with_name("qt-config.ini.gbox-touch-original").read_bytes().decode() == body
    assert not gamepads.enable_yuzu_mouse_touch(ini)


def test_yuzu_xinput_bridge_maps_face_buttons_and_sticks():
    from gbox.yuzu_input import keys_for_pad
    pad = {"buttons": 0x1000 | 0x0010, "lt": 0, "rt": 255,
           "lx": -20000, "ly": 21000, "rx": 17000, "ry": -18000}
    assert keys_for_pad(pad) == {0x43, 0x4D, 0x54, 0x41, 0x57, 0x4C, 0x4B}


def test_sdl3_only_build_installs_normalized_xbox_profile(tmp_path, monkeypatch):
    executable = tmp_path / "retroarch.exe"
    executable.touch()
    gamepads._driver.cache_clear()
    monkeypatch.setattr(gamepads.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="SDL3: yes\n"))
    assert gamepads.retroarch_driver(str(executable)) == "sdl3"
    profile = tmp_path / "autoconfig/sdl3/gbox-xbox.cfg"
    mapping = dict(line.split(" = ") for line in profile.read_text().splitlines())
    assert mapping["input_driver"] == '"sdl3"'
    assert mapping["input_device"] == '"XInput Controller"'
    # SDL Y is negative upwards, unlike the XInput profile's Y convention.
    for stick, axis in [("l", 1), ("r", 3)]:
        assert mapping[f"input_{stick}_y_minus_axis"] == f'"-{axis}"'
        assert mapping[f"input_{stick}_y_plus_axis"] == f'"+{axis}"'
    assert mapping["input_select_btn"] == '"4"'
    assert mapping["input_l_btn"] == '"9"'
    assert mapping["input_up_btn"] == '"11"'
    assert mapping["input_l2_axis"] == '"+4"'
    modified = profile.stat().st_mtime_ns
    gamepads.retroarch_driver(str(executable))
    assert profile.stat().st_mtime_ns == modified


def test_sdl2_profiles_are_left_alone(tmp_path, monkeypatch):
    executable = tmp_path / "retroarch.exe"
    executable.touch()
    gamepads._driver.cache_clear()
    monkeypatch.setattr(gamepads.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="SDL2: yes\nSDL3: yes\n"))
    assert gamepads.retroarch_driver(str(executable)) == "sdl2"
    assert not (tmp_path / "autoconfig").exists()


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
