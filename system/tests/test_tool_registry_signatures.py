"""Every registered tool is the function written under its @tool line (2026-10-27 09:44: #1299 put _park_autobot
between @tool("session_op") and session_op, so every session_op ran _park_autobot(SessionIn, ctx) and failed
"unhashable type: 'SessionIn'": MercMode's warm resume, pause, stop_game and F5 all broke and the rotation stalled)."""
import inspect

from gbox import tools
from gbox.registry import REGISTRY


def test_session_op_is_registered_as_session_op():
    assert REGISTRY["session_op"].fn is tools.session_op


def test_every_tool_takes_its_input_model_and_a_context():
    wrong = []
    for name, t in REGISTRY.items():
        params = list(inspect.signature(t.fn).parameters.values())
        first = params[0].annotation if params else inspect.Parameter.empty
        named = getattr(first, "__name__", first)
        if len(params) < 2 or (first is not inspect.Parameter.empty and named != t.In.__name__):
            wrong.append((name, t.fn.__name__, str(named)))
    assert wrong == []
