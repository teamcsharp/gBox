"""#1296: this PC's worker panel explains why it is offline and reconnects it (runs test_worker_reconnect.cjs)."""
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_worker_reconnect_cjs():
    r = subprocess.run(["node", "--test", str(HERE / "test_worker_reconnect.cjs")],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


@pytest.mark.parametrize('explicit', [False, True])
def test_cli_only_requests_refused_result_reconciliation_explicitly(cfg, monkeypatch, explicit):
    import sys
    from gbox import __main__ as cli, deps, worker
    recorded = []
    monkeypatch.setattr(cli.cfgmod, 'load', lambda _path: cfg)
    monkeypatch.setattr(deps, 'ensure_declared', lambda: None)
    monkeypatch.setattr(worker, 'run', lambda *args, **kwargs: recorded.append((args, kwargs)))
    args = ['gbox', '--config', 'private-fixture.toml', 'worker', '--server', 'http://fixture', '--name', 'owned-worker']
    if explicit: args.append('--reconcile-results')
    monkeypatch.setattr(sys, 'argv', args)
    cli.main()
    assert len(recorded) == 1
    assert recorded[0][1] == {'reconcile_results': explicit}
