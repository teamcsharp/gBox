from gbox.inbox import organize, parent_for

STANDING = 'examine the requests I give gBox and how it responds; make sure it has the means to accomplish them'


def operator(id='standing', body=STANDING, created=1, session='same'):
    return {'id': id, 'body': body, 'created': created, 'context': {'session': session}}


def review(**extra):
    return {'id': 'review', 'created': 10, 'context': {'session': 'same'},
            'body': f'gBox request review (recurring, set up at the operator\'s request: "{STANDING}").\nRun review.', **extra}


def test_recurring_review_is_not_parented_to_latest_unrelated_session_prompt():
    root = operator('thumbnail', 'Make the thumbnail popup larger', 9)
    assert parent_for(review(), [root, review()]) is None


def test_standing_instruction_wins_over_a_newer_unrelated_conversation_prompt():
    root = operator()
    unrelated = operator('thumbnail', 'Make the thumbnail popup larger', 9)
    assert parent_for(review(), [root, unrelated, review()]) == 'standing'


def test_partial_phrase_or_semantic_similarity_does_not_invent_a_standing_parent():
    root = operator(body='With these requests, I need you examining and looking at the output.')
    partial = operator('partial', 'I want to examine the requests in another report.', 3)
    assert parent_for(review(), [root, partial, review()]) is None


def test_missing_quoted_instruction_is_unlinked_even_with_matching_conversation():
    r = review(body='gBox request review\nRun review')
    assert parent_for(r, [operator(), r]) is None


def test_normalized_exact_instruction_matches_and_future_roots_are_excluded():
    past = operator('past', '  EXAMINE the requests I give gBox and how it responds;\nmake sure it has the means to accomplish them  ')
    future = operator('future', created=20)
    assert parent_for(review(), [past, future, review()]) == 'past'


def test_existing_explicit_review_parent_is_preserved_without_historical_reparenting():
    thumbnail = operator('thumbnail', 'Unrelated thumbnail task', 9)
    r = review(parent_request_id='thumbnail')
    rows = organize([thumbnail, operator(), r])
    assert rows[-1]['parent_request_id'] == 'thumbnail'


def test_explicit_context_parent_and_quoted_operator_matches_keep_precedence():
    root = operator('explicit', 'Another valid original request')
    r = review(context={'session': 'same', 'request_id': 'explicit'})
    assert parent_for(r, [root, operator(), r]) == 'explicit'
    quoted = review(body='gBox request review\n## What the operator asked\nAnother valid original request\n## Context\nDetail')
    assert parent_for(quoted, [root, operator(), quoted]) == 'explicit'


def test_auto_report_stays_first_class_even_with_explicit_origin():
    r = review(context={'auto_report': True, 'request_id': 'standing'})
    assert parent_for(r, [operator(), r]) is None


def test_non_review_automated_task_keeps_conversation_fallback():
    root = operator('last', 'Actual operator extraction request', 9)
    task = {'id': 'extraction', 'created': 10, 'source': 'characters', 'body': 'Extraction follow-up', 'context': {'session': 'same'}}
    assert parent_for(task, [root, task]) == 'last'


def test_curly_quoted_standing_instruction_links_in_list_and_single_lookup():
    # /api/requests uses organize(); request creation uses parent_for(). Both
    # must read the curly quotes the review writer can produce.
    r = review(body=f'gBox request review (recurring, set up at the operator\u2019s request: \u201c{STANDING}\u201d).\nRun review.')
    rows = [operator(), operator('thumbnail', 'Make the thumbnail popup larger', 9), r]
    assert parent_for(r, rows) == 'standing'
    assert organize(rows)[-1]['parent_request_id'] == 'standing'


def test_question_mark_inside_standing_instruction_is_not_a_closing_quote():
    question = 'can gBox examine the requests I give it?'
    r = review(body=f'gBox request review (recurring, set up at the operator\'s request: "{question}").\nRun review.')
    rows = [operator(body=question), r]
    assert parent_for(r, rows) == 'standing'
    assert organize(rows)[-1]['parent_request_id'] == 'standing'
