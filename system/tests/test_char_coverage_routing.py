"""gbox.char_coverage routing is read from the loaded bytecode, not the file on disk (#1554: a long-running worker
whose characters.py changed after import reported Crazy Taxi as having no routed writer, so cast_swap refused it)."""
import inspect

from gbox import char_coverage as CC

CT = {"game_id": "bc02bb68790ce2e7", "title": "Crazy Taxi (USA)", "platform": "gamecube"}


def _tool(inp):
    from gbox import crazy_taxi_swap
    from gbox import auf_swap as AS
    if inp:
        return crazy_taxi_swap.use(None, {}, {}, inp)
    return AS.use(None, {}, {}, inp)


def _unrouted(inp):
    from gbox import crazy_taxi_swap
    return crazy_taxi_swap.is_slot(inp)


def test_code_routes_reads_aliases_and_calls():
    r = CC.code_routes(_tool)
    assert r["imports"]["crazy_taxi_swap"] == "crazy_taxi_swap" and r["imports"]["AS"] == "auf_swap"
    assert CC.routes_to(r, "crazy_taxi_swap") and CC.routes_to(r, "auf_swap")
    assert not CC.routes_to(CC.code_routes(_unrouted), "crazy_taxi_swap")


def test_crazy_taxi_is_routed():
    w = CC.writer_for(CT)
    assert w["writer"] == "gbox.crazy_taxi_swap" and w["routed"] is True
    assert "driver:<axel|bd_joe|gena|gus>" in w["slots"]


def test_routing_survives_stale_source(monkeypatch):
    # what a worker saw after characters.py was edited on disk under it: getsource slices unrelated lines
    monkeypatch.setattr(inspect, "getsource", lambda obj: "def unrelated():\n    pass\n")
    assert CC.writer_for(CT)["routed"] is True


def test_cast_plan_accepts_crazy_taxi_drivers():
    import pytest
    from gbox import cast_swap
    # past the writer gate the plan resolves donors; an empty collection is the next (expected) refusal
    with pytest.raises(ValueError, match="no character entries"):
        cast_swap.plan(CT, [], "1a3f4cd416db9ffd", "by_role", "", "driver:axel,driver:bd_joe,driver:gena,driver:gus")
