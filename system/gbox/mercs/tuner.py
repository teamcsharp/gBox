"""Tier (a) of the learning loop: automatic tuning with no code change.

After each pass of the damage clusters (gbox/mercs/damage_clusters.py -> gbox/mercs/learning.py) the tuner looks at
each title's stages. Per stage there is at most one trial at a time:

  * start: over the stage's last TRIGGER_ROUNDS rounds, a rule's metric - the episodes per round of its causes plus
    DEATH_W x their deaths per round - is at or above its floor, and its constant can still move: the constant moves
    one bounded step (gbox/mercs/tuning.py PARAMS) in the file the bots read at their next round start;
  * judge: the stage's first EVAL_ROUNDS rounds whose Notebook row carries the new tuning_version (the bot stamped it:
    proof it played with the value). The metric WORSE or more above the baseline: reverted, and that constant left
    alone BLOCK_S; else kept (the next trial may step it again);
  * expire: no round confirmed the version within EXPIRE_S (the hooks not deployed, the stage not played): reverted.

Dead-end avoid spots are trials of their own: where the bot noted EVIDENCE_MIN or more relocation stops (tuning
dead_ends.jsonl) in one GRID_CM cell of a stage, a spot; judged on the round fault "relocation into a dead end".

Every step, keep, revert and expiry is a line in <data>/mercs/learned/<title>/tuning-log.jsonl and a change document
of gbox.mercs.learning (kind "tuning"), so GET /api/mercs/learning shows what changed and its effect.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import time

from . import tuning as T

STATE = 'mercs_tuner_state'
TRIGGER_ROUNDS, EVAL_ROUNDS = 10, 8
WORSE = 0.1                       # a trial whose metric rose this much over its baseline is reverted
DEATH_W = 3.0                     # a death weighs this many episodes in a rule's metric
BLOCK_S = 24 * 3600               # a reverted constant is left alone this long on that stage
EXPIRE_S = 24 * 3600              # a trial no round confirmed this long is reverted
GRID_CM, SPOT_R, EVIDENCE_MIN, EVIDENCE_S = 300.0, 250.0, 2, 7 * 86400
LOG = 'tuning-log.jsonl'
# title -> (rule, constant, the causes it answers, the metric floor that starts a trial)
RULES = {
    '010018100CD46000': (
        ('crowd', 're5_switch.RELOC_CROWD_N', ('crowd_4_in_2m', 'crowd_gun_down'), 1.5),
        ('heal', 're5_switch.HEAL_CRITICAL', ('low_hp_heal_unused', 'low_hp_no_heal'), 0.15),
        ('behind', 're5_switch.BEHIND_R', ('grabbed_from_behind', 'aimed_away_or_behind'), 0.6),
        ('mine', 're5_switch_mines.BLAST_CM', ('own_bomb',), 0.15),
    ),
    '01002A000CD48000': (
        ('crowd', 're6_switch.CROWD_R', ('crowd_4_in_2m', 'crowd_gun_down'), 1.0),
        ('keep', 're6_switch.KEEP_R', ('grabbed_front', 'faced_melee'), 1.5),
        ('tablet', 're6_switch.TABLET_HP', ('low_hp_heal_unused',), 0.1),
        ('bomb', 're6_switch.BOMB_MARGIN_CM', ('own_bomb',), 0.3),
    ),
}
AVOID = 'avoid'


def shipped(name):
    """The value a tunable constant ships with (the module as this process loaded it)."""
    mod, attr = name.rsplit('.', 1)
    module = importlib.import_module(T.PACKAGE + mod)
    return module.__dict__.get('_TUNING_SHIPPED', {}).get(attr, getattr(module, attr))


def metric(rounds, joined, dead, sigs):
    if not rounds:
        return None
    eps = sum(1 for r in rounds for _i, s, new in joined.get(r['id'], ()) if new and s in sigs)
    deaths = sum(1 for r in rounds for s in dead.get(r['id'], ()) if s in sigs)
    return round((eps + DEATH_W * deaths) / len(rounds), 3)


class Tuner:
    def __init__(self, store, data_dir, learning, *, now=time.time, defaults=shipped):
        self.store, self.learning, self.now, self.defaults = store, learning, now, defaults
        self.base = Path(data_dir) / 'mercs' / 'learned'

    def state(self):
        return self.store.get(STATE, 'state') or {'titles': {}}

    def tune(self, labelled, deaths):
        """One look at every title's stages. -> the log lines written this pass."""
        from . import damage_clusters as C
        from .learning import assign, fault_rate
        state, lines = self.state(), []
        for title, rules in RULES.items():
            gid = next((g for g, t in C.GAMES.items() if t == title), None)
            rounds = self.learning.rounds(title)
            if not rounds or gid is None:
                continue
            mine = [x for x in labelled if x[0].get('game_id') == gid]
            joined, _u = assign(mine, rounds)
            dj, _u2 = assign([(i, s, True) for i, s, _e in deaths if i.get('game_id') == gid], rounds)
            dead = {rid: [s for _i, s, _n in items] for rid, items in dj.items()}
            ts = state['titles'].setdefault(title, {'overrides': {}, 'avoid': {}, 'stages': {}})
            groups = {}
            for r in rounds:
                groups.setdefault(r['stage'] or '*', []).append(r)
            spots = self.spots(title)
            for stage, group in sorted(groups.items()):
                st = ts['stages'].setdefault(stage, {'trial': None, 'blocked': {}})
                trial = st['trial']
                if trial:
                    lines += self.judge(title, stage, ts, st, group, joined, dead)
                    continue
                recent = group[-TRIGGER_ROUNDS:]
                if len(recent) < TRIGGER_ROUNDS:
                    continue
                pick = None
                for rule, name, sigs, floor in rules:
                    if (st['blocked'].get(name) or 0) > self.now():
                        continue
                    m = metric(recent, joined, dead, sigs)
                    if m is None or m < floor:
                        continue
                    current = ts['overrides'].get(stage, {}).get(name)
                    base = current if current is not None else (ts['overrides'].get('*', {}).get(name)
                                                                if stage != '*' else None)
                    base = base if base is not None else self.defaults(name)
                    new = T.clamp(title, name, base + T.PARAMS[title][name][2])
                    if new is None or new == base:
                        continue                         # at its bound
                    if pick is None or m / floor > pick[0]:
                        pick = (m / floor, rule, name, sigs, current, new, m)
                fresh = [s for s in spots.get(stage, []) if s not in (ts['avoid'].get(stage) or [])]
                if pick is None and fresh and (st['blocked'].get(AVOID) or 0) <= self.now():
                    base = fault_rate(recent, title, 'reloc_dead_end') or 0.0
                    pick = (0, 'dead_end', AVOID, ('round:reloc_dead_end',), list(ts['avoid'].get(stage) or []),
                            (list(ts['avoid'].get(stage) or []) + fresh)[-T.AVOID_MAX:], base)
                if pick is None:
                    continue
                _ratio, rule, name, sigs, old, new, base = pick
                self.set(ts, stage, name, new)
                version = self.write(title, ts)
                st['trial'] = {'rule': rule, 'param': name, 'causes': list(sigs), 'old': old, 'new': new,
                               'baseline': base, 'at': self.now(), 'version': version,
                               'rounds_before': len(recent)}
                lines.append(self.log(title, stage, 'trial', st['trial'],
                                      f"{rule}: metric {base} per round over the last {len(recent)} rounds"))
        self.store.put(STATE, 'state', state)
        return lines

    def judge(self, title, stage, ts, st, group, joined, dead):
        from .learning import fault_rate
        trial = st['trial']
        confirm = [r for r in group if r['ts'] >= trial['at'] and r.get('tuning_version') == trial['version']]
        if len(confirm) < EVAL_ROUNDS:
            if not confirm and self.now() - trial['at'] >= EXPIRE_S:
                self.set(ts, stage, trial['param'], trial['old'])
                self.write(title, ts)
                st['trial'] = None
                return [self.log(title, stage, 'expired', trial, 'no round played with it: put back')]
            return []
        rounds = confirm[:EVAL_ROUNDS]
        if trial['param'] == AVOID:
            after = fault_rate(rounds, title, 'reloc_dead_end') or 0.0
        else:
            after = metric(rounds, joined, dead, set(trial['causes']))
        worse = after > trial['baseline'] * (1 + WORSE)
        status = 'reverted' if worse else 'kept'
        if worse:
            self.set(ts, stage, trial['param'], trial['old'])
            st['blocked'][trial['param']] = self.now() + BLOCK_S
            self.write(title, ts)
        done = dict(trial, after=after, rounds_after=len(rounds), status=status)
        st['trial'] = None
        line = self.log(title, stage, status, done,
                        f"metric {trial['baseline']} -> {after} per round over {len(rounds)} rounds")
        return [line]

    @staticmethod
    def set(ts, stage, name, value):
        if name == AVOID:
            if value:
                ts['avoid'][stage] = value
            else:
                ts['avoid'].pop(stage, None)
            return
        stage_params = ts['overrides'].setdefault(stage, {})
        if value is None:
            stage_params.pop(name, None)
        else:
            stage_params[name] = value
        if not stage_params:
            ts['overrides'].pop(stage, None)

    def write(self, title, ts):
        """The file the bots read (atomic). -> its version."""
        body = {'params': ts['overrides'], 'avoid': ts['avoid']}
        version = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]
        data = {'schema': T.SCHEMA, 'title': title, 'version': version, 'written': self.now(), **body}
        path = self.base / title / T.FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding='utf-8')
        os.replace(tmp, path)
        return version

    def log(self, title, stage, status, trial, reason):
        line = {'at': self.now(), 'title': title, 'stage': stage, 'status': status, 'param': trial['param'],
                'old': trial.get('old'), 'new': trial.get('new'), 'baseline': trial.get('baseline'),
                'after': trial.get('after'), 'version': trial.get('version'), 'reason': reason}
        path = self.base / title / LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(line, default=str) + '\n')
        if self.learning is not None:
            self.learning.record({'kind': 'tuning', 'title': title, 'at': self.now(), 'stage': stage,
                                  'param': trial['param'], 'old': trial.get('old'), 'new': trial.get('new'),
                                  'causes': trial.get('causes'),
                                  'status': status, 'reason': reason, 'source': f"{trial.get('version')}:{status}"})
        return line

    def spots(self, title):
        """{stage: [[x, z, r]]}: GRID_CM cells where the bot noted EVIDENCE_MIN or more relocation stops lately."""
        path = self.base / title / T.DEAD_ENDS
        cells = {}
        try:
            lines = path.read_text(encoding='utf-8').splitlines()[-2000:]
        except OSError:
            return {}
        for raw in lines:
            try:
                n = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(n, dict) or self.now() - (n.get('at') or 0) > EVIDENCE_S:
                continue
            for xk, zk in (('x', 'z'), ('gx', 'gz')):          # where he stopped, and the goal he ran for
                if type(n.get(xk)) not in (int, float) or type(n.get(zk)) not in (int, float):
                    continue
                key = (n.get('stage') or '*', int(n[xk] // GRID_CM), int(n[zk] // GRID_CM))
                cells.setdefault(key, []).append((n[xk], n[zk]))
        out = {}
        for (stage, _cx, _cz), pts in sorted(cells.items(), key=lambda kv: -len(kv[1])):
            if len(pts) >= EVIDENCE_MIN:
                x, z = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
                out.setdefault(stage, []).append([round(x), round(z), SPOT_R])
        return {s: v[:T.AVOID_MAX] for s, v in out.items()}

    def summary(self, title):
        ts = self.state()['titles'].get(title) or {}
        path = self.base / title / LOG
        try:
            log = [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()[-20:]]
        except (OSError, ValueError):
            log = []
        return {'overrides': ts.get('overrides') or {}, 'avoid': ts.get('avoid') or {},
                'trials': {s: v.get('trial') for s, v in (ts.get('stages') or {}).items() if v.get('trial')},
                'blocked': {s: v.get('blocked') for s, v in (ts.get('stages') or {}).items() if v.get('blocked')},
                'log': log}
