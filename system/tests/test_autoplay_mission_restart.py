"""A playbook mission that dies inside itself must not leave the game standing (gbox.tools _mission_restartable /
_restart_mission / _ended).

Live 2026-11-10, RE4: `re4_switch_mods.maintain` published a per-round weapon record and the playbook's mods panel summed
every value it returned, so the mission ended with "unsupported operand type(s) for +: 'int' and 'dict'" - the session
stayed up, nobody pressed anything, and the operator saw the bot just standing in the game. The mission is what died, so
the fix is to start it again on the same session (bounded), not to relaunch the game."""
import threading
import time
from types import SimpleNamespace

from gbox import tools as T


def run(**kw):
    base = {"sid": "w-1", "mode": "playbook", "playbook_module": "gbox.re4switch_bot", "inp": SimpleNamespace(session_id="w-1"),
            "driver": SimpleNamespace(stopped=False), "result": {"ok": False, "error": "int + dict"}, "mission_attempts": 0}
    base.update(kw)
    return base


def test_a_mission_that_died_with_its_own_exception_is_restartable():
    assert T._mission_restartable(run())


def test_a_mission_that_finished_well_or_was_stopped_or_taken_over_is_not():
    assert not T._mission_restartable(run(result={"ok": True}))
    assert not T._mission_restartable(run(result={"ok": False}, bad_end="black"))
    assert not T._mission_restartable(run(result={"ok": False}, took_over=True))
    assert not T._mission_restartable(run(result={"ok": False}, stopped=True))
    assert not T._mission_restartable(run(result={"ok": False}, driver=SimpleNamespace(stopped=True)))
    assert not T._mission_restartable(run(result={"ok": False}, mode="prepare")), "only playbook missions"
    assert not T._mission_restartable(run(result={"ok": False}, mission_attempts=T.MISSION_RESTART_MAX)), "bounded"


def test_the_restart_starts_the_same_playbook_on_the_same_session_with_one_more_attempt(monkeypatch):
    started = []
    monkeypatch.setattr(T, "AUTOPLAY", {})
    monkeypatch.setattr(T, "MISSION_RESTART_WAIT_S", 0)
    monkeypatch.setattr(T, "_start_playbook", lambda *a, **kw: started.append((a, kw)))
    r = run()
    T._restart_mission(r)
    for _ in range(100):
        if started:
            break
        time.sleep(0.01)
    assert started, "the mission is restarted"
    args, kw = started[0]
    assert args[0].__name__.rsplit(".", 1)[-1] == "re4switch_bot", "the same playbook"
    assert args[1] is r["inp"] and args[3] is None, "the same input/session, no adapter beyond the run's"
    assert kw["attempts"] == 1


def test_a_session_something_else_owns_is_never_taken_over(monkeypatch):
    started = []
    monkeypatch.setattr(T, "MISSION_RESTART_WAIT_S", 0)
    monkeypatch.setattr(T, "_start_playbook", lambda *a, **kw: started.append(kw))
    other = {"sid": "w-1", "mode": "playbook"}
    monkeypatch.setattr(T, "AUTOPLAY", {"w-1": other})
    T._restart_mission(run())
    time.sleep(0.1)
    assert not started


def test_ended_restarts_a_failed_mission_but_not_a_bad_end(monkeypatch):
    calls = []
    monkeypatch.setattr(T, "_saver_post", lambda *a, **kw: None)
    monkeypatch.setattr(T, "_restart_mission", lambda r: calls.append(r))
    monkeypatch.setattr(T, "_bad_end", lambda r: None)
    T._ended(run())
    assert len(calls) == 1
    calls.clear()
    T._ended(run(bad_end="black"))
    assert not calls, "a frozen game is _bad_end's, not a mission restart"
