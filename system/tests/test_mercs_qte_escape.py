import pytest
from gbox.mercs.qte_escape import Recovery


def setup(result=None):
    jobs, calls, stats = [], [], {'round_evidence_id': 'one'}
    def fire(identity, allowed):
        calls.append((identity, allowed()))
        return result or {'state': 'confirmed', 'verified': True}
    recovery = Recovery(None, submit=jobs.append, fire=fire)
    return recovery, jobs, calls, stats


def observe(r, stats, now, state=0, grants=0, generation=2, hp=100):
    r.observe({'player': {'ptr': 100, 'generation': generation, 'state': state, 'hp': hp}}, stats, now, grants)


def released(r, stats):
    observe(r, stats, 0, state=8, grants=1)
    observe(r, stats, .1)
    observe(r, stats, .21)


def test_flash_runs_during_grab_but_mines_require_grant_and_observed_release():
    r, jobs, calls, stats = setup()
    observe(r, stats, 0, state=8)
    assert len(jobs) == 1
    jobs.pop()()
    assert not stats.get('qte_escape_mines_due')
    observe(r, stats, .1)
    observe(r, stats, .3)
    assert not jobs and not stats.get('qte_escape_mines_due')
    released(r, stats)
    observe(r, stats, .4)
    assert len(jobs) == 1 and stats['qte_escape_active']
    jobs[0]()
    assert calls == [((100, 2), True)] * 2 and stats['qte_escape_mines_due']


@pytest.mark.parametrize('invalidate', ['life', 'round', 'operator', 'dead', 'regrab'])
def test_queued_flash_cannot_outlive_recovery(invalidate):
    r, jobs, calls, stats = setup()
    released(r, stats)
    if invalidate == 'round':
        stats['round_evidence_id'] = 'two'
    if invalidate == 'operator':
        stats['operator_control'] = True
    observe(r, stats, .3, generation=3 if invalidate == 'life' else 2,
            state=8 if invalidate == 'regrab' else 0, hp=0 if invalidate == 'dead' else 100)
    jobs[0]()
    assert not calls and not stats.get('qte_escape_mines_due')


def test_regrab_during_flash_cannot_schedule_mines():
    r, jobs, calls, stats = setup()
    def fire(identity, allowed):
        observe(r, stats, .4, state=8)
        return {'state': 'confirmed', 'verified': True}
    r.fire = fire
    released(r, stats)
    jobs[0]()
    assert not stats.get('qte_escape_mines_due')


def test_repeated_held_frames_flash_once_then_mines_after_verified_release():
    r, jobs, calls, stats = setup()
    observe(r, stats, 0, state=8, grants=1)
    jobs[0]()
    for now in (.1, .2, .3):
        observe(r, stats, now, state=8)
    assert len(jobs) == 1 and not stats.get('qte_escape_mines_due')
    observe(r, stats, .4)
    observe(r, stats, .51)
    assert stats['qte_escape_mines_due']


def test_uncertain_flash_never_schedules_mines_or_retries():
    r, jobs, calls, stats = setup({'state': 'uncertain', 'verified': False})
    released(r, stats)
    jobs[0]()
    observe(r, stats, .5)
    assert len(jobs) == 1 and not stats.get('qte_escape_mines_due')


def test_queued_flash_requires_recent_observation():
    r, jobs, calls, stats = setup()
    clock = [0.]
    r.clock = lambda: clock[0]
    released(r, stats)
    clock[0] = .76
    jobs[0]()
    assert not calls and not stats.get('qte_escape_mines_due')


def test_escape_returns_to_combat_after_bounded_retreat():
    r, jobs, calls, stats = setup()
    released(r, stats)
    jobs[0]()
    assert stats['qte_escape_active'] and stats['qte_escape_mines_due']
    observe(r, stats, 3.2)
    assert not stats['qte_escape_active'] and not stats.get('qte_escape_mines_due')
