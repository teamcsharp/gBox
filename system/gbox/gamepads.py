"""Windows emulator gamepad discovery without 3Dconnexion navigation devices."""
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

from .registry import ToolUnavailable


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
    blocked = ["0xbeef/0x046d"]  # virtual KMJ joystick
    blocked += [f"0x256f/0x{pid}" for pid in
                ("c62e", "c62f", "c631", "c632", "c633", "c635", "c636", "c638", "c652")]
    blocked += [f"0x046d/0x{pid}" for pid in
                ("c603", "c605", "c606", "c621", "c623", "c625", "c626", "c627", "c628", "c629", "c62b")]
    env["SDL_GAMECONTROLLER_IGNORE_DEVICES"] = ",".join(filter(None, [
        env.get("SDL_GAMECONTROLLER_IGNORE_DEVICES", ""), *blocked]))
    return env
