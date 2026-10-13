"""#1638: a drawn but static screen after resume gets one Start press before recovery gives up.

DOA2's first screen is a mostly black VMU prompt that waits for Start; auto-troubleshooting
reported it as a freeze. Start goes to player one as a down/up pair, only for the auto recipe,
only when the screen is drawn, and never instead of preserving the checkpoint.
"""
from test_emulation_issue import make_incident


def starts(calls):
    return [data['args']['events'] for tool, data in calls
            if tool == 'session_op' and data['op'] == 'send_input']


def test_static_prompt_is_woken_with_one_start_press_without_relaunch(cfg):
    # capture, 4 static resume frames, then the prompt advances after Start
    incident, calls = make_incident(cfg, ['black'] + ['white'] * 4 + ['white', 'blue'])
    incident.run()
    assert starts(calls) == [[{'key': 'start', 'down': True}], [{'key': 'start', 'down': False}]]
    export = next(i for i, (tool, data) in enumerate(calls) if tool == 'state_transfer' and data['op'] == 'export')
    press = next(i for i, (tool, data) in enumerate(calls) if tool == 'session_op' and data['op'] == 'send_input')
    assert export < press
    assert not any(tool == 'launch_game' for tool, _ in calls)
    job = incident.store.get('job', incident.job.id)
    assert job['state'] == 'succeeded'
    assert job['output']['motion'] and job['output']['method'] == 'press Start at static prompt'
    report = incident.store.get('request', incident.rid)
    assert any(m.get('task_step', {}).get('action') == 'press start at static prompt' for m in report['messages'])


def test_black_screen_gets_no_start_press(cfg):
    incident, calls = make_incident(cfg, ['black'] * 12)
    incident.run()
    assert starts(calls) == []


def test_resume_recipe_never_presses_start(cfg):
    incident, calls = make_incident(cfg, ['black'] + ['white'] * 8)
    incident.action = 'resume'
    incident.run()
    assert starts(calls) == []
    assert incident.store.get('job', incident.job.id)['output']['method'] == 'resume'


def test_still_static_after_start_falls_through_to_checkpointed_relaunch(cfg):
    incident, calls = make_incident(cfg, ['black'] + ['white'] * 8 + ['red', 'green'])
    incident.run()
    assert len(starts(calls)) == 2
    assert any(tool == 'launch_game' for tool, _ in calls)
