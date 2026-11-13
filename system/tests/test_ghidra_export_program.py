"""Run the CLI against real durable export manifests; no Ghidra project is opened."""
import json
import sys
from types import SimpleNamespace as NS

import pytest

from scripts import ghidra_export_program as CLI
from test_ghidra_resumable_export import Exporter


class ProgramExporter(Exporter):
    def __init__(self, root):
        super().__init__(root)
        self.closed = self.opened = False
        self.decompiler = None
        self.decompiler_calls = 0
        self.fail_until = None
        self.program.getExecutablePath = lambda: str(self.source)
        self.program.getExecutableSHA256 = lambda: self.info()['executable_sha256']

    def open(self, **kwargs):
        self.opened = True
        return self.info()

    def close(self):
        self.closed = True

    def _decompiler(self):
        self.decompiler_calls += 1
        return self.decompiler

    def decompile(self, target, **kwargs):
        address = target.removeprefix('0x')
        if self.fail_until is not None and self.calls.count(address) >= self.fail_until:
            self.fail.pop(address, None)
        return super().decompile(target, **kwargs)


@pytest.fixture
def run(tmp_path, monkeypatch):
    bridge = ProgramExporter(tmp_path)
    locks = []
    monkeypatch.setitem(sys.modules, 'fcntl', NS(LOCK_EX=2, LOCK_NB=4,
        flock=lambda stream, mode: locks.append(mode)))
    monkeypatch.setattr(CLI, 'Bridge', lambda: bridge)
    out = tmp_path / 'export'

    def invoke(*extra):
        monkeypatch.setattr(sys, 'argv', ['ghidra_export_program.py',
            '--binary', str(bridge.source), '--project-dir', str(tmp_path),
            '--project-name', 'existing', '--program', 'game.elf', '--export-dir', str(out), *extra])
        return CLI.main()

    invoke.bridge, invoke.out, invoke.locks = bridge, out, locks
    return invoke


@pytest.mark.parametrize('attempts', [1, 2, 4])
def test_total_attempt_limit_survives_resume_and_does_not_repeat_success(run, attempts):
    run.bridge.fail['00001000'] = TimeoutError('large function')
    assert run('--retry-attempts', str(attempts), '--batch-size', '1') == 2
    manifest = json.loads((run.out / '_manifest.json').read_text(encoding='utf-8'))
    assert manifest['outcomes']['00001000']['attempts'] == attempts
    assert manifest['outcomes']['00001000']['state'] == 'timeout'
    assert run.bridge.calls.count('00002000') == run.bridge.calls.count('00003000') == 1
    previous = list(run.bridge.calls)
    assert run('--retry-attempts', str(attempts)) == 2
    assert run.bridge.calls == previous
    assert run.bridge.closed and run.locks == [6, 6]


def test_retry_can_recover_only_the_failed_function(run):
    run.bridge.fail['00001000'] = RuntimeError('native payload too large')
    run.bridge.fail_until = 2
    assert run('--retry-attempts', '4') == 0
    manifest = json.loads((run.out / '_manifest.json').read_text(encoding='utf-8'))
    assert manifest['summary']['all_success']
    assert manifest['outcomes']['00001000']['attempts'] == 3
    assert run.bridge.calls == ['00001000', '00002000', '00003000', '00001000', '00001000']


def test_no_progress_retry_fails_explicitly_and_closes_project(run, monkeypatch):
    run.bridge.fail['00001000'] = RuntimeError('persistent')
    export = run.bridge.export

    def blocked_retry(*args, **kwargs):
        if kwargs.get('retry_failed'):
            return {'attempted_this_batch': 0}
        return export(*args, **kwargs)

    monkeypatch.setattr(run.bridge, 'export', blocked_retry)
    with pytest.raises(RuntimeError, match='no progress'):
        run()
    assert run.bridge.closed


class Options:
    def __init__(self):
        self.payload = None
        self.other_option = 'preserve'

    def setMaxPayloadMBytes(self, value):
        self.payload = value


@pytest.mark.parametrize('payload,existing', [(16, True), (512, False)])
def test_payload_option_is_applied_before_export_and_preserves_existing_options(run, monkeypatch, payload, existing):
    options = Options() if existing else None
    applied = []
    monkeypatch.setitem(sys.modules, 'ghidra.app.decompiler', NS(DecompileOptions=Options))
    run.bridge.decompiler = NS(getOptions=lambda: options,
        setOptions=lambda value: applied.append(value) is None)
    export = run.bridge.export

    def checked_export(*args, **kwargs):
        assert len(applied) == 1 and applied[0].payload == payload
        assert applied[0].other_option == 'preserve'
        if existing:
            assert applied[0] is options
        return export(*args, **kwargs)

    monkeypatch.setattr(run.bridge, 'export', checked_export)
    assert run('--max-payload-mb', str(payload)) == 0
    assert run.bridge.closed


def test_native_payload_refusal_stops_before_any_export_and_closes_project(run, monkeypatch):
    monkeypatch.setitem(sys.modules, 'ghidra.app.decompiler', NS(DecompileOptions=Options))
    run.bridge.decompiler = NS(getOptions=lambda: None, setOptions=lambda options: False)
    with pytest.raises(RuntimeError, match='refused the requested payload'):
        run('--max-payload-mb', '128')
    assert run.bridge.closed and not run.bridge.calls
    assert not (run.out / '_manifest.json').exists()


def test_default_payload_does_not_touch_native_options(run):
    assert run() == 0
    assert run.bridge.decompiler_calls == 0


@pytest.mark.parametrize('option,value', [('--retry-attempts', '0'), ('--retry-attempts', '5'),
    ('--max-payload-mb', '15'), ('--max-payload-mb', '513')])
def test_invalid_limits_refused_before_project_open(run, option, value):
    with pytest.raises(SystemExit) as exc:
        run(option, value)
    assert exc.value.code == 2
    assert not run.bridge.opened and not run.locks and not run.out.exists()
