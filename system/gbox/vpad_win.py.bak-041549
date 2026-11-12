"""Focus-independent virtual Xbox 360 gamepad for Windows Dolphin autoplay (ViGEmBus via a vendored vgamepad).

Why this exists. gBox's keyboard input (``win_send_keys``) is delivered with ``SendInput`` and only reaches the game
while the Dolphin window owns the foreground/focus. On a dedicated display (the Spark's :92/:93) that is always true,
but on a shared, churning Windows desktop (the i9-NUC) Dolphin keeps losing the foreground and the i9 also mis-reports
the operator as active, so the "polite" verdict withholds the bot's key presses and even the non-polite path's per-press
``give_focus`` only lands intermittently. The game never gets driven off its attract/title loop. A virtual *XInput* pad
sidesteps focus entirely: Dolphin's XInput backend polls it every frame with ``Dolphin.Input.BackgroundInput=True``
whether or not the window is focused, exactly like a real controller plugged into the PC.

Why a vendored vgamepad and no install. A virtual XInput pad needs the ViGEmBus kernel driver. gBox must never install
that driver (see ``gbox/doa3_pad.py``); here it is already present on the i9-NUC (the operator's Virtual Desktop / Oculus
stack registers "Nefarius Virtual Gamepad Emulation Bus"). vgamepad ships only as an sdist whose ``setup.py`` would run
the ViGEmBus installer, so instead of ``pip install`` the package (with its bundled ``ViGEmClient.dll``) is vendored under
``gbox-data/vgamepad-lib`` and imported straight from there. Nothing is installed; the existing driver is only *used*.

Scope / safety. This path is opt-in and Windows only. It is created by ``DolphinWinAdapter`` alone, only for PSO (gecko
id ``GPO*``) or when ``GBOX_DOLPHIN_VPAD`` opts a session in. It is never touched by the Linux/Eden adapters (the Spark's
RE sessions) or any other adapter, and when vgamepad or the driver is unavailable the adapter silently keeps the existing
keyboard path. The pad only *adds* a controller to a free XInput slot; the operator's own pad and keyboard are untouched.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

# The vendored vgamepad package (with its bundled ViGEmClient.dll). gbox-data sits beside the gbox package.
VENDOR = Path(__file__).resolve().parents[1] / "gbox-data" / "vgamepad-lib"

_vg = None
_vg_lock = threading.Lock()


def _vgamepad():
    """Import the vendored vgamepad (cached). Raises if it or the ViGEmBus driver is unavailable."""
    global _vg
    with _vg_lock:
        if _vg is None:
            if VENDOR.is_dir() and str(VENDOR) not in sys.path:
                sys.path.insert(0, str(VENDOR))
            import vgamepad as vg
            _vg = vg
        return _vg


def available() -> bool:
    """True when a virtual pad can be created on this host (Windows + vgamepad importable + ViGEmBus present)."""
    if os.name != "nt":
        return False
    try:
        _vgamepad()
        return True
    except Exception:                                        # noqa: BLE001 - any import/driver failure: fall back to keys
        return False


def _button_map(vg):
    """gBox pad name -> XUSB button. GameCube-on-XInput follows DolphinWinAdapter.PAD_INI_WIN: A/B/X/Y are the face
    buttons, Z is the right shoulder, the GC L/R are the analog triggers (handled separately), the main stick is the
    left stick and the C-stick the right stick."""
    B = vg.XUSB_BUTTON
    return {
        "a": B.XUSB_GAMEPAD_A, "b": B.XUSB_GAMEPAD_B, "x": B.XUSB_GAMEPAD_X, "y": B.XUSB_GAMEPAD_Y,
        "z": B.XUSB_GAMEPAD_RIGHT_SHOULDER, "start": B.XUSB_GAMEPAD_START,
        "select": B.XUSB_GAMEPAD_BACK, "back": B.XUSB_GAMEPAD_BACK,
        "l3": B.XUSB_GAMEPAD_LEFT_THUMB, "r3": B.XUSB_GAMEPAD_RIGHT_THUMB,
        "dup": B.XUSB_GAMEPAD_DPAD_UP, "ddown": B.XUSB_GAMEPAD_DPAD_DOWN,
        "dleft": B.XUSB_GAMEPAD_DPAD_LEFT, "dright": B.XUSB_GAMEPAD_DPAD_RIGHT,
    }


# GC L/R triggers (the campaign uses l / r; l2 / r2 are aliases for the same analog triggers).
_LTRIG = {"l", "l2"}
_RTRIG = {"r", "r2"}
# Main stick (left) directions. up/down/left/right are analog-stick aliases in the campaign (P1_ALIASES folds
# lup/ldown/lleft/lright onto them before send_input is called, but accept both to be safe).
_LSTICK = {"up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0),
           "lup": (0, 1), "ldown": (0, -1), "lleft": (-1, 0), "lright": (1, 0)}
# C-stick (right) directions.
_RSTICK = {"cup": (0, 1), "cdown": (0, -1), "cleft": (-1, 0), "cright": (1, 0)}
_DIGITAL_NAMES = {"a", "b", "x", "y", "z", "start", "select", "back", "l3", "r3",
                  "dup", "ddown", "dleft", "dright"}
KEYS = _DIGITAL_NAMES | _LTRIG | _RTRIG | set(_LSTICK) | set(_RSTICK)


def _clamp(v: int) -> int:
    return 32767 if v > 0 else (-32768 if v < 0 else 0)


class VGamepad:
    """One virtual Xbox 360 controller, held-state rendered in full on every change.

    ``set(held)`` holds exactly the given gBox pad names; ``apply(events)`` consumes send_input rows ({key, down})
    with the same down/up + same-batch-tap semantics as the keyboard sender, so a bot never notices the difference.
    """

    TAP_S = 0.035                                            # two frames: a press released in the same batch is still seen

    def __init__(self):
        vg = _vgamepad()
        self._vg = vg
        self._buttons = _button_map(vg)
        from . import xinput
        self._xinput = xinput
        self.lock = threading.RLock()
        self.held: set[str] = set()
        self.pad = vg.VX360Gamepad()
        self.slot = self._detect_slot()                      # the XInput slot Dolphin must bind (XInput/<slot>/Gamepad)

    def _detect_slot(self):
        """Find this pad's XInput slot (0-3) by a sentinel trigger value no idle controller shows, so a pre-existing
        pad in slot 0 (the i9's persistent virtual pad) is never mistaken for ours. None when it cannot be read."""
        fn = self._xinput.load()
        if fn is None:
            return None
        found = None
        try:
            self.pad.left_trigger(value=173)
            self.pad.update()
            time.sleep(0.12)
            for s in range(4):
                st = self._xinput.read(fn, s)
                if st is not None and 150 <= st.gamepad.lt <= 195:
                    found = s
                    break
        finally:
            self.pad.left_trigger(value=0)
            self.pad.update()
        return found

    def _render(self):
        pad = self.pad
        pad.reset()
        lx = ly = rx = ry = 0
        for name in self.held:
            if name in self._buttons:
                pad.press_button(button=self._buttons[name])
            elif name in _LTRIG:
                pad.left_trigger(value=255)
            elif name in _RTRIG:
                pad.right_trigger(value=255)
            elif name in _LSTICK:
                dx, dy = _LSTICK[name]
                lx += dx
                ly += dy
            elif name in _RSTICK:
                dx, dy = _RSTICK[name]
                rx += dx
                ry += dy
        pad.left_joystick(x_value=_clamp(lx), y_value=_clamp(ly))
        pad.right_joystick(x_value=_clamp(rx), y_value=_clamp(ry))
        pad.update()

    def set(self, held) -> None:
        with self.lock:
            self.held = {str(k).lower() for k in held if str(k).lower() in KEYS}
            self._render()

    def apply(self, events: list[dict], sleep=None) -> dict:
        sleep = sleep or time.sleep
        with self.lock:
            rows = [ev for ev in events if str(ev["key"]).lower() in KEYS]
            held, pressed = set(self.held), set()
            for i, ev in enumerate(rows):
                key = str(ev["key"]).lower()
                if ev.get("down", True):
                    held.add(key)
                    pressed.add(key)
                else:
                    if key in pressed:                       # down + up in one batch: let the game see the press first
                        self.held = set(held)
                        self._render()
                        sleep(self.TAP_S)
                        pressed.discard(key)
                        held.discard(key)
                        if i + 1 < len(rows):                # and its release, before anything that follows
                            self.held = set(held)
                            self._render()
                            sleep(self.TAP_S)
                    held.discard(key)
            if rows:
                self.held = set(held)
                self._render()
            return {"sent": len(rows), "via": f"dolphin virtual pad (XInput slot {self.slot})",
                    "held": sorted(self.held)}

    def release(self) -> None:
        with self.lock:
            self.held = set()
            try:
                self.pad.reset()
                self.pad.update()
            except Exception:                                # noqa: BLE001 - best effort; a dead pad needs nothing released
                pass

    def close(self) -> None:
        with self.lock:
            try:
                self.pad.reset()
                self.pad.update()
            except Exception:                                # noqa: BLE001
                pass
            self.pad = None
