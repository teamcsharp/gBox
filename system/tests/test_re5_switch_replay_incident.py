"""Replay of the recorded idle_among_foes incident (cluster aef43e59aa636e02, signature round:idle_among_foes)
through gbox.mercs.incident_replay: the stored driver snapshot had three live Majini within 5 m and the bot
idled among them (counters idle_in_5m_s: 40 at the hit). With the widened CLOSE_FIRE_CONE / RAMPAGE_BEHIND
the trigger must come down on the first tick against that exact recorded situation and stay down — the
new close-range fire decision, checked on the incident's own data, not a synthetic one."""
import json
from pathlib import Path

import pytest

from gbox.mercs import incident_replay
from gbox.mercs.titles import re5_switch as R

FX = Path(__file__).parent / 'fixtures' / 'mercs_incidents' / 're5_switch_idle_among_foes.json'


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "RAMPAGE", True)
    monkeypatch.setattr(R, "QUICK_TURN", True)


def _close_enemies(fx):
    out = []
    for e in fx['snapshot'].get('enemies') or []:
        p = e.get('pos')
        if not p:
            continue
        d = (p[0] ** 2 + p[2] ** 2) ** 0.5
        if d <= 500:
            out.append(e)
    return out


def test_fixture_is_the_recorded_cluster_incident():
    fx = json.loads(FX.read_text())
    assert fx['schema'] == 'gbox.mercs.incident-replay/1'
    assert fx['cluster']['id'] == 'aef43e59aa636e02'
    assert fx['cluster']['signature'] == 'round:idle_among_foes'
    assert _close_enemies(fx)                       # the incident: live foes within 5 m
    assert fx['counters']['idle_in_5m_s'] > 0       # and the bot had idled among them


def test_recorded_incident_now_fires_from_the_first_tick():
    fx = json.loads(FX.read_text())
    result = incident_replay.replay(fx, ticks=10)
    held = incident_replay.keys(result)
    assert 'zr' in held                             # the trigger was down
    for tick in result['ticks']:                    # ...from the very first tick, every tick
        assert 'zr' in (tick['act'].get('hold') or [])
    assert result['bot'].stats['idle_in_5m_s'] == 0     # no second spent idle among foes
    assert result['bot'].stats['rampage_s'] > 0         # the rampage fired
