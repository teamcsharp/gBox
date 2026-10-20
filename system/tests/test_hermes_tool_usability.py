"""2026-10-19: 60 of 148 Hermes tool calls failed in 12 h; the commonest were assimilate called with an op synonym or
no game, and inspection_builds plan/publish without a game_id (a 307 redirect, no reason)."""
from types import SimpleNamespace

import pytest

from gbox import assimilate as A, inspection_builds as IB


def test_assimilate_accepts_op_synonyms_and_explains_a_missing_game():
    out = A.assimilate.__wrapped__(A.AssimilateIn(op="list"), SimpleNamespace()) if hasattr(A.assimilate, "__wrapped__") \
        else A.assimilate(A.AssimilateIn(op="list"), SimpleNamespace())
    assert out["op"] == "known" and out["result"]["titles"]
    with pytest.raises(ValueError, match="game_id .*path .*title"):
        A.assimilate(A.AssimilateIn(op="scan"), SimpleNamespace(progress=lambda *a: None))
    with pytest.raises(ValueError, match="fingerprint \| known \| evaluate"):
        A.assimilate(A.AssimilateIn(op="disassemble"), SimpleNamespace())


def test_inspection_builds_plan_needs_a_game_id_and_reports_the_server_reason(monkeypatch):
    ctx = SimpleNamespace(server="http://cp", headers={})
    with pytest.raises(ValueError, match="needs game_id"):
        IB.watch(IB.WatchIn(op="publish", game_id=" "), ctx)

    class R:
        status_code = 422

        def json(self):
            return {"detail": "Describe the reviewed change_id"}
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())
    with pytest.raises(ValueError, match="HTTP 422: Describe the reviewed change_id"):
        IB.watch(IB.WatchIn(op="publish", game_id="g1", value={}), ctx)
