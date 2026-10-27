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
                         '{head: .head.sha, base: .base.sha, base_name: .base.ref}'))
    if refs['head'] != p['headRefOid'] or refs['base_name'] != p['baseRefName']:
        raise RuntimeError('PR head or target branch moved during discovery')
    # A PR's REST base.sha can lag the target branch (observed on PR603 after
    # PR601 merged). Review the actual current integration target, just as
    # discover() does; prepare() verifies it against the subsequent Git fetch.
    base = refs['base']
    if p['baseRefName'] == 'main':
        base = gh('api', f'repos/{D.REPOSITORY}/git/ref/heads/main', '--jq', '.object.sha').strip()
        if not re.fullmatch('[0-9a-f]{40}', base):
            raise RuntimeError('Main commit discovery is incomplete')
    return p | {'baseRefOid': base, 'reportedBaseRefOid': refs['base']}


class MainDrift:
    """Files main changed between an older main commit and the discovered one, from one fetch per discovery.
    files() raises RuntimeError when main cannot be fetched (transient: decide on the next tick) and returns None
    when the older commit is not an ancestor of the new main (rewritten history: never carry across it)."""

    def __init__(self, base):
        self.base, self.fetched, self.cache = base, False, {}

    def files(self, old):
        if old not in self.cache:
            repo = D.repository()
            run = lambda args: D._run(args, repo, timeout=180)
            if not self.fetched:
                run(['git', 'fetch', '--quiet', 'origin', 'main'])
                run(['git', 'cat-file', '-e', self.base + '^{commit}'])
                self.fetched = True
            try:
                if not re.fullmatch('[0-9a-f]{40}', old):
                    raise RuntimeError('Invalid reviewed base')
                run(['git', 'merge-base', '--is-ancestor', old, self.base])
                # --no-renames: a rename on main names both paths, so a PR that edits the old path still overlaps
                self.cache[old] = set(run(['git', 'diff', '--no-renames', '--name-only', old, self.base]).splitlines())
            except RuntimeError:
                self.cache[old] = None
        return self.cache[old]


def reviewed_base(expected, evidence):
    """The main commit a row's verdict was reviewed against: the row's own base, or the original base of a carried
    verdict. None when the evidence is for neither (or another head)."""
    base = evidence.get('base')
    if not base or evidence.get('head') != expected['headRefOid'] or base not in (
            expected['baseRefOid'], expected.get('reviewedBaseRefOid')):
        return None
    return base


def reviewed_files(row, expected):
    """(files the reviewed integration changed, both sides of a rename; the reviewed base), or (None, None) when the
    review's evidence cannot say exactly (missing, another head/base, a conflict without a diff, a truncated diff)."""
    try:
        evidence = json.loads(Path(row['evidence_file']).read_text(encoding='utf-8'))['evidence']
    except (OSError, ValueError, TypeError, KeyError):
        return None, None
    changed, diff, base = evidence.get('changed'), evidence.get('diff'), reviewed_base(expected, evidence)
    if not base or not isinstance(changed, list) or not changed or not isinstance(diff, str) or len(diff) >= 150000:
        return None, None
    return set(changed) | set(re.findall(r'^rename from (.+)$', diff, re.M)), base


def carry(row, expected, p, drift):
    """Main moved but this PR's head did not. A reviewed verdict moves to the new base's key when main changed none
    of the files the reviewed integration changed (cumulative from the original reviewed base); a carried
    approve_merge is integrated and tested again against the exact main before deliver_one merges it. An unreviewed
    row keeps its place in the queue (next_review drains these oldest first). Returns the note for the superseded
    row, or None when the new row has its own history already. Raises RuntimeError if main cannot be fetched."""
    key = f"pr:{p['number']}:{p['headRefOid']}:{p['baseRefOid']}"
    now = time.time()
    if row['state'] == 'reviewed' and row['verdict']:
        files, reviewed = reviewed_files(row, expected)
        if files is None:
            return 'Base moved; the reviewed files are not known exactly, so the new base gets a fresh review'
        changed = drift.files(reviewed)
        if changed is None:
            return 'Base moved and the reviewed base is not an ancestor of main; fresh review'
        overlap = sorted(files & changed)
        if overlap:
            return (f'Base moved; main changed {len(overlap)} file(s) of this PR ('
                    + ', '.join(overlap[:5]) + '); fresh review')
        payload = p | {'reviewedBaseRefOid': reviewed,
                       'carry': {'from': row['key'], 'reviewed_base': reviewed, 'main_files': len(changed), 'at': now}}
        # delivered=1: the guidance is the superseded row's own outbox entry, never posted twice
        sql = ("UPDATE reviews SET state='reviewed',verdict=?,attempts=?,delivered=1,error=NULL,evidence_file=?,"
               "response_file=?,payload=?,updated=? WHERE key=? AND state='pending' AND verdict IS NULL AND attempts=0")
        args = (row['verdict'], row['attempts'], row['evidence_file'], row['response_file'], json.dumps(payload),
                now, key)
        note = 'Base moved; main changed none of its files; verdict carried to ' + key
    else:
        payload = p | {'queuedSince': expected.get('queuedSince') or row['created']}
        retry = row['state'] == 'retry'                       # a failing review keeps its backoff
        sql = ("UPDATE reviews SET state=?,attempts=?,next_at=?,error=?,payload=?,updated=? "
               "WHERE key=? AND state='pending' AND verdict IS NULL AND attempts=0")
        args = ('retry' if retry else 'pending', row['attempts'], row['next_at'] if retry else 0, row['error'],
                json.dumps(payload), now, key)
        note = 'Base moved; unreviewed, queue place kept in ' + key
    with closing(R.connect()) as db, db:
        return note if db.execute(sql, args).rowcount else None


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
        # Reviewed rows first, newest first: the best history of a PR claims its new row.
        previous = [dict(r) for r in db.execute("SELECT * FROM reviews WHERE kind='pr' "
                                                "AND state NOT IN ('merged','closed','superseded') "
                                                "ORDER BY verdict IS NULL, updated DESC")]
    current = {p['number']: p for p in pulls}
    drift = MainDrift(base)
    for row in previous:
        if row['key'] in keys:
            continue
        expected = json.loads(row['payload'])
        state, note = 'superseded', None
        if expected['number'] not in current:
            observed = pull(expected['number'])
            if observed.get('state') == 'MERGED' and observed.get('headRefOid') == expected['headRefOid']:
                state = 'merged'  # Includes a merge whose successful response was lost.
            elif observed.get('state') == 'CLOSED':
                state = 'closed'
            elif observed.get('state') == 'OPEN':
                continue  # Incomplete/transient GitHub discovery is not a deletion receipt.
        elif current[expected['number']]['headRefOid'] == expected['headRefOid']:
            # Only the base moved (2026-10-27: main moved ~25 times a day while one review took 10-18 min, and
            # 494 PR reviews were thrown away in 2 h). A changed head always gets a fresh review.
            try:
                note = carry(row, expected, current[expected['number']], drift)
            except (RuntimeError, OSError, subprocess.SubprocessError):
                continue  # main could not be fetched: decide on the next tick rather than lose a verdict
        with closing(R.connect()) as db, db:
            db.execute('UPDATE reviews SET state=?,error=COALESCE(?,error),updated=? WHERE key=?',
                       (state, note, time.time(), row['key']))


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
    try:
        run(['git', '-c', 'core.hooksPath=/dev/null', 'merge', '--no-commit', '--no-ff', p['headRefOid']], worktree)
    except RuntimeError:
        # GitHub can still say MERGEABLE/UNKNOWN right after main moves: a local conflict is reviewed as a failure.
        return {'pull': p, 'head': p['headRefOid'], 'base': p['baseRefOid'], 'worktree': str(worktree),
                'integration': {'blocked': 'Merge conflict at integration; rebase preserving work, then test'},
                'complete': False}
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


def discard(worktree):
    """Remove a re-test worktree (its receipt keeps the outcome); review worktrees stay for inspection."""
    path = Path(worktree or '')
    if path.parent.name != 'gbox-result-review-worktrees' or not path.name.startswith('pr-'):
        return
    try:
        D._run(['git', 'worktree', 'remove', '--force', str(path)], D.repository(), timeout=180)
    except (RuntimeError, OSError, subprocess.SubprocessError):
        pass


def retest(row, expected, evidence):
    """A carried approve_merge, integrated and tested again against the exact current main. -> the passing receipt,
    or None after sending the row back for a fresh review (conflict, failing or incomplete tests, or an integration
    that is not the reviewed diff). Raises RuntimeError on a race (head/base moved, fetch), keeping the review."""
    receipt = expected.get('retest') or {}
    if (receipt.get('ok') and receipt.get('base') == expected['baseRefOid']
            and receipt.get('head') == expected['headRefOid']):
        return receipt                                     # this exact integration already passed
    fresh = prepare(expected)
    try:
        tests = fresh.get('integration') or {}
        reason = None
        if fresh.get('complete') is not True or tests.get('exit_code') != 0 or tests.get('passed', 0) <= 0:
            reason = 'no passing focused integration tests: ' + str(tests.get('blocked') or 'incomplete coverage')
        elif fresh.get('head') != expected['headRefOid'] or fresh.get('base') != expected['baseRefOid']:
            raise RuntimeError('Re-test integrated other commits; fetch a fresh review')
        elif sorted(fresh.get('changed') or []) != sorted(evidence.get('changed') or []):
            reason = 'the integration changes other files than the reviewed one'
        elif R.redact(fresh.get('diff') or '') != evidence.get('diff'):
            reason = 'the integration diff is not the reviewed diff'
    finally:
        discard(fresh.get('worktree'))
    receipt = {'ok': reason is None, 'base': expected['baseRefOid'], 'head': expected['headRefOid'],
               'at': time.time(), 'passed': tests.get('passed'), 'collected': tests.get('collected'),
               'tests': tests.get('tests'), 'reason': reason,
               'output': str(tests.get('output') or '')[-2000:] if reason else ''}
    with closing(R.connect()) as db, db:
        if reason is None:
            db.execute("UPDATE reviews SET payload=?,updated=? WHERE key=? AND state='reviewed'",
                       (json.dumps(expected | {'retest': receipt}), time.time(), row['key']))
            return receipt
        # The fresh review is of this base: the carried base no longer describes the row (its trail stays in 'carry').
        payload = {k: v for k, v in expected.items() if k != 'reviewedBaseRefOid'} | {'retest': receipt}
        db.execute("UPDATE reviews SET state='pending',verdict=NULL,next_at=0,error=?,payload=?,updated=? WHERE key=?",
                   ('Re-review: the approval carried from ' + str(expected.get('reviewedBaseRefOid'))[:12]
                    + ' failed its merge-time re-test against main ' + expected['baseRefOid'][:12] + ': ' + reason,
                    json.dumps(payload), time.time(), row['key']))
    return None


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
        reviewed = reviewed_base(expected, evidence)                # an older main once the verdict was carried
        if (evidence.get('complete') is not True or tests.get('exit_code') != 0 or tests.get('passed', 0) <= 0
                or not reviewed):
            raise RuntimeError('Independent integration evidence does not authorize this merge')
        p = pull(expected['number'])
        # Recover a lost merge acknowledgement without sending a second merge.
        if p.get('state') == 'MERGED' and p.get('headRefOid') == expected['headRefOid']:
            state = 'merged'
        else:
            identity(p, expected)
            if reviewed != expected['baseRefOid']:
                # Carried across base drift: the reviewed diff must still integrate and pass on this exact main.
                if not retest(row, expected, evidence):
                    return None
                p = pull(p['number'])
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
