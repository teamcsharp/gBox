"""Requested source components remain distinct deterministic pools; planning writes no source assets."""
import copy

import pytest

from gbox import cast_swap as C
from test_cast_alternate import _chars, _entry, _slot, _donor, DOA2


def sequences(result):
    pools = {row["slug"]: row["pool"] for row in result["donors"]}
    return [pools[row["character"]] for row in result["assignments"]]


def test_extractor_component_spanning_two_games_is_one_pool_and_keeps_order():
    chars = _chars()
    # A single extractor selection spans both regional game IDs, but is still one requested pool.
    chars.append(_entry("sa2_amy", "Amy", "Sonic Adventure 2 (Europe)", "dreamcast", "5a20000000000001"))
    original = copy.deepcopy(chars)
    result = C.plan(DOA2, chars, "sa2,mario", mapping="alternate", seed="regional")
    assert result["status"] == "planned"
    assert sequences(result) == ["extractor:sa2", "mario"] * (len(result["assignments"]) // 2) + (["extractor:sa2"] if len(result["assignments"]) % 2 else [])
    assert {row["source_game_id"] for row in result["donors"] if row["pool"] == "extractor:sa2"} == {"5a20000000000000", "5a20000000000001"}
    assert chars == original


def test_reversing_requested_components_reverses_starting_pool():
    chars = _chars()
    first = C.plan(DOA2, chars, "sonic,mario", mapping="alternate", seed="ordered")
    second = C.plan(DOA2, chars, "mario,sonic", mapping="alternate", seed="ordered")
    assert sequences(first)[:4] == ["sonic", "mario", "sonic", "mario"]
    assert sequences(second)[:4] == ["mario", "sonic", "mario", "sonic"]
    assert "sm64ds_mario" not in {r["character"] for r in second["assignments"]}


def test_title_component_spanning_two_games_is_one_pool():
    chars = _chars()
    chars.append(_entry("sa2_amy", "Amy", "Sonic Adventure 2 (Europe)", "dreamcast", "5a20000000000001"))
    result = C.plan(DOA2, chars, "Sonic Adventure 2,mario", mapping="alternate", seed="titles")
    seq = sequences(result)
    assert len(set(seq)) == 2 and seq[0].startswith("titles:")
    assert all(seq[i] == (seq[0] if i % 2 == 0 else "mario") for i in range(len(seq)))


def test_overlap_belongs_to_first_component_and_no_donor_duplicates():
    chars = _chars()
    chars.append(_entry("sa1_tails", "Tails", "Sonic Adventure (USA)", "dreamcast", "5a10000000000000"))
    source = C.resolve_source("sa2,sonic,mario", chars)
    assert source["groups"]["sa2_sonic"] == "extractor:sa2"
    assert source["groups"]["sa1_tails"] == "sonic"
    assert len(source["entries"]) == len({m["slug"] for m in source["entries"]})
    result = C.plan(DOA2, chars, "sa2,sonic,mario", mapping="alternate", seed="overlap")
    assert sequences(result)[:6] == ["extractor:sa2", "sonic", "mario"] * 2


def test_subsumed_component_is_not_silently_omitted():
    chars = _chars()
    chars.append(_entry("sa1_tails", "Tails", "Sonic Adventure (USA)", "dreamcast", "5a10000000000000"))
    with pytest.raises(ValueError, match="source pools have no eligible donors.*extractor:sa2"):
        C.plan(DOA2, chars, "sonic,sa2,mario", mapping="alternate", seed="overlap")
    # Existing non-alternating union semantics remain valid.
    assert C.plan(DOA2, chars, "sonic,sa2,mario", mapping="random", seed="overlap")["status"] == "planned"


def test_identical_alias_components_coalesce_without_duplicate_slots():
    source = C.resolve_source("sa2,Sonic Adventure 2,mario", _chars())
    assert source["pool_order"] == ["extractor:sa2", "mario"]
    result = C.plan(DOA2, _chars(), "sa2,Sonic Adventure 2,mario", mapping="alternate", seed="alias")
    assert len(set(sequences(result))) == 2
    slots = [r["slot"] for r in result["assignments"]]
    assert len(slots) == len(set(slots))


def test_explicit_pool_order_survives_donor_list_order():
    donors = [_donor("m", "mario"), _donor("s", "sonic")]
    result = C.assign([_slot(str(i)) for i in range(5)], donors, "alternate", "order", pool_order=["sonic", "mario"])
    assert [r["character"] for r in result] == ["s", "m", "s", "m", "s"]


def test_invalid_source_none_is_rejected_without_metadata_mutation():
    chars = _chars() + [{"slug": "unknown", "source": None}]
    original = copy.deepcopy(chars)
    with pytest.raises(ValueError, match="source is empty"):
        C.resolve_source(None, chars)
    assert chars == original
    assert C.resolve_source("sonic,mario", chars)["entries"]


def test_each_pool_exhausts_distinct_names_each_cycle_with_uneven_variants():
    donors = [_donor("a1", "sonic"), _donor("a2", "sonic"), _donor("a3", "sonic"),
              _donor("b", "sonic"), _donor("c", "sonic"), _donor("m", "mario")]
    for d in donors: d["name_key"] = "a" if d["slug"].startswith("a") else d["slug"]
    original = copy.deepcopy(donors)
    result = C.assign([_slot(str(i)) for i in range(18)], donors, "alternate", "variants")
    name = {d["slug"]: d["name_key"] for d in donors}
    sonic = [name[r["character"]] for r in result[::2]]
    assert all(set(sonic[i:i+3]) == {"a", "b", "c"} for i in range(0, 9, 3))
    assert donors == original
    assert {r["character"] for r in result if r["character"].startswith("a")} == {"a1", "a2", "a3"}
    assert result == C.assign([_slot(str(i)) for i in range(18)], donors, "alternate", "variants")


def test_pool_losing_all_donors_to_quality_gate_is_not_silently_omitted():
    chars = _chars()
    for row in chars:
        if row.get("donor_group") == "mario":
            row["rig"] = {}
    with pytest.raises(ValueError, match="source pools have no eligible donors.*mario"):
        C.plan(DOA2, chars, "sonic,mario", mapping="Alternate", seed="gate")


def test_doa3_target_alternates_pools_over_its_fighter_families():
    # DOA3 has a routed cast writer (gbox.doa3_cast, one disc build for every fighter family): the pools alternate
    # over the fighter slots, and Tengu (no costume files) is reported, never dealt
    game = {"game_id": "b8edf7040116f3aa", "title": "Dead or Alive 3 (USA)", "platform": "xbox"}
    result = C.plan(game, _chars(), "sonic,mario", mapping="alternate", seed="unfinished")
    assert result["status"] == "planned" and result["writer"] == "gbox.doa3_cast" and result["strategy"] == "pairs"
    assert len(result["assignments"]) == 19
    assert all(r["slot"].startswith("fighter:") for r in result["assignments"])
    assert "fighter:tengu" in {s["slot"] for s in result["skipped"]}
    seq = sequences(result)
    assert seq[:2] == ["sonic", "mario"] and abs(seq.count("sonic") - seq.count("mario")) <= 1

