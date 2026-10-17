"""Give cloud agents isolated Git workspaces and a bounded draft-PR handoff."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import time


REPOSITORY = 'teamcsharp/gBox'
ALLOWED = ('system/gbox/', 'system/tests/', 'system/clients/', 'system/docs/', 'system/hermes/')
PR_FIELDS = 'url,number,state,headRefName,headRefOid,baseRefName,isCrossRepository'


def state_dir() -> Path:
    return Path(os.environ.get('GBOX_HERMES_DISPATCH_STATE') or
                Path(__file__).resolve().parents[1] / 'gbox-data/hermes-dispatch')


def repository() -> Path:
    return Path(os.environ.get('GBOX_HERMES_REPO') or Path.home() / 'gbox-hermes-repo')


@contextmanager
def locked(name):
    root = state_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / (name + '.lock')
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            stream.write(b'0'); stream.flush(); stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _run(args, cwd, *, timeout=45, env=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, env=env)
    if result.returncode:
        # Git may include an authenticated origin URL in an error. Do not return it.
        if args[0] in ('git', 'gh'):
            raise RuntimeError(f'{args[0]} {args[1]} failed (exit {result.returncode}); no publication claimed')
        raise RuntimeError(result.stdout[-2500:] + result.stderr[-1500:])
    return result.stdout.strip()


def _record_path(request_id):
    if not re.fullmatch(r'[0-9a-f]{16}', request_id):
        raise ValueError('A real request ID is required')
    return state_dir() / (request_id + '.json')


def _verify_pull(pull, branch, commit):
    """A handoff must refer to an open PR for the exact pushed task commit."""
    if (not isinstance(pull, dict) or type(pull.get('number')) is not int
            or pull['number'] <= 0 or pull.get('state') != 'OPEN'
            or pull.get('headRefName') != branch or pull.get('headRefOid') != commit
            or pull.get('baseRefName') != 'main' or pull.get('isCrossRepository') is not False
            or pull.get('url') != f'https://github.com/{REPOSITORY}/pull/{pull["number"]}'):
        raise RuntimeError('GitHub has not confirmed an open main PR for the exact pushed commit; preserve the workspace')
    return pull


def _open_pull(root, branch, commit):
    # `pr view <branch>` also returns already merged/closed PRs. A resumed task
    # needs a new open review, and a failed discovery call must not imply none.
    pulls = json.loads(_run(['gh', 'pr', 'list', '--repo', REPOSITORY,
        '--head', branch, '--base', 'main', '--state', 'open', '--limit', '2',
        '--json', PR_FIELDS], root))
    if not isinstance(pulls, list) or len(pulls) > 1:
        raise RuntimeError('GitHub open-PR discovery is ambiguous; preserve the workspace')
    return _verify_pull(pulls[0], branch, commit) if pulls else None


def _read_pull(root, number, branch, commit):
    pull = json.loads(_run(['gh', 'pr', 'view', str(number), '--repo', REPOSITORY,
                           '--json', PR_FIELDS], root))
    return _verify_pull(pull, branch, commit)


def _local_run(request_id) -> bool:
    try:
        from . import hermes_local
        return hermes_local.run_was_local(request_id)
    except Exception:  # noqa: BLE001 - labelling is best effort; publication never depends on it
        return False


def _mark_local(root, number, existed) -> dict:
    """A local-model PR stays a draft and carries the "local model" label (best effort: never fails a publish)."""
    from . import hermes_local
    label = hermes_local.settings().pr_label
    done = {'label': label}
    steps = [('labelled', ['gh', 'api', f'repos/{REPOSITORY}/issues/{number}/labels', '--method', 'POST',
                           '-f', f'labels[]={label}'])]
    if existed:
        steps.append(('draft', ['gh', 'pr', 'ready', str(number), '--repo', REPOSITORY, '--undo']))
    for name, args in steps:
        try:
            result = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=45)
            done[name] = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            done[name] = False
    return done


def prepare(request_id: str, number: int) -> dict:
    record = _record_path(request_id)
    repo = repository()
    if not (repo / '.git').exists():
        raise RuntimeError('The tracked Hermes repository has not been provisioned')
    with locked(request_id):
        if record.exists():
            workspace = json.loads(record.read_text())
            if (Path(workspace['path']) / '.git').exists():
                return workspace | {'reused': True, 'shared_sources': _shared_sources(workspace)}
            raise RuntimeError('The recorded task workspace is missing; preserve its history before retrying')
        _run(['git', 'fetch', 'origin', 'main'], repo)
        branch = f'hermes/request-{int(number)}-{time.time_ns()}'
        path = repo.parent / 'gbox-hermes-tasks' / request_id
        path.parent.mkdir(parents=True, exist_ok=True)
        _run(['git', 'worktree', 'add', '-b', branch, str(path), 'origin/main'], repo)
        _run(['git', 'config', 'user.name', 'Hermes gBox'], path)
        _run(['git', 'config', 'user.email', 'hermes@gbox.local'], path)
        workspace = {'request_id': request_id, 'number': int(number), 'path': str(path),
                     'workdir': str(path / 'system'), 'branch': branch,
                     'baseline': _run(['git', 'rev-parse', 'HEAD'], path)}
        record.write_text(json.dumps(workspace, indent=2))
        return workspace | {'shared_sources': _shared_sources(workspace)}


def _shared_sources(workspace):
    from .shared_sources import references
    return references(workspace['path'], state_dir() / 'source-references' / workspace['request_id'])


def publish(request_id: str, title: str, files: list[str], tests: list[str]) -> dict:
    record = _record_path(request_id)
    with locked(request_id):
        workspace = json.loads(record.read_text())
        root = Path(workspace['path']).resolve()
        if not files or len(files) > 40:
            raise ValueError('Specify 1 to 40 changed source files')
        for name in files:
            path = root / name
            if (not name.startswith(ALLOWED) or '..' in Path(name).parts or path.is_symlink()
                    or not path.resolve().is_relative_to(root) or not path.is_file()
                    or any(part.startswith('.') for part in Path(name).parts)):
                raise ValueError('Only explicit source, test and documentation files can be published')
        # The executed regression files are part of the handoff, even when the
        # caller supplied them only in tests rather than repeating them in files.
        files = list(dict.fromkeys(files))
        if any(name.endswith('.py') for name in files):
            if not tests or len(tests) > 10:
                raise ValueError('Python changes require 1 to 10 focused test files')
            for name in tests:
                path = root / 'system' / name
                if (not re.fullmatch(r'tests/test_[\w]+\.py', name) or path.is_symlink()
                        or not path.resolve().is_relative_to(root / 'system') or not path.is_file()):
                    raise ValueError('Tests must be named files inside system/tests')
                if 'system/' + name not in files:
                    files.append('system/' + name)
            if len(files) > 40:
                raise ValueError('Source and focused test files together must fit the 40-file handoff')
            dirty = set(_run(['git', 'diff', 'HEAD', '--name-only', '--',
                              'system/gbox/', 'system/tests/'], root).splitlines())
            dirty.update(_run(['git', 'ls-files', '--others', '--exclude-standard', '--',
                               'system/gbox/', 'system/tests/'], root).splitlines())
            omitted = sorted(dirty - set(files))
            if omitted:
                raise ValueError('Include changed source/test helpers in files before validation: ' + ', '.join(omitted))
        _run(['git', 'diff', '--check'], root)
        # Workspaces survive their first PR merge. Refresh the comparison base
        # without changing the agent's branch, index or uncommitted source.
        _run(['git', 'fetch', 'origin', 'main'], root)
        checks = []
        system = root / 'system'
        env = os.environ | {'PYTHONPATH': str(system)}
        if any(name.endswith('.py') for name in files):
            if not tests or len(tests) > 10:
                raise ValueError('Python changes require 1 to 10 focused test files')
            for name in tests:
                path = system / name
                if (not re.fullmatch(r'tests/test_[\w]+\.py', name) or path.is_symlink()
                        or not path.resolve().is_relative_to(system) or not path.is_file()):
                    raise ValueError('Tests must be named files inside system/tests')
            python = Path(__file__).resolve().parents[1] / '.venv-linux-aarch64/bin/python'
            if not python.exists():
                import sys
                python = Path(sys.executable)
            checks.append(_run([str(python), '-m', 'pytest', *tests, '-q'], system, timeout=180, env=env)[-4000:])
        for name in files:
            if name.endswith('.js'):
                checks.append(_run(['node', '--check', name], root))
        _run(['git', 'add', '--', *files], root)
        staged = _run(['git', 'diff', '--cached', '--name-only'], root).splitlines()
        if set(staged) - set(files):
            raise RuntimeError('The index contains changes from outside this handoff')
        if staged:
            _run(['git', 'diff', '--cached', '--check'], root)
            _run(['git', 'commit', '-m', title[:180]], root)
        if not _run(['git', 'log', 'origin/main..HEAD', '--format=%H'], root):
            raise RuntimeError('No task commit exists; no GitHub progress was claimed')
        _run(['git', 'push', '-u', 'origin', workspace['branch']], root, timeout=90)
        commit = _run(['git', 'rev-parse', 'HEAD'], root)
        from . import hermes_device_work
        provenance = hermes_device_work.publication_provenance(request_id)
        local = any(r['device_id'] not in ('unknown', 'mixed') and not r['device_id'].startswith('provider:')
                    for run in provenance.get('runs', []) for r in run.get('routes', []))
        note = hermes_device_work.pr_note(provenance)
        body = (note + f"gBox request #{workspace['number']} ({request_id}).\n\n"
                f"{title}\n\nValidation files: {', '.join(tests)}\n\nValidation:\n```text\n" + '\n'.join(checks) +
                "\n```\n\nPublished for review. This PR does not by itself verify live emulation or close the inbox ticket.\n")
        body_path = state_dir() / (request_id + '-pr.md')
        body_path.write_text(body)
        existing = _open_pull(root, workspace['branch'], commit)
        if existing:
            number = existing['number']
            # Keep the review description in sync when a resumed task changes its patch.
            # REST avoids gh pr edit's dependency on deprecated classic project fields.
            update_path = state_dir() / (request_id + '-pr-update.json')
            update_path.write_text(json.dumps({'title': title[:180], 'body': body}), encoding='utf-8')
            _run(['gh', 'api', f'repos/{REPOSITORY}/pulls/{number}', '--method', 'PATCH',
                  '--input', str(update_path)], root)
        else:
            url = _run(['gh', 'pr', 'create', '--draft', '--repo', REPOSITORY, '--base', 'main',
                        '--head', workspace['branch'], '--title', title[:180], '--body-file', str(body_path)], root)
            match = re.fullmatch(r'https://github\.com/' + re.escape(REPOSITORY) + r'/pull/(\d+)', url)
            if not match:
                raise RuntimeError('GitHub creation was not confirmed; preserve the workspace and inspect open PRs before retrying')
            number = int(match[1])
        confirmed = _read_pull(root, number, workspace['branch'], commit)
        if local:
            workspace['local_model'] = _mark_local(root, number, existing is not None)
        else:
            # A reused workspace may carry a legacy global-route label receipt.
            # It is not evidence about this publication's actual contributor.
            workspace.pop('local_model', None)
        workspace.update(commit=commit, url=confirmed['url'], pr_number=number, pr_state=confirmed['state'],
                         base_head=_run(['git', 'rev-parse', 'origin/main'], root),
                         checks=checks, files=files, published_at=time.time(), provenance=provenance)
        record.write_text(json.dumps(workspace, indent=2))
        receipts = state_dir() / 'publications'
        receipts.mkdir(parents=True, exist_ok=True)
        receipt = receipts / f'{number}-{commit}.json'
        if not receipt.exists():
            with receipt.open('x', encoding='utf-8') as stream:
                json.dump(workspace, stream, indent=2)
        return workspace
