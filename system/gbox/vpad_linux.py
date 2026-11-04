"""Focus-independent virtual GameCube pad for Linux Dolphin autoplay (a /dev/uinput evdev gamepad).

Why this exists. On the Spark's private Xvfb session displays there is NO window manager, so a synthetic X key
event (xdotool / XTEST) has no focused window to land on and Dolphin's ``XInput2/0/Virtual core pointer`` keyboard
device never sees it - PSO's campaign, which drives its menus with synthetic key presses, could never leave the
title/attract loop (capture and menu recognition already worked there; input was the last blocker, #1153 class at
the RetroArch adapter's send_input). RE5/RE6 autoplay sidestep this with the eden/RetroArch UDP pad and RE4 GC with
native RAM/debugger dispatch, but a GameCube game driven through Dolphin's own pad had no focus-independent path.

This is the Linux analog of ``gbox/vpad_win.py`` (the Windows ViGEm/XInput pad). A ``/dev/uinput`` virtual gamepad is
a real evdev input device the kernel publishes at ``/dev/input/eventN``; Dolphin's evdev controller backend polls it
every frame regardless of X focus (``Dolphin.Input.BackgroundInput=True``), exactly like a controller plugged into
the PC. It unblocks EVERY Dolphin game on the Spark, not only PSO.

No dependency, no install. It talks to ``/dev/uinput`` with raw ioctls (``struct uinput_user_dev`` + ``input_event``),
so it needs neither python-evdev (absent on the aarch64 service venv) nor any build step, and it is hot-reloadable.

Deterministic names. The device declares ``BTN_JOYSTICK`` so Dolphin's evdev backend uses its NumberedButton/Axis
scheme - buttons are ``Button N`` (N = ascending position among the device's EV_KEY codes) and axes ``Axis N+``/
``Axis N-`` (N = ascending position among its EV_ABS codes). Both are derived purely from the order this module
declares codes, so ``gcpad_section`` and the device can never disagree and there is no libevdev-name ambiguity.

Permissions. The worker user must be able to open ``/dev/uinput`` (a udev rule puts it in the ``input`` group) and
the Dolphin flatpak (devices=all) reads the created ``/dev/input/eventN`` as the same user in the ``input`` group -
see the deploy note; this mirrors the video/render groups fix that unblocked RE5/6 rendering.

Scope / safety. Created only by ``DolphinAdapter`` on Linux, only for PSO (gecko id ``GPO*``) or when
``GBOX_DOLPHIN_VPAD`` opts a session in. Never touched by the Eden/RetroArch adapters (RE5/6) or the Windows ViGEm
path (the i9). When ``/dev/uinput`` is unavailable the adapter silently keeps the existing keyboard path.
"""
from __future__ import annotations

import fcntl
import os
import struct
import sys
import threading
import time

UINPUT_PATH = "/dev/uinput"

# ioctl request codes (asm-generic, matches aarch64 and x86_64).
#   _IO('U', n)            -> (0x55 << 8) | n
#   _IOW('U', n, sizeof(int)=4) -> (1<<30) | (4<<16) | (0x55<<8) | n
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_SET_EVBIT = 0x40045564          # _IOW('U', 100, int)
UI_SET_KEYBIT = 0x40045565         # _IOW('U', 101, int)
UI_SET_ABSBIT = 0x40045567         # _IOW('U', 103, int)

EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03
SYN_REPORT = 0x00

ABS_X, ABS_Y, ABS_RX, ABS_RY = 0x00, 0x01, 0x03, 0x04
ABS_CNT = 64                                              # size of the absmin/absmax/... arrays in uinput_user_dev

BUS_USB = 0x03
AXIS_MAX = 32767
AXIS_MIN = -32768

# Digital buttons in ASCENDING evdev key-code order. Dolphin's evdev backend (when the device has BTN_JOYSTICK, which
# 0x120 is) names the Nth key code "Button N", so each name's Dolphin input is "Button <its index here>". 0x120 is
# BTN_JOYSTICK/BTN_TRIGGER, which is what forces the NumberedButton scheme.
BUTTON_ORDER = ["a", "b", "x", "y", "z", "start", "l", "r", "dup", "ddown", "dleft", "dright", "select"]
BUTTON_CODE = {name: 0x120 + i for i, name in enumerate(BUTTON_ORDER)}
BUTTON_INDEX = {name: i for i, name in enumerate(BUTTON_ORDER)}
# Trigger aliases share the L/R button codes (the GC campaign sends l/l2, r/r2 for the same analog triggers).
BUTTON_CODE["l2"] = BUTTON_CODE["l"]
BUTTON_CODE["r2"] = BUTTON_CODE["r"]
BUTTON_INDEX["l2"] = BUTTON_INDEX["l"]
BUTTON_INDEX["r2"] = BUTTON_INDEX["r"]

# EV_ABS codes in ASCENDING order -> Dolphin "Axis N" index. Main stick = ABS_X/ABS_Y, C-stick = ABS_RX/ABS_RY.
ABS_ORDER = [ABS_X, ABS_Y, ABS_RX, ABS_RY]
ABS_AXIS_INDEX = {code: i for i, code in enumerate(ABS_ORDER)}

# Stick pad name -> (abs code, sign). evdev up is negative Y, so GC "up" writes ABS_Y negative; gcpad_section binds
# GC Up to "Axis <y>-" so the two always agree. lup/ldown/... are accepted too (the P1 campaign folds them onto
# up/down/... but be tolerant).
_LSTICK = {"up": (ABS_Y, -1), "down": (ABS_Y, 1), "left": (ABS_X, -1), "right": (ABS_X, 1),
           "lup": (ABS_Y, -1), "ldown": (ABS_Y, 1), "lleft": (ABS_X, -1), "lright": (ABS_X, 1)}
_RSTICK = {"cup": (ABS_RY, -1), "cdown": (ABS_RY, 1), "cleft": (ABS_RX, -1), "cright": (ABS_RX, 1)}

KEYS = set(BUTTON_CODE) | set(_LSTICK) | set(_RSTICK)


def _axis_field(code: int, sign: int) -> str:
    return "Axis %d%s" % (ABS_AXIS_INDEX[code], "-" if sign < 0 else "+")


def gcpad_section(player: int, device_name: str) -> str:
    """The complete ``[GCPad<player>]`` section binding a GameCube pad to the evdev device ``device_name`` with the
    deterministic Button/Axis names this module's device layout produces. ``Options/Always Connected`` keeps the port
    up while the pad rests at neutral between presses."""
    lines = [
        "[GCPad%d]" % player,
        "Device = evdev/0/%s" % device_name,
        "Options/Always Connected = True",
        "Buttons/A = `Button %d`" % BUTTON_INDEX["a"],
        "Buttons/B = `Button %d`" % BUTTON_INDEX["b"],
        "Buttons/X = `Button %d`" % BUTTON_INDEX["x"],
        "Buttons/Y = `Button %d`" % BUTTON_INDEX["y"],
        "Buttons/Z = `Button %d`" % BUTTON_INDEX["z"],
        "Buttons/Start = `Button %d`" % BUTTON_INDEX["start"],
        "Main Stick/Up = `%s`" % _axis_field(ABS_Y, -1),
        "Main Stick/Down = `%s`" % _axis_field(ABS_Y, 1),
        "Main Stick/Left = `%s`" % _axis_field(ABS_X, -1),
        "Main Stick/Right = `%s`" % _axis_field(ABS_X, 1),
        "C-Stick/Up = `%s`" % _axis_field(ABS_RY, -1),
        "C-Stick/Down = `%s`" % _axis_field(ABS_RY, 1),
        "C-Stick/Left = `%s`" % _axis_field(ABS_RX, -1),
        "C-Stick/Right = `%s`" % _axis_field(ABS_RX, 1),
        "Triggers/L = `Button %d`" % BUTTON_INDEX["l"],
        "Triggers/R = `Button %d`" % BUTTON_INDEX["r"],
        "Triggers/L-Analog = `Button %d`" % BUTTON_INDEX["l"],
        "Triggers/R-Analog = `Button %d`" % BUTTON_INDEX["r"],
        "D-Pad/Up = `Button %d`" % BUTTON_INDEX["dup"],
        "D-Pad/Down = `Button %d`" % BUTTON_INDEX["ddown"],
        "D-Pad/Left = `Button %d`" % BUTTON_INDEX["dleft"],
        "D-Pad/Right = `Button %d`" % BUTTON_INDEX["dright"],
    ]
    return "\n".join(lines) + "\n"


def available() -> bool:
    """True when a virtual pad can be created on this host (Linux + /dev/uinput openable for writing)."""
    if os.name != "nt" and sys.platform.startswith("linux"):
        try:
            fd = os.open(UINPUT_PATH, os.O_WRONLY | os.O_NONBLOCK)
            os.close(fd)
            return True
        except OSError:
            return False
    return False


def _clamp(v: int) -> int:
    return AXIS_MAX if v > 0 else (AXIS_MIN if v < 0 else 0)


class VGamepad:
    """One virtual GameCube-style evdev gamepad, held-state rendered in full on every change.

    ``set(held)`` holds exactly the given gBox pad names; ``apply(events)`` consumes send_input rows ({key, down})
    with the same down/up + same-batch-tap semantics as the keyboard sender (and the ViGEm pad), so a bot never
    notices the difference. ``device`` is the GCPadNew.ini device string Dolphin binds to."""

    TAP_S = 0.035                                            # two frames: a press released in the same batch is still seen

    def __init__(self, name: str = "gBox GC Pad", vendor: int = 0x6762, product: int = 0x6763):
        self.name = name[:79]
        self.lock = threading.RLock()
        self.held: set[str] = set()
        self._fd = os.open(UINPUT_PATH, os.O_WRONLY | os.O_NONBLOCK)
        try:
            self._create(vendor, product)
        except Exception:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
            raise

    @property
    def device(self) -> str:
        return "evdev/0/%s" % self.name

    def gcpad_section(self, player: int) -> str:
        return gcpad_section(player, self.name)

    def _create(self, vendor: int, product: int) -> None:
        fd = self._fd
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_ABS)
        for code in sorted(set(BUTTON_CODE.values())):
            fcntl.ioctl(fd, UI_SET_KEYBIT, code)
        for code in ABS_ORDER:
            fcntl.ioctl(fd, UI_SET_ABSBIT, code)
        absmin = [0] * ABS_CNT
        absmax = [0] * ABS_CNT
        for code in ABS_ORDER:
            absmin[code] = AXIS_MIN
            absmax[code] = AXIS_MAX
        # struct uinput_user_dev { char name[80]; struct input_id{u16 bus,vendor,product,version};
        #   u32 ff_effects_max; s32 absmax[64]; s32 absmin[64]; s32 absfuzz[64]; s32 absflat[64]; }
        dev = struct.pack(
            "<80sHHHHI" + ("%di" % (ABS_CNT * 4)),
            self.name.encode("utf-8"), BUS_USB, vendor & 0xFFFF, product & 0xFFFF, 1, 0,
            *absmax, *absmin, *([0] * ABS_CNT), *([0] * ABS_CNT))
        os.write(fd, dev)
        fcntl.ioctl(fd, UI_DEV_CREATE)
        time.sleep(0.05)                                     # let udev publish /dev/input/eventN before Dolphin enumerates

    def _emit(self, etype: int, code: int, value: int) -> None:
        # struct input_event { struct timeval{long sec; long usec}; u16 type; u16 code; s32 value } on 64-bit.
        os.write(self._fd, struct.pack("<qqHHi", 0, 0, etype, code, value))

    def _render(self) -> None:
        if self._fd is None:
            return
        axes = {ABS_X: 0, ABS_Y: 0, ABS_RX: 0, ABS_RY: 0}
        down_codes: set[int] = set()
        for name in self.held:
            if name in BUTTON_CODE:
                down_codes.add(BUTTON_CODE[name])
            elif name in _LSTICK:
                code, sign = _LSTICK[name]
                axes[code] += sign
            elif name in _RSTICK:
                code, sign = _RSTICK[name]
                axes[code] += sign
        for code in sorted(set(BUTTON_CODE.values())):
            self._emit(EV_KEY, code, 1 if code in down_codes else 0)
        for code in ABS_ORDER:
            self._emit(EV_ABS, code, _clamp(axes[code]))
        self._emit(EV_SYN, SYN_REPORT, 0)

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
            self.held = set(held)
            self._render()
            return {"sent": len(rows), "via": "dolphin virtual pad (%s)" % self.device,
                    "held": sorted(self.held)}

    def release(self) -> None:
        with self.lock:
            self.held = set()
            try:
                self._render()
            except OSError:
                pass

    def close(self) -> None:
        with self.lock:
            fd, self._fd = self._fd, None
            if fd is None:
                return
            try:
                fcntl.ioctl(fd, UI_DEV_DESTROY)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass
