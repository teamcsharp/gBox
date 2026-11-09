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

A round confirms a trial when it PLAYED THE TRIAL'S VALUE (its tuning_params, tuning.in_force), not when it carries
the file's version: the per-stage avoid trials rewrite the file - a new version - every few minutes, so a numeric
trial's version was superseded before any round could carry it ("0 of 8 rounds confirmed it in time", every pooled
trial of 2026-11-09 expired so).

THE OPERATOR'S GOAL (OBJECTIVES; RE5 Switch No Mercy, operator 2026-11-09: "400 kills as fast as possible with a combo
being maintained the entire time ... faster and faster ... until it has SS rank on every level"). For these titles a
numeric trial is judged on gbox.mercs.ss_ledger's game rounds (the Notebook's fragments stitched), not on its rule's
causes: each round's cost (ss_ledger.round_cost: a win costs its seconds to 400, a round not won its projected time
plus NOT_WON_S, a death DEATH_S more; combo breaks add, the max combo takes off) over its own stage's mean cost before
the trial (the baseline, per stage, OBJ_BASE_ROUNDS each), the ratios pooled over every stage - judged per stage, but
confirmed on the rounds of a day. Kept unless the mean ratio is WORSE above 1; reverted (and blocked BLOCK_S) when it is,
or when deaths per round rose more than OBJ_DEATH_TOL over the baseline's (the hard penalty). Confirmed by
OBJ_EVAL_ROUNDS judged rounds that played the value; expired when OBJ_EXPIRE_ROUNDS judged rounds of the title went by
without them (the hooks not live) or after OBJ_EXPIRE_S. The rules' cause metrics still pick WHICH constant to try.
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
        ('behind', 're6_switch.QT_BEHIND_R', ('grabbed_from_behind',), 1.0),
        ('tablet', 're6_switch.TABLET_HP', ('low_hp_heal_unused',), 0.1),
        ('bomb', 're6_switch.BOMB_MARGIN_CM', ('own_bomb',), 0.3),
    ),
    'BLUS30491': (
        ('heal', 're5_ps3.HEAL_CRITICAL', ('low_hp_heal_unused', 'low_hp_no_heal'), 0.15),
    ),
}
AVOID = 'avoid'
# titles whose numeric trials are judged on the operator's goal (the module text): title -> its ledger module
OBJECTIVES = {'010018100CD46000': 'ss_ledger'}
OBJ_EVAL_ROUNDS = 6           # judged game rounds that played the trial's value
OBJ_EXPIRE_ROUNDS = 30        # ... judged rounds of the title since the trial began without them: expired
OBJ_EXPIRE_S = 72 * 3600
OBJ_BASE_ROUNDS = 10          # each stage's last this many judged rounds before a trial are its baseline
OBJ_BASE_MIN = 5              # fewer judged rounds than this before it: no baseline, the rule's own metric judges
OBJ_DEATH_TOL = 0.25          # deaths per round up more than this over the baseline's: reverted (the hard penalty)


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


def ran_with(params, name, value, default) -> bool:
    """Whether a round with these tuning_params played `name` at `value` (tuning.in_force; None: no hooks, no)."""
    got = T.in_force(params, name, default)
    return got is not None and value is not None and abs(float(got) - float(value)) < 1e-6


class Tuner:
    def __init__(self, store, data_dir, learning, *, now=time.time, defaults=shipped):
        self.store, self.learning, self.now, self.defaults = store, learning, now, defaults
        self.base = Path(data_dir) / 'mercs' / 'learned'
        self.data = Path(data_dir)
        self._tails = {}                          # title -> ss_ledger.NotebookTail (OBJECTIVES)

    def state(self):
        return self.store.get(STATE, 'state') or {'titles': {}}

    def ledger(self, title) -> list:
        """The title's game rounds (gbox.mercs.ss_ledger), oldest first, from the newest Notebook rows."""
        from . import ss_ledger
        tail = self._tails.get(title)
        if tail is None:
            tail = self._tails[title] = ss_ledger.NotebookTail(self.data / 'mercs/curriculum' / title / 'rounds.sqlite')
        return ss_ledger.ledger(tail.rows())

    def migrate(self, title, ts) -> list:
        """A title whose stage key changed (tuning.STAGE_V): its per-stage overrides, avoid spots and per-stage trials
        were made under other stages' names - dropped once, the pooled '*' values kept. -> the log lines."""
        want = T.STAGE_V.get(title, 1)
        if (ts.get('stage_v') or 1) >= want:
            return []
        dropped = sorted(s for s in ts['overrides'] if s != '*') + sorted(ts['avoid'])
        ts['overrides'] = {s: v for s, v in ts['overrides'].items() if s == '*'}
        ts['avoid'] = {}
        for stage, st in ts['stages'].items():
            if stage != '*':
                st['trial'] = None
        ts['stage_v'] = want
        self.write(title, ts)
        return [self.log(title, '*', 'migrated', {'param': 'stage_key', 'old': dropped, 'new': want},
                         f'stage key version {want}: per-stage values and avoid spots of {len(dropped)} stage entries '
                         'were keyed by the next round\'s target - dropped, the pooled values kept')]

    def tune(self, labelled, deaths):
        """One look at every title's stages. -> the log lines written this pass."""
        from . import damage_clusters as C
        from .learning import assign
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
            if 'stage_v' not in ts and not ts['overrides'] and not ts['avoid'] and not ts['stages']:
                ts['stage_v'] = T.STAGE_V.get(title, 1)              # a fresh state is keyed by the right stage
            lines += self.migrate(title, ts)
            # The stage-agnostic survival constants are trialed once, pooled under '*', over EVERY round of the title:
            # tuning.apply applies '*' params to every stage and each round carries the file's version, so the whole
            # day's rounds (~36) count toward the EVAL_ROUNDS confirmation instead of a single stage's handful (~4.5),
            # which is what left most trials to expire unconfirmed. Dead-end avoid spots stay per-stage (positional).
            lines += self.numeric_trial(title, rounds, ts, rules, joined, dead)
            groups = {}
            for r in rounds:
                groups.setdefault(r['stage'] or '*', []).append(r)
            spots = self.spots(title)
            for stage, group in sorted(groups.items()):
                if stage == '*':
                    continue                             # the '*' slot is the pooled numeric trial above
                lines += self.avoid_trial(title, stage, group, ts, spots, joined, dead)
        self.store.put(STATE, 'state', state)
        return lines

    def numeric_trial(self, title, rounds, ts, rules, joined, dead):
        """The pooled survival-constant trial under '*': judge the one in flight, or start one over all rounds."""
        st = ts['stages'].setdefault('*', {'trial': None, 'blocked': {}})
        trial = st['trial']
        if trial and trial['param'] != AVOID:
            return self.judge(title, '*', ts, st, rounds, joined, dead)
        if trial:                                        # an avoid trial never lives under '*'; leave it to clear
            return []
        recent = rounds[-TRIGGER_ROUNDS:]
        if len(recent) < TRIGGER_ROUNDS:
            return []
        pick = None
        for rule, name, sigs, floor in rules:
            if (st['blocked'].get(name) or 0) > self.now():
                continue
            m = metric(recent, joined, dead, sigs)
            if m is None or m < floor:
                continue
            current = ts['overrides'].get('*', {}).get(name)
            base = current if current is not None else self.defaults(name)
            new = T.clamp(title, name, base + T.PARAMS[title][name][2])
            if new is None or new == base:
                continue                                 # at its bound
            if pick is None or m / floor > pick[0]:
                pick = (m / floor, rule, name, sigs, current, new, m)
        if pick is None:
            return []
        _ratio, rule, name, sigs, old, new, base = pick
        objective = self.objective_baseline(title)
        self.set(ts, '*', name, new)
        version = self.write(title, ts)
        st['trial'] = {'rule': rule, 'param': name, 'causes': list(sigs), 'old': old, 'new': new,
                       'baseline': base, 'at': self.now(), 'version': version, 'rounds_before': len(recent),
                       'default': self.defaults(name), 'objective': objective}
        why = f"{rule}: metric {base} per round over the last {len(recent)} rounds"
        if objective:
            why += (f"; judged on the goal against {objective['rounds']} rounds' per-stage baselines "
                    f"(deaths {objective['deaths_rate']} per round)")
        return [self.log(title, '*', 'trial', st['trial'], why)]

    def objective_baseline(self, title) -> dict | None:
        """OBJECTIVES: the per-stage baselines a trial starting now is judged against, None for another title or too
        few judged rounds (the rule's own metric judges it then)."""
        if title not in OBJECTIVES:
            return None
        from . import ss_ledger
        judged = [r for r in self.ledger(title) if ss_ledger.round_cost(r) is not None]
        if len(judged) < OBJ_BASE_MIN:
            return None
        recent = judged[-max(OBJ_BASE_ROUNDS * len(ss_ledger.STAGE_NAMES), 30):]
        base = ss_ledger.stage_baselines(recent, OBJ_BASE_ROUNDS)
        return {'baselines': {k: round(v, 1) for k, v in base.items()}, 'rounds': len(recent),
                'deaths_rate': round(sum(r['deaths'] for r in recent[-30:]) / len(recent[-30:]), 3),
                'wins': sum(r['outcome'] == 'won' for r in recent)}

    def avoid_trial(self, title, stage, group, ts, spots, joined, dead):
        """Per-stage dead-end avoid spots; also drains any legacy per-stage numeric trial left in flight."""
        from .learning import fault_rate
        st = ts['stages'].setdefault(stage, {'trial': None, 'blocked': {}})
        if st['trial']:
            return self.judge(title, stage, ts, st, group, joined, dead)
        recent = group[-TRIGGER_ROUNDS:]
        if len(recent) < TRIGGER_ROUNDS:
            return []
        fresh = [s for s in spots.get(stage, []) if s not in (ts['avoid'].get(stage) or [])]
        if not fresh or (st['blocked'].get(AVOID) or 0) > self.now():
            return []
        base = fault_rate(recent, title, 'reloc_dead_end') or 0.0
        old = list(ts['avoid'].get(stage) or [])
        new = (old + fresh)[-T.AVOID_MAX:]
        self.set(ts, stage, AVOID, new)
        version = self.write(title, ts)
        st['trial'] = {'rule': 'dead_end', 'param': AVOID, 'causes': ['round:reloc_dead_end'], 'old': old,
                       'new': new, 'baseline': base, 'at': self.now(), 'version': version,
                       'rounds_before': len(recent)}
        return [self.log(title, stage, 'trial', st['trial'],
                         f"dead_end: {len(fresh)} new avoid spots over the last {len(recent)} rounds")]

    def judge(self, title, stage, ts, st, group, joined, dead):
        from .learning import fault_rate
        trial = st['trial']
        if trial['param'] != AVOID and trial.get('objective'):
            return self.judge_objective(title, stage, ts, st)
        if trial['param'] == AVOID:
            confirm = [r for r in group if r['ts'] >= trial['at'] and r.get('tuning_version') == trial['version']]
        else:                                                # the value in force, not the file's version
            default = trial.get('default', self.defaults(trial['param']))
            confirm = [r for r in group if r['ts'] >= trial['at'] and r.get('tuning_version')
                       and ran_with((r.get('observed') or {}).get('tuning_params'), trial['param'], trial['new'],
                                    default)]
        if len(confirm) < EVAL_ROUNDS:
            if self.now() - trial['at'] >= EXPIRE_S:
                self.set(ts, stage, trial['param'], trial['old'])
                self.write(title, ts)
                st['trial'] = None
                return [self.log(title, stage, 'expired', trial,
                                 f'{len(confirm)} of {EVAL_ROUNDS} rounds confirmed it in time: put back')]
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

    def judge_objective(self, title, stage, ts, st):
        """OBJECTIVES: the trial's game rounds against their stages' baselines (the module text)."""
        from . import ss_ledger
        trial, obj = st['trial'], st['trial']['objective']
        default = trial.get('default', self.defaults(trial['param']))
        played = [r for r in self.ledger(title) if r['ended_at'] >= trial['at'] and ss_ledger.round_cost(r) is not None]
        confirm = [r for r in played if r.get('tuning')
                   and all(ran_with(params, trial['param'], trial['new'], default) for _v, params in r['tuning'])]
        if len(confirm) < OBJ_EVAL_ROUNDS:
            if len(played) - len(confirm) >= OBJ_EXPIRE_ROUNDS or self.now() - trial['at'] >= OBJ_EXPIRE_S:
                self.set(ts, stage, trial['param'], trial['old'])
                self.write(title, ts)
                st['trial'] = None
                return [self.log(title, stage, 'expired', trial,
                                 f"{len(confirm)} of {OBJ_EVAL_ROUNDS} game rounds played {trial['new']} "
                                 f"({len(played)} judged since it began): put back")]
            return []
        res = ss_ledger.objective(confirm[:OBJ_EVAL_ROUNDS], obj['baselines'])
        if res is None:
            return []
        worse_goal = res['ratio'] > 1 + WORSE
        worse_deaths = res['deaths_rate'] > obj['deaths_rate'] + OBJ_DEATH_TOL
        status = 'reverted' if worse_goal or worse_deaths else 'kept'
        if status == 'reverted':
            self.set(ts, stage, trial['param'], trial['old'])
            st['blocked'][trial['param']] = self.now() + BLOCK_S
            self.write(title, ts)
        done = dict(trial, after=res['ratio'], rounds_after=res['rounds'], status=status,
                    objective_after=res)
        st['trial'] = None
        why = (f"the goal: cost {res['ratio']:.3f} x the per-stage baseline over {res['rounds']} game rounds "
               f"({res['wins']} won, deaths {obj['deaths_rate']} -> {res['deaths_rate']} per round)")
        if worse_deaths:
            why += f"; deaths up more than {OBJ_DEATH_TOL} per round: the hard penalty"
        elif worse_goal:
            why += f"; more than {WORSE:.0%} slower to the goal"
        return [self.log(title, stage, status, done, why)]

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
        data = {'schema': T.SCHEMA, 'title': title, 'version': version, 'written': self.now(),
                'avoid_v': ts.get('stage_v') or 1, **body}
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
            if (n.get('stage_v') or 1) < T.STAGE_V.get(title, 1):
                continue                                 # noted under another stage's name (tuning.STAGE_V)
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
