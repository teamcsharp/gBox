import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('chat_review', Path(__file__).parents[1] / 'scripts/chat_review.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def events(result, op='use'):
    return [{'type': 'tool_call', 'name': 'characters', 'args': {'op': op, 'character': 'aya'}},
            {'type': 'tool_result', 'name': 'characters', 'text': json.dumps(result)},
            {'type': 'assistant', 'text': 'The attempted result is described here.'}]


@pytest.mark.parametrize('result', [{'status': 'overlay'}, {'status': 'missing', 'overlay_error': 'session ended'},
                                  {'status': 'launched'}, {'result': {'status': 'overlay', 'verified': True}}])
def test_review_flags_unfulfilled_native_swap_even_when_answer_is_candid(result):
    flags, _, _ = review.judge({'text': 'Pick whip: replace Aya in the game'}, events(result))
    assert any('Native character' in flag or 'no verified' in flag for flag in flags)


def test_verified_native_swap_passes_but_an_explicit_overlay_request_is_not_a_rom_claim():
    assert not review.judge({'text': 'Pick whip: replace Aya in the game'},
                            events({'status': 'in_engine', 'verified': True}))[0]
    assert not review.judge({'text': 'Show Aya as an overlay'}, events({'status': 'overlay'}, op='overlay'))[0]


def test_null_error_metadata_does_not_make_a_successful_read_look_failed():
    flags, _, _ = review.judge({'text': 'Inspect the current game'},
                              [{'type': 'tool_result', 'name': 'session_info',
                                'text': json.dumps({'state': 'succeeded', 'error': None})},
                               {'type': 'assistant', 'text': 'The game is running.'}])
    assert not flags


@pytest.mark.parametrize('payload', [{'state': 'failed', 'result': {'verified': True}},
                                   {'error': 'worker disconnected', 'result': {'status': 'ok'}}])
def test_failure_on_job_wrapper_is_not_hidden_by_a_nested_result(payload):
    flags, _, _ = review.judge({'text': 'Inspect the current game'},
                              [{'type': 'tool_result', 'name': 'session_info', 'text': json.dumps(payload)},
                               {'type': 'assistant', 'text': 'The worker returned a result.'}])
    assert any('tool error' in flag for flag in flags)


def test_original_half_open_window_turn_split_stays_exact():
    seq = [{'type': 'assistant', 'text': 'old'},
           {'type': 'user', 'text': 'at start', 'ts': 100},
           {'type': 'assistant', 'text': 'answer'},
           {'type': 'user', 'text': 'at end', 'ts': 1000},
           {'type': 'assistant', 'text': 'answer'}]
    matched = [(r, e) for r, e in review.turns(seq) if 100 <= r['ts'] < 1000]
    assert len(matched) == 1 and matched[0][0]['text'] == 'at start'
    assert matched[0][1] == [{'type': 'assistant', 'text': 'answer'}]
