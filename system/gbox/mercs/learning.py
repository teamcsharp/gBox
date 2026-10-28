"""The RE bots' self-improvement loop: rounds -> causes -> a change -> its measured effect.

The operator (2026-10-27 ~19:50): "every report that tells it about an incident where it failed to defend itself or
dispatch the enemies in the area or lost or died ... gets analyzed and results in meaningful change happening with
the bot ... better and better gameplay where we have the bot capable of self improvement and learning from the game."

What this module adds on top of gbox.mercs.damage_clusters (the hits and their causes):

  * rounds: every terminal round the Notebook saved (curriculum/<title>/rounds.sqlite, the driver's per-round
    counters), read incrementally. Each hit incident is joined to its round (its session's first round that ended at
    or after the hit), so a cause has a real rate per round - rounds without a hit count as zero - and each round
    names its stage when the driver recorded one (RE6 observed.stage, tuning_stage once the tuning hooks run).
  * round faults: causes no single hit shows - "bonus seen, not taken", "enemies within 5 m left alive (idle)",
    "gun lowered with enemies within 5 m", "relocation into a dead end", "a threat behind him while aiming",
    "aiming at a wall" - each with its rate per round and example rounds. Rounds a fault marks often enough become
    batch requests like the hit causes (gbox.mercs.damage_clusters.Clusters.upsert).
  * changes: a bot code change going live on the worker that plays the title (a bot_reload job that reloaded the
    title's modules, or a restart that changed their source hashes), and the learned tuning changes (tier a,
    gbox/mercs/tuning.py) are recorded as change documents.
  * effect: for each change, every cause's rate per round over the rounds before it and the EFFECT_ROUNDS after it.
    A batch request closed with a fix is reopened with the new evidence when no bot change went live within
    NO_CHANGE_S, or when its cause's rate did not drop by TARGET_DROP within EFFECT_ROUNDS rounds of the change.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import threading
import time

CHANGE = 'mercs_bot_change'
STATE = 'mercs_learning_state'
EFFECT_ROUNDS = 10                    # rounds after a change before its effect is judged
BASELINE_ROUNDS = 30                  # at most this many rounds before a change are its baseline
TARGET_DROP = 0.2                     # a fix must cut its cause's rate per round by this much
NO_CHANGE_S = 48 * 3600               # a closed batch with no bot change live this long after is reopened
ROUND_MAX_S = 900.0                   # a hit belongs to its session's first round ending at most this long after it
ROUNDS_READ = 600                     # newest Notebook rounds kept per title
TERMINAL = ('completed', 'died')

# Round faults: (key, label, value(observed) -> number, a round counts as marked at >= this, rule in words)
def _n(observed, *keys):
    for k in keys:
        v = observed.get(k)
        if type(v) in (int, float) and math.isfinite(v):
            return float(v)
    return 0.0


FAULTS = {
    '010018100CD46000': (
        ('bonus_missed', 'time bonus seen, not taken',
         lambda o: max(0.0, _n(o, 'round_bonuses_seen') - _n(o, 'round_bonuses_taken', 'bonuses_taken'))
         if _n(o, 'round_bonuses_seen') else 0.0, 1,
         'a statue seen (round_bonuses_seen) and not taken (round_bonuses_taken): the misses per round'),
        ('idle_among_foes', 'enemies within 5 m left alive (idle)', lambda o: _n(o, 'round_idle_in_5m_s'), 20,
         'seconds a round with a Majini within 5 m and no shot at it (round_idle_in_5m_s)'),
        ('unaimed_in_5m', 'gun lowered with enemies within 5 m', lambda o: _n(o, 'round_unaims_in_5m'), 3,
         'the gun lowered with a Majini within 5 m (round_unaims_in_5m)'),
        ('reloc_dead_end', 'relocation into a dead end',
         lambda o: _n(o, 'round_reloc_stuck') + _n(o, 'round_reloc_dead_ends'), 1,
         'a relocation that stopped against a wall or a dead end (round_reloc_stuck, round_reloc_dead_ends)'),
        ('behind_threat', 'a threat behind him while aiming at another', lambda o: _n(o, 'round_behind_threat_s'), 20,
         'seconds a Majini stood within 3 m behind him while he aimed at another (round_behind_threat_s)'),
        ('wall_aim', 'aiming at a wall', lambda o: _n(o, 'round_wall_aim_s'), 2,
         'seconds the gun\'s ray ended on geometry short of the target (round_wall_aim_s)'),
    ),
    '01002A000CD48000': (
        ('bonus_missed', 'time bonus seen, not taken', lambda o: _n(o, 'round_bonuses_missed'), 1,
         'time bonuses passed by (round_bonuses_missed)'),
        ('tablet_misses', 'tablet presses the game ignored', lambda o: _n(o, 'round_tablet_misses'), 3,
         'an R press for a tablet whose count did not fall (round_tablet_misses)'),
        ('pursuit_stuck', 'pursuit stuck on the way to the enemies', lambda o: _n(o, 'round_pursuit_stuck'), 2,
         'a pursuit of the census\'s nearest that made no progress (round_pursuit_stuck)'),
        ('bomb_act_damage', 'health lost while busy with his bomb', lambda o: _n(o, 'round_bomb_hits_taken'), 150,
         'health lost while placing, facing, walking off or setting off his bomb (round_bomb_hits_taken)'),
    ),
}
_R5S, _R6S = 'gbox/mercs/titles/re5_switch.py', 'gbox/mercs/titles/re6_switch.py'
FAULT_CODE = {
    '010018100CD46000': {
        'bonus_missed': ('statues are seen but the bonus run is not taken or not finished',
                         [(_R5S, 'Bot._bonus_tick'), (_R5S, 'Bot._go_bonus')]),
        'idle_among_foes': ('Majini within 5 m are not dispatched: no shot while they stand in reach',
                            [(_R5S, 'Bot._rampage'), (_R5S, 'Bot._choose'), (_R5S, 'Bot._decide')]),
        'unaimed_in_5m': ('the gun comes down (unaim, relocation, heal, mine) with Majini within 5 m',
                          [(_R5S, 'Bot._decide'), (_R5S, 'Bot._gun_down'), (_R5S, 'Bot._relocate')]),
        'reloc_dead_end': ('the relocation heading runs into walls and dead ends', [(_R5S, 'Bot._relocate')]),
        'behind_threat': ('the threat pick keeps the aim ahead while one stands close behind',
                          [(_R5S, 'Bot._threat_pick'), (_R5S, 'Bot._fault_tick')]),
        'wall_aim': ('the wall gate: the ray ends on geometry short of the target', [(_R5S, 'Bot._decide')]),
    },
    '01002A000CD48000': {
        'bonus_missed': ('time bonuses passed by', [(_R6S, 'Bot._bonus'), (_R6S, 'Bot._bonus_run')]),
        'tablet_misses': ('the tablet press is ignored by the game (timing, another action)',
                          [(_R6S, 'Bot._decide'), (_R6S, 'Bot._tablet_check')]),
        'pursuit_stuck': ('pursuit headings run into geometry', [(_R6S, 'Bot._pursue'), (_R6S, 'Bot._nav_heading')]),
        'bomb_act_damage': ('the bomb acts (place, face, walk off, set off) leave him open to hits',
                            [(_R6S, 'Bot._bomb'), (_R6S, 'Bot._bomb_escape'), (_R6S, 'Bot._bomb_walk')]),
    },
}
FAULT_MIN_SHARE, FAULT_MIN_ROUNDS = 0.1, 10  # a round fault becomes a batch when it marks this share of the rounds
# A code change for a title: a reloaded module or a changed source file with one of these prefixes (shared engine
# modules change every title's play).
MODULES = {
    '010018100CD46000': ('gbox.mercs.titles.re5_switch', 'gbox/mercs/titles/re5_switch'),
    '01002A000CD48000': ('gbox.mercs.titles.re6_switch', 'gbox/mercs/titles/re6_switch'),
    'BLUS30491': ('gbox.mercs.titles.re5_ps3', 'gbox.mercs.titles.re5_combat', 'gbox/mercs/titles/re5_ps3',
                  'gbox/mercs/titles/re5_combat'),
}
SHARED = ('gbox.mercs.engine', 'gbox.mercs.brain', 'gbox.mercs_bot', 'gbox.mercs.tuning', 'gbox/mercs/engine.py',
          'gbox/mercs/brain/', 'gbox/mercs_bot.py', 'gbox/mercs/tuning.py')


def touches(title, names) -> list:
    """The names (modules or source paths) whose change is a change of this title's bot."""
    own = MODULES.get(title, ())
    return sorted(n for n in names if isinstance(n, str) and (n.startswith(own) or n.startswith(SHARED)))


def stage_of(observed, row_stage=None):
    for v in (observed.get('tuning_stage'), observed.get('stage'), row_stage):
        if isinstance(v, str) and v and v != 'unknown':
            return v[:80]
    return None


def round_record(row):
    """The part of a Notebook row the loop reads."""
    o = row['observed']
    return {'id': row['id'], 'ts': row['ts'], 'outcome': row['outcome'], 'stage': stage_of(o, row.get('stage')),
            'session_id': o.get('source_session_id'), 'turn': o.get('source_autoplay_job_id'),
            'evidence_id': o.get('round_evidence_id') or row['id'], 'tuning_version': o.get('tuning_version'),
            'observed': o}


def assign(labelled, rounds):
    """{round id: [(incident, signature, new_episode)]} plus the unmatched: an incident's own round_evidence_id when it
    recorded one, else the first round of its session that ended at or after the hit (within ROUND_MAX_S)."""
    by_evidence = {r['evidence_id']: r for r in rounds}
    by_session = {}
    for r in rounds:
        by_session.setdefault(r['session_id'], []).append(r)
    for items in by_session.values():
        items.sort(key=lambda r: r['ts'])
    out, unmatched = {}, 0
    for inc, sig, new in labelled:
        r = by_evidence.get(inc.get('round_evidence_id'))
        if r is None:
            at = inc.get('observed_at') or 0
            r = next((x for x in by_session.get(inc.get('session_id'), ()) if 0 <= x['ts'] - at <= ROUND_MAX_S), None)
        if r is None:
            unmatched += 1
            continue
        out.setdefault(r['id'], []).append((inc, sig, new))
    return out, unmatched


def rates(rounds, joined, deaths_by_round, keys):
    """{signature: {'episodes', 'deaths', 'rounds', 'rate', 'deaths_per_round', 'marked_rounds'}} over these rounds."""
    out = {k: {'episodes': 0, 'deaths': 0, 'marked_rounds': 0} for k in keys}
    for r in rounds:
        seen = set()
        for _inc, sig, new in joined.get(r['id'], ()):
            if sig in out and new:
                out[sig]['episodes'] += 1
                seen.add(sig)
        for sig in deaths_by_round.get(r['id'], ()):
            if sig in out:
                out[sig]['deaths'] += 1
                seen.add(sig)
        for sig in seen:
            out[sig]['marked_rounds'] += 1
    n = len(rounds)
    for v in out.values():
        v.update(rounds=n, rate=round(v['episodes'] / n, 3) if n else None,
                 deaths_per_round=round(v['deaths'] / n, 3) if n else None)
    return out


def fault_rate(rounds, title, key):
    spec = next((f for f in FAULTS.get(title, ()) if f[0] == key), None)
    if spec is None or not rounds:
        return None
    values = [spec[2](r['observed']) for r in rounds]
    return round(sum(values) / len(values), 3)


class Learning:
    def __init__(self, store, data_dir, *, now=time.time):
        self.store, self.now = store, now
        self.root = Path(data_dir) if data_dir else None
        self._rounds = {}                 # title -> {'rowid': cursor, 'rows': [record]}
        self._lock = threading.Lock()     # the pass thread and the API's listing share the cache

    # rounds -------------------------------------------------------------------------------------------------------
    def rounds(self, title):
        """The newest ROUNDS_READ terminal rounds of a title, oldest first; only new Notebook rows are parsed."""
        with self._lock:
            return list(self._read_rounds(title))

    def _read_rounds(self, title):
        cache = self._rounds.setdefault(title, {'rowid': 0, 'rows': []})
        path = self.root / 'mercs/curriculum' / title / 'rounds.sqlite' if self.root else None
        if path is None or not path.is_file():
            return cache['rows']
        try:
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
                if not cache['rowid']:
                    first = db.execute('SELECT COALESCE(MAX(rowid),0) FROM rounds').fetchone()[0]
                    cache['rowid'] = max(0, first - ROUNDS_READ)
                found = db.execute('SELECT rowid, id, ts, stage, outcome, data FROM rounds WHERE rowid>? '
                                   'ORDER BY rowid LIMIT 400', (cache['rowid'],)).fetchall()
        except sqlite3.Error:
            return cache['rows']
        for rowid, rid, ts, stage, outcome, data in found:
            cache['rowid'] = rowid
            if outcome not in TERMINAL or len(data) > 512 * 1024:
                continue
            try:
                observed = json.loads(data)
            except ValueError:
                continue
            cache['rows'].append(round_record({'id': rid, 'ts': ts, 'stage': stage, 'outcome': outcome,
                                               'observed': observed}))
        cache['rows'] = sorted(cache['rows'], key=lambda r: r['ts'])[-ROUNDS_READ:]
        return cache['rows']

    # the clusters' rates and the round faults ----------------------------------------------------------------------
    def enrich(self, clusters, incidents, *, window_s):
        """Add the rate per round (Notebook rounds as the denominator) and the per-turn rates to the hit clusters, and
        return the round-fault clusters of the window. `clusters`: damage_clusters.summarize's output."""
        from . import damage_clusters as C
        start = self.now() - window_s
        labelled, deaths = C.label_all(incidents)
        faults = {}
        for gid, title in C.GAMES.items():
            if title not in {C.title_of(g) for g, _s in clusters} and title not in FAULTS:
                continue
            rounds = [r for r in self.rounds(title) if r['ts'] >= start]
            mine = [x for x in labelled if x[0].get('game_id') == gid]
            joined, unmatched = assign(mine, rounds)
            dead = {}
            dj, _u = assign([(inc, sig, True) for inc, sig, _e in deaths if inc.get('game_id') == gid], rounds)
            for rid, items in dj.items():
                dead[rid] = [sig for _i, sig, _n2 in items]
            sigs = [s for g, s in clusters if g == gid]
            overall = rates(rounds, joined, dead, sigs)
            turns = {}
            for r in rounds:
                turns.setdefault(r['turn'], []).append(r)
            per_turn = {t: rates(rs, joined, dead, sigs) for t, rs in turns.items()}
            for sig in sigs:
                c = clusters[(gid, sig)]
                c.update(rounds=len(rounds), rate_per_round=overall[sig]['rate'],
                         deaths_per_round=overall[sig]['deaths_per_round'],
                         marked_rounds=overall[sig]['marked_rounds'], unmatched_hits=unmatched,
                         round_turns=[{'turn': t, 'start': rs[0]['ts'], 'rounds': len(rs),
                                       'rate': per_turn[t][sig]['rate'], 'deaths': per_turn[t][sig]['deaths']}
                                      for t, rs in sorted(turns.items(), key=lambda kv: kv[1][0]['ts'])][-12:],
                         example_rounds=sorted({rid for rid, items in joined.items()
                                                for _i, s, _n2 in items if s == sig})[-5:])
            for key, label, value, mark, rule in FAULTS.get(title, ()):
                if not rounds:
                    continue
                vals = [(r, value(r['observed'])) for r in rounds]
                marked = [(r, v) for r, v in vals if v >= mark]
                suspect, code = FAULT_CODE.get(title, {}).get(key, ('unclassified', []))
                by_turn = []
                for t, rs in sorted(turns.items(), key=lambda kv: kv[1][0]['ts']):
                    vs = [value(r['observed']) for r in rs]
                    by_turn.append({'turn': t, 'start': rs[0]['ts'], 'rounds': len(rs),
                                    'rate': round(sum(vs) / len(vs), 3),
                                    'marked': sum(1 for v in vs if v >= mark)})
                share = len(marked) / len(rounds)
                faults[(gid, 'round:' + key)] = {
                    'id': C.cluster_id(gid, 'round:' + key), 'kind': 'round', 'game_id': gid, 'title': title,
                    'game': C.TITLE_NAMES.get(title, title), 'signature': 'round:' + key, 'label': label,
                    'rule': rule + f'; a round counts at {mark} or more', 'rounds': len(rounds),
                    'marked_rounds': len(marked), 'share_of_rounds': round(share, 3),
                    'rate_per_round': round(sum(v for _r, v in vals) / len(vals), 3),
                    'hits': 0, 'episodes': len(marked), 'deaths': sum(1 for r, _v in marked if r['outcome'] == 'died'),
                    'hp_lost': 0, 'first_at': rounds[0]['ts'], 'last_at': rounds[-1]['ts'],
                    'runs': sorted({str(r['turn']) for r, _v in marked}), 'turns': by_turn[-12:],
                    'trend': _trend([t['rate'] for t in by_turn]),
                    'examples': [{'round_id': r['id'], 'at': r['ts'], 'stage': r['stage'], 'value': v,
                                  'outcome': r['outcome'], 'turn': r['turn'], 'session_id': r['session_id'],
                                  'reviewer': f'/api/mercs/reviewer/round?title={title}&id={r["id"]}'}
                                 for r, v in sorted(marked, key=lambda x: -x[1])[:C.EXAMPLES]],
                    'suspect': suspect, 'code': [{'file': f, 'function': fn} for f, fn in code],
                    'batchable': share >= FAULT_MIN_SHARE and len(marked) >= FAULT_MIN_ROUNDS}
        return faults

    # changes and their effect --------------------------------------------------------------------------------------
    def track_changes(self, titles):
        """Change documents for bot code that went live: bot_reload jobs that reloaded a title's modules, and worker
        registrations whose source hashes of a title's files changed (a restart / deploy)."""
        state = self.store.get(STATE, 'changes') or {'jobs_after': 0, 'hashes': {}}
        found = []
        with self.store.reading() as db:
            jobs = db.execute("SELECT body FROM docs WHERE kind='job' AND json_extract(body,'$.tool')='bot_reload' "
                              "AND json_extract(body,'$.state')='succeeded' "
                              "AND COALESCE(json_extract(body,'$.finished'),0)>?", (state['jobs_after'],)).fetchall()
            workers = db.execute("SELECT id, json_extract(body,'$.build_sources') FROM docs WHERE kind='worker' "
                                 "AND json_extract(body,'$.build_sources') IS NOT NULL").fetchall()
        for (body,) in jobs:
            job = json.loads(body)
            result = job.get('result') or {}
            if result.get('ok') is not True:
                continue
            at = _stamp(job.get('finished')) or self.now()
            state['jobs_after'] = max(state['jobs_after'], at)
            for title in titles:
                names = touches(title, result.get('reloaded') or [])
                if names:
                    found.append({'kind': 'reload', 'title': title, 'at': at, 'modules': names,
                                  'worker': job.get('worker_id'), 'source': job.get('id')})
        for wid, sources in workers:
            try:
                sources = json.loads(sources) if isinstance(sources, str) else sources
            except ValueError:
                continue
            if not isinstance(sources, dict):
                continue
            for title in titles:
                files = {k: v for k, v in sources.items() if touches(title, [k])}
                if not files:
                    continue
                key = f'{wid}:{title}'
                digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:16]
                old = state['hashes'].get(key)
                state['hashes'][key] = {'digest': digest, 'files': files}
                if old and old['digest'] != digest:
                    changed = sorted(k for k in set(files) | set(old['files']) if files.get(k) != old['files'].get(k))
                    found.append({'kind': 'restart', 'title': title, 'at': self.now(), 'files': changed,
                                  'worker': wid, 'source': digest})
        for change in found:
            self.record(change)
        self.store.put(STATE, 'changes', state)
        return found

    def record(self, change):
        cid = hashlib.sha256(json.dumps([change['kind'], change['title'], change.get('source'), change['at']],
                                        default=str).encode()).hexdigest()[:16]
        if self.store.get(CHANGE, cid) is None:
            self.store.put(CHANGE, cid, {'id': cid, **change, 'effects': {}, 'recorded': self.now()})
        return cid

    def changes(self, title=None, since=0.0):
        with self.store.reading() as db:
            found = [json.loads(b) for (b,) in db.execute("SELECT body FROM docs WHERE kind=?", (CHANGE,))]
        return sorted((c for c in found if (title is None or c.get('title') == title) and c.get('at', 0) >= since),
                      key=lambda c: c['at'])

    def effects(self, labelled, deaths):
        """Each change's effect on every cause of its title: the rate per round over the BASELINE_ROUNDS rounds before
        it and up to BASELINE_ROUNDS after it, judged once EFFECT_ROUNDS have been played."""
        from . import damage_clusters as C
        out = []
        for change in self.changes(since=self.now() - 14 * 86400):
            title = change['title']
            rounds = self.rounds(title)
            before = [r for r in rounds if r['ts'] < change['at']][-BASELINE_ROUNDS:]
            after = [r for r in rounds if r['ts'] >= change['at']][:BASELINE_ROUNDS]
            if change.get('judged') or not before:
                out.append(change)
                continue
            gid = next(g for g, t in C.GAMES.items() if t == title)
            mine = [x for x in labelled if x[0].get('game_id') == gid]
            joined, _u = assign(mine, before + after)
            dj, _u2 = assign([(i, s, True) for i, s, _e in deaths if i.get('game_id') == gid], before + after)
            dead = {rid: [s for _i, s, _n in items] for rid, items in dj.items()}
            sigs = sorted({s for _i, s, _n in mine} | set(C.ORDER) - {'other'})
            b, a = rates(before, joined, dead, sigs), rates(after, joined, dead, sigs)
            effects = {}
            for sig in sigs:
                if not b[sig]['episodes'] and not a[sig]['episodes']:
                    continue
                effects[sig] = {'before': b[sig]['rate'], 'after': a[sig]['rate'], 'rounds_before': len(before),
                                'rounds_after': len(after), 'deaths_before': b[sig]['deaths_per_round'],
                                'deaths_after': a[sig]['deaths_per_round'],
                                'verdict': verdict(b[sig]['rate'], a[sig]['rate'], len(after))}
            for key, _label, _value, _mark, _rule in FAULTS.get(title, ()):
                fb, fa = fault_rate(before, title, key), fault_rate(after, title, key)
                if fb is not None:
                    effects['round:' + key] = {'before': fb, 'after': fa, 'rounds_before': len(before),
                                               'rounds_after': len(after), 'verdict': verdict(fb, fa, len(after))}
            change = dict(change, effects=effects, judged=len(after) >= BASELINE_ROUNDS, evaluated=self.now())
            self.store.put(CHANGE, change['id'], change)
            out.append(change)
        return out

    def follow_up(self, clusters):
        """Batch requests closed with a fix: once a bot change of the title went live after the close and
        EFFECT_ROUNDS rounds were played, the cause's rate must have dropped by TARGET_DROP; else the request reopens
        with the numbers. No bot change live NO_CHANGE_S after the close while the cause goes on: reopened too."""
        now, done = self.now(), []
        for key, c in clusters.items():
            doc = self.store.get('mercs_damage_cluster', c['id']) or {}
            rid = doc.get('request_id')
            req = self.store.get('request', rid) if rid else None
            if not req or req.get('status') != 'done' or (req.get('context') or {}).get('batched_into'):
                continue
            closed = req.get('completed') or 0
            if doc.get('followed_close') == closed:
                continue
            title = c['title']
            rounds = self.rounds(title)
            change = next((ch for ch in self.changes(title, since=closed)), None)
            text, verdict_ = None, None
            if change is None:
                if now - closed >= NO_CHANGE_S and (c.get('episodes') or 0) + (c.get('deaths') or 0) > 0:
                    verdict_ = 'no_change_live'
                    text = (f"Reopened: no {c['game']} bot change went live in the {NO_CHANGE_S // 3600} h since this "
                            f"was closed, and the cause goes on ({c.get('rate_per_round')} per round over "
                            f"{c.get('rounds')} rounds). Merge and hot-reload the fix, or make one.")
            else:
                after = [r for r in rounds if r['ts'] >= change['at']]
                if len(after) < EFFECT_ROUNDS:
                    continue
                effect = (self.store.get(CHANGE, change['id']) or change).get('effects', {}).get(c['signature'])
                if effect is None or effect.get('before') is None:
                    continue
                if effect['after'] is not None and effect['after'] <= effect['before'] * (1 - TARGET_DROP):
                    verdict_ = 'improved'
                    text = (f"Effect measured: {c['label']} went from {effect['before']} to {effect['after']} per round "
                            f"({effect['rounds_before']} rounds before the {change['kind']} at "
                            f"{_clock(change['at'])}, {effect['rounds_after']} after). Kept closed.")
                else:
                    verdict_ = 'not_improved'
                    text = (f"Reopened: after the {change['kind']} at {_clock(change['at'])} ("
                            f"{', '.join(change.get('modules') or change.get('files') or [])[:200]}) {c['label']} is "
                            f"{effect['after']} per round over {effect['rounds_after']} rounds, against "
                            f"{effect['before']} over the {effect['rounds_before']} before: not the "
                            f"{TARGET_DROP:.0%} drop the target asks for. The newest examples are in the body.")
            if text is None:
                continue
            with self.store.lock:
                req = self.store.get('request', rid)
                if req.get('status') != 'done' or (req.get('completed') or 0) != closed:
                    continue
                if verdict_ != 'improved':
                    req.update(status='open', completed=None)
                req.setdefault('messages', []).append({'id': f'follow-up-{int(now)}', 'author': 'agent', 'ts': now,
                                                       'text': text, 'attachments': []})
                self.store.put('request', rid, req)
            doc.update(followed_close=closed, last_verdict=verdict_, last_change=(change or {}).get('id'),
                       last_effect_at=now)
            self.store.put('mercs_damage_cluster', c['id'], doc)
            done.append((c['id'], verdict_))
        return done

    def summary(self, game=None):
        """GET /api/mercs/learning: per title the rounds, the changes and their effects, the tuning in force."""
        from . import damage_clusters as C
        gid = C.resolve_game(game)
        titles = sorted({t for g, t in C.GAMES.items() if not gid or g == gid})
        out = {}
        for title in titles:
            rounds = [r for r in self.rounds(title) if r['ts'] >= self.now() - C.WINDOW_S]
            if not rounds and not self.changes(title):
                continue
            out[title] = {'game': C.TITLE_NAMES.get(title, title), 'rounds_24h': len(rounds),
                          'deaths_per_round': round(sum(r['outcome'] == 'died' for r in rounds) / len(rounds), 3)
                          if rounds else None,
                          'stages': _counts(r['stage'] for r in rounds),
                          'changes': [{k: c.get(k) for k in ('id', 'kind', 'at', 'modules', 'files', 'param', 'stage',
                                                             'old', 'new', 'reason', 'effects', 'judged', 'status')}
                                      for c in self.changes(title)[-20:]]}
            try:
                from . import tuning
                out[title]['tuning'] = tuning.read(self.root / 'mercs/learned', title) if self.root else None
            except (ImportError, OSError, ValueError):
                out[title]['tuning'] = None
        return {'generated_at': self.now(), 'titles': out, 'effect_rounds': EFFECT_ROUNDS,
                'target_drop': TARGET_DROP}


def verdict(before, after, rounds_after):
    if before is None or after is None or rounds_after < EFFECT_ROUNDS:
        return 'pending'
    if before == 0:
        return 'worse' if after > 0 else 'unchanged'
    change = (after - before) / before
    return 'improved' if change <= -TARGET_DROP else 'worse' if change >= TARGET_DROP else 'unchanged'


def _trend(values):
    if len(values) < 3:
        return 'new'
    recent, earlier = values[-2:], values[:-2]
    r, e = sum(recent) / len(recent), sum(earlier) / len(earlier)
    return 'rising' if r > 1.2 * e else 'falling' if r < 0.8 * e else 'flat'


def _counts(values):
    out = {}
    for v in values:
        out[v or 'unknown'] = out.get(v or 'unknown', 0) + 1
    return out


def _stamp(value):
    if type(value) in (int, float):
        return float(value)
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError):
        return None


def _clock(at):
    return time.strftime('%m-%d %H:%M', time.localtime(at)) if type(at) in (int, float) and at > 0 else '?'
