"""Exact-head PR delivery behind independent review and real integration tests.

Uses detached worktrees; never resets the canonical checkout or removes task
branches. A PR merge is source delivery only, never runtime/task acceptance.
"""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

from . import hermes_delivery as D, hermes_result_review as R

FIELDS = ('number,title,body,url,state,headRefOid,baseRefName,headRefName,'
          'isCrossRepository,isDraft,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup,comments,reviews')


def gh(*args):
    return D._run(['gh', *args], D.repository(), timeout=90)


def pull(number):
    p = json.loads(gh('pr', 'view', str(number), '--repo', D.REPOSITORY, '--json', FIELDS))
    # Older deployed gh versions do not expose baseRefOid through `pr --json`.
    refs = json.loads(gh('api', f'repos/{D.REPOSITORY}/pulls/{number}', '--jq',
                         '{head: .head.sha, base: .base.sha}'))
    if refs['head'] != p['headRefOid']:
        raise RuntimeError('PR head moved during discovery')
    return p | {'baseRefOid': refs['base']}


def discover():
    pulls = json.loads(gh('pr', 'list', '--repo', D.REPOSITORY, '--state', 'open', '--base', 'main',
                         '--limit', '1000', '--json', 'number,headRefOid,headRefName'))
    if len(pulls) >= 1000:
        raise RuntimeError('Open-PR inventory reached its limit; do not infer missing publications')
    base = gh('api', f'repos/{D.REPOSITORY}/git/ref/heads/main', '--jq', '.object.sha').strip()
    if not re.fullmatch('[0-9a-f]{40}', base):
        raise RuntimeError('Main commit discovery is incomplete')
    publications = {}
    for path in D.state_dir().glob('*.json'):
        if not re.fullmatch('[0-9a-f]{16}', path.stem):
            continue
        data = json.loads(path.read_text())
        if data.get('pr_number'):
            publications[int(data['pr_number'])] = path.stem
    keys = set()
    for p in pulls:
        p['baseRefOid'] = base
        key = f"pr:{p['number']}:{p['headRefOid']}:{p['baseRefOid']}"
        keys.add(key)
        R.enqueue(key, 'pr', publications.get(p['number'], ''), p)
    with closing(R.connect()) as db:
        previous = [dict(r) for r in db.execute("SELECT key,payload FROM reviews WHERE kind='pr' "
                                                "AND state NOT IN ('merged','closed','superseded')")]
    open_numbers = {p['number'] for p in pulls}
    for row in previous:
        if row['key'] in keys:
            continue
        expected = json.loads(row['payload'])
        state = 'superseded'
        if expected['number'] not in open_numbers:
            observed = pull(expected['number'])
            if observed.get('state') == 'MERGED' and observed.get('headRefOid') == expected['headRefOid']:
                state = 'merged'  # Includes a merge whose successful response was lost.
            elif observed.get('state') == 'CLOSED':
                state = 'closed'
            elif observed.get('state') == 'OPEN':
                continue  # Incomplete/transient GitHub discovery is not a deletion receipt.
        with closing(R.connect()) as db, db:
            db.execute('UPDATE reviews SET state=?,updated=? WHERE key=?', (state, time.time(), row['key']))


def identity(p, expected):
    if (p.get('state') != 'OPEN' or p.get('baseRefName') != 'main' or p.get('isCrossRepository') is not False
            or p.get('headRefOid') != expected['headRefOid'] or p.get('baseRefOid') != expected['baseRefOid']):
        raise RuntimeError('PR head/base/state changed; fetch a fresh review')


def checks(p):
    if p.get('mergeable') != 'MERGEABLE' or p.get('reviewDecision') == 'CHANGES_REQUESTED':
        raise RuntimeError('GitHub mergeability or requested changes block delivery')
    if p.get('mergeStateStatus') in ('DIRTY', 'BLOCKED', 'BEHIND', 'UNKNOWN', 'UNSTABLE'):
        raise RuntimeError('GitHub merge state blocks delivery')
    for check in p.get('statusCheckRollup') or []:
        if check.get('__typename') == 'CheckRun':
            okay = check.get('status') == 'COMPLETED' and check.get('conclusion') == 'SUCCESS'
        else:
            okay = check.get('state') == 'SUCCESS'
        if not okay:
            raise RuntimeError('A GitHub check is pending or unsuccessful')


def test(worktree, tests, log, junit):
    env = dict(os.environ, PYTHONPATH=str(worktree / 'system'), GBOX_LOCAL_LLM_NOLOG='1')
    deployed_python = Path(__file__).resolve().parents[1] / '.venv-linux-aarch64/bin/python'
    python = str(deployed_python) if deployed_python.is_file() else sys.executable
    with log.open('w', encoding='utf-8') as stream:
        proc = subprocess.Popen([python, '-m', 'pytest', '-q', *tests, '--junitxml=' + str(junit)],
                                cwd=worktree / 'system', env=env, stdout=stream, stderr=subprocess.STDOUT,
                                start_new_session=os.name != 'nt')
        try:
            code = proc.wait(timeout=900)
        except subprocess.TimeoutExpired:
            if os.name != 'nt':
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
            proc.wait()
            raise RuntimeError('Integration tests timed out; worktree and log retained') from None
    if code or not junit.is_file():
        raise RuntimeError('Integration tests failed; inspect retained log')
    cases = ET.parse(junit).getroot().findall('.//testcase')
    passed = sum(not any(c.find(tag) is not None for tag in ('skipped', 'failure', 'error')) for c in cases)
    if not passed or any(c.find('failure') is not None or c.find('error') is not None for c in cases):
        raise RuntimeError('No passing integration evidence')
    return {'passed': passed, 'collected': len(cases), 'exit_code': code, 'tests': tests,
            'log': str(log), 'junit': str(junit)}


def prepare(expected):
    from .spark_grunt import select_tests
    p = pull(expected['number'])
    identity(p, expected)
    if p.get('mergeable') == 'CONFLICTING':
        # Review the conflict as a failure, without testing a fictitious integration.
        return {'pull': p, 'integration': {'blocked': 'Merge conflict; rebase preserving work, then test'},
                'complete': False}
    for key in ('headRefOid', 'baseRefOid'):
        if not re.fullmatch('[0-9a-f]{40}', p[key]):
            raise ValueError('Invalid commit identity')
    repo = D.repository()
    run = lambda args, cwd=repo: D._run(args, cwd, timeout=180)
    ref = f"refs/gbox-review/pr-{p['number']}"
    run(['git', 'fetch', '--quiet', 'origin', 'main', f'+refs/pull/{p["number"]}/head:{ref}'])
    if run(['git', 'rev-parse', ref]) != p['headRefOid'] or run(['git', 'rev-parse', 'origin/main']) != p['baseRefOid']:
        raise RuntimeError('Remote commits moved before integration')
    worktree = repo.parent / 'gbox-result-review-worktrees' / f"pr-{p['number']}-{uuid.uuid4().hex[:12]}"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    run(['git', 'worktree', 'add', '--detach', str(worktree), p['baseRefOid']])
    run(['git', '-c', 'core.hooksPath=/dev/null', 'merge', '--no-commit', '--no-ff', p['headRefOid']], worktree)
    changed = run(['git', 'diff', '--cached', '--name-only'], worktree).splitlines()
    diff = run(['git', 'diff', '--cached', '--no-ext-diff'], worktree)
    supported = all(re.fullmatch(r'system/(?:gbox/\w+\.py|tests/test_\w+\.py|docs/[\w.-]+\.md|hermes/gbox/[\w.-]+)', n)
                    for n in changed)
    tests = select_tests(changed, worktree / 'system', limit=1000)
    covered = all(any(Path(t).stem.startswith('test_' + Path(n).stem) for t in tests)
                  for n in changed if n.startswith('system/gbox/') and n.endswith('.py'))
    sources = {}
    for name in changed:
        path = worktree / name
        if path.is_file() and not path.is_symlink() and path.stat().st_size <= 80000:
            sources[name] = path.read_text(encoding='utf-8')
    complete = bool(changed and supported and covered and tests and len(tests) <= 50
                    and len(diff) + sum(map(len, sources.values())) < 150000
                    and all(n in sources for n in changed if (worktree / n).exists()))
    receipt = {'blocked': 'No complete, supported focused integration coverage'}
    if complete:
        try:
            receipt = test(worktree, tests, worktree / 'integration.log', worktree / 'integration.xml')
        except RuntimeError as exc:
            log = worktree / 'integration.log'
            receipt = {'blocked': str(exc), 'log': str(log),
                       'output': log.read_text(encoding='utf-8', errors='replace')[-16000:] if log.exists() else ''}
    return {'pull': p, 'head': p['headRefOid'], 'base': p['baseRefOid'], 'worktree': str(worktree),
            'changed': changed, 'diff': diff[:150000], 'sources': sources if complete else {},
            'complete': complete, 'integration': receipt}


def deliver_one():
    if not R.config().get('auto_merge') or not (R.M._job() or {}).get('enabled'):
        return None
    with closing(R.connect()) as db:
        row = db.execute("SELECT * FROM reviews WHERE kind='pr' AND state='reviewed' "
                         "AND json_extract(verdict,'$.verdict')='approve_merge' ORDER BY updated LIMIT 1").fetchone()
    if not row:
        return None
    row = dict(row)
    expected = json.loads(row['payload'])
    try:
        evidence = json.loads(Path(row['evidence_file']).read_text(encoding='utf-8'))['evidence']
        tests = evidence.get('integration', {})
        if (evidence.get('complete') is not True or tests.get('exit_code') != 0 or tests.get('passed', 0) <= 0
                or evidence.get('head') != expected['headRefOid'] or evidence.get('base') != expected['baseRefOid']):
            raise RuntimeError('Independent integration evidence does not authorize this merge')
        p = pull(expected['number'])
        # Recover a lost merge acknowledgement without sending a second merge.
        if p.get('state') == 'MERGED' and p.get('headRefOid') == expected['headRefOid']:
            state = 'merged'
        else:
            identity(p, expected)
            checks(p)
            if not R.config().get('enabled') or not R.config().get('auto_merge') or not (R.M._job() or {}).get('enabled'):
                return None
            if p.get('isDraft'):
                gh('pr', 'ready', str(p['number']), '--repo', D.REPOSITORY)
            # Recheck after ready: required checks/protections may change.
            p = pull(p['number'])
            identity(p, expected)
            checks(p)
            if not R.config().get('enabled') or not R.config().get('auto_merge') or not (R.M._job() or {}).get('enabled'):
                return None
            gh('pr', 'merge', str(p['number']), '--repo', D.REPOSITORY, '--merge',
               '--match-head-commit', expected['headRefOid'])
            observed = pull(p['number'])
            if observed.get('state') != 'MERGED' or observed.get('headRefOid') != expected['headRefOid']:
                raise RuntimeError('Merge not yet confirmed by GitHub')
            state = 'merged'
        with closing(R.connect()) as db, db:
            db.execute('UPDATE reviews SET state=?,error=NULL,updated=? WHERE key=?', (state, time.time(), row['key']))
        from . import hermes_merges
        hermes_merges.reconcile(R._api, force=True)
        hermes_merges.reconcile_branches(R._api, force=True)
        return row['key']
    except Exception as exc:
        # Leave reviewed evidence durable; poll again after GitHub/infrastructure recovery.
        with closing(R.connect()) as db, db:
            db.execute('UPDATE reviews SET error=?,updated=? WHERE key=?',
                       (type(exc).__name__ + ': ' + str(exc)[:400], time.time(), row['key']))
        return None
