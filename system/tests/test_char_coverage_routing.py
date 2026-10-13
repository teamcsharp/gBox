"""#1361: char_coverage.writer_for must judge routing by the LOADED characters_tool, not by whatever file is on disk.
A worker that started before a deploy kept old code in memory; getsource then read the new file by stale line numbers
and DOA2 LE's cast_swap plan reported "no routed character writer"."""
import types

from gbox import char_coverage as CC
from gbox import characters as C

DOA2 = {"game_id": "1de2e7634f3161ff", "title": "Dead or Alive 2 - Limited Edition (Japan)", "platform": "dreamcast"}


def test_doa2_le_writer_is_routed():
    w = CC.writer_for(DOA2)
    assert w and w["writer"] == "gbox.doa2_swap" and w["routed"] is True


def test_routed_survives_stale_source(monkeypatch):
    # the file on disk no longer matches the loaded function (deploy after the worker started)
    monkeypatch.setattr(CC.inspect, "getsource", lambda fn: "def other_tool(x):\n    return x\n")
    w = CC.writer_for(DOA2)
    assert w and w["routed"] is True


def test_routed_survives_missing_source(monkeypatch):
    def boom(fn):
        raise OSError("could not get source code")
    monkeypatch.setattr(CC.inspect, "getsource", boom)
    assert CC.writer_for(DOA2)["routed"] is True


def test_unrouted_code_stays_unrouted(monkeypatch):
    def characters_tool(inp):                                # never reaches doa2_swap.use
        return {"result": inp}
    monkeypatch.setattr(C, "characters_tool", characters_tool)
    monkeypatch.setattr(CC.inspect, "getsource", lambda fn: "def characters_tool(inp):\n    return {'result': inp}\n")
    assert CC.writer_for(DOA2)["routed"] is False


def test_code_names_reach_nested_functions():
    def outer():
        def inner():
            from gbox import doa2_swap
            return doa2_swap.use
        return inner
    names = CC._code_names(outer)
    assert {"doa2_swap", "use"} <= names
