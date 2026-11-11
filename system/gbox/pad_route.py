"""Decide whether a bot's button press should go to the virtual pad or to the game's own keyboard bindings.

The i9 failure this exists for (2026-11-10): ``DolphinWinAdapter.send_input`` presses ``self.vpad`` whenever the object exists, but the
ViGEm target behind it can quietly stop reporting (the machine had ghost Xbox 360 devices churning through the four XInput slots). The
press is then *acknowledged* - ``{"sent": 2, "via": "dolphin virtual pad (XInput slot 0)"}`` - while the emulator sees nothing, so a
campaign, a mission and a boot sequence all run to completion without touching the game.

The check is behavioural rather than structural: a pad that reports its own press is usable, a pad that does not is not. That is
different from "the slot has a device", because a dead virtual pad still reads as a connected device that reports exact zeros.
"""

from __future__ import annotations

from typing import Callable, Mapping, Sequence

# A button value that no idle controller reports, so a hit in the read-back is proof the press reached the emulator.
SENTINEL_BUTTON = 0x0400


def press_registered(before: Mapping[str, float | int], after: Mapping[str, float | int],
                     button: str = "buttons") -> bool:
    """True when the read-back after a press differs from the read-back before it.

    ``before``/``after`` are slot readings (``{"buttons": ..., "lx": ..., "ly": ...}``). Any change counts: a digital press changes
    ``buttons``, a stick press changes ``lx``/``ly``, and a dead pad changes nothing at all.
    """
    keys = set(before) | set(after)
    for key in keys:
        if before.get(key) != after.get(key):
            return True
    return False


def choose_path(vpad_present: bool, probe: Callable[[], bool] | None) -> str:
    """``"vpad"`` when a virtual pad exists and its probe proves a press lands, else ``"keyboard"``.

    ``probe`` performs one press and read-back (``press`` then ``press_registered``); ``None`` means it was never attempted. A missing
    probe is treated as unproven, because pressing a pad nobody has shown to work is exactly the silent-drop this fixes.
    """
    if not vpad_present:
        return "keyboard"
    if probe is None:
        return "keyboard"
    try:
        return "vpad" if probe() else "keyboard"
    except Exception:                                              # noqa: BLE001 - a failing probe is not a working pad
        return "keyboard"


def slot_reading(state) -> dict:
    """Reduce an XInput slot reading (as ``xinput.read`` returns it) to the comparable fields ``press_registered`` uses."""
    if state is None:
        return {}
    pad = getattr(state, "gamepad", state)
    return {name: getattr(pad, name, None) for name in ("buttons", "lx", "ly", "rx", "ry", "lt", "rt")}


def keyboard_events(events: Sequence[dict], keymap: Mapping[str, str]) -> list[dict]:
    """Translate pad names to keyboard names for the adapter's ``win_send_keys`` branch (``z`` -> ``e``, ``dup`` -> ``t``...).

    Unmapped names pass through unchanged, so a caller that already uses keyboard names keeps working.
    """
    return [{**event, "key": keymap.get(event["key"], event["key"])} for event in events]


def report(path: str, vpad_slot, probe_result) -> dict:
    """One structured line for the session detail/log, so a dropped pad is visible instead of silent."""
    return {"input_path": path, "vpad_slot": vpad_slot, "vpad_probe": probe_result,
            "reason": ("the virtual pad does not report its own presses" if path == "keyboard"
                       else "the virtual pad reports its presses")}
