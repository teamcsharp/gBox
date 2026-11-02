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
BOTS = {'010018100CD46000': 'gbox.mercs.titles.re5_switch', '01002A000CD48000': 'gbox.mercs.titles.re6_switch', 'BLUS30491': 'gbox.mercs.titles.re5_ps3'}
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


class _MockNavMesh:
    """Minimal nav mesh for replaying mine-retreat incidents.

    The real nav mesh comes from RAM and cannot be serialised into a fixture.
    This mock provides just enough surface for Bot._mine_retreat to run:
    the player is on floor, floor segments are clear, but no safe 600cm
    retreat route exists (retreat returns None).  That lets the blast-radius
    guard (the fix under test) trigger instead of the earlier 'no escape mesh'
    or 'returning to observed floor' branches.
    """

    learning_sig = 'mock'
    links = {}  # no mesh links; nav_learning.observe() will not find crossings

    def find(self, pos, floor_only=True, height_slack=60.):
        return 0  # player is on floor

    def member(self, pos):
        return 0  # a single mock node

    def floor_segment(self, a, b, blocked_links=None):
        return True

    def hazard_segment_clear(self, a, b, margins, departing=True):
        return True

    def retreat(self, start, hazard, min_distance, blocked_links=None, link_penalties=None):
        return None  # no safe route at this distance

    def route_avoiding_hazards(self, start, goal, hazards, avoid=None, blocked_links=None,
                               link_penalties=None):
        return None

    def route(self, start, goal, avoid=None, blocked_links=None, link_penalties=None):
        return None

    def route_length(self, start, goal, avoid=None, blocked_links=None, link_penalties=None):
        return None


def replay(fx, ticks=10, dt=0.05, stats=None, start=1000.0):
    """The bot's decisions on the recorded snapshot, `ticks` ticks `dt` apart on a fake clock. Each tick gets a fresh
    copy of the snapshot (the drivers may annotate it). -> {'ticks': [{'t', 'act', 'doing', 'why'}], 'bot', 'stats'}.

    The snapshot's ground_mines (recorded by the Observer) are fed to the bot by
    patching the title's ground_mines reader so the decision logic sees the same
    mines that were on the floor at the hit — the replay bot has no RAM reader."""
    if fx.get('schema') != SCHEMA:
        raise ValueError('not an incident replay fixture')
    clock = [float(start)]
    b = bot(fx['title'], stats=dict(stats or {}), clock=lambda: clock[0])
    # Feed the recorded ground mines to the bot's mine reader.
    recorded_mines = copy.deepcopy(fx['snapshot'].get('ground_mines') or {})
    if recorded_mines:
        from gbox.mercs.titles import re5_mines as mines_mod
        original_gm = mines_mod.ground_mines
        mines_mod.ground_mines = lambda memory, _recorded=recorded_mines: dict(_recorded)
    # Seed the mine-retreat escape state so _mine_retreat runs on the recorded
    # snapshot rather than falling through to combat.  The fixture's decision
    # phase tells us the bot was actively leaving its own bomb; replay that
    # state by initializing the controller's escape record from the recorded
    # ground mine.  Without this the controller never enters the placement
    # cycle (action=5 makes it busy) and the blast-radius hold is unreachable.
    decision_phase = (fx.get('decision') or {}).get('phase')
    if decision_phase in ('leave_proximity_bomb', 'clear_nearby') and recorded_mines:
        # Pre-create the mine controller on the bot so we can seed its escape
        # state before the first tick.  _tick_main would create it lazily, but
        # we need it now to set escape before the tick flow reaches the
        # mandatory-escape check.
        from gbox.mercs.titles import re5_mines as mines_mod
        if getattr(b, 'mines', None) is None:
            b.mines = mines_mod.Controller(None, b.stats, getattr(b, '_switch_weapon', lambda *a: None))
        mines = b.mines
        ptr, row = next(iter(recorded_mines.items()))
        mines.escape = {
            'pos': tuple(row.get('pos', (0, 0, 0))),
            'actor': ptr,
            'at': 0.0,
            'hazards': {ptr: tuple(row.get('pos', (0, 0, 0)))},
            'route': None,
            'geometry': None,
            'detonation_observed': bool(row.get('detonating')),
            'armed': not row.get('detonating', False),
        }
        b.nav_dynamic_mines = dict(recorded_mines)
        # Mark the round active so observe_round does not fire the round-start
        # reset, which would clear the seeded mines.escape before the first
        # tick reaches the mandatory-escape check.
        b.round_active = True
    # The fixture records the player state at the moment of damage, when
    # action=5 (hit callback) is set.  That state makes the mandatory-escape
    # check true and the bot skip _mine_retreat entirely (the hit callback
    # retains control until it finishes).  The decision the incident is about
    # was made in the tick BEFORE the hit, when the player was walking (action
    # 0 or 1).  Override the action so the replay exercises the retreat logic
    # rather than the hit-callback hold.
    if decision_phase in ('leave_proximity_bomb', 'clear_nearby'):
        player = fx['snapshot'].get('player')
        if player and player.get('action') in (4, 5):
            player['action'] = 0
    # _mine_retreat requires a nav mesh (snap['nav']).  The replay snapshot has
    # none (the Observer cannot serialise the RAM nav mesh), so inject a minimal
    # mock that lets the retreat logic run: the player is on floor, no safe
    # 600cm route exists (retreat returns None), and the blast-radius guard at
    # the heart of the fix is reached.
    if decision_phase in ('leave_proximity_bomb', 'clear_nearby'):
        fx['snapshot']['nav'] = _MockNavMesh()
    # _tick_main overwrites snap['ground_mines'] with the bot's RAM read
    # (ground_mines(self.m)), which returns an empty result when memory is
    # None.  Restore the fixture's ground_mines each tick so the controller
    # sees the same mines that were on the floor at the hit.
    out = []
    try:
        for _ in range(max(1, int(ticks))):
            snap = copy.deepcopy(fx['snapshot'])
            if recorded_mines:
                snap['ground_mines'] = copy.deepcopy(recorded_mines)
            act = b.tick(snap)
            out.append({'t': round(clock[0] - start, 3), 'act': act, 'doing': getattr(b, 'doing', None),
                        'why': getattr(b, 'why', None)})
            clock[0] += dt
    finally:
        if recorded_mines:
            mines_mod.ground_mines = original_gm
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
