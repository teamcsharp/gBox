"""The local-model pipeline's scoring and prompt assembly - no server needed for these."""
import json

import pytest

from gbox import pso_llm as L


def test_the_gold_set_is_the_proven_code_map():
    assert len(L.GOLD) == 30                                  # section 3's table has 30 rows
    assert L.GOLD["80103748"][0] == "F_DELETE" and L.GOLD["801057a8"][0] == "F_CREATE"
    assert L.GOLD["801bab1c"][0] == "WARP" and L.GOLD["80228540"][0] == "SET_TARGET"
    # placeholders are kept but excluded from the role score
    assert "8010b198" in L.GOLD and "8010b198" not in L.scored(list(L.GOLD))
    assert len(L.scored(list(L.GOLD))) == 25


def test_an_exact_name_beats_everything_and_is_case_insensitive():
    assert L.score_answer({"name": "f_delete"}, "80103748") == "name"
    assert L.score_answer({"name": "F_DELETE", "role": "garbage"}, "80103748") == "name"


def test_the_same_role_in_words_counts_as_a_role_hit():
    # role: "object delete"
    assert L.score_answer({"name": "REMOVE_THING", "role": "Deletes an object from the table."}, "80103748") == "role"
    # role: "sets the area-load request flag"
    assert L.score_answer({"name": "REQUEST_LOAD", "role": "Sets a flag that requests an area load."},
                          "8000f998") == "role"


def test_an_unrelated_answer_is_wrong():
    assert L.score_answer({"name": "RENDER_UI", "role": "Draws the HUD."}, "80103748") == "wrong"
    assert L.score_answer({}, "80103748") == "wrong"


def test_the_prompt_carries_no_address_and_no_ghidra_name():
    c = "void this_function(void) { callee_1(); }"
    prompt = L.prompt_for("80103748", c, 88)
    assert "80103748" not in prompt and "FUN_" not in prompt and "this_function" in prompt
    assert "88 bytes" in prompt


def test_a_run_writes_a_summary_with_honest_counts(tmp_path, monkeypatch):
    decompiles = {"80103748": {"bytes": 88, "ghidra_name": "FUN_80103748", "c": "void this_function(void){}"},
                  "801057a8": {"bytes": 204, "ghidra_name": "FUN_801057a8", "c": "void this_function(void){}"}}
    monkeypatch.setattr(L, "load_decompiles", lambda path=None: decompiles)
    monkeypatch.setattr(L, "GOLD_DIR", tmp_path)
    answers = iter([{"name": "F_DELETE", "role": "object delete"}, {"name": "NOPE", "role": "draws a HUD"}])
    monkeypatch.setattr(L, "ask", lambda model, prompt, **kw: next(answers))
    summary = L.run("test-model:1b", refresh=True)
    assert summary["functions"] == 2 and summary["name_exact"] == 1 and summary["wrong"] == 1
    assert summary["role_rate"] == 0.5
    written = json.loads((tmp_path / "gold34-test-model-1b.json").read_text(encoding="utf-8"))
    assert written["model"] == "test-model:1b" and len(written["answers"]) == 2
    assert all("proven" in row and "seconds" in row for row in written["answers"])


def test_a_dead_server_is_recorded_not_raised(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "load_decompiles", lambda path=None: {"80103748": {"bytes": 88, "c": "void x(){}"}})
    monkeypatch.setattr(L, "GOLD_DIR", tmp_path)
    monkeypatch.setattr(L, "ask", lambda model, prompt, **kw: (_ for _ in ()).throw(OSError("connection refused")))
    summary = L.run("dead-model", refresh=True)
    assert summary["answers"][0]["verdict"] == "wrong"
    assert "connection refused" in summary["answers"][0]["error"]
