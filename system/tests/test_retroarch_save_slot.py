"""Focused tests for the RetroArch saved-slot fix (report #1106).

The defect: save_state(slot=91) returned {"slot": 91} while RetroArch actually wrote
state89, because incremental STATE_SLOT_PLUS/MINUS commands drop at low frame rate.
The fix makes save_state/load_state report the slot the emulator ACTUALLY used, backed
by evidence (direct-command ack, emulator log line, and the written state file), and
raises instead of returning the requested number on faith.

These tests drive a RetroArchAdapter whose UDP cmd is faked and whose log/state files
live in a tmp dir, so they exercise the real slot-selection code without an emulator.
"""
import time

import pytest

from gbox import adapters
from gbox.config import Config, HOST_OS, EmulatorConfig


def make_adapter(tmp_path, stem="mygame"):
    cfg = Config(runtime_dirs={HOST_OS: str(tmp_path)})
    ad = adapters.RetroArchAdapter(EmulatorConfig(adapter="retroarch", executable="x", core="y"),
                                   config=cfg)
    ad.state_stem = stem
    ad.log_path = tmp_path / "retroarch.log"
    (tmp_path / "states").mkdir(exist_ok=True)
    return ad


def state_file(tmp_path, stem, slot):
    return tmp_path / "states" / f"{stem}.state{slot}"


def append_log(ad, line):
    with open(ad.log_path, "a") as fh:
        fh.write(line + "\n")


def test_slot_files_prefers_exact_stem(tmp_path):
    ad = make_adapter(tmp_path, stem="mygame")
    states = tmp_path / "states"
    (states / "mygame.state91").write_bytes(b"mine")
    (states / "othergame.state91").write_bytes(b"theirs")
    # the exact content match must win over another game's slot-91 file
    assert [f.name for f in ad._slot_files(91)] == ["mygame.state91"]


def test_log_slot_parses_and_rejects_failure(tmp_path):
    ad = make_adapter(tmp_path)
    append_log(ad, 'save task COMPLETED for slot 0, path "mygame.state89" (1234 bytes).')
    assert ad._log_slot(0, "sav") == 89
    # a failure line must never count as evidence
    append_log(ad, 'failed to load state "mygame.state5"')
    assert ad._log_slot(0, "load") is None


def test_save_state_direct_ack_reports_actual_slot_verified(tmp_path, monkeypatch):
    ad = make_adapter(tmp_path)
    ad._direct_known = True                                  # skip the probe

    def fake_cmd(text, reply=False, timeout=2.0):
        parts = text.split()
        if parts[0] == "SAVE_STATE_SLOT":
            slot = int(parts[1])
            state_file(tmp_path, "mygame", slot).write_bytes(b"state-bytes")
            append_log(ad, f'save task COMPLETED for slot {slot}, path "mygame.state{slot}" (11 bytes).')
            return f"SAVE_STATE_SLOT {slot}" if reply else None
        return None

    monkeypatch.setattr(ad, "cmd", fake_cmd)
    res = ad.save_state(91)
    assert res["slot"] == 91 and res["requested"] == 91 and res["verified"] is True
    assert state_file(tmp_path, "mygame", 91).read_bytes() == b"state-bytes"


def test_save_state_legacy_reports_log_slot_not_requested(tmp_path, monkeypatch):
    """The core defect: requested 91, emulator actually wrote 89. The result must say 89."""
    ad = make_adapter(tmp_path)
    ad.slot = 0
    ad._direct_known = False                                # legacy build: no direct slot commands

    def fake_cmd(text, reply=False, timeout=2.0):
        parts = text.split()
        if parts[0] == "SAVE_STATE":
            # emulator stepped wrong (dropped steps) and really wrote slot 89
            state_file(tmp_path, "mygame", 89).write_bytes(b"actual-89")
            append_log(ad, 'save task COMPLETED for slot 0, path "mygame.state89" (9 bytes).')
        return None

    monkeypatch.setattr(ad, "cmd", fake_cmd)
    res = ad.save_state(91)
    assert res["slot"] == 89 and res["requested"] == 91 and res["verified"] is True
    assert ad.slot == 89                                     # adapter cache follows reality


def test_save_state_no_evidence_raises(tmp_path, monkeypatch):
    ad = make_adapter(tmp_path)
    ad._direct_known = False
    monkeypatch.setattr(ad, "cmd", lambda text, reply=False, timeout=2.0: None)
    monkeypatch.setattr(ad, "_wait_log_slot", lambda pos, verb, timeout=1.5: None)
    monkeypatch.setattr(ad, "_await_write", lambda slot, pos, before, timeout=None:
                        {"slot": slot, "verified": False, "detail": "nothing"})
    with pytest.raises(RuntimeError, match="no evidence of a save"):
        ad.save_state(91)


def test_save_state_unverified_write_raises(tmp_path, monkeypatch):
    ad = make_adapter(tmp_path)
    ad._direct_known = True

    def fake_cmd(text, reply=False, timeout=2.0):
        parts = text.split()
        if parts[0] == "SAVE_STATE_SLOT":
            return f"SAVE_STATE_SLOT {parts[1]}" if reply else None   # acks but never writes disk
        return None

    monkeypatch.setattr(ad, "cmd", fake_cmd)
    ad._save_timeout = 0.1                                 # keep the test fast
    with pytest.raises(RuntimeError, match="no changed state file"):
        ad.save_state(91)


def test_load_state_direct_ack_reports_actual_slot(tmp_path, monkeypatch):
    ad = make_adapter(tmp_path)
    ad._direct_known = True

    def fake_cmd(text, reply=False, timeout=2.0):
        parts = text.split()
        if parts[0] == "LOAD_STATE_SLOT":
            return f"LOAD_STATE_SLOT {parts[1]}" if reply else None
        return None

    monkeypatch.setattr(ad, "cmd", fake_cmd)
    res = ad.load_state(91)
    assert res["slot"] == 91 and res["verified"] is True


def test_direct_slots_probe_falls_back_when_no_ack(tmp_path, monkeypatch):
    ad = make_adapter(tmp_path)
    monkeypatch.setattr(ad, "cmd", lambda text, reply=False, timeout=2.0: None)
    assert ad._direct_slots() is False                      # no ack -> legacy build


def test_save_state_reports_probe_and_verify_flow(tmp_path, monkeypatch):
    """End-to-end: probe discovers direct slots, save acks and writes, result is verified."""
    ad = make_adapter(tmp_path)
    acked = {}

    def fake_cmd(text, reply=False, timeout=2.0):
        parts = text.split()
        if parts[0] == "LOAD_STATE_SLOT" and reply:
            return f"LOAD_STATE_SLOT {parts[1]}"            # probe ack
        if parts[0] == "SAVE_STATE_SLOT":
            slot = int(parts[1])
            acked[slot] = True
            state_file(tmp_path, "mygame", slot).write_bytes(b"x")
            append_log(ad, f'save task COMPLETED for slot {slot}, path "mygame.state{slot}" (1 bytes).')
            return f"SAVE_STATE_SLOT {slot}" if reply else None
        return None

    monkeypatch.setattr(ad, "cmd", fake_cmd)
    res = ad.save_state(91)
    assert res["slot"] == 91 and res["verified"] is True
    assert ad._direct_known is True
    assert 91 in acked
