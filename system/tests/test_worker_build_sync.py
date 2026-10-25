"""Worker restarts do not publish local game builds without an explicit opt-in."""
import threading
from types import SimpleNamespace

import pytest

from gbox import config, worker


def test_build_sync_is_off_by_default_and_can_be_enabled_per_host(tmp_path):
    path = tmp_path / 'gbox.toml'
    path.write_text(config.TEMPLATE, encoding='utf-8')
    assert config.Config().sync_mod_builds_on_startup is False
    assert config.load(path).sync_mod_builds_on_startup is False
    config.local_overlay(path).write_text('sync_mod_builds_on_startup = true\n', encoding='utf-8')
    assert config.load(path).sync_mod_builds_on_startup is True


@pytest.mark.parametrize('enabled', [False, True])
def test_worker_uploads_builds_only_after_explicit_opt_in(cfg, monkeypatch, enabled):
    cfg.sync_mod_builds_on_startup = enabled
    uploads = []
    monkeypatch.setattr('gbox.filemods.push_missing', lambda *args: uploads.append(args) or [])
    monkeypatch.setattr('gbox.cache_tiers.install', lambda *_: None)
    monkeypatch.setattr('gbox.inspection_builds.source_inventory', lambda: {})
    monkeypatch.setattr('gbox.worker_client_control.from_environment', lambda: None)
    monkeypatch.setattr(worker, 'describe', lambda *_: worker.WorkerInfo(name='fixture', os='linux', tools=[]))
    monkeypatch.setattr(worker, 'ResultOutbox', lambda *_: SimpleNamespace(
        send_ready=lambda *_a, **_k: None, held=lambda: [], protected_sessions=lambda *_: []))

    class Client:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass

    class Thread:
        def __init__(self, target, args=(), name=None, **_):
            self.target, self.args, self.name = target, args, name

        def start(self):
            if self.name == 'mod-build-sync':
                self.target(*self.args)

    stop = threading.Event()
    stop.set()
    monkeypatch.setattr(worker.httpx, 'Client', Client)
    monkeypatch.setattr(worker.threading, 'Thread', Thread)
    worker.run('http://fixture.invalid', 'fixture-token', cfg, 'fixture', stop=stop)
    assert len(uploads) == int(enabled)
    if enabled:
        assert uploads[0][0] is cfg and uploads[0][1] == 'http://fixture.invalid'
