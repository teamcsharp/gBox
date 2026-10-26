"""Focused acceptance tests for the Puyo Puyo Tetris save reader + overlay (#2221).

A synthetic-but-honest Switch save container is constructed here so the
structural reader and the revision-gated overlay can be exercised on this
machine without the remote executable. Every test verifies a concrete guard.
"""
from __future__ import annotations

import copy

import pytest

from gbox import puyotetris_save as S
from gbox.puyotetris_unlock import PROVEN_REVISIONS  # type: ignore
from gbox import puyotetris_unlock as P

REV = "b" * 64
TITLE_ID = S.TITLE_ID


def _make_save(flag_word: int = 0) -> bytes:
    """Build a structurally valid base-save container (honest synthetic fixture)."""
    data = bytearray(S.INTEGRITY_OFFSET + 4)
    data[S.TITLE_ID_OFFSET:S.TITLE_ID_OFFSET + 16] = TITLE_ID.encode("ascii")
    data[S.SAVE_KIND_OFFSET:S.SAVE_KIND_OFFSET + 4] = S.KIND_BASE_SAVE.to_bytes(4, "big")
    data[S.FLAG_WORD_OFFSET:S.FLAG_WORD_OFFSET + 4] = flag_word.to_bytes(4, "big")
    data[S.INTEGRITY_OFFSET:S.INTEGRITY_OFFSET + 4] = S._sum_check(bytes(data)).to_bytes(4, "big")
    return bytes(data)


def teardown_function(_):
    PROVEN_REVISIONS.clear()


# --- structural reader ----------------------------------------------------

def test_inspect_valid_save_reports_layout_and_no_unlock():
    rep = S.inspect_save(_make_save(flag_word=0x13))
    assert rep["title_id"] == S.TITLE_ID
    assert rep["save_kind"] == S.KIND_BASE_SAVE
    assert rep["integrity"]["valid"] is True
    assert rep["flag_word_hex"] == "00000013"
    assert rep["gameplay_verified"] is False
    assert rep["complete_unlock_profile"] is False
    assert rep["unlock_claims"] == []


def test_inspect_rejects_wrong_title_id():
    data = bytearray(_make_save())
    data[S.TITLE_ID_OFFSET:S.TITLE_ID_OFFSET + 16] = "ffffffffffffffff".encode("ascii")
    with pytest.raises(ValueError, match="title id"):
        S.inspect_save(bytes(data))


def test_inspect_rejects_non_base_save_kind():
    data = bytearray(_make_save())
    data[S.SAVE_KIND_OFFSET:S.SAVE_KIND_OFFSET + 4] = (99).to_bytes(4, "big")
    with pytest.raises(ValueError, match="kind"):
        S.inspect_save(bytes(data))


def test_inspect_rejects_small_container():
    with pytest.raises(ValueError, match="smaller than expected"):
        S.inspect_save(b"\x00" * 32)


# --- permanent write gate -------------------------------------------------

def test_overlay_refuses_unproven_revision():
    with pytest.raises(PermissionError, match="no REA/Ghidra"):
        S.apply_overlay(_make_save(), REV, {"all_puyos": True})


def test_overlay_refuses_malformed_hash():
    PROVEN_REVISIONS[REV] = {"artifact": "art1"}
    with pytest.raises(PermissionError, match="64-char hex"):
        S.apply_overlay(_make_save(), "zz", {"all_puyos": True})


# --- accepted monotonic write on a proven revision ------------------------

def test_overlay_sets_flags_and_recomputes_integrity():
    PROVEN_REVISIONS[REV] = {"artifact": "art1"}
    save = _make_save(flag_word=0x00)
    res = S.apply_overlay(save, REV.upper(), {"all_puyos": True, "hidden_modes": True})
    assert res["applied"] is True
    assert res["updated_flag"] == "00000003"
    # integrity word must now validate against the updated bytes
    rep = S.inspect_save(res["updated"])
    assert rep["integrity"]["valid"] is True
    assert rep["flag_word_hex"] == "00000003"
    # original preserved + rollback handle is a sha256 of the original bytes
    assert res["original"] == save
    import hashlib
    assert res["rollback"]["restore_bytes"] == save
    assert res["rollback"]["handle"] == hashlib.sha256(save).hexdigest()


def test_overlay_is_monotonic_and_noop_when_already_set():
    PROVEN_REVISIONS[REV] = {"artifact": "art1"}
    save = _make_save(flag_word=S.FLAG_BITS["all_puyos"])  # already set
    res = S.apply_overlay(save, REV, {"all_puyos": True})
    assert res["applied"] is False
    assert res["updated"] == save


def test_overlay_never_clears_existing_bits():
    PROVEN_REVISIONS[REV] = {"artifact": "art1"}
    save = _make_save(flag_word=S.FLAG_BITS["all_puyos"] | S.FLAG_BITS["costumes"])
    # requesting only costumes must NOT clear the already-set all_puyos bit
    res = S.apply_overlay(save, REV, {"costumes": True})
    assert res["applied"] is False
    assert int(res["updated_flag"], 16) == (S.FLAG_BITS["all_puyos"] | S.FLAG_BITS["costumes"])


def test_overlay_rejects_unknown_flag_name():
    PROVEN_REVISIONS[REV] = {"artifact": "art1"}
    with pytest.raises(ValueError, match="unknown flag"):
        S.apply_overlay(_make_save(), REV, {"bogus": True})


def test_overlay_rejects_empty_flag_selection():
    PROVEN_REVISIONS[REV] = {"artifact": "art1"}
    with pytest.raises(ValueError, match="no flags"):
        S.apply_overlay(_make_save(), REV, {})


def test_profile_exposes_gate_and_flag_bits():
    prof = S.profile()
    assert prof["save_reader_available"] is True
    assert prof["save_overlay_gated"] is True
    assert prof["save_title_id"] == S.TITLE_ID
    assert "0x00000001" not in prof["flag_bits"]  # values are 8-hex, not 0x-prefixed
    assert prof["flag_bits"]["all_puyos"] == "00000001"
