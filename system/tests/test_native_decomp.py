import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import native_decomp as nd, native_decomp_runtime as rt
from gbox.config import Config
from gbox.registry import Ctx, ToolUnavailable


@pytest.fixture
def setup(tmp_path):
    home = tmp_path / 'upstream'
    template = home / 'targets/dreamcast_sh4/template/TcInputs.java'
    template.parent.mkdir(parents=True)
    template.write_text('// independent input generator')
    header = home / 'targets/dreamcast_sh4/runtime/tc_rt.h'
    header.parent.mkdir(); header.write_text('typedef unsigned int u32;')
    (home / 'decomp.py').write_text('print("analysis ran")')
    cfg = Config(data_dir=tmp_path / 'data', native_decomp={'decomp_pipeline': {'home': str(home)}})
    binary = tmp_path / 'owned.bin'; binary.write_bytes(bytes.fromhex('07e00b000900') + bytes(26))
    return cfg, Ctx(cfg), binary


def init(setup, engine='decomp_pipeline', name='fixture', **kwargs):
    cfg, ctx, binary = setup
    return nd.operate(cfg, engine, nd.NativeDecompIn(op='init', work_id=name, binary_path=str(binary),
        expected_sha256=rt.sha(binary), game_end='8c010006', **kwargs), ctx)


def test_init_isolated_hashes_and_no_overwrite(setup):
    cfg, ctx, binary = setup
    result = init(setup)
    work = Path(result['project'])
    assert result['source_unchanged'] and result['source_sha256'] == rt.sha(binary)
    assert (work / 'input.bin').read_bytes() == binary.read_bytes()
    config = rt.read_json(work / 'project.json')
    assert config['target'] == 'dreamcast_sh4' and config['game_end'] == '8c010006'
    assert config['max_workers'] == 1 and config['watcher_max_tries'] == 0
    with pytest.raises(FileExistsError):
        init(setup)
    assert binary.read_bytes().startswith(bytes.fromhex('07e00b00'))


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'a/b', 'a\\b', '..', '', 'x' * 65])
def test_work_id_cannot_escape(setup, name):
    with pytest.raises(ValueError, match='work_id'):
        init(setup, name=name)


def test_wrong_hash_rejected_before_project_created(setup):
    cfg, ctx, binary = setup
    with pytest.raises(ValueError, match='SHA-256'):
        nd.operate(cfg, 'decomp_pipeline', nd.NativeDecompIn(op='init', work_id='wrong', binary_path=str(binary),
            expected_sha256='0'*64, game_end='8c010006'), ctx)
    assert not rt.project(cfg, 'decomp_pipeline', 'wrong').exists()


def test_xex_rejects_other_formats(setup):
    with pytest.raises(ValueError, match='XEX2'):
        init(setup, engine='xenonrecomp')


def test_xex_rejects_short_and_out_of_bounds_header(setup):
    import struct
    cfg, ctx, binary = setup
    for blob in (b'XEX2', b'XEX2' + struct.pack('>IIIII', 1, 32, 0, 0, 100)):
        binary.write_bytes(blob)
        with pytest.raises(ValueError, match='XEX2'):
            init(setup, engine='rexglue')


def test_environment_home_overrides_installed_defaults(setup, monkeypatch):
    cfg, _, _ = setup
    local = Path(cfg.runtime) / 'decomp-tools/gbox-local.json'
    local.parent.mkdir(parents=True)
    rt.write_json(local, {'rexglue': {'home': str(local.parent / 'installed')}})
    monkeypatch.setenv('GBOX_REXGLUE_HOME', str(local.parent / 'override'))
    assert rt.home(cfg, 'rexglue') == (local.parent / 'override').resolve()


def test_inventory_does_not_recursively_include_earlier_receipts(setup):
    work = Path(init(setup)['project'])
    rt.write_json(work / 'receipt-earlier.json', {'large': 'old artifacts'})
    assert 'receipt-earlier.json' not in {x['path'] for x in rt.inventory(work)}


def test_command_execution_and_copied_input_change_fail(setup):
    cfg, ctx, binary = setup
    result = init(setup); work = Path(result['project'])
    out = nd.operate(cfg, 'decomp_pipeline', nd.NativeDecompIn(op='setup', work_id='fixture'), ctx)
    assert out['returncode'] == 0 and out['input_unchanged'] and not out['verified']
    assert out['argv'][-1] == 'setup' and 'analysis ran' in out['tail']
    (work / 'input.bin').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='input changed'):
        nd.operate(cfg, 'decomp_pipeline', nd.NativeDecompIn(op='setup', work_id='fixture'), ctx)


def test_failed_child_does_not_count_as_success(setup):
    cfg, ctx, _ = setup
    init(setup)
    (rt.home(cfg, 'decomp_pipeline') / 'decomp.py').write_text('import sys; print("bad analysis"); sys.exit(3)')
    with pytest.raises(RuntimeError, match='exit 3'):
        nd.operate(cfg, 'decomp_pipeline', nd.NativeDecompIn(op='setup', work_id='fixture'), ctx)
    assert any(name == 'native-decomp.json' for name, *_ in ctx.artifacts)


def test_task_excludes_hidden_oracle_and_does_not_claim_pass(setup):
    cfg, ctx, _ = setup
    work = Path(init(setup)['project'])
    packet = work / 'packets/8c010000'; packet.mkdir(parents=True)
    (packet / 'asm.txt').write_text('mov #7,r0; rts; nop')
    (packet / 'ghidra.c').write_text('return 7;')
    (packet / 'secret.txt').write_text('do not disclose')
    harness = work / 'harness/8c010000'; harness.mkdir(parents=True)
    rt.write_json(harness / 'meta.json', {'signature': 'u32 answer(void)', 'hidden': 'never expose'})
    (harness / 'hidden.txt').write_text('secret vectors')
    out = nd.operate(cfg, 'decomp_pipeline', nd.NativeDecompIn(op='task', work_id='fixture', address='8c010000'), ctx)
    assert out['signature'] == 'u32 answer(void)' and not out['verified']
    assert 'secret' not in json.dumps(out) and 'never expose' not in json.dumps(out)
    assert set(out['files']) == {'asm.txt', 'ghidra.c', 'tc_rt.h'}


def test_checker_on_linux_reports_windows_requirement(setup):
    if os.name == 'nt':
        pytest.skip('Linux readiness contract')
    cfg, ctx, _ = setup; init(setup)
    with pytest.raises(ToolUnavailable, match='Windows/MSVC'):
        nd.operate(cfg, 'decomp_pipeline', nd.NativeDecompIn(op='check', work_id='fixture', address='8c010000',
            candidate_source='u32 answer(void){return 7;}'), ctx)


@pytest.mark.parametrize('options', [{'file_path': '../source'}, {'skip_lr': True}, {'functions': [{'address': 4, 'size': -4}]},
    {'functions': [{'address': 3, 'size': 4}]}, {'setjmp_address': True}])
def test_xenon_options_reject_path_and_unverified_optimization_overrides(options):
    with pytest.raises(ValueError):
        nd._xenon_options(options)


def test_xenon_options_keep_independent_function_extents():
    assert nd._xenon_options({'functions': [{'address': 0x82000000, 'size': 8}]}) == [
        'functions = [{ address = 2181038080, size = 8 }]']


def test_process_timeout_kills_only_owned_process(setup):
    import sys
    _, ctx, _ = setup
    work = Path(init(setup)['project'])
    with pytest.raises(TimeoutError):
        rt.execute([sys.executable, '-c', 'import time; time.sleep(20)'], work, ctx, 1)


def test_project_lock_excludes_second_operation(setup):
    work = Path(init(setup)['project'])
    with rt.locked(work):
        with pytest.raises(RuntimeError, match='active operation'):
            with rt.locked(work):
                pass


def test_tools_registered_and_agent_methods_match():
    from gbox import agent, registry, tools
    assert 'native_decomp' in tools._load_tool_modules.__defaults__[0]
    for name in nd.OPS:
        assert name in registry.REGISTRY
        spec = next(s['function'] for s in agent.tool_specs() if s['function']['name'] == name)
        assert set(spec['parameters']['properties']) <= set(inspect.signature(getattr(agent.Agent, name)).parameters)
        a = object.__new__(agent.Agent); calls = []
        a._job = lambda tool, inp, **kw: calls.append((tool, inp, kw)) or {'state': 'queued', 'id': 'preserved'}
        assert getattr(a, name)(op='status', worker='spark2')['job_id'] == 'preserved'
        assert calls[0][2]['worker'] == 'spark2'
    assert 'decomp_pipeline status' in agent.SYSTEM
