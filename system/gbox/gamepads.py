"""Windows emulator gamepad discovery without 3Dconnexion navigation devices."""
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

from .registry import ToolUnavailable


def retroarch_driver(executable: str) -> str:
    path = Path(executable)
    return _driver(str(path), path.stat().st_mtime_ns if path.is_file() else 0)


@lru_cache(maxsize=8)
def _driver(executable: str, modified: int) -> str:
    # RetroArch's Windows "xinput" driver also enumerates DirectInput joysticks.
    # Use SDL so its per-process device exclusions apply, including on hotplug.
    try:
        result = subprocess.run([executable, "--features"], capture_output=True, text=True,
                                errors="replace", timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        # SDL2 first: its Xbox autoconfig profiles are mature. RetroArch's SDL3 joypad driver is new, ships no profiles
        # (autoconfig/sdl3 has only gamecontrollerdb.cfg) and inverted the N64 stick's up/down on this PC (2026-10-08).
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
