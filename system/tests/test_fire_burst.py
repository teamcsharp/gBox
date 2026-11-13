from gbox.mercs.core.fire_burst import Burst


def test_input_requests_cannot_complete_twenty_discharge_goal():
    stats = {}
    burst = Burst(stats)
    burst.observe(('round', 10, 2), 0)
    burst.begin(0)
    for i in range(20):
        burst.requested()
        burst.observe(('round', 10, 2), (i + 1) * .1, i < 12)
    assert burst.active(2) and stats['fire_burst_remaining'] == 8
    assert stats.get('fire_bursts_completed', 0) == 0
    for i in range(8):
        burst.observe(('round', 10, 2), 3 + i * .1, True)
    assert not burst.active(4) and stats['fire_bursts_completed'] == 1


def test_round_reset_interrupts_and_missing_evidence_expires_without_completion():
    stats = {}
    burst = Burst(stats)
    burst.observe(('round', 10, 2), 0)
    burst.begin(0)
    burst.observe(('round', 10, 2), .1, True)
    burst.observe(('next', 10, 2), .2)
    assert not burst.active(.2) and stats['fire_bursts_interrupted'] == 1
    burst.begin(1)
    assert not burst.active(9)
    assert stats['fire_burst_state'] == 'discharge_confirmation_timeout'
    assert stats.get('fire_bursts_completed', 0) == 0


def test_repeated_raise_does_not_restart_remaining_goal():
    burst = Burst({})
    burst.observe(('round', 10, 2), 0)
    burst.begin(0)
    burst.observe(('round', 10, 2), .1, True)
    burst.begin(.2)
    assert burst.seen == 1 and burst.started == 0
