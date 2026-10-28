"""Keep or revert a bot code change by what it did to the title's play (operator 2026-10-27: "We don't want any of the
improvements to be destructive, so we do want the ability to revert things back in the event that they make an update
or change that's detrimental ... if the improvements result in meaningful change, which means a higher score or
greater efficiency, then yes").

Every bot code change that went live (gbox.mercs.learning change documents of kind reload / restart: a hot reload
or restart that changed the title's modules) is judged on the title's first AFTER_ROUNDS rounds after it (only those
before the title's next change) against its BEFORE_ROUNDS rounds before it:

  * per round: score, kills, kills per minute (minutes played: the driver's round_t_* decision seconds), died, time
    bonuses taken;
  * worse: the score's mean AND median down WORSE_SCORE or more, or deaths per round up WORSE_DEATHS (and at least
    DEATHS_MIN more deaths) - with at least MIN_SAMPLE rounds on each side; better: score or kills per minute up
    BETTER or more without being worse; else kept, no clear change. Fewer than MIN_SAMPLE rounds before the next
    change: confounded, no action.

Worse: the merged pull request that brought the change (GitHub: the PRs whose commits touched the title's driver
between the title's previous change and this one) is reverted with a revert PR merged on main - the auto-deploy then
ships and hot-reloads it - and the title's batch requests closed just before the change reopen with the numbers. Only
an agent's PR (a Claude Code / Hermes PR) that touched nothing but this title's driver files, tests and docs is
reverted, and only when it is the one such PR in the window; anything else (an operator's change, server or core
files, several PRs, one of these reverts) is flagged for a human with a request. Better or kept: an "Effect measured"
note on those batch requests. Every decision is on the change document (gate) and in GET /api/mercs/learning.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import tempfile
import time

STATE = 'mercs_gate_state'
BEFORE_ROUNDS, AFTER_ROUNDS, MIN_SAMPLE = 10, 10, 8
WORSE_SCORE, WORSE_DEATHS, DEATHS_MIN, BETTER = 0.10, 0.25, 2, 0.10
P_MAX, P_REVERT, PERMUTATIONS = 0.05, 0.01, 2000
LONG_ROUNDS = 30                     # an automatic revert also needs the loss against this longer baseline
REVERT_GAP_S = 24 * 3600             # at most one automatic revert per title this long; later ones go to a human     # and the difference must be unlikely by chance (one-sided permutation test):
                                     # without it, 10 rounds against 10 called "worse" at a third of the split points
                                     # of 2026-10-27's rounds where nothing changed (stages rotate, deaths are lumpy)
BATCH_WINDOW_S = 48 * 3600            # batch requests closed this long before a change are its tickets
REPO = 'teamcsharp/gBox'
DRIVERS = {'010018100CD46000': 'system/gbox/mercs/titles/re5_switch',
           '01002A000CD48000': 'system/gbox/mercs/titles/re6_switch',
           'BLUS30491': 'system/gbox/mercs/titles/re5_ps3'}
SAFE_PREFIXES = ('system/tests/', 'system/docs/')     # beside the driver itself, what a revertable PR may touch
REVERT_BRANCH = 'gbox-learning-revert-'
AUTO_REVERT = os.environ.get('GBOX_MERCS_AUTO_REVERT', '1') != '0'


def _num(o, *keys):
    for k in keys:
        v = o.get(k)
        if type(v) in (int, float):
            return float(v)
    return None


def round_metrics(r):
    """One round's play numbers from its Notebook row."""
    o = r['observed']
    played = sum(v for k, v in o.items() if k.startswith('round_t_') and type(v) in (int, float) and v > 0)
    kills = _num(o, 'kills')
    return {'score': _num(o, 'score'), 'kills': kills,
            'kpm': round(kills / (played / 60.0), 3) if kills is not None and played >= 20 else None,
            'died': 1.0 if r['outcome'] == 'died' else 0.0,
            'bonuses': _num(o, 'round_bonuses_taken', 'time_bonuses_taken', 'bonuses_taken')}


def p_lower(before, after, n=PERMUTATIONS, seed=0):
    """One-sided permutation p-value that `after`'s mean is this much lower than `before`'s by chance."""
    before, after = [v for v in before if v is not None], [v for v in after if v is not None]
    if not before or not after:
        return 1.0
    observed = sum(before) / len(before) - sum(after) / len(after)
    pool, k, rng, hits = before + after, len(before), random.Random(seed), 0
    for _ in range(n):
        rng.shuffle(pool)
        if sum(pool[:k]) / k - sum(pool[k:]) / (len(pool) - k) >= observed - 1e-9:
            hits += 1
    return (hits + 1) / (n + 1)


def summary(rounds):
    ms = [round_metrics(r) for r in rounds]

    def mean(key):
        vs = [m[key] for m in ms if m[key] is not None]
        return round(sum(vs) / len(vs), 3) if vs else None
    scores = [m['score'] for m in ms if m['score'] is not None]
    return {'rounds': len(ms), 'score': mean('score'), 'score_median': statistics.median(scores) if scores else None,
            'kills': mean('kills'), 'kpm': mean('kpm'), 'deaths_per_round': mean('died'),
            'deaths': int(sum(m['died'] for m in ms)), 'bonuses': mean('bonuses'),
            'values': {k: [m[k] for m in ms] for k in ('score', 'kpm', 'died')},
            'completed': sum(1 for r in rounds if r['outcome'] == 'completed')}


def _drop(before, after):
    return None if before in (None, 0) or after is None else (before - after) / abs(before)


def judge(before, after):
    """(verdict, reasons, p) for two summaries: worse / better / kept / pending; p: the smallest p-value of the losses
    (1.0 when not worse)."""
    if before['rounds'] < MIN_SAMPLE or after['rounds'] < MIN_SAMPLE:
        return 'pending', ['fewer than %d rounds on a side' % MIN_SAMPLE], 1.0
    reasons, ps = [], []
    mean_drop, median_drop = _drop(before['score'], after['score']), _drop(before['score_median'],
                                                                           after['score_median'])
    vb, va = before.get('values') or {}, after.get('values') or {}
    if mean_drop is not None and median_drop is not None and mean_drop >= WORSE_SCORE and median_drop >= WORSE_SCORE:
        p = p_lower(vb.get('score') or [], va.get('score') or [])
        if p <= P_MAX:
            ps.append(p)
            reasons.append(f"score {before['score']:.0f} -> {after['score']:.0f} per round (median "
                           f"{before['score_median']:.0f} -> {after['score_median']:.0f}, p {p:.3f})")
    db, da = before['deaths_per_round'] or 0.0, after['deaths_per_round'] or 0.0
    if da > db * (1 + WORSE_DEATHS) and after['deaths'] - before['deaths'] * after['rounds'] / before['rounds'] \
            >= DEATHS_MIN:
        p = p_lower([-v for v in vb.get('died') or []], [-v for v in va.get('died') or []])
        if p <= P_MAX:
            ps.append(p)
            reasons.append(f'deaths per round {db:.2f} -> {da:.2f} (p {p:.3f})')
    if reasons:
        return 'worse', reasons, min(ps)
    gains = []
    if mean_drop is not None and -mean_drop >= BETTER \
            and p_lower(va.get('score') or [], vb.get('score') or []) <= P_MAX:
        gains.append(f"score {before['score']:.0f} -> {after['score']:.0f} per round")
    kpm = _drop(before['kpm'], after['kpm'])
    if kpm is not None and -kpm >= BETTER and p_lower(va.get('kpm') or [], vb.get('kpm') or []) <= P_MAX:
        gains.append(f"kills per minute {before['kpm']} -> {after['kpm']}")
    return ('better', gains, 1.0) if gains else ('kept', ['no clear change in score, kills per minute or deaths'], 1.0)


class GitHub:
    """The few GitHub reads and the revert the gate needs, through the Spark's gh (its auth) and the deploy source clone."""

    def __init__(self, repo=REPO, clone=None, run=subprocess.run):
        self.repo, self.run = repo, run
        self.clone = Path(clone or os.environ.get('GBOX_SRC') or Path.home() / 'gBox_alt' / 'gBox-src')

    def _gh(self, *args, timeout=60):
        out = self.run(['gh', *args], capture_output=True, text=True, timeout=timeout)
        if out.returncode:
            raise RuntimeError(f"gh {' '.join(args[:2])}: {(out.stderr or out.stdout).strip()[:300]}")
        return out.stdout

    def api(self, path):
        return json.loads(self._gh('api', path) or 'null')

    def prs_between(self, prefix, since, until):
        """Merged PRs whose commits on main touched files under `prefix` between two times."""
        iso = lambda t: time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t))
        directory = prefix.rsplit('/', 1)[0]
        found = []
        commits = self.api(f'repos/{self.repo}/commits?sha=main&path={directory}&since={iso(since)}&until={iso(until)}'
                           '&per_page=100') or []
        for c in commits:
            for pr in self.api(f"repos/{self.repo}/commits/{c['sha']}/pulls") or []:
                if pr.get('merged_at') and pr['number'] not in found:
                    found.append(pr['number'])
        return found

    def pr(self, number):
        p = self.api(f'repos/{self.repo}/pulls/{number}')
        files = [f['filename'] for f in self.api(f'repos/{self.repo}/pulls/{number}/files?per_page=100') or []]
        return {'number': number, 'title': p.get('title'), 'body': p.get('body') or '', 'head': (p.get('head') or {}).get('ref'),
                'merge_commit_sha': p.get('merge_commit_sha'), 'merged_at': p.get('merged_at'), 'files': files}

    def revert(self, pr, reason):
        """A revert PR of `pr` merged on main. -> its number."""
        branch = REVERT_BRANCH + str(pr['number'])
        git = lambda *a, cwd=None: self.run(['git', *a], cwd=cwd or str(self.clone), capture_output=True, text=True,
                                            timeout=120)
        done = git('fetch', '-q', 'origin', 'main')
        if done.returncode:
            raise RuntimeError('git fetch: ' + done.stderr[:200])
        tmp = Path(tempfile.mkdtemp(prefix='gbox-revert-'))
        try:
            for args in (('worktree', 'add', '-B', branch, str(tmp / 'w'), 'origin/main'),):
                done = git(*args)
                if done.returncode:
                    raise RuntimeError('git worktree: ' + done.stderr[:200])
            w = str(tmp / 'w')
            parents = git('rev-list', '--parents', '-n', '1', pr['merge_commit_sha'], cwd=w).stdout.split()
            mainline = ['-m', '1'] if len(parents) > 2 else []
            done = git('-c', 'user.name=gBox learning gate', '-c', 'user.email=gbox-learning@localhost', 'revert',
                       '--no-edit', *mainline, pr['merge_commit_sha'], cwd=w)
            if done.returncode:
                git('revert', '--abort', cwd=w)
                raise RuntimeError('git revert: ' + (done.stderr or done.stdout)[:300])
            done = git('push', '-q', '-u', 'origin', branch, cwd=w)
            if done.returncode:
                raise RuntimeError('git push: ' + done.stderr[:200])
            url = self._gh('pr', 'create', '-R', self.repo, '--base', 'main', '--head', branch,
                           '--title', f"Revert #{pr['number']}: {str(pr['title'])[:90]} (the learning gate)",
                           '--body', reason).strip()
            number = int(url.rstrip('/').rsplit('/', 1)[-1])
            self._gh('pr', 'merge', str(number), '-R', self.repo, '--merge')
            return number
        finally:
            git('worktree', 'remove', '--force', str(tmp / 'w'))


def agent_made(pr) -> bool:
    return 'Generated with [Claude Code]' in pr['body'] or str(pr.get('head') or '').startswith('hermes/')


def revertable(pr, title):
    """(True, '') when the gate may revert this PR itself, else (False, why a human decides)."""
    own = DRIVERS.get(title)
    if str(pr.get('head') or '').startswith(REVERT_BRANCH):
        return False, 'it is one of the gate\'s own reverts'
    if not agent_made(pr):
        return False, 'not an agent\'s PR (an operator change is never reverted automatically)'
    other = [f for f in pr['files'] if not (own and f.startswith(own)) and not f.startswith(SAFE_PREFIXES)]
    if other:
        return False, 'it also changes server or core files: ' + ', '.join(other[:6])
    if not pr.get('merge_commit_sha'):
        return False, 'no merge commit to revert'
    return True, ''


class Gate:
    def __init__(self, store, learning, *, github=None, now=time.time, auto_revert=None):
        self.store, self.learning, self.now = store, learning, now
        self.github = github if github is not None else GitHub()
        self.auto_revert = AUTO_REVERT if auto_revert is None else auto_revert

    def poll(self):
        """Judge every undecided code change. -> the decisions taken this pass."""
        from .learning import CODE_KINDS
        decided = []
        changes = [c for c in self.learning.changes(since=self.now() - 7 * 86400) if c.get('kind') in CODE_KINDS]
        for i, change in enumerate(changes):
            gate = change.get('gate') or {}
            if gate.get('final'):
                continue
            title = change['title']
            rounds = self.learning.rounds(title)
            nxt = next((c['at'] for c in changes[i + 1:] if c['title'] == title), None)
            earlier = [r for r in rounds if r['ts'] < change['at']]
            before = earlier[-BEFORE_ROUNDS:]
            after = [r for r in rounds if r['ts'] >= change['at'] and (nxt is None or r['ts'] < nxt)][:AFTER_ROUNDS]
            b, a = summary(before), summary(after)
            verdict, reasons, p = judge(b, a)
            if verdict == 'pending':
                if nxt is not None and a['rounds'] < MIN_SAMPLE:
                    verdict, reasons = 'confounded', ['the next change went live before %d rounds' % MIN_SAMPLE]
                else:
                    self._save(change, {'state': 'pending', 'before': b, 'after': a, 'reasons': reasons})
                    continue
            gate = {'state': verdict, 'before': b, 'after': a, 'reasons': reasons, 'final': True, 'at': self.now(),
                    'p': p}
            if verdict == 'worse':
                # clear enough to undo by itself: p <= P_REVERT and a loss against the longer baseline as well
                long_verdict, _r, long_p = judge(summary(earlier[-LONG_ROUNDS:]), a)
                clear = p <= P_REVERT and long_verdict == 'worse'
                gate.update(self.act(change, b, a, reasons, clear=clear, p=p, long_p=long_p))
            elif verdict == 'better':
                gate['notified'] = self.note(change, verdict, b, a, reasons)
            self._save(change, gate)
            self.log(change, gate)
            decided.append((change['id'], gate['state']))
        return decided

    def act(self, change, b, a, reasons, clear=True, p=None, long_p=None):
        title = change['title']
        numbers = f"{'; '.join(reasons)} over {a['rounds']} rounds after the {change['kind']} at " \
                  f"{_clock(change['at'])}, against {b['rounds']} before"
        prev = [c['at'] for c in self.learning.changes(title) if c['at'] < change['at']
                and c.get('kind') in ('reload', 'restart')]
        since = max(prev) if prev else change['at'] - 6 * 3600
        out = {}
        try:
            prs = self.github.prs_between(DRIVERS[title], since - 1800, change['at'])
            details = [self.github.pr(n) for n in prs]
        except Exception as exc:  # noqa: BLE001 - GitHub unreachable: a human decides
            return {'state': 'flagged', 'flag': f'GitHub unavailable: {type(exc).__name__}: {exc}'[:300],
                    'request': self.flag(change, numbers, [], 'GitHub could not be read')}
        mine = [p for p in details if any(f.startswith(DRIVERS[title]) for f in p['files'])]
        out['prs'] = [p['number'] for p in mine]
        if len(mine) != 1:
            why = 'no PR found for it' if not mine else f'{len(mine)} PRs changed the driver in that window'
            return out | {'state': 'flagged', 'flag': why, 'request': self.flag(change, numbers, mine, why)}
        pr = mine[0]
        ok, why = revertable(pr, title)
        recent = [d for d in self.decisions(title) if d.get('state') == 'reverted'
                  and self.now() - (d.get('at') or 0) < REVERT_GAP_S]
        if ok and recent:
            ok, why = False, f"another automatic revert of this title {_clock(recent[-1]['at'])}: at most one a day"
        if ok and not clear:
            ok, why = False, (f'probably worse (p {p:.3f}; against the {LONG_ROUNDS} rounds before p {long_p:.3f}) but '
                              f'not clear enough to undo automatically (p <= {P_REVERT} on both)')
        if not ok or not self.auto_revert:
            why = why or 'automatic reverts are off (GBOX_MERCS_AUTO_REVERT=0)'
            return out | {'state': 'flagged', 'flag': why, 'request': self.flag(change, numbers, [pr], why)}
        reason = (f"The learning gate (gbox/mercs/gate.py) reverts #{pr['number']}: after it went live {numbers}. "
                  'The auto-deploy ships and hot-reloads this revert; the batch tickets it answered reopen with the '
                  'numbers.\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)')
        try:
            revert = self.github.revert(pr, reason)
        except Exception as exc:  # noqa: BLE001
            why = f'the revert failed: {type(exc).__name__}: {exc}'[:300]
            return out | {'state': 'revert_failed', 'flag': why, 'request': self.flag(change, numbers, [pr], why)}
        reopened = self.reopen(change, f"Reopened: #{pr['number']} made {title_name(title)} play worse and was "
                                       f"reverted (#{revert}): {numbers}.")
        return out | {'state': 'reverted', 'reverted_pr': pr['number'], 'revert_pr': revert, 'reopened': reopened}

    def tickets(self, change):
        """The title's batch requests closed in the BATCH_WINDOW_S before the change: what it was meant to fix."""
        from . import damage_clusters as C
        games = {g for g, t in C.GAMES.items() if t == change['title']}
        with self.store.reading() as db:
            found = [json.loads(b) for (b,) in db.execute(
                "SELECT body FROM docs WHERE kind='request' AND json_extract(body,'$.source')=?", (C.SOURCE,))]
        return [r for r in found if (r.get('context') or {}).get('game_id') in games and r.get('status') == 'done'
                and change['at'] - BATCH_WINDOW_S <= (r.get('completed') or 0) <= change['at']]

    def reopen(self, change, text):
        done = []
        for r in self.tickets(change):
            with self.store.lock:
                req = self.store.get('request', r['id'])
                if req.get('status') != 'done':
                    continue
                req.update(status='open', completed=None)
                req.setdefault('messages', []).append({'id': f"gate-{change['id']}", 'author': 'agent',
                                                       'ts': self.now(), 'text': text, 'attachments': []})
                self.store.put('request', r['id'], req)
            done.append(r.get('number'))
        return done

    def note(self, change, verdict, b, a, reasons):
        text = (f"Effect measured: kept - {'; '.join(reasons)} over {a['rounds']} rounds after the {change['kind']} at "
                f"{_clock(change['at'])} (score {b['score']} -> {a['score']}, kills per minute {b['kpm']} -> "
                f"{a['kpm']}, deaths per round {b['deaths_per_round']} -> {a['deaths_per_round']}).")
        done = []
        for r in self.tickets(change):
            with self.store.lock:
                req = self.store.get('request', r['id'])
                if any(m.get('id') == f"gate-{change['id']}" for m in req.get('messages') or ()):
                    continue
                req.setdefault('messages', []).append({'id': f"gate-{change['id']}", 'author': 'agent',
                                                       'ts': self.now(), 'text': text, 'attachments': []})
                self.store.put('request', r['id'], req)
            done.append(r.get('number'))
        return done

    def flag(self, change, numbers, prs, why):
        """One request per judged change for a human (deterministic id: never twice). -> its number."""
        import hashlib
        listed = ', '.join(f"#{p['number']} ({p['title']})" for p in prs) or 'none found'
        body = (f"The learning gate (gbox/mercs/gate.py) judged the {title_name(change['title'])} bot change that went "
                f"live at {_clock(change['at'])} ({change['kind']}: "
                f"{', '.join(change.get('modules') or change.get('files') or [])}) worse: {numbers}. It did not "
                f"revert it automatically: {why}. PRs in the window: {listed}. Decide whether to revert; "
                'GET /api/mercs/learning has the numbers.')
        rid = hashlib.sha256(('mercs-learning-gate:' + change['id']).encode()).hexdigest()[:16]
        now = self.now()
        with self.store.lock:
            self.store.db.execute('BEGIN IMMEDIATE')
            try:
                row = self.store.db.execute("SELECT body FROM docs WHERE kind='request' AND id=?", (rid,)).fetchone()
                if row:
                    self.store.db.rollback()
                    return json.loads(row[0]).get('number')
                number = self.store.db.execute("SELECT COALESCE(MAX(CAST(json_extract(body,'$.number') AS INT)),0)+1 "
                                               "FROM docs WHERE kind='request'").fetchone()[0]
                req = {'id': rid, 'number': number, 'body': body, 'source': 'mercs_learning_gate', 'kind': 'report',
                       'title': f"Bot change made {title_name(change['title'])} worse: a human decides"[:140],
                       'author': 'agent', 'automated': True, 'status': 'open', 'created': now, 'started': None,
                       'completed': None, 'parent_request_id': None, 'image': None, 'element': None,
                       'context': {'learning_gate': True, 'change_id': change['id'], 'game_title': change['title'],
                                   'prs': [p['number'] for p in prs]},
                       'messages': [{'author': 'agent', 'text': body, 'ts': now, 'attachments': []}],
                       'metrics': {'tokens_in': 0, 'tokens_out': 0, 'tools': {}, 'files_changed': [],
                                   'duration_s': None, 'turns': 0}}
                self.store.db.execute('INSERT INTO docs VALUES(?,?,?)', ('request', rid, json.dumps(req)))
                self.store.db.commit()
                return number
            except BaseException:
                self.store.db.rollback()
                raise

    def _save(self, change, gate):
        from .learning import CHANGE
        doc = self.store.get(CHANGE, change['id']) or change
        doc['gate'] = gate
        self.store.put(CHANGE, change['id'], doc)
        change['gate'] = gate

    def log(self, change, gate):
        state = self.store.get(STATE, 'log') or {'decisions': []}
        state['decisions'] = (state['decisions'] + [{
            'at': self.now(), 'change': change['id'], 'title': change['title'], 'kind': change['kind'],
            'change_at': change['at'], **{k: gate.get(k) for k in ('state', 'p', 'reasons', 'prs', 'reverted_pr',
                                                                    'revert_pr', 'flag', 'request', 'reopened',
                                                                    'notified')},
            'score': [gate['before'].get('score'), gate['after'].get('score')],
            'deaths_per_round': [gate['before'].get('deaths_per_round'), gate['after'].get('deaths_per_round')],
            'kpm': [gate['before'].get('kpm'), gate['after'].get('kpm')]}])[-100:]
        self.store.put(STATE, 'log', state)

    def decisions(self, title=None):
        found = (self.store.get(STATE, 'log') or {}).get('decisions') or []
        return [d for d in found if title is None or d['title'] == title]


def title_name(title):
    from .damage_clusters import TITLE_NAMES
    return TITLE_NAMES.get(title, title)


def _clock(at):
    return time.strftime('%m-%d %H:%M', time.localtime(at)) if type(at) in (int, float) and at > 0 else '?'
