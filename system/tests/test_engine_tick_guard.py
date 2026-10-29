import pytest

from gbox.mercs import engine, lessons


def run(tmp_path, monkeypatch, raises, ticks=8, snap_raises=()):
    """play_round over `ticks` playing snapshots; the brain's tick raises a TypeError on the tick numbers in `raises`,
    the driver's snapshot on those in `snap_raises`."""
    monkeypatch.setattr(lessons, "ROOT", tmp_path / "mercs" / "lessons")
    stats, logged, sent, index, calls = {}, [], [], [-1], []

    class Brain:
        _round_started = None

        def observe_round(self, snap, where, now):
            if self._round_started is None:
                self._round_started = now

        def recall(self, rows): pass
        def plan(self): return {}

        def tick(self, snap):
            calls.append(index[0])
            if index[0] in raises:
                return None - 1.0                    # the live crash: unsupported operand type(s) for -
            return {"hold": {"lup"}}

        def prompt_ok(self, *a): return True
        def save(self): pass

    class Driver:
        frame = None
        def snapshot(self, m):
            if index[0] in snap_raises:
                return {"timer": 90.0 - None}
            return {"where": "playing", "player": {"pos": (0., 0., 0.), "hp": 100}}
        def screen(self, m, snap): return snap["where"]
        def progress(self, snap): return {"score": 0, "kills": 0, "timer": 100.}
        def prompt_source(self, *a): return lambda: None
        def prompt_keys(self, b): return []

    def stopped():
        index[0] += 1
        return index[0] >= ticks

    def send(rows): sent.extend(rows)

    why = engine.play_round({"map_id": "TICKGUARD"}, object(), send, stopped, stats, logged.append,
                            brain=Brain(), driver=Driver(), clock=lambda: index[0] * .1, sleep=lambda _: None)
    return why, stats, logged, sent, calls


def test_a_tick_that_raises_costs_the_tick_not_the_round(tmp_path, monkeypatch):
    why, stats, logged, sent, calls = run(tmp_path, monkeypatch, raises={2})
    assert why == "stopped"
    assert calls == list(range(8))                   # every tick after the bad one still decided
    assert stats["tick_errors"] == 1
    assert stats["tick_error"].startswith("TypeError: unsupported operand type(s) for -")
    assert "test_engine_tick_guard.py:" in stats["tick_error"] and "tick" in stats["tick_error"]
    rows = [r for r in logged if r["kind"] == "tick_error"]
    assert len(rows) == 1 and "Traceback" in rows[0]["trace"]
    # the keys were let go on the bad tick and pressed again on the next
    ups = [i for i, r in enumerate(sent) if r == {"key": "lup", "down": False}]
    downs = [i for i, r in enumerate(sent) if r == {"key": "lup", "down": True}]
    assert ups and any(d > ups[0] for d in downs)


def test_the_same_error_is_logged_once_while_it_repeats(tmp_path, monkeypatch):
    _, stats, logged, _, _ = run(tmp_path, monkeypatch, raises={1, 2, 3, 5})
    assert stats["tick_errors"] == 4
    assert len([r for r in logged if r["kind"] == "tick_error"]) == 1


def test_ticks_that_keep_raising_end_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "TICK_ERRORS_MAX", 3)
    with pytest.raises(TypeError):
        run(tmp_path, monkeypatch, raises=set(range(1, 20)), ticks=20)


def test_a_reader_that_raises_costs_the_tick_too(tmp_path, monkeypatch):
    why, stats, _, _, calls = run(tmp_path, monkeypatch, raises=set(), snap_raises={3})
    assert why == "stopped" and calls == [0, 1, 2, 4, 5, 6, 7]
    assert stats["tick_errors"] == 1 and "snapshot" in stats["tick_error"]
