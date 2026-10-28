"""Replay a recorded damage incident through the title's bot: the replay test a damage batch's PR adds.

A damage batch (gbox/mercs/damage_clusters.py) names its representative hits. GET
/api/mercs/damage-clusters/{id}/replay turns each one's durable receipt (gbox/player_damage.py) into a fixture:

  * snapshot: the driver snapshot at the hit, as the Observer froze it before health maintenance (player, enemies,
    inventory, laser, bomb and mines; values that could not be stored as JSON are left out);
  * held: the buttons held at the hit; counters: the driver's numeric stats then; preceding_history: his path, health,
    buttons and plan over the seconds before;
  * the HP change and the cluster it belongs to.

replay(fixture) feeds that snapshot to a fresh Bot of the title (re5_switch / re6_switch) for a few ticks on a fake
clock and returns each tick's decision, so a test can assert what the bot does now in the exact situation that hurt it:

    fx = json.loads(Path('tests/fixtures/mercs_incidents/re5_crowd_gun_down.json').read_text())
    result = incident_replay.replay(fx, ticks=10)
    assert 'zr' in incident_replay.keys(result)          # the fix: he keeps firing into the circle

One frame is recorded per hit (the enemies' motion between ticks is not), so a replay checks a decision, not a fight.
"""
from __future__ import annotations

import copy
import importlib
import math

SCHEMA = 'gbox.mercs.incident-replay/1'
BOTS = {'010018100CD46000': 'gbox.mercs.titles.re5_switch', '01002A000CD48000': 'gbox.mercs.titles.re6_switch',
        'BLUS30491': 'gbox.mercs.titles.re5_ps3'}
HISTORY = 15


def _plain(value, depth=0):
    """JSON values only; the Observer's {"unavailable": ...} placeholders are dropped."""
    if depth > 10:
        return None
    if isinstance(value, dict):
        if set(value) == {'unavailable'}:
            return None
        out = {}
        for k, v in value.items():
            v = _plain(v, depth + 1)
            if v is not None:
                out[str(k)] = v
        return out
    if isinstance(value, (list, tuple)):
        return [x for x in (_plain(v, depth + 1) for v in value) if x is not None]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value if value is None or isinstance(value, (str, bool, int, float)) else None


def fixture(event, cluster=None) -> dict:
    """A replay fixture from a receipt event (gbox.player_damage, as stored under the ledger's receipt)."""
    if event.get('packed_context'):
        from .incident import unpack_context
        event = unpack_context(event)
    logic = event.get('logic') if isinstance(event.get('logic'), dict) else {}
    out = {'schema': SCHEMA, 'title': event.get('title'), 'event_id': event.get('event_id'),
           'observed_at': event.get('observed_at'), 'hp_before': event.get('hp_before'),
           'hp_after': event.get('hp_after'), 'hp_max': event.get('hp_max'), 'loss': event.get('loss'),
           'held': sorted(k for k in event.get('held') or () if isinstance(k, str)),
           'snapshot': _plain(event.get('snapshot') or {}) or {},
           'counters': {k: v for k, v in logic.items() if type(v) in (int, float) and math.isfinite(v)},
           'decision': {k: logic[k] for k in ('act', 'phase', 'aim', 'heal_status', 'mine_status', 'k_plan')
                        if k in logic},
           'preceding_history': _plain(list(event.get('preceding_history') or ())[-HISTORY:]) or []}
    if cluster:
        out['cluster'] = {k: cluster.get(k) for k in ('id', 'game_id', 'signature', 'label')}
    return out


def bot(title, stats=None, clock=None):
    """A fresh Bot of the title (no RAM writer, no learned files): the decision logic alone."""
    if title not in BOTS:
        raise ValueError(f'no replayable bot for {title!r} (replayable: {", ".join(sorted(BOTS))})')
    module = importlib.import_module(BOTS[title])
    return module.Bot(stats=stats if stats is not None else {}, clock=clock or (lambda: 0.0))


def replay(fx, ticks=10, dt=0.05, stats=None, start=1000.0):
    """The bot's decisions on the recorded snapshot, `ticks` ticks `dt` apart on a fake clock. Each tick gets a fresh
    copy of the snapshot (the drivers may annotate it). -> {'ticks': [{'t', 'act', 'doing', 'why'}], 'bot', 'stats'}."""
    if fx.get('schema') != SCHEMA:
        raise ValueError('not an incident replay fixture')
    clock = [float(start)]
    b = bot(fx['title'], stats=dict(stats or {}), clock=lambda: clock[0])
    out = []
    for _ in range(max(1, int(ticks))):
        act = b.tick(copy.deepcopy(fx['snapshot']))
        out.append({'t': round(clock[0] - start, 3), 'act': act, 'doing': getattr(b, 'doing', None),
                    'why': getattr(b, 'why', None)})
        clock[0] += dt
    return {'ticks': out, 'bot': b, 'stats': b.stats}


def keys(result) -> set:
    """Every button the replay held or tapped."""
    found = set()
    for tick in result['ticks']:
        act = tick['act'] or {}
        for name in ('hold', 'tap'):
            v = act.get(name)
            if isinstance(v, str):
                found.add(v)
            elif isinstance(v, (list, tuple)):
                found.update(x for x in v if isinstance(x, str))
    return found
