"""Focused tests for the SCDA (GameCube, gwye41) unlock-gate discovery helpers."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gbox.scda_unlock_gate import (  # noqa: E402
    ARTIFACT_DIR,
    BUILD,
    DISC_ID,
    EXPECTED_DIGESTS,
    GATE_TOKENS,
    gate_report,
    scan_gate_tokens,
    sha256_file,
    verify_artifacts,
)

HAVE_ARTIFACTS = (ARTIFACT_DIR / "main.dol").is_file()


def test_gate_vocabulary_is_pinned():
    assert GATE_TOKENS == ("UnlockCondition", "UnLocked", "BashUnLocked")
    assert BUILD == "gwye41"
    assert DISC_ID == "GCEX41"


def test_scan_reports_all_tokens_even_when_absent():
    found = scan_gate_tokens(b"nothing to see here")
    assert set(found) == set(GATE_TOKENS)
    assert all(offsets == [] for offsets in found.values())


def test_scan_finds_each_token_at_its_true_offset():
    # "UnLocked" is a suffix of "BashUnLocked", so both hits must be reported.
    blob = b"\x00" + b"UnlockCondition" + b"\x00" + b"UnLocked" + b"\x00" + b"BashUnLocked"
    found = scan_gate_tokens(blob)
    assert found["UnlockCondition"] == [1]
    assert found["UnLocked"] == [17, 30]
    assert found["BashUnLocked"] == [26]


def test_scan_ignores_condition_text_that_is_not_a_gate():
    found = scan_gate_tokens(b" CONDITION `%s`")
    assert all(offsets == [] for offsets in found.values())


def test_verify_flags_a_digest_mismatch(tmp_path):
    (tmp_path / "main.dol").write_bytes(b"payload")
    report = verify_artifacts(tmp_path, expected={"main.dol": "0" * 64})
    entry = report["main.dol"]
    assert entry["present"] is True
    assert entry["matches"] is False
    assert entry["sha256"] == hashlib.sha256(b"payload").hexdigest()


def test_verify_accepts_a_correct_digest(tmp_path):
    (tmp_path / "main.dol").write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()
    report = verify_artifacts(tmp_path, expected={"main.dol": digest})
    assert report["main.dol"]["matches"] is True


def test_sha256_file_matches_hashlib(tmp_path):
    path = tmp_path / "blob.bin"
    path.write_bytes(b"abc" * 5000)
    assert sha256_file(path) == hashlib.sha256(b"abc" * 5000).hexdigest()


@pytest.mark.skipif(not HAVE_ARTIFACTS, reason="owned build artifacts not present")
def test_owned_artifacts_match_the_pinned_digests():
    report = verify_artifacts()
    for name, entry in report.items():
        assert entry["present"], name
        assert entry["matches"], name
    assert set(report) == set(EXPECTED_DIGESTS)


@pytest.mark.skipif(not HAVE_ARTIFACTS, reason="owned build artifacts not present")
def test_owned_dol_carries_every_gate_token():
    blob = (ARTIFACT_DIR / "main.dol").read_bytes()
    found = scan_gate_tokens(blob)
    for token in GATE_TOKENS:
        assert found[token], token
    assert found["UnlockCondition"] == sorted(found["UnlockCondition"])


@pytest.mark.skipif(not HAVE_ARTIFACTS, reason="owned build artifacts not present")
def test_gate_report_is_internally_consistent():
    report = gate_report()
    assert report["game_id"] == "3ee1e44d0f1ebf5e"
    assert report["all_artifacts_match"] is True
    assert all(report["gate_tokens_present"].values())
