from types import SimpleNamespace

from gbox import worker
from gbox.config import Config


def test_one_broken_capability_probe_does_not_drop_the_entire_worker(monkeypatch):
    def broken(_):
        raise OSError('optional program missing')
    monkeypatch.setattr(worker, 'REGISTRY', {
        'broken': SimpleNamespace(name='broken', unavailable_reason=broken),
        'working': SimpleNamespace(name='working', unavailable_reason=lambda _: None)})
    info = worker.describe(Config(), 'fixture')
    assert info.tools == ['working']
    assert 'optional program missing' in info.unavailable['broken']


def test_failed_tool_modules_are_retried_without_reloading_running_sessions(monkeypatch):
    from gbox import tools
    calls = []
    monkeypatch.setattr(tools, 'LOAD_ERRORS', {'optional': 'missing dependency'})
    monkeypatch.setattr(tools, '_load_tool_modules', lambda names: calls.append(tuple(names)))
    monkeypatch.setattr(worker, 'REGISTRY', {})
    worker.describe(Config(), 'fixture')
    assert calls == [('optional',)]
