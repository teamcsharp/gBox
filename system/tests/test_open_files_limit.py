"""serve/worker raise the soft open-file limit (systemd's 1024 ran out right after each restart, 2026-10-27)."""
import sys
import types

from gbox import __main__ as cli


def fake_resource(soft, hard, fail=False):
    calls = []

    def setrlimit(_, value):
        if fail:
            raise ValueError("not allowed")
        calls.append(value)
    mod = types.SimpleNamespace(RLIMIT_NOFILE=7, RLIM_INFINITY=-1, getrlimit=lambda _: (soft, hard),
                                setrlimit=setrlimit)
    return mod, calls


def test_the_soft_limit_rises_to_the_target_under_the_hard_one(monkeypatch):
    mod, calls = fake_resource(1024, 524288)
    monkeypatch.setitem(sys.modules, "resource", mod)
    assert cli.raise_open_files() == 65536 and calls == [(65536, 524288)]


def test_never_past_the_hard_limit_and_never_lowered(monkeypatch):
    mod, calls = fake_resource(1024, 4096)
    monkeypatch.setitem(sys.modules, "resource", mod)
    assert cli.raise_open_files() == 4096 and calls == [(4096, 4096)]
    mod, calls = fake_resource(100000, 524288)
    monkeypatch.setitem(sys.modules, "resource", mod)
    assert cli.raise_open_files() == 100000 and calls == []


def test_a_refused_raise_keeps_the_current_limit(monkeypatch):
    mod, _ = fake_resource(1024, 524288, fail=True)
    monkeypatch.setitem(sys.modules, "resource", mod)
    assert cli.raise_open_files() == 1024
