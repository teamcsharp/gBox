from gbox.mercs.re4_reactive_ring import Reactions
from gbox.mercs import grenade_ring as GR


def snap(hp=1000, phase='playing', generation=1):
    return {'player': {'ptr': 10, 'id': generation, 'hp': hp, 'pos': [0, 0, 0]},
            'game': {'phase': phase}, 'enemies': [], 'screen': 'playing'}


def test_every_new_damage_edge_triggers_once_without_a_periodic_cooldown():
    r, stats = Reactions(), {'rounds': 1}
    assert r.observe(snap(), stats, 1) is None
    assert r.observe(snap(900), stats, 1.1)['kind'] == 'hand'
    assert r.observe(snap(900), stats, 1.2) is None
    assert r.observe(snap(800), stats, 1.3)['damage'] == 100
    assert r.observe(snap(1000), stats, 1.4) is None
    assert r.observe(snap(950), stats, 1.5)['kind'] == 'hand'


def test_grab_qte_has_priority_over_damage_and_one_flash_per_episode():
    r, stats = Reactions(), {'rounds': 1}
    r.observe(snap(), stats, 1)
    assert r.observe(snap(700, 'grabbed'), stats, 2)['kind'] == 'flash'
    assert r.observe(snap(700, 'grabbed'), stats, 2.1) is None
    r.observe(snap(700), stats, 2.2)
    assert r.observe(snap(700, 'grabbed'), stats, 2.3)['kind'] == 'flash'


def test_new_round_player_menu_dead_and_operator_do_not_invent_damage():
    r, stats = Reactions(), {'rounds': 1}
    r.observe(snap(), stats, 1)
    assert r.observe(snap(500, generation=2), stats, 2) is None
    stats['rounds'] = 2
    assert r.observe(snap(400, generation=2), stats, 3) is None
    assert r.observe(snap(0, 'dead', 2), stats, 4) is None
    assert r.observe(snap(100, 'intro', 2), stats, 5) is None
    stats['operator_control'] = True
    assert r.observe(snap(50, 'grabbed', 2), stats, 6) is None
    stats['operator_control'] = False
    assert r.observe(snap(50, 'grabbed', 2), stats, 7) is None


def test_control_dispatches_flash_during_grab_and_does_not_replay_uncertain_ring():
    class Ring:
        def __init__(self): self.calls = []
        def grenade_ring(self, kind, **kwargs):
            self.calls.append((kind, kwargs))
            return {'state': 'uncertain', 'verified': False, 'detonated': 3}
    ring, stats = Ring(), {'rounds': 1, 'screen': 'playing', 'ring_last_at': 10}
    step = GR.control(None, {'map_id': '010099A00BC1E000'}, ring=ring)
    step(snap(), stats, 10)
    out = step(snap(900, 'grabbed'), stats, 10.1)
    assert out['attempted'] and not out['fired']
    assert ring.calls[0][0] == 'flash'
    step(snap(900, 'grabbed'), stats, 10.2)
    assert len(ring.calls) == 1
    assert stats['reactive_ring_receipt']['state'] == 'uncertain'


def test_switch_off_still_prevents_native_reaction():
    stats = {'rounds': 1, 'screen': 'playing', 'ring': {'enabled': False}}
    step = GR.control(None, {'map_id': '010099A00BC1E000'})
    assert not step(snap(900, 'grabbed'), stats, 10).get('attempted')
