from gbox.prompt_history import markdown


def test_followups_globally_ordered_and_initial_body_preserved():
    rows = [dict(id='a', number=1, created=10, body='first', messages=[
        dict(author='agent', text='answer', ts=11), dict(author='operator', text='third', ts=30)]),
        dict(id='b', created=20, body='second')]
    text = markdown(rows)
    assert text.index('\nfirst\n') < text.index('\nsecond\n') < text.index('\nthird\n')
    assert '\nanswer\n' not in text


def test_linked_chat_dedup_preserves_repeated_prompts_and_unlinked_turns():
    rows = [dict(id='a', created=10, body='same', context={'conversation': 'c'})]
    chats = [dict(id='c', events=[dict(type='user', text='same', ts=10),
                                dict(type='user', text='same', ts=100),
                                dict(type='user', text='untracked', ts=101)])]
    text = markdown(rows, chats)
    assert text.count('\nsame\n') == 2
    assert '\nuntracked\n' in text


def test_automated_body_excluded_but_operator_response_and_unicode_kept():
    rows = [dict(id='a', automated=True, body='robot', messages=[
        dict(author='operator', ts=3, text='日本語 password=secret\ud800')])]
    text = markdown(rows, redact=lambda s: s.replace('secret', '[redacted]'))
    assert 'robot' not in text and '日本語' in text and 'secret' not in text
    text.encode('utf8')


def test_legacy_automation_initial_message_is_not_an_operator_prompt():
    rows = [dict(id='a', source='automation', created=1, body='scheduled task',
                 context={'conversation': 'c'}, messages=[
                     dict(author='operator', ts=1, text='scheduled task'),
                     dict(author='operator', ts=100, text='my followup')])]
    chats = [dict(id='c', events=[dict(type='user', text='scheduled task', ts=1)])]
    text = markdown(rows, chats)
    assert 'scheduled task' not in text and 'my followup' in text
