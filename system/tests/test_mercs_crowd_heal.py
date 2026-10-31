"""#5051: RE6 Switch crowd damage cluster — the tablet gate lowered the gun in a crowd.

The fix removes the CROWD_TABLET_* branch from the tablet gate and adds a `crowd == 0` guard,
so the bot keeps the gun up and firing (zl + zr) instead of tapping R (tablet) mid-swarm.
"""
import json
from pathlib import Path

from gbox.mercs import incident_replay

FIXTURES = Path(__file__).parent / 'fixtures' / 'mercs_incidents'


def test_re6_switch_crowd_gun_down_fixture_fights_not_heals():
    """#5051: 4+ within 2.3 m at 488/900 (54%) — the tablet gate lowered the gun in the crowd.

    Over 30 ticks on the fixture snapshot: tablet ticks drop to 0 and crowd firing dominates,
    because the gun no longer lowers for a tablet while a crowd is close.
    """
    fx = json.loads((FIXTURES / 're6_switch_crowd_gun_down.json').read_text())
    result = incident_replay.replay(fx, ticks=30)
    keys = incident_replay.keys(result)
    # Gun raised and firing into the crowd
    assert 'zl' in keys, f'gun never raised in crowd: {[t["doing"] for t in result["ticks"]]}'
    assert 'zr' in keys, f'never fired in crowd: {[t["doing"] for t in result["ticks"]]}'
    doings = [t['doing'] for t in result['ticks']]
    # No tablet ticks at all — the gun never lowers in the crowd
    assert doings.count('tablet') == 0, f'{doings.count("tablet")} tablet ticks: {doings}'
    # Crowd firing is present
    assert doings.count('crowd') >= 5, f'only {doings.count("crowd")} crowd ticks: {doings}'
