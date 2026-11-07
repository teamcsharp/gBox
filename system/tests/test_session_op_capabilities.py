"""`session_op` must not hand an op to an emulator that declares it unsupported.

The failure this pins: `load_state` on the Switch session (Eden has no save states, and says so in `checkpoint_reason`)
was dispatched anyway, pressed an F-key and raised `KeyError: 'load_state'` out of an adapter whose hotkey table has no
such entry - which the operator saw as a dead autoplay with the game sitting still.
"""
import pathlib
import re

import pytest

TOOLS = pathlib.Path(__file__).resolve().parent.parent / "gbox" / "tools.py"


def dispatch_source() -> str:
    return TOOLS.read_text(encoding="utf-8")


def test_the_dispatcher_checks_the_adapters_supported_set():
    body = dispatch_source()
    assert 'supported = getattr(ad, "supported", None)' in body
    assert 'if supported is not None and inp.op not in supported and inp.op != "stop_game":' in body
    assert "is not available on this emulator" in body


def test_the_guard_comes_before_the_call_and_names_the_reason():
    body = dispatch_source()
    guard = body.index("is not available on this emulator")
    call = body.index("res = getattr(ad, inp.op)(**inp.args)", guard)
    assert guard < call, "the capability guard must run before the adapter call"
    assert 'getattr(ad, "checkpoint_reason", "")' in body
