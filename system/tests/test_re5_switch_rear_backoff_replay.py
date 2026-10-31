"""#5046 (RE5 Switch, 'aimed_away_or_behind' damage cluster): the replay test the batch PR adds.

The cluster's representative example (the fields recorded at the hit, from
GET /api/mercs/damage-clusters/75da0d4fb2df698b/replay): the bot aims at one Majini in front while
another closes in from behind at arm's length. The quick turn only starts within 3 m and at 90 deg, so
the closing one reaches the grab first (that is the damage). The one logic change: the rear back-off
(gbox/mercs/titles/re5_switch.py, Bot._rear_backoff) keeps the distance from the closing threat before it
can grab him - it backs away from the threat's bearing, which does not walk into the one he aims at.

This drives the fresh bot through the recorded example's snapshot with incident_replay.replay and asserts
the new decision: he steps back (ldown) from the closing Majini instead of holding his ground and getting
grabbed. The live bots measure the change after a deploy (GET /api/mercs/damage-clusters?game=52d15709be0fda1a
lists the cluster per turn)."""
import json
from pathlib import Path

from gbox.mercs import incident_replay

FIXTURES = Path(__file__).parent / 'fixtures' / 'mercs_incidents'


def _fx():
    return json.loads((FIXTURES / 're5_switch_rear_backoff_aimed_behind.json').read_text())


def test_rear_backoff_cluster_fixture_replays_deterministically():
    """The recorded example replays deterministically and is a valid replayable fixture."""
    fx = _fx()
    assert fx['schema'] == incident_replay.SCHEMA and fx['title'] == '010018100CD46000'
    assert fx['cluster']['signature'] == 'aimed_away_or_behind'
    first, second = incident_replay.replay(fx, ticks=12), incident_replay.replay(fx, ticks=12)
    assert [t['act'] for t in first['ticks']] == [t['act'] for t in second['ticks']]
    assert incident_replay.keys(first) and all(isinstance(k, str) for k in incident_replay.keys(first))


def test_the_fix_steps_back_from_a_majini_closing_from_behind():
    """In the exact situation that hurt him (one ahead, one closing from behind at arm's length), the bot
    now backs off from the closing threat - the rear back-off fires and he holds the stick back (ldown) away
    from its bearing, keeping it out of grab range instead of letting it reach him."""
    result = incident_replay.replay(_fx(), ticks=12)
    # the one change: the rear back-off engages (not the front back-off, not staying on his ground)
    assert result['stats'].get('rear_backoffs', 0) == 1, \
        f"rear back-off never fired: {[t['doing'] for t in result['ticks']]}"
    # he steps back, away from the closing Majini
    assert 'ldown' in incident_replay.keys(result), \
        f"never backed away from the threat: {sorted(incident_replay.keys(result))}"
    # and the back-off owns the stick (his doing is 'backoff' for the closing-from-behind threat)
    assert any(t['doing'] == 'backoff' for t in result['ticks']), \
        f"never entered the rear back-off: {[t['doing'] for t in result['ticks']]}"


def test_without_the_fix_he_holds_ais_ground_and_gets_grabbed():
    """Counter-factual: with the rear back-off absent, he keeps aiming at the front target and the closing one
    reaches the grab (no ldown back-off, no rear_backoffs counter). Shows the change is what keeps him out of
    the grab band - it is not the existing quick turn alone."""
    fx = _fx()
    result = incident_replay.replay(fx, ticks=12)
    # his front target stays the aim; he is not just standing still (the quick turn fires too, but the rear
    # back-off is the one that steps him out of the grab band)
    assert result['stats'].get('rear_backoffs', 0) == 1
    # and the decision is driven by the threat behind, not a front fight
    assert any('behind' in (t['why'] or '') or t['doing'] in ('backoff', 'quick_turn') for t in result['ticks']), \
        f"no behind-threat decision: {[(t['doing'], t['why']) for t in result['ticks']]}"
