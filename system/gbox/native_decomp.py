"""DecompPipeline, XenonRecomp and RexGlue adapters; local tasks, isolated sources, real verdicts (#2396)."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import uuid
from typing import Literal

from pydantic import BaseModel, Field
from .models import Permission as P
from .registry import ToolUnavailable, tool
from . import native_decomp_runtime as rt

UPSTREAM = {
    'decomp_pipeline': {'url': 'https://github.com/GeneralAtrox/DecompPipeline',
        'reviewed_revision': '84dcbc44bfa5ba451ac1da35e924bc534e02bcd9',
        'scope': 'Dreamcast SH-4 function analysis and sampled behavioral checking; not compiler byte matching.'},
    'xenonrecomp': {'url': 'https://github.com/hedge-dev/XenonRecomp',
        'reviewed_revision': 'ddd128bcca99fe8bfbb99bea583c972351fa6ace',
        'scope': 'Xbox 360 XEX to C++; requires a separate runtime and per-game validation.'},
    'rexglue': {'url': 'https://github.com/rexglue/rexglue-sdk', 'reviewed_revision': 'v0.10.0',
        'scope': 'Xbox 360 project and C++ generation plus SDK runtime; generated code is not proof of a playable port.'},
}
OPS = {'decomp_pipeline': ['status', 'init', 'setup', 'prepare', 'task', 'check', 'audit'],
       'xenonrecomp': ['status', 'init', 'analyze', 'codegen'], 'rexglue': ['status', 'init', 'codegen']}


class NativeDecompIn(BaseModel):
    op: Literal['status', 'init', 'setup', 'prepare', 'task', 'check', 'audit', 'analyze', 'codegen'] = 'status'
    work_id: str = ''
    binary_path: str = ''
    expected_sha256: str = ''
    game_id: str = ''
    game_end: str = ''  # verified exclusive end of SH-4 game code, not guessed from file length
    address: str = ''
    candidate_source: str = Field(default='', max_length=1 << 20)
    xenon_options: dict = Field(default_factory=dict)
    timeout_s: int = Field(default=900, ge=1, le=3600)


class NativeDecompOut(BaseModel):
    op: str
    result: dict


def status(cfg, engine):
    root = rt.home(cfg, engine)
    names = {'decomp_pipeline': ['decomp.py'], 'xenonrecomp': ['XenonAnalyse', 'XenonRecomp'], 'rexglue': ['rexglue']}[engine]
    found = {n: (root / n if engine == 'decomp_pipeline' else rt.executable(cfg, engine, n)) for n in names}
    available = all(p and p.is_file() for p in found.values())
    result = {**UPSTREAM[engine], 'home': str(root), 'installed': available, 'operations': OPS[engine],
              'programs': {n: str(p) if p and p.is_file() else None for n, p in found.items()},
              'project_root': str(rt.projects(cfg, engine)), 'paid_model_calls': False,
              'configure': f'native_decomp.{engine}.home or GBOX_{engine.upper()}_HOME',
              'readiness': 'Program discovery only; see operation receipts for executed proof.'}
    if engine == 'decomp_pipeline':
        opts = rt.settings(cfg, engine)
        ghidra = Path(opts.get('ghidra_home') or getattr(cfg, 'ghidra_home', '') or '.')
        language = ghidra / 'Ghidra/Processors/SuperH4/data/languages/SuperH4_tc_le.sla'
        vcvars = opts.get('vcvars')
        result['dependencies'] = {'ghidra': str(ghidra), 'patched_sh4_language': language.is_file(),
            'checker': 'Windows MSVC x64 required by upstream',
            'checker_configured': os.name == 'nt' and bool(vcvars and Path(vcvars).is_file()),
            'tasking': 'op=prepare then op=task; local model submits C through op=check. Hidden oracle is never in task output.'}
    return result


def address(value):
    if not re.fullmatch(r'(?:0x)?[0-9a-fA-F]{1,8}', value):
        raise ValueError('address must be a 32-bit hexadecimal address')
    value = int(value, 16)
    if not 0x8c010000 <= value < 0x8d000000 or value % 2:
        raise ValueError('address must be aligned inside Dreamcast SH-4 RAM')
    return f'{value:08x}'


def _xenon_options(options):
    addresses = {'restgprlr_14_address', 'savegprlr_14_address', 'restfpr_14_address', 'savefpr_14_address',
                 'restvmx_14_address', 'savevmx_14_address', 'restvmx_64_address', 'savevmx_64_address',
                 'longjmp_address', 'setjmp_address'}
    lines = []
    for key, value in options.items():
        if key in addresses and type(value) is int and 0 <= value < 1 << 32:
            lines.append(f'{key} = {value}')
        elif key == 'functions' and isinstance(value, list) and len(value) <= 100000:
            rows = []
            for f in value:
                if not isinstance(f, dict) or set(f) != {'address', 'size'} or any(type(v) is not int for v in f.values()):
                    raise ValueError('functions needs integer address and size')
                a, s = f['address'], f['size']
                if a % 4 or s % 4 or s <= 0 or not 0 <= a < a + s <= 1 << 32:
                    raise ValueError('Invalid PPC function extent')
                rows.append(f'{{ address = {a}, size = {s} }}')
            lines.append('functions = [' + ', '.join(rows) + ']')
        else:
            raise ValueError('Unsupported Xenon option: ' + key)
    return lines


def _project_config(cfg, work, source_sha, inp):
    opts = rt.settings(cfg, 'decomp_pipeline')
    end = address(inp.game_end)
    if int(end, 16) <= 0x8c010000 or int(end, 16) > 0x8c010000 + (work / 'input.bin').stat().st_size:
        raise ValueError('game_end must be an exclusive code boundary within the copied binary')
    config = {'name': inp.work_id, 'target': 'dreamcast_sh4', 'ghidra_name': inp.work_id,
        'binary': 'input.bin', 'binary_sha256': source_sha, 'game_end': end, 'references': [],
        'priority': [], 'workers': 1, 'max_workers': 1, 'ghidra_parallel': 1,
        'ghidra_timeout_s': inp.timeout_s, 'watcher_max_tries': 0}
    for key in ('ghidra_home', 'java_home', 'vcvars', 'sevenzip'):
        if opts.get(key):
            config[key] = opts[key]
    if 'ghidra_home' not in config and getattr(cfg, 'ghidra_home', None):
        config['ghidra_home'] = str(cfg.ghidra_home)
    if 'java_home' not in config:
        from . import provision
        jdk = provision.jdk21(cfg)
        if jdk:
            config['java_home'] = str(jdk)
    rt.write_json(work / 'project.json', config)
    oracle = work / 'oracle'; oracle.mkdir()
    template = rt.home(cfg, 'decomp_pipeline') / 'targets/dreamcast_sh4/template/TcInputs.java'
    shutil.copyfile(rt.require(template, 'DecompPipeline SH-4 template'), oracle / 'TcInputs.java')


def initialize(cfg, engine, inp, ctx):
    if not inp.binary_path:
        raise ValueError('init requires binary_path')
    src = Path(inp.binary_path).expanduser().resolve(strict=True)
    if not src.is_file() or not 0 < src.stat().st_size <= 512 << 20:
        raise ValueError('Expected an extracted executable of 1..512 MiB, not a disc image')
    if inp.expected_sha256 and not re.fullmatch('[0-9a-fA-F]{64}', inp.expected_sha256):
        raise ValueError('expected_sha256 must be a SHA-256 hex digest')
    if inp.game_id and not re.fullmatch('[0-9a-f]{16}', inp.game_id):
        raise ValueError('Invalid game_id')
    if engine != 'decomp_pipeline':
        with src.open('rb') as stream:
            header = stream.read(24)
        if len(header) != 24 or header[:4] != b'XEX2':
            raise ValueError('Expected a complete Xbox 360 XEX2 header')
        header_size, count = struct.unpack_from('>I', header, 8)[0], struct.unpack_from('>I', header, 20)[0]
        if not 24 + 8 * count <= header_size <= src.stat().st_size:
            raise ValueError('XEX2 optional header table outside executable')
    options = _xenon_options(inp.xenon_options) if engine == 'xenonrecomp' else []
    digest = rt.sha(src)
    if inp.expected_sha256 and digest != inp.expected_sha256.lower():
        raise ValueError('Source SHA-256 does not match expected build')
    work = rt.project(cfg, engine, inp.work_id)
    work.mkdir(parents=True, exist_ok=False)  # never overwrite or reuse another project
    with rt.locked(work):
        dst = work / ('input.bin' if engine == 'decomp_pipeline' else 'input.xex')
        shutil.copyfile(src, dst)
        if rt.sha(dst) != digest or rt.sha(src) != digest:
            raise ValueError('Source changed during staging')
        receipt = {'engine': engine, 'work_id': inp.work_id, 'game_id': inp.game_id, 'source': str(src),
                   'source_sha256': digest, 'input': dst.name, 'input_sha256': digest,
                   'upstream': status(cfg, engine), 'state': 'initializing'}
        rt.write_json(work / 'gbox-project.json', receipt)
        if engine == 'decomp_pipeline':
            _project_config(cfg, work, digest, inp)
        elif engine == 'xenonrecomp':
            (work / 'generated').mkdir()
            lines = ['[main]', 'file_path = "input.xex"', 'out_directory_path = "generated"',
                     'switch_table_file_path = "switches.toml"'] + options
            (work / 'config.toml').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        else:
            exe = rt.require(rt.executable(cfg, engine, 'rexglue'), 'RexGlue')
            run = rt.execute([exe, 'init', '--project-name', inp.work_id, '--xex-path', dst,
                              '--project-root', work / 'project'], work, ctx, inp.timeout_s)
            receipt['init'] = run
            if run['returncode']:
                receipt['state'] = 'failed'; rt.write_json(work / 'gbox-project.json', receipt)
                raise RuntimeError('RexGlue init failed: ' + run['tail'][-2000:])
        receipt['state'] = 'initialized'
        receipt['source_unchanged'] = rt.sha(src) == digest
        if not receipt['source_unchanged'] or rt.sha(dst) != digest:
            raise RuntimeError('Input changed during initialization')
        rt.write_json(work / 'gbox-project.json', receipt)
    return {**receipt, 'project': str(work), 'next': 'setup' if engine == 'decomp_pipeline' else ('analyze' if engine == 'xenonrecomp' else 'codegen')}


def task(cfg, work, addr):
    packet = rt.inside(work, work / 'packets' / addr)
    if not packet.is_dir():
        raise ValueError('No packet for address; run op=prepare first')
    files, size = {}, 0
    for p in sorted(packet.iterdir()):
        if p.name == 'asm.txt' or re.fullmatch(r'ghidra(?:_\d+)?\.c', p.name):
            rt.inside(packet, p)
            size += p.stat().st_size
            if size > 256 << 10:
                raise ValueError('Packet exceeds 256 KiB; split the analysis before tasking')
            files[p.name] = p.read_text(encoding='utf-8')
    meta = rt.read_json(rt.inside(work, work / 'harness' / addr / 'meta.json'))
    if not files or not meta.get('signature'):
        raise ValueError('Prepared packet has no code/signature')
    header = rt.home(cfg, 'decomp_pipeline') / 'targets/dreamcast_sh4/runtime/tc_rt.h'
    with rt.require(header, 'SH-4 C runtime API').open(encoding='utf-8') as stream:
        api = stream.read(65537)
    if len(api) > 65536:
        raise ValueError('C runtime API exceeds 64 KiB')
    files['tc_rt.h'] = api
    return {'address': addr, 'signature': meta['signature'], 'files': files,
            'instructions': 'Translate this one function to C using the signature and tc_rt.h API. Submit candidate_source with op=check. Never edit the oracle, hidden vectors or checker. A local model can perform this task; no paid agent is launched.',
            'status': 'task_ready', 'verified': False}


def _decomp_command(cfg, work, inp):
    root = rt.home(cfg, 'decomp_pipeline')
    entry = rt.require(root / 'decomp.py', 'DecompPipeline')
    cmd = [sys.executable, entry, '--project', work, inp.op]
    if inp.op in ('prepare', 'check'):
        cmd += [address(inp.address)]
    if inp.op == 'check':
        opts = rt.read_json(work / 'project.json')
        if os.name != 'nt' or not opts.get('vcvars') or not Path(opts['vcvars']).is_file():
            raise ToolUnavailable('Upstream behavioral checker needs Windows/MSVC and native_decomp.decomp_pipeline.vcvars. Route this project to a configured Windows worker; Linux analysis/tasking remains available.')
        if not inp.candidate_source.strip():
            raise ValueError('check requires candidate_source')
        candidates = work / 'candidates'; candidates.mkdir(exist_ok=True)
        candidate = candidates / (uuid.uuid4().hex + '.c')
        candidate.write_text(inp.candidate_source, encoding='utf-8')
        cmd += ['--work', candidate, '--json']
    if inp.op == 'audit':
        cmd += ['--json']
    return cmd


def operate(cfg, engine, inp, ctx):
    if inp.op not in OPS[engine]:
        raise ValueError('Supported operations: ' + ', '.join(OPS[engine]))
    if inp.op == 'status':
        return status(cfg, engine)
    if inp.op == 'init':
        return initialize(cfg, engine, inp, ctx)
    work = rt.project(cfg, engine, inp.work_id)
    with rt.locked(work):
        manifest = rt.read_json(work / 'gbox-project.json')
        if manifest['engine'] != engine or manifest['state'] not in ('initialized', 'operated'):
            raise ValueError('Project was not initialized successfully for this tool')
        source = rt.inside(work, work / manifest['input'])
        if rt.sha(source) != manifest['input_sha256']:
            raise ValueError('Project input changed; initialize a new exact-build project')
        if inp.op == 'task':
            return task(cfg, work, address(inp.address))
        if engine == 'decomp_pipeline':
            cmd = _decomp_command(cfg, work, inp)
        elif engine == 'xenonrecomp':
            name = 'XenonAnalyse' if inp.op == 'analyze' else 'XenonRecomp'
            exe = rt.require(rt.executable(cfg, engine, name), name)
            if inp.op == 'analyze':
                cmd = [exe, source, work / 'switches.toml']
            else:
                rt.require(work / 'switches.toml', 'Jump table analysis (op=analyze)')
                header = rt.home(cfg, engine) / 'XenonUtils/ppc_context.h'
                cmd = [exe, work / 'config.toml', rt.require(header, 'PPC context header')]
        else:
            exe = rt.require(rt.executable(cfg, engine, 'rexglue'), 'RexGlue')
            candidates = list((work / 'project').glob('*.toml'))
            candidates = [p for p in candidates if p.name not in ('achievements.toml',)]
            if len(candidates) != 1:
                raise ValueError('Expected exactly one generated RexGlue project TOML')
            cmd = [exe, 'codegen', candidates[0]]
        run = rt.execute(cmd, work, ctx, inp.timeout_s)
        unchanged = rt.sha(source) == manifest['input_sha256']
        result = {'engine': engine, 'work_id': inp.work_id, 'op': inp.op, **run,
                  'input_unchanged': unchanged, 'source_sha256': manifest['source_sha256'], 'verified': False}
        if not unchanged:
            result['error'] = 'Tool changed the staged input'
        if inp.op == 'check' and run['returncode'] in (0, 1):
            # Only the upstream official dev+hidden checker can issue PASS; never parse a model's prose.
            try:
                verdict = json.loads(run['tail'])
            except ValueError:
                verdict = {}
            if not isinstance(verdict, dict):
                verdict = {}
            result['verdict'] = verdict
            if verdict.get('verdict') not in ('PASS', 'FAIL'):
                result['error'] = 'Official checker returned no structured verdict'
            result['verified'] = (run['returncode'] == 0 and unchanged and verdict.get('verdict') == 'PASS' and verdict.get('stage') == 'compare'
                and verdict.get('failing') == 0 and not verdict.get('run_error')
                and all(verdict.get('vectors', {}).get(s, {}).get('total', 0) >= 16 for s in ('dev', 'hidden')))
        result['artifacts'] = rt.inventory(work)
        if inp.op == 'codegen':
            result['generated_source_count'] = sum(a['path'].endswith('.cpp') for a in result['artifacts'])
            with Path(run['log']).open(encoding='utf-8', errors='replace') as stream:
                result['unsupported_instruction_count'] = sum('Unrecognized instruction' in line for line in stream)
            result['completion'] = ('generated_with_unsupported_instructions' if result['unsupported_instruction_count']
                                    else 'generated_requires_runtime_validation')
            if not result['generated_source_count']:
                result['error'] = 'Code generator produced no C++ source'
        receipt = work / ('receipt-' + uuid.uuid4().hex + '.json')
        rt.write_json(receipt, result)
        ctx.artifact('native-decomp.json', json.dumps(result).encode(), 'application/json', source_sha256=manifest['source_sha256'])
        checked_failure = (inp.op == 'check' and run['returncode'] == 1 and
                           result.get('verdict', {}).get('verdict') == 'FAIL')
        if (run['returncode'] and not checked_failure) or not unchanged or result.get('error'):
            raise RuntimeError(f'{engine} {inp.op} failed (exit {run["returncode"]}); receipt={receipt}; '
                               + result.get('error', '') + run['tail'][-2000:])
        return {**result, 'receipt': str(receipt), 'scope': UPSTREAM[engine]['scope']}


@tool('decomp_pipeline', '1.0', NativeDecompIn, NativeDecompOut,
      capabilities=['reverse-engineering', 'decompilation', 'tasking'], platforms=['windows', 'linux'],
      permissions=[P.READ, P.STAGE, P.EXECUTE], timeout_s=3700, artifacts=['native-decomp.json'],
      side_effects=['Writes isolated projects under runtime/native-decomp; runs only explicit operations, no model API calls'])
def decomp_pipeline(inp, ctx):
    """Dreamcast SH-4 DecompPipeline: status, init(binary_path,work_id,game_end), setup, prepare(address), task(address), check(address,candidate_source), audit. Local models use task/check; checker requires Windows MSVC. Never launches paid agents."""
    return {'op': inp.op, 'result': operate(ctx.config, 'decomp_pipeline', inp, ctx)}


@tool('xenonrecomp', '1.0', NativeDecompIn, NativeDecompOut,
      capabilities=['reverse-engineering', 'recompilation', 'xbox360'], platforms=['windows', 'linux'],
      permissions=[P.READ, P.STAGE, P.EXECUTE], timeout_s=3700, artifacts=['native-decomp.json'],
      side_effects=['Copies extracted XEX into isolated project; writes analysis and generated C++'])
def xenonrecomp(inp, ctx):
    """Xbox 360 XenonRecomp: status, init(binary_path,work_id,expected_sha256,xenon_options), analyze, codegen. Generated C++ needs a runtime and per-game proof; inputs remain unchanged."""
    return {'op': inp.op, 'result': operate(ctx.config, 'xenonrecomp', inp, ctx)}


@tool('rexglue', '1.0', NativeDecompIn, NativeDecompOut,
      capabilities=['reverse-engineering', 'recompilation', 'xbox360'], platforms=['windows', 'linux'],
      permissions=[P.READ, P.STAGE, P.EXECUTE], timeout_s=3700, artifacts=['native-decomp.json'],
      side_effects=['Creates isolated RexGlue project and generated C++; does not launch a game'])
def rexglue(inp, ctx):
    """RexGlue Xbox 360 SDK: status, init(binary_path,work_id,expected_sha256), codegen. SDK runtime and generated source do not establish playable game support. Project artifacts and logs remain local."""
    return {'op': inp.op, 'result': operate(ctx.config, 'rexglue', inp, ctx)}


def main():
    """The same typed tools for Hermes terminal tasks and deployment-independent inspection."""
    import argparse
    from . import config
    from .registry import Ctx
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('engine', choices=list(OPS))
    parser.add_argument('--config', default='gbox.toml')
    parser.add_argument('--input-file', help='JSON NativeDecompIn; default is op=status')
    args = parser.parse_args()
    inp = NativeDecompIn.model_validate(rt.read_json(args.input_file)) if args.input_file else NativeDecompIn()
    config_path = Path(args.config).resolve()
    os.chdir(config_path.parent)
    ctx = Ctx(config.load(config_path))
    result = operate(ctx.config, args.engine, inp, ctx)
    print(json.dumps({'op': inp.op, 'result': result}, indent=2))


if __name__ == '__main__':
    main()
