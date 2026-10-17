import pytest

from gbox.last_played import end_reason


@pytest.mark.parametrize('code', [1, 2, -1, -9, -15, 0xc000013a])
def test_generic_codes_and_operator_termination_are_not_proof_of_a_crash(code):
    reason = end_reason({'state': 'ended', 'exit': {'returncode': code}})
    assert not reason['crash']
    assert 'unexpected' not in reason['text']
    assert 'closed' in reason['text']


@pytest.mark.parametrize('code', [0xc0000005, -1073741819, 0xc0000409, -11, -6])
def test_recognizable_exception_or_fatal_signal_still_warns(code):
    reason = end_reason({'state': 'ended', 'exit': {'returncode': code}})
    assert reason['crash'] and reason['kind'] == 'crash'


def test_explicit_stop_takes_precedence_over_the_process_termination_value():
    assert end_reason({'state': 'ended', 'exit': {'returncode': 0xc0000005, 'via': 'stop'}}) == {
        'kind': 'stopped', 'crash': False, 'text': 'You stopped it.'}
