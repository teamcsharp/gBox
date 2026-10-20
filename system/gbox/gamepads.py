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
    from . import xinput
    fn = xinput.load()                     # shared binding (#1638): never retype the DLL's cached function
    return [slot for slot in range(4) if xinput.read(fn, slot) is not None] if fn is not None else []


def xinput_snapshot(slots=range(4)) -> list[dict]:
    """Live pad state for the desktop app (controller glyph, and Player 1 of a streamed game), independent of Chromium focus."""
    from . import xinput
    fn = xinput.load()                     # shared binding (#1638): never retype the DLL's cached function
    out = []
    for slot in (slots if fn is not None else ()):
        state = xinput.read(fn, slot)
        if state is not None:
            pad = state.gamepad
            out.append({"slot": slot, "buttons": pad.buttons, "lt": pad.lt, "rt": pad.rt,
                        "lx": pad.lx, "ly": pad.ly, "rx": pad.rx, "ry": pad.ry})
    return out


def bind_savemgo_xinput(home: Path, slots: list[int]) -> bool:
    """Replace only the portable package's stale DualSense selection, per PC.

    Existing custom mappings and non-XInput setups are left intact. Keep a byte
    exact backup and preserve every setting outside the six device/face bindings.
    """
    if not slots or any(type(s) is not int or not 0 <= s < 4 for s in slots):
        return False
    from .savemgo import _guard
    path = _guard(home / 'config/input_configs/global/Default.yml')
    if not path.is_file():
        return False
    original = path.read_bytes()
    body = original.decode('utf-8')
    sections = re.split(r'(?m)(?=^Player [2-7] Input:)', body, maxsplit=1)
    first = sections[0]
    if not (first.startswith('Player 1 Input:')
            and re.search(r'^  Handler: SDL\s*$', first, re.M)
            and re.search(r'^  Device: DualSense Wireless Controller 1\s*$', first, re.M)):
        return False
    replacements = {'Handler': 'XInput', 'Device': f'"XInput Pad #{min(slots) + 1}"',
                    'Square': 'X', 'Cross': 'A', 'Circle': 'B', 'Triangle': 'Y'}
    for key, value in replacements.items():
        first, count = re.subn(r'(?m)^(\s*' + key + r': )[^\r\n]*', lambda m: m[1] + value, first)
        if count != 1:
            raise ValueError('Incomplete bundled MGO controller mapping')
    backup = _guard(path.with_name(path.name + '.gbox-original'))
    if not backup.exists():
        backup.write_bytes(original)
    path.write_bytes((first + ''.join(sections[1:])).encode('utf-8'))
    return True


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


YUZU_KEYBOARD_BUTTONS = {
    "a": 67, "b": 88, "x": 86, "y": 90, "lstick": 70, "rstick": 71,
    "l": 81, "r": 69, "zl": 82, "zr": 84, "plus": 77, "minus": 78,
    "dleft": 16777234, "dup": 16777235, "dright": 16777236, "ddown": 16777237,
    "sl": 81, "sr": 69,
}


def bind_yuzu_xinput_bridge(config_path: Path) -> bool:
    """Bind player one to keys emitted from XInput when this Yuzu SDL build reads no pad state."""
    original = config_path.read_bytes()
    body = original.decode("utf-8")
    bindings = {f"player_0_button_{name}": f'"engine:keyboard,code:{code},toggle:0"'
                for name, code in YUZU_KEYBOARD_BUTTONS.items()}
    bindings["player_0_lstick"] = ('"engine:analog_from_button,up:engine$0keyboard$1code$087$1toggle$00,'
                                    'left:engine$0keyboard$1code$065$1toggle$00,'
                                    'modifier:engine$0keyboard$1code$016777248$1toggle$00,'
                                    'down:engine$0keyboard$1code$083$1toggle$00,'
                                    'right:engine$0keyboard$1code$068$1toggle$00,modifier_scale:0.500000"')
    bindings["player_0_rstick"] = ('"engine:analog_from_button,up:engine$0keyboard$1code$073$1toggle$00,'
                                    'left:engine$0keyboard$1code$074$1toggle$00,'
                                    'modifier:engine$0keyboard$1code$00$1toggle$00,'
                                    'down:engine$0keyboard$1code$075$1toggle$00,'
                                    'right:engine$0keyboard$1code$076$1toggle$00,modifier_scale:0.500000"')
    lines = []
    for line in body.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        key = bare.partition("=")[0]
        lines.append(f"{key}={bindings[key]}{line[len(bare):]}" if key in bindings else line)
    changed = "".join(lines)
    if changed == body:
        return False
    backup = config_path.with_name(config_path.name + ".gbox-sdl")
    if not backup.exists():
        backup.write_bytes(original)
    config_path.write_bytes(changed.encode("utf-8"))
    return True


def enable_yuzu_mouse_touch(config_path: Path) -> bool:
    """Make a click on Yuzu's game window a Switch touch at that position.

    Yuzu receives the native mouse event directly. The emulated Switch must be
    handheld for games that expose touch controls only off the dock.
    """
    original = config_path.read_bytes()
    body = original.decode("utf-8")
    values = {"mouse_enabled": "false", "touchscreen_enabled": "true",
              "use_docked_mode": "false", "use_docked_mode\\default": "false"}
    lines, section, seen = [], "", set()
    for line in body.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        if bare.startswith("[") and bare.endswith("]"):
            if section == "Controls":
                lines.extend(f"{key}={value}\n" for key, value in values.items() if key not in seen)
            section = bare[1:-1]
        key = bare.partition("=")[0]
        if section == "Controls" and key in values:
            line = f"{key}={values[key]}{line[len(bare):]}"
            seen.add(key)
        lines.append(line)
    if section == "Controls":
        lines.extend(f"{key}={value}\n" for key, value in values.items() if key not in seen)
    changed = "".join(lines)
    if changed == body:
        return False
    backup = config_path.with_name(config_path.name + ".gbox-touch-original")
    if not backup.exists():
        backup.write_bytes(original)
    config_path.write_bytes(changed.encode("utf-8"))
    return True


def retroarch_driver(executable: str) -> str:
    path = Path(executable)
    try:
        driver = _driver(str(path), path.stat().st_mtime_ns if path.is_file() else 0)
    except _ProbeTimeout:
        # 2026-10-20: the probe timed out on the operator's busy PC and the whole Turok launch failed. Every RetroArch
        # gBox ships has SDL2; play now, ask again next launch (the timeout is not cached).
        return "sdl2"
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


class _ProbeTimeout(Exception):
    """`retroarch --features` didn't answer in time (a PC busy with a game or a build): not cached, probed again next launch."""


@lru_cache(maxsize=8)
def _driver(executable: str, modified: int) -> str:
    # RetroArch's Windows "xinput" driver also enumerates DirectInput joysticks.
    # Use SDL so its per-process device exclusions apply, including on hotplug.
    try:
        result = subprocess.run([executable, "--features"], capture_output=True, text=True,
                                errors="replace", timeout=30,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        # Prefer SDL2 when available; SDL3-only builds get an explicit Xbox profile.
        for version in (2, 3):
            if re.search(rf"^\s*SDL{version}\b[^\r\n]*\byes\s*$", result.stdout, re.M | re.I):
                return f"sdl{version}"
    except subprocess.TimeoutExpired as exc:
        raise _ProbeTimeout(str(exc)) from exc
    except OSError as exc:
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


def _signature(pads: list[dict]) -> tuple:
    """What counts as a change: every button exactly; triggers and sticks coarsely, so resting-stick jitter stays quiet."""
    stick = lambda v: int(v / 1024)                          # toward zero: jitter around the centre is one bucket
    return tuple((p["slot"], p["buttons"], p["lt"] >> 4, p["rt"] >> 4,
                  stick(p["lx"]), stick(p["ly"]), stick(p["rx"]), stick(p["ry"])) for p in pads)


def watch(emit, read=xinput_snapshot, sleep=time.sleep, clock=time.monotonic,
          poll: float = 0.008, heartbeat: float = 0.25, rescan: float = 1.0, ticks: int | None = None) -> None:
    """Stream XInput state to the desktop app: a line the moment anything changes (~8 ms polls), else a heartbeat.

    The desktop view forwards this as Player 1 of a streamed game (#1532), so a change must not wait for a fixed 20 Hz
    tick. Querying an empty XInput slot is slow, so only connected slots are polled; the others once a second.
    """
    last, sent_at, scanned_at, slots = None, float("-inf"), float("-inf"), []
    while ticks is None or ticks > 0:
        now = clock()
        if now - scanned_at >= rescan:
            pads, scanned_at = read(), now
            slots = [p["slot"] for p in pads]
        else:
            pads = read(slots)
            if len(pads) != len(slots):                      # one went away: look at every slot now
                pads, scanned_at = read(), now
                slots = [p["slot"] for p in pads]
        sig = _signature(pads)
        if sig != last or now - sent_at >= heartbeat:
            emit(json.dumps(pads, separators=(",", ":")))
            last, sent_at = sig, now
        if ticks is not None:
            ticks -= 1
        sleep(poll)


if __name__ == "__main__":
    if "--watch" in sys.argv:
        watch(lambda line: print(line, flush=True))
    else:
        print(json.dumps(xinput_devices()))
