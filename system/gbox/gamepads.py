"""Windows emulator gamepad discovery without 3Dconnexion navigation devices."""
import os
import json
import re
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path

from .registry import ToolUnavailable


def xinput_devices() -> list[int]:
    """Connected Xbox/XInput slots, independent of browser gamepad activation."""
    if os.name != "nt":
        return []
    import ctypes
    class Gamepad(ctypes.Structure):
        _fields_ = [("buttons", ctypes.c_ushort), ("lt", ctypes.c_ubyte), ("rt", ctypes.c_ubyte),
                    ("lx", ctypes.c_short), ("ly", ctypes.c_short), ("rx", ctypes.c_short), ("ry", ctypes.c_short)]
    class State(ctypes.Structure):
        _fields_ = [("packet", ctypes.c_uint), ("gamepad", Gamepad)]
    for name in ("xinput1_4", "xinput9_1_0"):
        try:
            dll = getattr(ctypes.windll, name)
        except OSError:
            continue
        dll.XInputGetState.argtypes = [ctypes.c_uint, ctypes.POINTER(State)]
        dll.XInputGetState.restype = ctypes.c_uint
        return [slot for slot in range(4) if dll.XInputGetState(slot, ctypes.byref(State())) == 0]
    return []


def xinput_snapshot() -> list[dict]:
    """Live pad state for the desktop glyph, independent of Chromium focus."""
    if os.name != "nt":
        return []
    import ctypes
    class Gamepad(ctypes.Structure):
        _fields_ = [("buttons", ctypes.c_ushort), ("lt", ctypes.c_ubyte), ("rt", ctypes.c_ubyte),
                    ("lx", ctypes.c_short), ("ly", ctypes.c_short), ("rx", ctypes.c_short), ("ry", ctypes.c_short)]
    class State(ctypes.Structure):
        _fields_ = [("packet", ctypes.c_uint), ("gamepad", Gamepad)]
    for name in ("xinput1_4", "xinput9_1_0"):
        try:
            dll = getattr(ctypes.windll, name)
        except OSError:
            continue
        dll.XInputGetState.argtypes = [ctypes.c_uint, ctypes.POINTER(State)]
        dll.XInputGetState.restype = ctypes.c_uint
        out = []
        for slot in range(4):
            state = State()
            if dll.XInputGetState(slot, ctypes.byref(state)) == 0:
                pad = state.gamepad
                out.append({"slot": slot, "buttons": pad.buttons, "lt": pad.lt, "rt": pad.rt,
                            "lx": pad.lx, "ly": pad.ly, "rx": pad.rx, "ry": pad.ry})
        return out
    return []


def sdl2_xbox_guid(dll_path: Path) -> str | None:
    """SDL GUID for the connected Xbox controller as Yuzu sees it."""
    if os.name != "nt" or not dll_path.is_file() or not xinput_devices():
        return None
    import ctypes
    class Guid(ctypes.Structure):
        _fields_ = [("data", ctypes.c_ubyte * 16)]
    sdl = ctypes.WinDLL(str(dll_path))
    sdl.SDL_InitSubSystem.argtypes = [ctypes.c_uint32]
    sdl.SDL_InitSubSystem.restype = ctypes.c_int
    sdl.SDL_QuitSubSystem.argtypes = [ctypes.c_uint32]
    sdl.SDL_NumJoysticks.restype = ctypes.c_int
    sdl.SDL_IsGameController.argtypes = [ctypes.c_int]
    sdl.SDL_IsGameController.restype = ctypes.c_int
    sdl.SDL_JoystickNameForIndex.argtypes = [ctypes.c_int]
    sdl.SDL_JoystickNameForIndex.restype = ctypes.c_char_p
    sdl.SDL_JoystickGetDeviceGUID.argtypes = [ctypes.c_int]
    sdl.SDL_JoystickGetDeviceGUID.restype = Guid
    sdl.SDL_JoystickGetGUIDString.argtypes = [Guid, ctypes.c_char_p, ctypes.c_int]
    joystick = 0x200
    if sdl.SDL_InitSubSystem(joystick) != 0:
        return None
    try:
        for index in range(sdl.SDL_NumJoysticks()):
            name = (sdl.SDL_JoystickNameForIndex(index) or b"").decode(errors="replace").lower()
            if "xbox" not in name or not sdl.SDL_IsGameController(index):
                continue
            buf = ctypes.create_string_buffer(33)
            sdl.SDL_JoystickGetGUIDString(sdl.SDL_JoystickGetDeviceGUID(index), buf, len(buf))
            guid = buf.value.decode("ascii").lower()
            if re.fullmatch(r"[0-9a-f]{32}", guid):
                return guid
    finally:
        sdl.SDL_QuitSubSystem(joystick)
    return None


def bind_yuzu_player_one(config_path: Path, guid: str) -> bool:
    """Replace stale player-one SDL GUIDs, preserving the original config once."""
    if not re.fullmatch(r"[0-9a-f]{32}", guid):
        raise ValueError("invalid SDL controller GUID")
    original = config_path.read_bytes()
    body = original.decode("utf-8")
    changed = "".join(
        re.sub(r"guid:[0-9a-fA-F]{32}", f"guid:{guid}", line)
        if line.startswith("player_0_") else line
        for line in body.splitlines(keepends=True)
    )
    if changed == body:
        return False
    backup = config_path.with_name(config_path.name + ".gbox-original")
    if not backup.exists():
        backup.write_bytes(original)
    config_path.write_bytes(changed.encode("utf-8"))
    return True


def retroarch_driver(executable: str) -> str:
    path = Path(executable)
    driver = _driver(str(path), path.stat().st_mtime_ns if path.is_file() else 0)
    if path.is_file() and driver == "sdl3":
        install_sdl3_xbox_profile(path.parent / "autoconfig")
    return driver


def install_sdl3_xbox_profile(directory: Path) -> Path:
    """Keep SDL's normalized Xbox mapping ahead of the incompatible XInput fallback.

    RetroArch can match the name 'XInput Controller' to its XInput profile even
    while SDL3 is reading it. XInput's Y signs and shoulder/Back indices differ
    from SDL_Gamepad. A driver-local profile also works when SDL2 isn't built.
    """
    buttons = {"b": 0, "a": 1, "y": 2, "x": 3, "select": 4, "start": 6,
               "l3": 7, "r3": 8, "l": 9, "r": 10,
               "up": 11, "down": 12, "left": 13, "right": 14, "menu_toggle": 5}
    axes = {"l2": "+4", "r2": "+5", "l_x_minus": "-0", "l_x_plus": "+0",
            "l_y_minus": "-1", "l_y_plus": "+1", "r_x_minus": "-2", "r_x_plus": "+2",
            "r_y_minus": "-3", "r_y_plus": "+3"}
    names = ["XInput Controller", "Xbox One Controller", "Xbox One Wireless Controller",
             "Xbox Series X Controller", "Xbox Wireless Controller", "Xbox 360 Controller"]
    lines = ['input_driver = "sdl3"', 'input_device_display_name = "Xbox controller (SDL3)"']
    lines += [f'input_device{"_alt" + str(i) if i else ""} = "{name}"' for i, name in enumerate(names)]
    lines += [f'input_{key}_btn = "{value}"' for key, value in buttons.items()]
    lines += [f'input_{key}_axis = "{value}"' for key, value in axes.items()]
    profile = directory / "sdl3" / "gbox-xbox.cfg"
    body = "\n".join(lines) + "\n"
    profile.parent.mkdir(parents=True, exist_ok=True)
    if not profile.is_file() or profile.read_text(encoding="utf-8") != body:
        profile.write_text(body, encoding="utf-8")
    return profile


@lru_cache(maxsize=8)
def _driver(executable: str, modified: int) -> str:
    # RetroArch's Windows "xinput" driver also enumerates DirectInput joysticks.
    # Use SDL so its per-process device exclusions apply, including on hotplug.
    try:
        result = subprocess.run([executable, "--features"], capture_output=True, text=True,
                                errors="replace", timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        # Prefer SDL2 when available; SDL3-only builds get an explicit Xbox profile.
        for version in (2, 3):
            if re.search(rf"^\s*SDL{version}\b[^\r\n]*\byes\s*$", result.stdout, re.M | re.I):
                return f"sdl{version}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolUnavailable(f"Could not check RetroArch controller support: {exc}") from exc
    raise ToolUnavailable("This RetroArch build needs SDL2 or SDL3 controller support to exclude SpaceMouse devices.")


def emulator_environment(source: dict[str, str]) -> dict[str, str]:
    env = dict(source)
    # Disable the joystick DirectInput backend, not keyboard/mouse input. XInput
    # remains available for wired/wireless Xbox controllers.
    env["SDL_JOYSTICK_DIRECTINPUT"] = "0"                # SDL3's name for it
    env["SDL_DIRECTINPUT_ENABLED"] = "0"                 # SDL2's name: no DirectInput joysticks (SpaceMouse, KMJ)
    env["SDL_XINPUT_ENABLED"] = "1"
    # A native emulator docked inside Electron does not always own Windows'
    # foreground window. SDL otherwise suppresses pad updates altogether.
    env["SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"] = "1"
    blocked = ["0xbeef/0x046d"]  # virtual KMJ joystick
    blocked += [f"0x256f/0x{pid}" for pid in
                ("c62e", "c62f", "c631", "c632", "c633", "c635", "c636", "c638", "c652")]
    blocked += [f"0x046d/0x{pid}" for pid in
                ("c603", "c605", "c606", "c621", "c623", "c625", "c626", "c627", "c628", "c629", "c62b")]
    env["SDL_GAMECONTROLLER_IGNORE_DEVICES"] = ",".join(filter(None, [
        env.get("SDL_GAMECONTROLLER_IGNORE_DEVICES", ""), *blocked]))
    return env


if __name__ == "__main__":
    if "--watch" in sys.argv:
        while True:
            print(json.dumps(xinput_snapshot(), separators=(",", ":")), flush=True)
            time.sleep(0.05)
    else:
        print(json.dumps(xinput_devices()))
