"""Focused check for the Mercs opening-phase protocol artifact (request #4847)."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ARTIFACT = os.path.join(HERE, "..", "docs", "mercs", "opening_phase_protocol.json")


def load():
    with open(ARTIFACT, "r", encoding="utf-8") as f:
        return json.load(f)


def test_schema_and_source():
    a = load()
    assert a["schema"] == "gbox.mercs.opening_phase_protocol/1"
    assert a["request_number"] == 4847
    assert a["source_request_id"] == "4ffb97eaaee54068"
    assert "Checkpoint to Checkpoint" in a["operator_instruction_verbatim"]


def test_phase_order():
    a = load()
    phases = a["phases"]
    assert [p["order"] for p in phases] == [1, 2]
    assert phases[0]["name"] == "opening"
    assert phases[0]["end_condition"] == "all time bonuses grabbed"
    assert phases[1]["name"] == "match"
    assert phases[1]["start_condition"] == "all time bonuses grabbed"
    assert "checkpoint to checkpoint" in phases[0]["objective"].lower()


def test_time_bonus_acquisition_re5_re6():
    a = load()
    for game in ("resident_evil_5", "resident_evil_6"):
        tb = a["time_bonus_acquisition"][game]
        assert tb["method"] == "walk_up_and_melee"
        assert tb["can_be_shot_from_distance"] is False


def main():
    test_schema_and_source()
    test_phase_order()
    test_time_bonus_acquisition_re5_re6()
    print("PASS: opening_phase_protocol.json checks (3/3)")


if __name__ == "__main__":
    main()
