"""Spark helper: LLM-free chores that make Hermes's work cheaper, run by the gBox service at idle priority.

A registry of chores with per-chore cooldowns. One chore runs at a time in one background thread (nice 19, idle
I/O class), and only while the Spark is free: no game the operator plays on the Spark, no build running. A running
chore checks ``give_way()`` between steps and stops (``Yielded``) the moment that changes; the jobs it submitted are
cancelled. Nothing here calls a language model, merges a PR, or starts a game on the operator's PC.

GET  /api/grunt            status: what the helper is doing, why it waits, each chore's last result and next run
POST /api/grunt            {"enabled": bool} pause/resume the helper; {"run": "<chore>"} make one chore due now

Chores (docs/hermes-local-fallback.md):

  triage_inbox         new inbox items: classify, find duplicates, attach related failed jobs, queue priority
  draft_pr_tests       open Hermes draft PRs: focused tests in a scratch worktree, results on the PR and request
  fingerprints         favorite games without an assimilate fingerprint: one assimilate op=fingerprint job each
  character_readiness  characters op=readiness (replacement readiness and the compatibility index)
  collect_characters   favorite / recently played games with a reader and no collection: one collect job each
  mod_manifests        SHA-256 manifests of built mod folders (data_dir/built_mod_manifests), bounded per pass
  warm_indexes         asset, character and built-mod indexes rebuilt ahead of use
  hot_cache            recently played and favorite games queued for promotion to the hot cache tier
  verify_launch_fixes  resolved launch-failure tickets: one evidence_capture on an allowed idle node (never the
                       operator's PC or JAYBUILTFINALE), result posted on the ticket
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

IS_LINUX = sys.platform.startswith('linux')


class Yielded(Exception):
    """The Spark became busy (the operator plays, a build started): the chore stopped early."""


# ------------------------------------------------------------------------------------------------ registry

class Chore:
    def __init__(self, name: str, title: str, cooldown_s: float, fn, doing: str = ''):
        self.name, self.title, self.cooldown_s, self.fn, self.doing = name, title, cooldown_s, fn, doing or title


class Registry:
    """Runs at most one due chore per tick, oldest-run first. `gate()` returns why the Spark is busy, or None.
    State (last run, results, per-chore memory such as tested PR heads) persists in `state_path`."""

    def __init__(self, chores, gate, ctx, *, state_path: Path | None = None, clock=time.time, cooldowns=None,
                 disabled=(), tick_s: float = 60.0, start_delay_s: float = 0.0):
        self.chores = list(chores)
        self.gate, self.ctx, self.clock = gate, ctx, clock
        self.state_path = state_path
        self.cooldowns = dict(cooldowns or {})
        self.disabled = set(disabled)
        self.tick_s, self.start_delay_s = tick_s, start_delay_s
        self.lock = threading.RLock()
        self.running: str | None = None
        self.running_since = 0.0
        self.waiting: str | None = None
        self.thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self.state = self._load()
        ctx.memory = self.memory

    # -- persistence
    def _load(self) -> dict:
        if self.state_path and self.state_path.exists():
            with contextlib.suppress(OSError, ValueError):
                data = json.loads(self.state_path.read_text())
                if isinstance(data, dict):
                    data.setdefault('chores', {})
                    data.setdefault('memory', {})
                    data.setdefault('enabled', True)
                    return data
        return {'enabled': True, 'chores': {}, 'memory': {}}

    def save(self) -> None:
        if not self.state_path:
            return
        with self.lock, contextlib.suppress(OSError):
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.state, indent=1, default=str))
            tmp.replace(self.state_path)

    def memory(self, name: str) -> dict:
        """A chore's own durable notes (tested PR heads, triaged requests, ...)."""
        with self.lock:
            return self.state['memory'].setdefault(name, {})

    # -- scheduling
    def cooldown(self, chore: Chore) -> float:
        return float(self.cooldowns.get(chore.name, chore.cooldown_s))

    def due(self, now: float | None = None) -> list[Chore]:
        now = self.clock() if now is None else now
        out = []
        for chore in self.chores:
            rec = self.state['chores'].get(chore.name) or {}
            if chore.name in self.disabled:
                continue
            if rec.get('force') or now - (rec.get('last_run') or 0) >= self.cooldown(chore):
                out.append(chore)
        return sorted(out, key=lambda c: (not (self.state['chores'].get(c.name) or {}).get('force'),
                                          (self.state['chores'].get(c.name) or {}).get('last_run') or 0,
                                          self.chores.index(c)))

    def give_way(self) -> None:
        reason = self.gate()
        if reason:
            raise Yielded(reason)

    def tick(self) -> dict:
        """One scheduling step: the busy reason, or the chore that ran and its result."""
        if not self.state.get('enabled', True):
            self.waiting = 'paused by the operator'
            return {'waiting': self.waiting}
        reason = self.gate()
        if reason:
            self.waiting = reason
            return {'waiting': reason}
        self.waiting = None
        due = self.due()
        if not due:
            return {'idle': True}
        chore = due[0]
        with self.lock:
            self.running, self.running_since = chore.name, self.clock()
        t0 = self.clock()
        rec = dict(self.state['chores'].get(chore.name) or {})
        rec.pop('force', None)
        try:
            result = chore.fn(self.ctx, self.give_way) or {}
            rec.update(last_status='ok', last_result=_short(result), runs=rec.get('runs', 0) + 1)
        except Yielded as e:
            result = {'yielded': str(e)}
            rec.update(last_status='yielded', last_result=result)
            self.waiting = str(e)
        except Exception as e:                         # noqa: BLE001 - one chore never stops the helper
            result = {'error': f'{type(e).__name__}: {e}'[:300]}
            rec.update(last_status='error', last_result=result, errors=rec.get('errors', 0) + 1)
        finally:
            with self.lock:
                self.running = None
        now = self.clock()
        # A chore that gave way runs again soon (its cooldown restarts only after a full pass).
        rec.update(last_run=now if rec.get('last_status') != 'yielded' else rec.get('last_run', 0),
                   last_attempt=now, last_duration_s=round(now - t0, 1))
        with self.lock:
            self.state['chores'][chore.name] = rec
        self.save()
        return {'ran': chore.name, 'result': result}

    def force(self, name: str) -> None:
        if not any(c.name == name for c in self.chores):
            raise KeyError(name)
        with self.lock:
            self.state['chores'].setdefault(name, {})['force'] = True
        self.save()
        self._wake.set()

    def set_enabled(self, on: bool) -> None:
        with self.lock:
            self.state['enabled'] = bool(on)
        self.save()
        self._wake.set()

    def status(self) -> dict:
        now = self.clock()
        with self.lock:
            running = self.running
            chores = []
            for c in self.chores:
                rec = self.state['chores'].get(c.name) or {}
                last = rec.get('last_run') or 0
                chores.append({'name': c.name, 'title': c.title, 'enabled': c.name not in self.disabled,
                               'cooldown_s': self.cooldown(c), 'last_run': last or None,
                               'last_status': rec.get('last_status'), 'last_result': rec.get('last_result'),
                               'last_duration_s': rec.get('last_duration_s'), 'runs': rec.get('runs', 0),
                               'errors': rec.get('errors', 0), 'running': c.name == running,
                               'next_run_at': None if c.name in self.disabled else max(now, last + self.cooldown(c))})
        doing = next((c.doing for c in self.chores if c.name == running), None)
        return {'enabled': bool(self.state.get('enabled', True)), 'running': running, 'running_since':
                self.running_since if running else None, 'doing': doing, 'waiting': self.waiting,
                'label': f'Spark helper: {doing}' if doing else (
                    f'Spark helper waiting: {self.waiting}' if self.waiting else 'Spark helper idle'),
                'alive': bool(self.thread and self.thread.is_alive()), 'chores': chores}

    # -- thread
    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self._stop.clear()
        self.thread = threading.Thread(target=self._loop, name='spark-grunt', daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _loop(self) -> None:
        lower_priority()
        if self._stop.wait(self.start_delay_s):
            return
        while not self._stop.is_set():
            with contextlib.suppress(Exception):
                self.tick()
            self._wake.wait(self.tick_s)
            self._wake.clear()


def _short(result) -> dict:
    text = json.dumps(result, default=str)
    if len(text) <= 2000:
        return result if isinstance(result, dict) else {'result': result}
    return {'summary': text[:2000] + '…'}


def lower_priority() -> None:
    """This thread at nice 19 and in the idle I/O class (Linux; no-op elsewhere)."""
    from . import cache_tiers
    cache_tiers._nice_thread(19)
    cache_tiers._io_priority(True)


def low_priority_cmd(args: list[str]) -> list[str]:
    """A subprocess at nice 19 / idle I/O when those tools exist (Linux)."""
    if not IS_LINUX:
        return args
    import shutil
    prefix = []
    if shutil.which('nice'):
        prefix += ['nice', '-n', '19']
    if shutil.which('ionice'):
        prefix += ['ionice', '-c', '3']
    return prefix + args


# ------------------------------------------------------------------------------------------------ gates

def is_build(job: dict) -> bool:
    """A running job that builds (a mod writer, cast swap, export ...), by build_notify's rules."""
    from . import build_notify as B
    tool, inp = str(job.get('tool') or ''), job.get('input') if isinstance(job.get('input'), dict) else {}
    op = str(inp.get('op') or '').lower()
    if tool in B.NOT_BUILD_TOOLS or tool.startswith('session') or op in B.NOT_BUILD_OPS or inp.get('plan_only'):
        return False
    if inp.get('session_id') and op not in B.FILE_BUILD_OPS:
        return False
    return op in B.BUILD_OPS or (not op and bool(B.BUILDER_NAME.search(tool)))


def spark_workers(workers: list[dict], local_name: str | None = None) -> set[str]:
    """Worker ids that are this control plane's node (the Spark): its Linux workers, or the one named like the host."""
    import platform
    name = (local_name or platform.node() or '').casefold()
    return {w['id'] for w in workers if w.get('os') == 'linux' or (name and str(w.get('name', '')).casefold() == name)}


def operator_session_on(sessions, labels, node_ids, resolve=lambda wid: wid) -> dict | None:
    """A running game on these nodes that the operator (not an agent's test) started, else None."""
    for sess in sessions:
        sid = sess.get('session_id') or ''
        if sess.get('state') != 'running' or resolve(sid.split('-')[0]) not in node_ids:
            continue
        label = labels.get(sid) or {}
        if label.get('owner') == 'agent' or str(label.get('label', '')).startswith(('Evidence capture', 'Spark helper')):
            continue
        return sess
    return None


# ------------------------------------------------------------------------------------------------ chores

LAUNCH_WORDS = re.compile(r"\b(fail\w* to (?:launch|boot|start|load)|(?:launch|boot)(?:es|s|ed|ing)? fail\w*|"
                          r"(?:won'?t|doesn'?t|does not|can'?t|cannot|never) (?:boot|start|launch|load)|"
                          r"boots? (?:to|into) (?:a )?black|(?:launch|boot)\w* .{0,40}\b(?:black screen|crash\w*|hang\w*|stuck))",
                          re.I)
KINDS = (('launch_failure', LAUNCH_WORDS),
         ('crash', re.compile(r'\b(crash\w*|freez\w*|frozen|hang\w*|stall\w*|\d+ ?fps|slow ?down|stutter\w*)\b', re.I)),
         ('regression', re.compile(r'\b(regression|used to work|broke|broken since|stopped working|after (the )?update)\b', re.I)),
         ('character', re.compile(r'\b(character|replacement|swap|model|rig|skin|costume|cast)\b', re.I)),
         ('ui', re.compile(r'\b(button|window|panel|icon|menu|ui|layout|tooltip|dock|overlay)\b', re.I)))
URGENT = ('launch_failure', 'crash', 'regression')


def classify(request: dict) -> str:
    text = f"{request.get('title') or ''}\n{request.get('body') or ''}"
    return next((kind for kind, rx in KINDS if rx.search(text)), 'feature')


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r'[a-z0-9]+', (text or '').lower()) if len(w) > 2 and w not in
            {'the', 'and', 'for', 'with', 'when', 'that', 'this', 'from', 'auto', 'report', 'failed', 'game'}}


def duplicate_of(request: dict, others: list[dict], threshold: float = 0.75) -> dict | None:
    """The oldest other open request with (nearly) the same title, on the same game when both name one."""
    mine = _words(request.get('title') or '')
    if len(mine) < 2:
        return None
    gid = (request.get('context') or {}).get('game_id')
    best = None
    for other in others:
        if other.get('id') == request.get('id') or other.get('status') not in ('open', 'in_progress'):
            continue
        if (other.get('created') or 0) > (request.get('created') or 0):
            continue
        ogid = (other.get('context') or {}).get('game_id')
        if gid and ogid and gid != ogid:
            continue
        theirs = _words(other.get('title') or '')
        if not theirs:
            continue
        score = len(mine & theirs) / len(mine | theirs)
        if score >= threshold and (best is None or (other.get('created') or 0) < (best.get('created') or 0)):
            best = other
    return best


def triage_inbox(ctx, give_way) -> dict:
    """New open requests: kind, duplicate, related failed jobs (as a short note), urgent ones into the queue priority."""
    mem = ctx.memory('triage_inbox')
    seen = set(mem.get('seen') or [])
    requests = ctx.requests()
    now = time.time()
    fresh = [r for r in requests if r.get('id') not in seen and r.get('status') in ('open', 'in_progress')
             and now - (r.get('created') or 0) < 14 * 86400
             and not str(r.get('title') or '').startswith('gBox request review')]
    if not mem.get('primed'):
        # First pass: remember what is already there; only items that arrive later get notes.
        mem.update(primed=True, seen=sorted({r.get('id') for r in requests if r.get('id')})[-5000:])
        return {'primed': len(mem['seen'])}
    noted, urgent, kinds = [], [], {}
    for r in sorted(fresh, key=lambda r: r.get('created') or 0)[:25]:
        give_way()
        kind = classify(r)
        kinds[kind] = kinds.get(kind, 0) + 1
        lines = []
        dup = duplicate_of(r, requests)
        if dup:
            lines.append(f"Possible duplicate of #{dup.get('number')} ({dup.get('id')}): {str(dup.get('title'))[:100]}")
        gid = (r.get('context') or {}).get('game_id')
        failed = ctx.failed_jobs(gid, since=(r.get('created') or now) - 86400) if gid else []
        for j in failed[:3]:
            lines.append(f"Related failed job {j.get('id')} ({j.get('tool')}): {str(j.get('error') or '')[:160]}")
        if kind in URGENT:
            urgent.append(r['id'])
        if lines:
            ctx.post(r['id'], 'Spark helper triage (' + kind.replace('_', ' ') + '):\n' + '\n'.join(lines))
            noted.append(r.get('number'))
        seen.add(r['id'])
        mem.setdefault('kinds', {})[r['id']] = kind
    if urgent:
        ctx.prioritize(urgent)
    mem['seen'] = sorted(seen)[-5000:]
    mem['kinds'] = dict(list((mem.get('kinds') or {}).items())[-2000:])
    return {'triaged': sum(kinds.values()), 'kinds': kinds, 'noted': noted, 'prioritized': len(urgent)}


def select_tests(changed: list[str], system_dir: Path, limit: int = 10) -> list[str]:
    """Focused tests for a PR: the test files it changes, then tests named after the modules it changes."""
    out: list[str] = []
    for name in changed:
        rel = name[len('system/'):] if name.startswith('system/') else name
        if re.fullmatch(r'tests/test_\w+\.py', rel) and (system_dir / rel).is_file():
            out.append(rel)
    for name in changed:
        m = re.fullmatch(r'(?:system/)?gbox/(\w+)\.py', name)
        if not m:
            continue
        for cand in sorted((system_dir / 'tests').glob(f'test_{m[1]}*.py')):
            out.append(f'tests/{cand.name}')
    return list(dict.fromkeys(out))[:limit]


def pytest_summary(output: str) -> str:
    found = re.findall(r'(\d+) (passed|failed|errors?|skipped|xfailed|xpassed)', output or '')
    if not found:
        return 'no pytest summary'
    return ', '.join(f'{n} {w}' for n, w in found)


def draft_pr_tests(ctx, give_way) -> dict:
    """The oldest open Hermes draft PR whose head was not tested yet: focused tests in a scratch worktree."""
    mem = ctx.memory('draft_pr_tests')
    tested = mem.setdefault('tested', {})
    pulls = ctx.draft_pulls()
    todo = [p for p in pulls if p.get('isDraft') and str(p.get('headRefName', '')).startswith('hermes/')
            and tested.get(str(p['number'])) != p.get('headRefOid')]
    if not todo:
        return {'open_drafts': len(pulls), 'tested': 0}
    pull = min(todo, key=lambda p: p['number'])
    give_way()
    result = ctx.test_pull(pull, give_way)
    tested[str(pull['number'])] = pull['headRefOid']
    for key in list(tested):
        if key not in {str(p['number']) for p in pulls}:
            tested.pop(key)
    text = (f"Spark helper ran this draft's focused tests at {pull['headRefOid'][:10]} (no merge): "
            f"{result.get('summary')}.\nTests: {', '.join(result.get('tests') or []) or 'none found'}")
    if result.get('tail'):
        text += '\n```text\n' + result['tail'][-1500:] + '\n```'
    ctx.comment_pull(pull['number'], text)
    rid = request_of(pull)
    if rid:
        ctx.post(rid, f"Draft PR #{pull['number']}: {text}")
    return {'pr': pull['number'], 'summary': result.get('summary'), 'request_id': rid}


def request_of(pull: dict) -> str | None:
    m = re.search(r'gBox request #\d+ \(([0-9a-f]{16})\)', pull.get('body') or '')
    return m[1] if m else None


def fingerprints(ctx, give_way) -> dict:
    """One favorite queue game without a usable assimilate fingerprint: run assimilate op=fingerprint for it."""
    items = [i for i in ctx.queue_favorites() if not i.get('fingerprint') or (i.get('fingerprint') or {}).get('source') == 'error']
    if not items:
        return {'missing': 0}
    item = items[0]
    give_way()
    job = ctx.run_job('assimilate', {'op': 'fingerprint', 'game_id': item['game_id']}, give_way, timeout_s=1800)
    out = ((job.get('output') or {}).get('result')) if job.get('state') == 'succeeded' else None
    if not out:
        return {'game_id': item['game_id'], 'state': job.get('state'), 'error': str(job.get('error') or '')[:200]}
    from .assimilate import compact
    fp = compact(out)
    ctx.save_fingerprint(item['game_id'], fp)
    return {'game_id': item['game_id'], 'summary': str(fp.get('summary') or '')[:200], 'missing_left': len(items) - 1}


def character_readiness(ctx, give_way) -> dict:
    give_way()
    job = ctx.run_job('characters', {'op': 'readiness'}, give_way, timeout_s=3600)
    res = (job.get('output') or {}).get('result') or {}
    return {'state': job.get('state'), **{k: res[k] for k in ('characters', 'games', 'updated', 'status') if k in res},
            **({'error': str(job.get('error'))[:200]} if job.get('error') else {})}


def collect_characters(ctx, give_way) -> dict:
    """One favorite or recently played game with a registered reader and no collection: run its collect job."""
    for game in ctx.collection_candidates():
        give_way()
        job_id = ctx.schedule_collect(game)
        if not job_id:
            continue
        job = ctx.wait_job(job_id, give_way, timeout_s=3600)
        res = (job.get('output') or {}).get('result') or {}
        return {'game_id': game.get('game_id'), 'title': game.get('title'), 'state': job.get('state'),
                'status': res.get('status'), 'collected': res.get('collected')}
    return {'candidates': 0}


def mod_manifests(ctx, give_way) -> dict:
    """SHA-256 manifests of built mod folders (new or changed markers first), bounded per pass."""
    from . import built_mods
    root = built_mods.mods_root(ctx.config)
    out_root = Path(ctx.config.data_dir) / 'built_mod_manifests'
    budget = int(getattr(ctx.config.hermes.grunt, 'manifest_budget_mb', 4096)) << 20
    done, hashed = [], 0
    for gid, name, folder, st in built_mods._mod_dirs(root):
        if name is None:
            continue
        target = out_root / gid / f'{name}.json'
        marker = [st.st_mtime_ns, st.st_size]
        with contextlib.suppress(OSError, ValueError):
            if json.loads(target.read_text()).get('marker') == marker:
                continue
        files, total = {}, 0
        for path in sorted(folder.rglob('*')):
            give_way()
            if path.is_symlink() or not path.is_file():
                continue
            h = hashlib.sha256()
            with path.open('rb') as f:
                for block in iter(lambda: f.read(1 << 20), b''):
                    h.update(block)
                    total += len(block)
                    if total % (64 << 20) < (1 << 20):
                        give_way()
            files[path.relative_to(folder).as_posix()] = {'sha256': h.hexdigest(), 'size': path.stat().st_size}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({'game_id': gid, 'mod': name, 'marker': marker, 'hashed_at': time.time(),
                                      'bytes': total, 'files': files}, indent=1))
        done.append(f'{gid}/{name}')
        hashed += total
        if hashed >= budget:
            break
    return {'hashed': len(done), 'bytes': hashed, 'mods': done[:10]}


def warm_indexes(ctx, give_way) -> dict:
    give_way()
    return ctx.warm()


def hot_cache(ctx, give_way) -> dict:
    from . import cache_tiers
    give_way()
    games = ctx.recent_games(days=3) + [g.get('game_id') for g in ctx.favorites()]
    keys = [g for g in dict.fromkeys(games) if g]
    if cache_tiers.ACTIVE is None:
        return {'tiers': 'single tier', 'games': len(keys)}
    cache_tiers.touch(*keys, queue=True)
    return {'queued_for_hot_tier': len(keys)}


def verify_launch_fixes(ctx, give_way) -> dict:
    """One resolved launch-failure ticket: an evidence capture on an allowed idle node, the result on the ticket."""
    mem = ctx.memory('verify_launch_fixes')
    verified = mem.setdefault('verified', {})
    now = time.time()
    tickets = [r for r in ctx.requests() if r.get('status') == 'done' and r.get('id') not in verified
               and now - (r.get('completed') or 0) < 14 * 86400 and (r.get('context') or {}).get('game_id')
               and classify(r) == 'launch_failure']
    if not tickets:
        return {'tickets': 0}
    node = ctx.verify_node()
    if not node:
        return {'tickets': len(tickets), 'waiting': 'no allowed idle node (i9-NUC / Spark)'}
    r = min(tickets, key=lambda r: r.get('completed') or 0)
    gid = r['context']['game_id']
    give_way()
    job = ctx.run_job('evidence_capture', {'game_id': gid, 'node': node['name']}, give_way, timeout_s=1800)
    out = job.get('output') or {}
    runs = out.get('runs') or []
    reached = any(x.get('reached') for x in runs)
    frames = out.get('frames') or []
    verified[r['id']] = {'at': now, 'job_id': job.get('id'), 'state': job.get('state'), 'reached': reached}
    if job.get('state') == 'succeeded':
        text = (f"Spark helper verification launch on {node['name']} (job {job.get('id')}): "
                + ('the game reached gameplay' if reached else 'the game did NOT reach gameplay')
                + f"; {len(frames)} frame(s) captured" + (': ' + ', '.join(f.get('sha256', '')[:12] for f in frames[:4])
                                                          if frames else '') + '.')
        if not reached:
            text += ' The fix may not hold on this node; consider reopening.'
    else:
        text = f"Spark helper verification launch on {node['name']} could not finish: {str(job.get('error') or job.get('state'))[:200]}"
    ctx.post(r['id'], text)
    return {'request': r.get('number'), 'node': node['name'], 'reached': reached, 'state': job.get('state')}


CHORES = (
    Chore('triage_inbox', 'Inbox triage', 600, triage_inbox, 'triaging new inbox items'),
    Chore('draft_pr_tests', 'Draft PR tests', 1800, draft_pr_tests, 'testing a Hermes draft PR'),
    Chore('fingerprints', 'Assimilate fingerprints', 1800, fingerprints, 'fingerprinting a favorite game'),
    Chore('character_readiness', 'Character readiness', 6 * 3600, character_readiness,
          'backfilling character readiness'),
    Chore('collect_characters', 'Character collection', 3600, collect_characters, 'collecting a game\'s characters'),
    Chore('mod_manifests', 'Built mod manifests', 2 * 3600, mod_manifests, 'hashing built mod manifests'),
    Chore('warm_indexes', 'Index warm-up', 1800, warm_indexes, 'warming the asset and character indexes'),
    Chore('hot_cache', 'Hot cache promotion', 3600, hot_cache, 'queueing recent games for the hot cache'),
    Chore('verify_launch_fixes', 'Launch-fix verification', 3600, verify_launch_fixes,
          'verifying a resolved launch failure'),
)


# ------------------------------------------------------------------------------------------------ git / gh helpers

def _run(args, cwd, timeout=120, env=None):
    result = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=timeout, env=env)
    if result.returncode:
        # Never echo git/gh stderr: it can carry an authenticated remote URL.
        raise RuntimeError(f'{args[0]} {args[1] if len(args) > 1 else ""} failed (exit {result.returncode})')
    return result.stdout


def list_draft_pulls(repo: Path) -> list[dict]:
    from . import hermes_delivery
    rows = json.loads(_run(['gh', 'pr', 'list', '--repo', hermes_delivery.REPOSITORY, '--state', 'open', '--limit',
                            '60', '--json', 'number,headRefName,headRefOid,isDraft,body,title'], repo, timeout=60))
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get('number'), int)]


def run_pull_tests(pull: dict, give_way, *, repo: Path, timeout_s: float = 900.0) -> dict:
    """Fetch the PR head into a detached scratch worktree, run its focused tests at low priority, remove it."""
    number, sha = int(pull['number']), str(pull['headRefOid'])
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('unexpected PR head')
    scratch = repo.parent / 'gbox-grunt-scratch' / f'pr-{number}'
    ref = f'refs/gbox-grunt/pr-{number}'
    if scratch.exists():
        with contextlib.suppress(Exception):
            _run(['git', 'worktree', 'remove', '--force', str(scratch)], repo)
    _run(['git', 'fetch', '--quiet', 'origin', 'main', f'+refs/pull/{number}/head:{ref}'], repo, timeout=180)
    if _run(['git', 'rev-parse', ref], repo).strip() != sha:
        return {'summary': 'skipped: the PR head moved while fetching', 'tests': []}
    _run(['git', 'worktree', 'add', '--detach', str(scratch), sha], repo)
    try:
        changed = _run(['git', 'diff', '--name-only', f'origin/main...{sha}'], scratch).split()
        system = scratch / 'system'
        tests = select_tests(changed, system)
        if not tests:
            return {'summary': 'no focused tests for the changed files', 'tests': [], 'changed': changed[:20]}
        python = Path(__file__).resolve().parents[1] / '.venv-linux-aarch64/bin/python'
        python = python if python.exists() else Path(sys.executable)
        env = os.environ | {'PYTHONPATH': str(system), 'GBOX_LOCAL_LLM_NOLOG': '1'}
        proc = subprocess.Popen(low_priority_cmd([str(python), '-m', 'pytest', *tests, '-q', '-p', 'no:cacheprovider']),
                                cwd=str(system), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding='utf-8', errors='replace', env=env)
        start = time.time()
        try:
            while proc.poll() is None:
                if time.time() - start > timeout_s:
                    proc.kill()
                    return {'summary': f'timed out after {int(timeout_s)} s', 'tests': tests}
                give_way()
                time.sleep(2)
        except Yielded:
            proc.kill()
            raise
        output = proc.stdout.read() if proc.stdout else ''
        summary = pytest_summary(output) + ('' if proc.returncode == 0 else f' (exit {proc.returncode})')
        return {'summary': summary, 'tests': tests, 'tail': '\n'.join(output.strip().splitlines()[-15:]),
                'exit': proc.returncode}
    finally:
        with contextlib.suppress(Exception):
            _run(['git', 'worktree', 'remove', '--force', str(scratch)], repo)
        with contextlib.suppress(Exception):
            _run(['git', 'update-ref', '-d', ref], repo)


def comment_pull(number: int, text: str, repo: Path) -> None:
    from . import hermes_delivery
    path = hermes_delivery.state_dir() / f'grunt-pr-{int(number)}.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    try:
        _run(['gh', 'pr', 'comment', str(int(number)), '--repo', hermes_delivery.REPOSITORY, '--body-file', str(path)],
             repo, timeout=60)
    finally:
        with contextlib.suppress(OSError):
            path.unlink()


# ------------------------------------------------------------------------------------------------ the service side

class ServiceContext:
    """What the chores need from the running control plane, as plain methods (tests pass their own object).

    submit(tool, input) -> job dict; cancel(job_id); workers() -> worker rows; resolve(worker_id) -> current id."""

    def __init__(self, *, store, config, submit, cancel, workers, auto_collection=None, app_state=None,
                 resolve=lambda wid: wid, poll_s: float = 3.0):
        self.store, self.config = store, config
        self._submit, self._cancel, self._workers = submit, cancel, workers
        self.auto_collection, self.app_state, self.resolve, self.poll_s = auto_collection, app_state, resolve, poll_s
        self.jobs_started: set[str] = set()
        self.memory = lambda name: {}

    # -- inbox
    def requests(self) -> list[dict]:
        return self.store.all('request')

    def post(self, rid: str, text: str) -> None:
        with self.store.lock:
            r = self.store.get('request', rid)
            if not r:
                return
            r.setdefault('messages', []).append({'author': 'agent', 'text': text[:4000], 'ts': time.time(),
                                                 'attachments': []})
            self.store.put('request', rid, r)
        with contextlib.suppress(Exception):
            self.store.audit('spark-helper', 'request.message', rid, {'author': 'agent', 'chars': len(text)})

    def failed_jobs(self, gid: str, since: float) -> list[dict]:
        out = []
        for j in self.store.jobs(states=('failed',), limit=200, reverse=True):
            inp = j.get('input') if isinstance(j.get('input'), dict) else {}
            game = inp.get('game') if isinstance(inp.get('game'), dict) else {}
            if (j.get('finished') or 0) >= since and gid in (inp.get('game_id'), game.get('game_id')):
                out.append({'id': j.get('id'), 'tool': j.get('tool'), 'error': j.get('error')})
        return out

    def prioritize(self, ids) -> None:
        from . import hermes_work_queue
        with contextlib.suppress(OSError):           # the queue tick holds its lock: next pass
            hermes_work_queue.add_triage_priority(ids)

    # -- GitHub
    def _repo(self) -> Path:
        from . import hermes_delivery
        repo = hermes_delivery.repository()
        if not (repo / '.git').exists():
            raise RuntimeError('the tracked Hermes repository is not provisioned on this node')
        return repo

    def draft_pulls(self) -> list[dict]:
        return list_draft_pulls(self._repo())

    def test_pull(self, pull, give_way) -> dict:
        return run_pull_tests(pull, give_way, repo=self._repo(),
                              timeout_s=float(self.config.hermes.grunt.pr_test_timeout_s))

    def comment_pull(self, number, text) -> None:
        comment_pull(number, text, self._repo())

    # -- Hermes queue
    def queue_favorites(self) -> list[dict]:
        from . import hermes_work_queue as Q
        data = Q._read()
        # starred favorites and showcase titles (recently played, no writer yet: ensure_item) alike
        items = [i for i in data.get('items', {}).values() if i.get('lane') == 'favorite'
                 and (i.get('favorite') or i.get('showcase')) and i.get('in_catalog')]
        return sorted(items, key=lambda i: (Q.priority_rank(i, data), i.get('created') or 0))

    def save_fingerprint(self, gid: str, fp: dict) -> None:
        from . import hermes_delivery, hermes_work_queue as Q
        with hermes_delivery.locked('work-queue'):
            data = Q._read()
            item = data.get('items', {}).get('favorite:' + gid)
            if item is not None:
                item['fingerprint'] = fp
                Q._save(data)

    # -- jobs
    def submit(self, tool: str, inp: dict) -> dict:
        job = self._submit(tool, inp)
        if job.get('id'):
            self.jobs_started.add(job['id'])
        return job

    def wait_job(self, job_id: str, give_way, timeout_s: float = 3600.0) -> dict:
        start = time.time()
        while True:
            job = self.store.get('job', job_id) or {}
            if job.get('state') not in ('queued', 'running', 'cancelling'):
                self.jobs_started.discard(job_id)
                return job
            try:
                give_way()
            except Yielded:
                with contextlib.suppress(Exception):
                    self._cancel(job_id)
                raise
            if time.time() - start > timeout_s:
                with contextlib.suppress(Exception):
                    self._cancel(job_id)
                return job | {'state': 'timeout'}
            time.sleep(self.poll_s)

    def run_job(self, tool: str, inp: dict, give_way, timeout_s: float = 3600.0) -> dict:
        job = self.submit(tool, inp)
        if job.get('state') not in ('queued', 'running'):
            return job
        return self.wait_job(job['id'], give_way, timeout_s)

    # -- games
    def favorites(self) -> list[dict]:
        from .favorite_capabilities import paginate_favorites

        def page(params):
            total, items = self.store.search(**params)
            return {'total': total, 'offset': params['offset'], 'items': items}
        try:
            games, _ = paginate_favorites(page)
        except Exception:                          # noqa: BLE001 - favorites are a hint for chores, never required
            return []
        return games

    def recent_games(self, days: float = 7) -> list[str]:
        since = time.time() - days * 86400
        rows = sorted((s for s in self.store.all('session') if (s.get('started') or 0) >= since),
                      key=lambda s: -(s.get('started') or 0))
        return list(dict.fromkeys(s.get('game_id') for s in rows if s.get('game_id')))

    def collection_candidates(self) -> list[dict]:
        if self.auto_collection is None:
            return []
        from .character_collection import registered
        out, seen = [], set()
        for gid in [g.get('game_id') for g in self.favorites()] + self.recent_games(14):
            if not gid or gid in seen:
                continue
            seen.add(gid)
            game = self.store.catalog_get(gid)
            if not game or not registered(game):
                continue
            state = self.auto_collection.status(gid)
            if state.get('state') == 'not_started' or state.get('stale_reader'):
                out.append(game)
        return out

    def schedule_collect(self, game: dict) -> str | None:
        gid = game.get('game_id')
        before = (self.store.get('character_collection', gid) or {}).get('job_id')
        self.auto_collection._schedule(game, None, None, lambda request: self.submit(request['tool'], request['input']))
        after = (self.store.get('character_collection', gid) or {}).get('job_id')
        return after if after and after != before else None

    def warm(self) -> dict:
        out = {}
        assets = getattr(self.app_state, 'assets', None)
        if assets is not None:
            with contextlib.suppress(Exception):
                assets.warm()
                out['assets'] = 'warming'
        with contextlib.suppress(Exception):
            from . import characters
            root = characters.library_root(self.config)
            if Path(root).is_dir():
                out['characters'] = len(characters.list_all(root))
        built = getattr(self.app_state, 'built_mods', None)
        if built is not None:
            with contextlib.suppress(Exception):
                built.ask()
                out['built_mods'] = 'refreshing'
        return out

    # -- verification launches
    def verify_node(self) -> dict | None:
        """An online node the operator allowed for verification launches, idle and without a running game."""
        from . import background_testing
        grunt = self.config.hermes.grunt
        allowed = {n.casefold() for n in grunt.verify_nodes}
        never = {n.casefold() for n in grunt.never_nodes} | {'jaybuiltfinale'}
        operator = (os.environ.get('GBOX_OPERATOR_WORKER') or '').casefold()
        workers = [w for w in self._workers() if w.get('online')]
        spark = spark_workers(workers)
        excluded = background_testing.excluded(self.store)
        running = {self.resolve((s.get('session_id') or '').split('-')[0]) for s in self.store.all('session')
                   if s.get('state') == 'running'}
        for w in workers:
            name = str(w.get('name') or '').casefold()
            if name in never or (operator and name == operator):
                continue
            if not (name in allowed or ('spark' in allowed and w['id'] in spark)):
                continue
            if not background_testing.allowed(w, excluded) or w['id'] in running:
                continue
            if w.get('os') == 'windows' and (w.get('idle_seconds') is None or w['idle_seconds'] < 900):
                continue
            return w
        return None


def install(app, store, config, *, submit, cancel, workers, auto_collection, resolve) -> Registry:
    """Build the helper for this control plane (started at service start-up on the Spark only)."""
    from . import hermes_delivery
    grunt = config.hermes.grunt
    ctx = ServiceContext(store=store, config=config, submit=submit, cancel=cancel, workers=workers,
                         auto_collection=auto_collection, app_state=app.state, resolve=resolve)

    def gate():
        rows = workers()
        spark = spark_workers(rows)
        labels = {x['session_id']: x for x in store.all('slabel')}
        sess = operator_session_on(store.all('session'), labels, spark, resolve)
        if sess:
            return f"the operator is playing {sess.get('title') or sess.get('game_id') or 'a game'} on the Spark"
        for job in store.jobs(states=('running',)):
            if job.get('id') not in ctx.jobs_started and is_build(job):
                op = (job.get('input') or {}).get('op') if isinstance(job.get('input'), dict) else ''
                return f"a build is running ({job.get('tool')}{' ' + op if op else ''})"
        return None

    registry = Registry(CHORES, gate, ctx, state_path=hermes_delivery.state_dir() / 'spark-grunt.json',
                        cooldowns=grunt.cooldowns, disabled=grunt.disabled, tick_s=grunt.tick_s,
                        start_delay_s=grunt.start_delay_s)
    app.state.grunt = registry
    return registry
