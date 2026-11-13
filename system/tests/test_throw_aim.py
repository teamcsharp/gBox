from gbox.mercs.core.throw_aim import ThrowAim


def snap(pos=(0, 0, 700), units=()):
    return {'player': {'ptr': 1, 'generation': 2},
            'enemies': [{'ptr': 10, 'generation': 3, 'hp': 100, 'pos': pos}], 'throwables': units}


def test_throw_leads_a_moving_target_and_does_not_lead_a_teleport():
    aim = ThrowAim({})
    aim.observe(snap(), 0)
    current = snap((20, 0, 700))
    aim.observe(current, .1)
    plan = aim.plan('frag', (0, 0, 0), current['enemies'], .1)
    assert plan['target'][0] == 90
    current = snap((2000, 0, 700))
    aim.observe(current, .2)
    assert aim.plan('frag', (0, 0, 0), current['enemies'], .2)['target'][0] == 2000


def test_owned_projectile_landing_teaches_bounded_correction_and_persists(tmp_path):
    stats = {}
    aim = ThrowAim(stats, tmp_path)
    current = snap()
    aim.observe(current, 0)
    plan = aim.plan('remote', (0, 0, 0), current['enemies'], 0)
    aim.request('remote', (0, 0, 0), plan, 0, aligned=True)
    unit = {'unit': 20, 'generation': 4, 'kind': 'remote', 'pos': (0, 100, 100), 'action': 'in_flight'}
    aim.observe(snap(units=[unit]), .1)
    unit.update(pos=(40, 0, 600), action='cWpAction_wp_act_setting')
    aim.observe(snap(units=[unit]), .5)
    assert stats['throw_aim_observed'] == 1
    assert stats['throw_aim_last']['learned'] is True
    assert stats['throw_aim_last']['damage_attribution'] == 'unknown'
    loaded = ThrowAim({}, tmp_path)
    corrected = loaded.plan('remote', (0, 0, 0), current['enemies'], 1)
    assert corrected['aim'][0] < 0 and corrected['aim'][2] > 700


def test_ring_ambiguity_and_missing_projectiles_cannot_teach_or_count_as_hits():
    stats = {}
    aim = ThrowAim(stats)
    current = snap()
    aim.observe(current, 0)
    plan = aim.plan('frag', (0, 0, 0), current['enemies'], 0)
    aim.request('frag', (0, 0, 0), plan, 0, aligned=True)
    units = [{'unit': n, 'generation': 4, 'kind': 'frag', 'pos': (0, 0, 100),
              'action': 'cWpAction_wp_act_bomb'} for n in (20, 21)]
    aim.observe(snap(units=units), .1)
    assert not aim.cells and stats['throw_aim_last']['state'] == 'ambiguous_projectiles'
    aim.request('frag', (0, 0, 0), plan, 1, aligned=True)
    aim.observe(snap(), 8)
    assert stats['throw_aim_last']['state'] == 'unresolved' and not aim.cells


def test_two_unbound_requests_cannot_claim_one_projectile_as_the_first_is_removed():
    stats = {}
    aim = ThrowAim(stats)
    current = snap()
    aim.observe(current, 0)
    plan = aim.plan('frag', (0, 0, 0), current['enemies'], 0)
    for at in (0, .01):
        aim.request('frag', (0, 0, 0), plan, at, aligned=True)
    aim.observe(snap(units=[{'unit': 20, 'generation': 4, 'kind': 'frag', 'pos': (0, 0, 100),
                             'action': 'cWpAction_wp_act_bomb'}]), .1)
    assert len(stats['throw_aim_history']) == 2 and not aim.pending
    assert all(r['state'] == 'ambiguous_projectiles' for r in stats['throw_aim_history'])
    assert not stats.get('throw_aim_observed')
