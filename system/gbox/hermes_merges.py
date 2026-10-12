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


def reconcile(api, *, gh=_gh, carriers=_carriers, now=None, force=False):
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
        for number in sorted(numbers - done):
            try:
                pull = gh(number)
            except Exception as error:
                errors.append(f'#{number}: {error}')
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
    saved['checked_at'] = now
    with hermes_delivery.locked('merges'):
        path.write_text(json.dumps(saved, indent=2))
    return {'posted': posted, 'open': open_prs, 'errors': errors}
