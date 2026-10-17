"""Tell each inbox request what became of the draft PRs Hermes published for it.

`publish_task_changes` opens draft PRs, but nothing reported a merge or a
close back on the ticket (#1300). This reconciler reads every PR that
publication posted to a request, asks GitHub for its state and posts one
reply per PR when it is merged or closed. It also flags a task commit pushed
after its PR merged, which is not on main (the lost #1275 `to_glb` commit).
"""
from __future__ import annotations

import json
import re
import subprocess
import time

from . import hermes_delivery

PUBLISHED = re.compile(r'Published tested task changes: https://github\.com/'
                       + re.escape(hermes_delivery.REPOSITORY) + r'/pull/(\d+)')
NOTICE = re.compile(r'^PR #(\d+) (?:merged to main|closed without merge)', re.M)
FIELDS = 'number,state,mergedAt,closedAt,mergeCommit,headRefOid,baseRefName,url'
INTERVAL = 600


def _gh(number):
    out = subprocess.run(['gh', 'pr', 'view', str(number), '--repo', hermes_delivery.REPOSITORY,
                          '--json', FIELDS], cwd=hermes_delivery.repository(), capture_output=True,
                         text=True, encoding='utf-8', errors='replace', timeout=45)
    if out.returncode:
        raise RuntimeError(f'gh pr view {number} failed (exit {out.returncode})')
    return json.loads(out.stdout)


def _carriers(sha):
    """PRs GitHub associates with a commit: [{number, state, merged_at}]."""
    out = subprocess.run(['gh', 'api', f'repos/{hermes_delivery.REPOSITORY}/commits/{sha}/pulls'],
                         cwd=hermes_delivery.repository(), capture_output=True, text=True,
                         encoding='utf-8', errors='replace', timeout=45)
    if out.returncode:
        raise RuntimeError(f'gh api commits/{sha[:12]}/pulls failed (exit {out.returncode})')
    return [{'number': p['number'], 'state': p['state'], 'merged_at': p.get('merged_at')}
            for p in json.loads(out.stdout)]


def _stamp(value):
    return (value or '').replace('T', ' ').replace('Z', ' UTC')


def _late_commit(commit, number, carriers):
    """Where a commit pushed after its PR finished ended up."""
    try:
        others = [p for p in carriers(commit) if p['number'] != number]
    except Exception:
        return f' Its last published commit {commit[:12]} came later; check whether it reached main.'
    merged = [p for p in others if p.get('merged_at')]
    if merged:
        return f" Its later commit {commit[:12]} reached main through PR #{merged[0]['number']}."
    waiting = [p for p in others if p.get('state') == 'open']
    if waiting:
        return f" Its later commit {commit[:12]} is not on main yet; it is waiting in open PR #{waiting[0]['number']}."
    return f' Its later commit {commit[:12]} is NOT on main and no open PR carries it. Republish it as a new PR.'


def notice(pull, record=None, carriers=_carriers):
    """The reply for a finished PR, or None while it is still open."""
    number = pull['number']
    if pull.get('state') == 'MERGED':
        sha = ((pull.get('mergeCommit') or {}).get('oid') or '')[:12]
        text = f"PR #{number} merged to {pull.get('baseRefName') or 'main'} as {sha or 'an unknown commit'} at {_stamp(pull.get('mergedAt'))}."
        commit = (record or {}).get('commit')
        if record and pr_number(record) == number and commit and commit != pull.get('headRefOid'):
            text += _late_commit(commit, number, carriers)
        return text
    if pull.get('state') == 'CLOSED':
        return (f"PR #{number} closed without merge at {_stamp(pull.get('closedAt'))}. Its changes are not on "
                "main unless another PR carried them.")
    return None


def pr_number(record):
    """Records from older delivery code keep only the PR URL."""
    if type(record.get('pr_number')) is int:
        return record['pr_number']
    match = re.fullmatch(r'https://github\.com/' + re.escape(hermes_delivery.REPOSITORY) + r'/pull/(\d+)',
                         record.get('url') or '')
    return int(match[1]) if match else None


def _records(root):
    for path in sorted(root.glob('*.json')):
        if re.fullmatch(r'[0-9a-f]{16}', path.stem):
            try:
                yield json.loads(path.read_text())
            except (OSError, ValueError):
                continue


def reconcile(api, *, gh=_gh, carriers=_carriers, now=None, force=False, evidence_backfill=None):
    """Post a reply for every published PR that merged or closed since the last pass."""
    now = time.time() if now is None else now
    root = hermes_delivery.state_dir()
    path = root / 'merges.json'
    try:
        saved = json.loads(path.read_text())
    except (OSError, ValueError):
        saved = {}
    if not force and now - saved.get('checked_at', 0) < INTERVAL:
        return {'skipped': 'interval'}
    finished = saved.setdefault('finished', {})
    posted, errors, open_prs = [], [], 0
    backfilled = 0
    for record in _records(root):
        rid = record.get('request_id')
        current = pr_number(record)
        if not rid or not current:
            continue
        done = set(finished.get(rid, []))
        try:
            report = api('/api/requests/' + rid)
        except Exception as error:  # an unreachable ticket must not stop the others
            errors.append(f'{rid}: {type(error).__name__}')
            continue
        texts = [m.get('text') or '' for m in report.get('messages', [])]
        numbers = {int(n) for t in texts for n in PUBLISHED.findall(t)} | {current}
        done |= {int(n) for t in texts for n in NOTICE.findall(t)}
        unseen = {n for n in numbers if str(n) not in saved.get('observations', {})}
        # Migrate existing notices without reposting them or fetching every old
        # PR in one pass. The ordinary open-PR reconciliation remains unchanged.
        backfill = set(sorted(unseen & done)[:max(0, 20 - backfilled)])
        backfilled += len(backfill)
        for number in sorted((numbers - done) | backfill):
            try:
                pull = gh(number)
            except Exception as error:
                errors.append(f'#{number}: {error}')
                continue
            # Preserve the exact GitHub observation for the read-only device
            # evidence view. A notice string alone cannot prove head identity.
            saved.setdefault('observations', {})[str(number)] = {
                key: pull.get(key) for key in ('number', 'state', 'mergedAt', 'closedAt',
                    'mergeCommit', 'headRefOid', 'baseRefName', 'url')}
            saved['observations'][str(number)]['observed_at'] = now
            if number in done:
                continue
            text = notice(pull, record, carriers)
            if text is None:
                open_prs += 1
                continue
            api(f'/api/requests/{rid}/messages', {'author': 'agent', 'text': text, 'task_step': {
                'action': 'reconcile published PR with GitHub', 'attempt': '1',
                'result': f"PR #{number} {pull['state'].lower()}", 'status': 'finished'}})
            done.add(number)
            posted.append({'request_id': rid, 'number': report.get('number'), 'pr': number,
                           'state': pull['state']})
        finished[rid] = sorted(done)
    # Producer-side bounded historical joins; the activity endpoint never
    # queries GitHub or scans publication transcripts on a UI poll.
    from . import hermes_device_work, hermes_publication_evidence
    try:
        errors += (evidence_backfill or hermes_publication_evidence.backfill)(
            saved, hermes_device_work.publications(), now=now)
    except (OSError, ValueError, TypeError) as error:
        errors.append('Publication evidence: ' + type(error).__name__)
    saved['checked_at'] = now
    with hermes_delivery.locked('merges'):
        path.write_text(json.dumps(saved, indent=2))
    return {'posted': posted, 'open': open_prs, 'errors': errors}


# --- task branches: is each ticket's published work actually on main? ---------------------------------
# PR notices say what GitHub did with a PR. They cannot see a commit pushed after
# its PR merged, or work that reached main through another (rebased) PR. This pass
# compares every task branch with main by patch identity (git cherry). Commits on
# no open PR, and on no PR the operator deliberately closed, get a draft PR so they
# come back for review instead of being lost (the #1275 to_glb commit).

STRANDED_GRACE = 1800       # a branch pushed in the last 30 min may still be mid-publication
PULL_FIELDS = 'number,state,headRefName,headRefOid,url'


class Branches:
    """The Hermes repository's view of task branches on origin."""

    def __init__(self, root):
        self.root = root

    def _git(self, *args, timeout=60):
        return hermes_delivery._run(['git', *args], self.root, timeout=timeout)

    def refresh(self):
        self._git('fetch', '--quiet', '--prune', 'origin', '+refs/heads/main:refs/remotes/origin/main',
                  '+refs/heads/hermes/*:refs/remotes/origin/hermes/*', timeout=180)

    def heads(self):
        """{branch: (sha, committer time)} for every hermes/* branch on origin."""
        out = self._git('for-each-ref', '--format=%(refname:lstrip=3) %(objectname) %(committerdate:unix)',
                        'refs/remotes/origin/hermes/')
        heads = {}
        for line in out.splitlines():
            name, sha, stamp = line.split()
            heads[name] = (sha, float(stamp))
        return heads

    def pending(self, sha):
        """[(sha, subject)] of commits whose change is not on main, oldest first."""
        out = self._git('cherry', '-v', 'origin/main', sha)
        return [(line[2:].partition(' ')[0], line[2:].partition(' ')[2].strip())
                for line in out.splitlines() if line.startswith('+ ')]

    def pulls(self):
        """{branch: [pull]} for every PR GitHub has for a hermes/* branch."""
        rows = json.loads(hermes_delivery._run(['gh', 'pr', 'list', '--repo', hermes_delivery.REPOSITORY,
            '--state', 'all', '--limit', '500', '--json', PULL_FIELDS], self.root))
        out = {}
        for pull in rows:
            if (pull.get('headRefName') or '').startswith('hermes/'):
                out.setdefault(pull['headRefName'], []).append(pull)
        return out

    def open_pull(self, branch, record, pending):
        """Open a draft PR for stranded commits; return {number, url}."""
        title = f"Recover unmerged Hermes work for request #{record.get('number')}"
        body = (f"gBox request #{record.get('number')} ({record['request_id']}).\n\n"
                f"These commits on `{branch}` were not on main and no open PR carried them "
                "(for example, pushed after the branch's earlier PR merged):\n\n"
                + '\n'.join(f'- {sha[:12]} {subject.strip()}' for sha, subject in pending)
                + "\n\nOpened automatically by the gBox Hermes outcome reconciler so the work is reviewed instead of lost.\n")
        path = hermes_delivery.state_dir() / (record['request_id'] + '-recover-pr.md')
        path.write_text(body, encoding='utf-8')
        url = hermes_delivery._run(['gh', 'pr', 'create', '--draft', '--repo', hermes_delivery.REPOSITORY,
                                    '--base', 'main', '--head', branch, '--title', title[:180],
                                    '--body-file', str(path)], self.root).strip()
        match = re.fullmatch(r'https://github\.com/' + re.escape(hermes_delivery.REPOSITORY) + r'/pull/(\d+)', url)
        if not match:
            raise RuntimeError('GitHub did not confirm the recovery PR')
        return {'number': int(match[1]), 'url': url}


VERIFY_NOTE = ("This ticket's published fix is fully on main (branch head {sha}). Check that the Spark runtime "
               "has it, then verify the acceptance criteria live and mark the ticket done with solved_by, or post "
               "the exact remaining gap. Do this before starting new work: a merged fix nobody verifies is "
               "never resolved.")


def on_main_requests(root=None) -> dict[str, str]:
    """{request_id: branch head} for tickets whose published task branch is fully on main (#1308).

    Reads the state `reconcile_branches` saved. Advisory only: a missing or
    unreadable file returns {} so listing requests never breaks."""
    try:
        saved = json.loads(((root or hermes_delivery.state_dir()) / 'branches.json').read_text())
        reported = saved.get('reported') or {}
        return {rid: state.split(':', 1)[1] for rid, state in reported.items()
                if isinstance(rid, str) and isinstance(state, str) and state.startswith('on_main:')}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def _default_branches():
    root = hermes_delivery.repository()
    return Branches(root) if (root / '.git').exists() else None


def _busy_requests():
    from . import hermes_recovery
    return hermes_recovery._active_requests()


def branch_state(record, heads, pulls, branches):
    """(state key, detail) for one request's task branch, or None if it was never pushed."""
    branch = record.get('branch')
    if not branch or branch not in heads:
        return None
    sha, pushed = heads[branch]
    if sha == record.get('baseline'):
        return f'unchanged:{sha}', {'sha': sha}
    pending = branches.pending(sha)
    if not pending:
        return f'on_main:{sha}', {'sha': sha}
    prs = pulls.get(branch, [])
    open_pr = next((p for p in prs if p.get('state') == 'OPEN'), None)
    if open_pr:
        return f"review:{open_pr['number']}:{sha}", {'sha': sha, 'pull': open_pr, 'pending': pending}
    closed = next((p for p in prs if p.get('state') == 'CLOSED' and p.get('headRefOid') == sha), None)
    if closed:
        # The operator or an integration PR closed exactly this head: never reopen it on our own.
        return f"closed:{closed['number']}:{sha}", {'sha': sha, 'pull': closed, 'pending': pending}
    return f'stranded:{sha}', {'sha': sha, 'pushed': pushed, 'pending': pending}


def reconcile_branches(api, *, branches=None, busy=_busy_requests, now=None, force=False):
    """Report when a ticket's work is fully on main; recover commits no PR carries."""
    now = time.time() if now is None else now
    root = hermes_delivery.state_dir()
    path = root / 'branches.json'
    try:
        saved = json.loads(path.read_text())
    except (OSError, ValueError):
        saved = {}
    if not force and now - saved.get('checked_at', 0) < INTERVAL:
        return {'skipped': 'interval'}
    branches = branches or _default_branches()
    if branches is None:
        return {'skipped': 'no_repository'}
    branches.refresh()
    heads, pulls = branches.heads(), branches.pulls()
    try:
        owned = set(busy())
    except Exception:
        owned = None            # unknown ownership: report, but never open a PR under an active run
    reported = saved.setdefault('reported', {})
    posted, recovered, errors = [], [], []
    for record in _records(root):
        rid = record.get('request_id')
        if not rid:
            continue
        try:
            found = branch_state(record, heads, pulls, branches)
        except Exception as error:
            errors.append(f'{rid}: {type(error).__name__}')
            continue
        if found is None:
            continue
        state, detail = found
        if reported.get(rid) == state:
            continue
        text = None
        if state.startswith('on_main:'):
            text = (f"All published work for this ticket is on main: branch {record['branch']} "
                    f"(head {detail['sha'][:12]}) has no change that main lacks.")
        elif state.startswith('stranded:'):
            if owned is None or rid in owned or now - detail['pushed'] < STRANDED_GRACE:
                continue        # decide again next pass; nothing is recorded
            try:
                pull = branches.open_pull(record['branch'], record, detail['pending'])
            except Exception as error:
                errors.append(f'{rid}: recovery PR failed ({type(error).__name__})')
                continue
            recovered.append({'request_id': rid, 'number': record.get('number'), 'pr': pull['number']})
            text = (f"{len(detail['pending'])} commit(s) on branch {record['branch']} were not on main and no open PR "
                    f"carried them. Opened draft PR #{pull['number']} to bring them back for review: {pull['url']}\n"
                    + '\n'.join(f'- {sha[:12]} {subject.strip()}' for sha, subject in detail['pending'][:10]))
            state = f"review:{pull['number']}:{detail['sha']}"
        if text:
            try:
                api(f'/api/requests/{rid}/messages', {'author': 'agent', 'text': text, 'task_step': {
                    'action': 'check ticket branch against main', 'attempt': '1',
                    'result': state.split(':', 1)[0], 'status': 'finished'}})
            except Exception as error:
                errors.append(f'{rid}: {type(error).__name__}')
                continue
            posted.append({'request_id': rid, 'number': record.get('number'), 'state': state.split(':', 1)[0]})
        reported[rid] = state
    saved['checked_at'] = now
    with hermes_delivery.locked('branches'):
        path.write_text(json.dumps(saved, indent=2))
    return {'posted': posted, 'recovered': recovered, 'errors': errors}
