"""#1119: the in-app gBox agent must know that 'skip this talking' is zelda op=skip_text."""
import re

from gbox import agent, zelda_tool


def _spec(name):
    return next(t["function"] for t in agent.tool_specs() if t["function"]["name"] == name)


def test_zelda_tool_description_offers_skip_text():
    desc = _spec("zelda")["description"]
    assert "skip_text" in desc and "talking" in desc
    assert {"session_id", "op", "count"} <= set(_spec("zelda")["parameters"]["properties"])


def test_system_prompt_routes_talk_skip_and_keeps_deku_story_skip_separate():
    line = next(l for l in agent.SYSTEM.splitlines() if "Skip this talking" in l)
    assert "zelda op=skip_text" in line
    assert "zelda_oot op=skip_deku_tree" in agent.SYSTEM


def test_advertised_op_names_resolve_to_skip_text():
    # every op word the prompt teaches must be one the tool actually accepts
    src = open(zelda_tool.__file__, encoding="utf-8").read()
    assert re.search(r'"skip": "skip_text"', src) and "def _skip_text(" in src
    for alias in ("skip_text", "skip", "skip_talk", "skip_dialogue", "skip_cutscene"):
        assert alias == "skip_text" or f'"{alias}": "skip_text"' in src


def test_session_op_fallback_names_real_adapter_methods():
    from gbox import adapters
    assert "fast_forward" in agent.SYSTEM and "send_input" in agent.SYSTEM
    assert hasattr(adapters.RetroArchAdapter, "fast_forward") and hasattr(adapters.RetroArchAdapter, "send_input")
