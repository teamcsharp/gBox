"""Focused tests for gbox/bot_directive.py (request #5326: operator-directed bot control)."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox import bot_directive as bd


def test_directive_validation():
    try:
        bd.Directive(kind="teleport")
        raise AssertionError("unknown kind accepted")
    except bd.DirectiveError:
        pass
    try:
        bd.Directive(kind=bd.MOVE_TO)
        raise AssertionError("move_to without a target accepted")
    except bd.DirectiveError:
        pass
    try:
        bd.Directive(kind=bd.WAIT)
        raise AssertionError("wait without seconds accepted")
    except bd.DirectiveError:
        pass
    try:
        bd.Directive(kind=bd.PARAM_SET)
        raise AssertionError("param_set without params accepted")
    except bd.DirectiveError:
        pass
    d = bd.Directive(kind=bd.MOVE_TO, target=(1, 2, 3), priority=5)
    assert d.target == (1.0, 2.0, 3.0) and d.priority == 5
    assert bd.Directive(kind=bd.HOLD).kind == bd.HOLD


def test_json_roundtrip():
    d = bd.Directive(kind=bd.FIGHT, target=(0, 0, 12), note="go", priority=1,
                     expires_in_s=9.0)
    back = bd.Directive.from_dict(d.to_dict())
    assert back == d
    j = d.to_dict()
    assert isinstance(j["target"], list) and j["note"] == "go"
    p = bd.ParamSet(difficulty="01", burst_s=1.5, strafe=False)
    assert bd.ParamSet.from_dict(p.to_dict()).set_fields() == p.set_fields()
    lp = bd.LogicPreset(name="pacifist", params={"difficulty": "00"}, objective="survive")
    assert bd.LogicPreset.from_dict(lp.to_dict()) == lp


def test_paramset_merges_without_clobbering():
    base = {"reaction_s": 0.8, "aim_jitter_deg": 7.0, "turn_rate": 400.0}
    out = bd.ParamSet(aim_jitter_deg=2.0).merged(base)
    assert out == {"reaction_s": 0.8, "aim_jitter_deg": 2.0, "turn_rate": 400.0}
    assert base["aim_jitter_deg"] == 7.0          # base never mutated
    assert bd.ParamSet().merged(base) == base     # empty set is a no-op
    lp = bd.LogicPreset(name="hard", params={"difficulty": "02", "reaction_s": 0.3})
    assert lp.apply(base) == {"difficulty": "02", "reaction_s": 0.3}   # full swap


def test_queue_priority_fifo_and_ttl():
    q = bd.DirectiveQueue()
    q.add(bd.Directive(kind=bd.HOLD, priority=10))
    q.add(bd.Directive(kind=bd.STOP, priority=1))
    q.add(bd.Directive(kind=bd.HOLD, priority=10))       # same priority: FIFO after the first HOLD
    due, stale = q.pop_due(now=100.0)                    # all issued at ~now, none expired
    assert [d.kind for d in due] == [bd.STOP, bd.HOLD, bd.HOLD]
    assert stale == [] and q.size() == 0                  # pop_due drains

    q.add(bd.Directive(kind=bd.WAIT, seconds=5.0, priority=50, expires_in_s=1.0))
    due, stale = q.pop_due(now=q._heap[0].issued_at + 5.0)
    assert due == [] and len(stale) == 1                  # expired: dropped but reported

    q.add(bd.Directive(kind=bd.MOVE_TO, target=(1, 1, 1)))
    assert len(q.pending()) == 1


def test_queue_thread_safety():
    q = bd.DirectiveQueue()
    n_per_thread = 200

    def worker(i):
        for k in range(n_per_thread):
            q.add(bd.Directive(kind=bd.WAIT, seconds=1.0, priority=100 + i))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert q.size() == 8 * n_per_thread
    due, stale = q.pop_due()
    assert len(due) == 8 * n_per_thread and stale == []
    assert q.clear() == 0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("all bot_directive tests passed")
