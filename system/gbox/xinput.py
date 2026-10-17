"""One XInputGetState binding for every Windows pad poller in gBox (#1638).

ctypes caches ``ctypes.windll.xinput1_4`` per process, and with it the ``XInputGetState`` function object, so
``argtypes`` assigned to that attribute are process-wide. gamepads.py, rewind.py and padstate.py each declared a
private XINPUT_STATE class and assigned ``argtypes`` with it; whichever ran last made the others raise
``ctypes.ArgumentError: argument 2: TypeError: expected LP_ST instance instead of pointer to ST``. On #1638 that
killed padstate.watch_xinput one second into the session: the controller mirror and the PLAYER_TOUCH activity
signal stopped for the rest of the game. Every poller now uses these structure classes and :func:`load`, which
builds a private prototype and never retypes the DLL's shared attribute.
"""
from __future__ import annotations

import ctypes
import os
import threading

ERROR_SUCCESS = 0
DLLS = ("xinput1_4", "xinput9_1_0")


class XInputGamepad(ctypes.Structure):
    _fields_ = [("buttons", ctypes.c_ushort), ("lt", ctypes.c_ubyte), ("rt", ctypes.c_ubyte),
                ("lx", ctypes.c_short), ("ly", ctypes.c_short), ("rx", ctypes.c_short), ("ry", ctypes.c_short)]


class XInputState(ctypes.Structure):
    _fields_ = [("packet", ctypes.c_uint), ("gamepad", XInputGamepad)]


_lock = threading.Lock()
_loaded: list = []                                   # [function or None] once resolved


def _prototype():
    factory = getattr(ctypes, "WINFUNCTYPE", None) or ctypes.CFUNCTYPE
    return factory(ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(XInputState))


def bind(dll):
    """A private XInputGetState for `dll`: a new function object, so code that assigns argtypes to
    ``dll.XInputGetState`` can't change the signature gBox's pollers call."""
    return _prototype()(("XInputGetState", dll))


def load():
    """XInputGetState from xinput1_4 (else xinput9_1_0); None off Windows or without XInput."""
    if os.name != "nt":
        return None
    with _lock:
        if not _loaded:
            fn = None
            for name in DLLS:
                try:
                    fn = bind(getattr(ctypes.windll, name))
                    break
                except (OSError, AttributeError):
                    continue
            _loaded.append(fn)
        return _loaded[0]


def read(fn, slot: int, state: XInputState | None = None) -> XInputState | None:
    """Pad `slot`'s state, or None when the slot is empty or the call fails. Never raises, so one bad call
    can't end a poller thread."""
    if fn is None:
        return None
    state = XInputState() if state is None else state
    try:
        return state if fn(slot, ctypes.byref(state)) == ERROR_SUCCESS else None
    except (ctypes.ArgumentError, OSError, ValueError, TypeError):
        return None
