"""#1638: every Windows XInput poller shares one XInputGetState binding and one state structure class.

ctypes caches a DLL's function objects per process, so argtypes assigned to ``windll.xinput1_4.XInputGetState``
are global. gamepads, rewind and padstate each assigned them with a private structure class; the last writer made
the other callers raise ``expected LP_ST instance instead of pointer to ST`` and padstate.watch_xinput died at
session start (desktop console of #1638, padstate.py:168).
"""
import ctypes
import inspect
import os
import types

import httpx
import pytest

from gbox import gamepads, padstate, rewind, xinput


def _private_state_class():
    class ST(ctypes.Structure):                       # the shape each module used to declare for itself
        _fields_ = [("packet", ctypes.c_uint), ("gp", xinput.XInputGamepad)]
    return ST


def _fake_get_state(buttons=0x1000, lt=200, packet=7):
    """XInputGetState stand-in with the shared prototype: only slot 0 holds a pad."""
    def cb(slot, ptr):
        if slot != 0:
            return 1167                                # ERROR_DEVICE_NOT_CONNECTED
        st = ptr.contents
        st.packet, st.gamepad.buttons, st.gamepad.lt = packet, buttons, lt
        return xinput.ERROR_SUCCESS
    return xinput._prototype()(cb)


def test_private_state_classes_on_one_cached_function_reproduce_1638():
    lib = ctypes.CDLL("msvcrt") if os.name == "nt" else ctypes.CDLL(None)   # a private library object
    fn = lib.time                                     # any cached foreign function stands in for XInputGetState
    first, second = _private_state_class(), _private_state_class()
    fn.argtypes = [ctypes.POINTER(first)]             # gamepads / rewind retyped the shared attribute
    with pytest.raises(ctypes.ArgumentError, match="expected LP_ST instance instead of pointer to ST"):
        fn(ctypes.byref(second()))                    # padstate.watch_xinput then passed its own class


@pytest.mark.parametrize("module", [gamepads, padstate, rewind])
def test_pollers_never_retype_the_shared_dll_function(module):
    src = inspect.getsource(module)
    assert "XInputGetState.argtypes" not in src
    assert "xinput.load()" in src


def test_shared_read_rejects_foreign_classes_without_raising():
    fn = _fake_get_state()
    assert xinput.read(fn, 0).packet == 7
    assert xinput.read(fn, 1) is None                 # empty slot
    assert xinput.read(None, 0) is None
    with pytest.raises(ctypes.ArgumentError):
        fn(0, ctypes.byref(_private_state_class()()))  # the prototype only accepts the shared class
    assert xinput.read(lambda slot, ref: (_ for _ in ()).throw(ctypes.ArgumentError("bad")), 0) is None


def test_every_poller_reads_through_the_shared_binding(monkeypatch):
    fn = _fake_get_state(buttons=rewind.BACK | 0x1000, lt=200)
    monkeypatch.setattr(xinput, "load", lambda: fn)
    assert gamepads.xinput_devices() == [0]
    snap = gamepads.xinput_snapshot()
    assert [(s["slot"], s["buttons"], s["lt"]) for s in snap] == [(0, rewind.BACK | 0x1000, 200)]
    pad = rewind.XInputPad()
    assert pad.ok and pad.read() == (True, 200 > rewind.TRIGGER, False, False, False)


def test_off_windows_no_poller_touches_xinput(monkeypatch):
    monkeypatch.setattr(xinput, "os", types.SimpleNamespace(name="posix"))
    assert xinput.load() is None
    assert gamepads.xinput_devices() == [] and gamepads.xinput_snapshot() == []
    assert not rewind.XInputPad().ok and rewind.XInputPad().read() is None


def test_watch_xinput_survives_a_failed_call_and_keeps_mirroring(monkeypatch):
    fn, calls = _fake_get_state(buttons=0x1000, lt=200), []

    def flaky(slot, ref):
        calls.append(slot)
        if len(calls) == 1:
            raise ctypes.ArgumentError("argument 2: TypeError: expected LP_ST instance instead of pointer to ST")
        return fn(slot, ref)
    monkeypatch.setattr(xinput, "load", lambda: flaky)
    monkeypatch.setattr(padstate, "PLAYER_TOUCH", {})
    posts = []

    class Client:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def post(self, url, json): posts.append((url, json))
    monkeypatch.setattr(httpx, "Client", Client)
    ticks = iter(range(4))
    padstate.watch_xinput("http://spark", {}, "win-1638", lambda: next(ticks, None) is not None)
    assert len(calls) >= 2                            # the thread kept polling after the failed call
    assert posts and posts[0][0] == "/api/sessions/win-1638/pad"
    assert posts[0][1]["events"] and all(e["down"] for e in posts[0][1]["events"])
    assert "win-1638" in padstate.PLAYER_TOUCH        # the activity signal ring_record reads on Windows


@pytest.mark.skipif(os.name != "nt", reason="real XInput DLL")
def test_real_binding_ignores_argtypes_another_module_assigns():
    """On Windows: retyping windll.xinput1_4.XInputGetState (what the old pollers did) leaves the shared one working."""
    fn = xinput.load()
    if fn is None:
        pytest.skip("no XInput DLL on this PC")
    dll = next(getattr(ctypes.windll, n) for n in xinput.DLLS if hasattr(ctypes.windll, n))
    shared = dll.XInputGetState
    saved = shared.argtypes
    try:
        shared.argtypes = [ctypes.c_uint, ctypes.POINTER(_private_state_class())]
        for slot in range(4):                         # empty slots return None; nothing raises either way
            assert xinput.read(fn, slot) is None or isinstance(xinput.read(fn, slot), xinput.XInputState)
    finally:
        shared.argtypes = saved
