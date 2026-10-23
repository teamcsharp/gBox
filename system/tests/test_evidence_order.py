from pathlib import Path
from gbox import agent

ROOT = Path(__file__).resolve().parents[1]


def test_system_prompt_ranks_ram_before_vision():
    s = agent.SYSTEM
    assert 'EVIDENCE ORDER' in s
    assert s.index('Level 1: live RAM') < s.index('Level 3 (last resort)')
    assert 'never\noverrides a RAM value' in s or 'never overrides a RAM value' in s.replace('\n', ' ')


def test_look_at_screen_marked_last_resort():
    src = (ROOT / 'gbox/agent.py').read_text()
    assert 'LAST RESORT: capture the game screen' in src


def test_hermes_docs_state_evidence_order():
    for f in ('TASK_MODE.md', 'SKILL.md'):
        assert 'Evidence order: code and RAM first, vision last' in (ROOT / 'hermes/gbox' / f).read_text()
