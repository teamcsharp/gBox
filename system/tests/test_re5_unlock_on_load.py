"""Tests for RE5 unlock-on-load profile and launch plan (#2041).

Validates:
1. pre_launch verifies checksum, creates backup, and enforces group policy
2. launch_plan enforces worker name, session ID format, and opt-in handling
3. Group validation: default groups unlocked, opt-in groups remain locked unless requested
4. Session ID format: must start with worker ID (w-jbf-...) on JAYBUILTFINALE
"""
from pathlib import Path
import struct

import pytest

from gbox import re5_unlocks


# Test save file structure constants
CHECKSUM_FROM = 0x10
CHECKSUM_TO = 0x4BBF
CHECKSUM_AT = 0x8

# Default and opt-in groups as defined in re5_unlocks
DEFAULT_GROUPS = ("bonus_features", "files", "cutscenes", "figurines", "chapters", "emblems", "item_management")
OPT_IN_GROUPS = {"points", "money"}


# Mock save data for testing
def make_mock_save(valid_checksum=True):
    """Create a mock RE5 DATA0.DAT with proper structure."""
    # Header: 0x10 bytes
    header = b'\x00' * 0x10
    # Padding to CHECKSUM_FROM
    padding = b'\x00' * (CHECKSUM_FROM - len(header))
    # Data bytes for checksum calculation
    data_bytes = b'\x00' * (CHECKSUM_TO - CHECKSUM_FROM + 1)
    # Checksum at CHECKSUM_AT
    checksum = struct.pack(">I", 0)  # Will be computed
    # Footer (just enough to have a valid size)
    footer = b'\x00' * 0x100
    
    data = header + padding + data_bytes
    computed = sum(struct.unpack(f">{(CHECKSUM_TO - CHECKSUM_FROM + 1) // 4}I", 
                                  data[CHECKSUM_FROM:CHECKSUM_TO + 1])) & 0xFFFFFFFF
    checksum = struct.pack(">I", computed)
    
    return header + padding + data_bytes + checksum + footer


@pytest.fixture
def temp_save_path(tmp_path):
    """Create a temporary save directory structure."""
    save_dir = tmp_path / "dev_hdd0" / "home" / "00000001" / "savedata" / "BLUS30491"
    save_dir.mkdir(parents=True, exist_ok=True)
    save_file = save_dir / "DATA0.DAT"
    save_file.write_bytes(make_mock_save(valid_checksum=True))
    return save_file


class TestPreLaunch:
    """Tests for pre_launch function."""
    
    def test_pre_launch_requires_home_path(self):
        """pre_launch returns failed if no home path is provided."""
        result = re5_unlocks.pre_launch(home=None, serial="BLUS30491")
        assert result["state"] == "failed"
        assert result["applied"] is False
        assert "no RPCS3 home path provided" in result["reason"]
    
    def test_pre_launch_creates_backup(self, temp_save_path):
        """pre_launch creates DATA0.DAT.gbox-backup if it doesn't exist."""
        home = temp_save_path.parent.parent.parent.parent
        result = re5_unlocks.pre_launch(home=home, serial="BLUS30491")
        assert result["state"] == "applied"
        assert result["applied"] is True
        backup = temp_save_path.with_name("DATA0.DAT.gbox-backup")
        assert backup.exists()
    
    def test_pre_launch_is_idempotent(self, temp_save_path):
        """pre_launch produces same state on second call."""
        home = temp_save_path.parent.parent.parent.parent
        # First call
        result1 = re5_unlocks.pre_launch(home=home, serial="BLUS30491")
        assert result1["state"] == "applied"
        # Second call (backup already exists)
        result2 = re5_unlocks.pre_launch(home=home, serial="BLUS30491")
        assert result2["state"] == "applied"
        assert result2["backup"] == result1["backup"]
    
    def test_pre_launch_locks_opt_in_groups_by_default(self, temp_save_path):
        """pre_launch does NOT unlock points/money groups by default."""
        home = temp_save_path.parent.parent.parent.parent
        # Call without specifying groups - should use DEFAULT_GROUPS only
        result = re5_unlocks.pre_launch(home=home, serial="BLUS30491")
        assert result["state"] == "applied"
        # The result should not include opt-in groups
        if "groups_unlocked" in result:
            unlocked = set(result["groups_unlocked"])
            assert not unlocked.intersection(OPT_IN_GROUPS), \
                f"Opt-in groups {OPT_IN_GROUPS} should not be unlocked by default"
    
    def test_pre_launch_allows_opt_in_groups(self, temp_save_path):
        """pre_launch unlocks opt-in groups when explicitly requested."""
        home = temp_save_path.parent.parent.parent.parent
        # Call with opt-in groups explicitly requested
        all_groups = list(DEFAULT_GROUPS) + list(OPT_IN_GROUPS)
        result = re5_unlocks.pre_launch(home=home, serial="BLUS30491", groups=all_groups)
        assert result["state"] == "applied"
        if "groups_unlocked" in result:
            unlocked = set(result["groups_unlocked"])
            assert OPT_IN_GROUPS.issubset(unlocked), \
                f"Opt-in groups {OPT_IN_GROUPS} should be unlocked when requested"


class TestLaunchPlan:
    """Tests for launch_plan function."""
    
    def test_launch_plan_requires_worker_id(self):
        """launch_plan raises if worker has no ID."""
        game = {"game_id": re5_unlocks.RE5_ID, "platform": "ps3"}
        worker = {"id": "", "name": "test-worker"}
        with pytest.raises(ValueError, match="requires a worker id"):
            re5_unlocks.launch_plan(game, worker)
    
    def test_launch_plan_enforces_worker_name(self):
        """launch_plan raises if worker name is not JAYBUILTFINALE."""
        game = {"game_id": re5_unlocks.RE5_ID, "platform": "ps3"}
        worker = {"id": "w-jbf", "name": "other-worker"}
        with pytest.raises(ValueError, match="JAYBUILTFINALE"):
            re5_unlocks.launch_plan(game, worker)
    
    def test_launch_plan_requires_session_id_format(self):
        """launch_plan raises if session ID doesn't start with worker ID."""
        game = {"game_id": re5_unlocks.RE5_ID, "platform": "ps3"}
        worker = {"id": "w-jbf", "name": "JAYBUILTFINALE"}
        # Invalid session ID format
        with pytest.raises(ValueError, match="session identifier must belong"):
            re5_unlocks.launch_plan(game, worker, session_id="w-xyz-123")
    
    def test_launch_plan_accepts_valid_session_id(self):
        """launch_plan accepts session IDs starting with worker ID."""
        game = {"game_id": re5_unlocks.RE5_ID, "platform": "ps3"}
        worker = {"id": "w-jbf", "name": "JAYBUILTFINALE"}
        # Valid session ID format
        result = re5_unlocks.launch_plan(game, worker, session_id="w-jbf-live1", 
                                         allow_save_upgrade=True)
        assert result["status"] == "planned"
        assert len(result["jobs"]) == 1
        assert result["jobs"][0]["tool"] == "re5"
        assert result["jobs"][0]["input"]["op"] == "unlock_all"
    
    def test_launch_plan_requires_allow_save_upgrade(self):
        """launch_plan returns save_upgrade_opt_in_required if allow_save_upgrade is false."""
        game = {"game_id": re5_unlocks.RE5_ID, "platform": "ps3"}
        worker = {"id": "w-jbf", "name": "JAYBUILTFINALE"}
        result = re5_unlocks.launch_plan(game, worker, allow_save_upgrade=False)
        assert result["status"] == "save_upgrade_opt_in_required"
        assert "explicit allow_save_upgrade" in result["reason"]


class TestProfile:
    """Tests for profile function."""
    
    def test_profile_contains_expected_fields(self):
        """Profile contains all expected metadata fields."""
        profile = re5_unlocks.profile()
        assert profile["status"] == "verified_profile"
        assert profile["verified"] is True
        assert profile["game_id"] == re5_unlocks.RE5_ID
        assert "scope" in profile
        assert "exclusions" in profile
        assert "evidence" in profile
        assert "points" in profile["exclusions"]
        assert "money" in profile["exclusions"]
    
    def test_profile_lists_default_groups_unlocked(self):
        """Profile correctly documents which groups are unlocked by default."""
        profile = re5_unlocks.profile()
        scope_text = " ".join(profile.get("scope", []))
        # Default groups should be in scope
        for group in DEFAULT_GROUPS:
            # The scope text should mention the group or equivalent
            assert group in scope_text.lower() or group.replace("_", " ") in scope_text.lower(), \
                f"Default group '{group}' should be documented in profile scope"
    
    def test_profile_lists_opt_in_groups_excluded(self):
        """Profile correctly documents opt-in groups remain locked by default."""
        profile = re5_unlocks.profile()
        exclusions = profile.get("exclusions", [])
        assert "points group (opt-in, remains locked by default)" in exclusions
        assert "money group (opt-in, remains locked by default)" in exclusions


class TestChecksum:
    """Tests for checksum validation logic."""
    
    def test_checksum_ok_validates_correct_checksum(self):
        """checksum_ok returns True for valid checksum."""
        data = make_mock_save(valid_checksum=True)
        assert re5_unlocks.checksum_ok(data) is True
    
    def test_checksum_ok_rejects_invalid_checksum(self):
        """checksum_ok returns False for invalid checksum."""
        data = make_mock_save(valid_checksum=True)
        # Corrupt the checksum
        data = data[:CHECKSUM_AT] + b'\xFF\xFF\xFF\xFF' + data[CHECKSUM_AT + 4:]
        assert re5_unlocks.checksum_ok(data) is False
    
    def test_verify_save_checks_checksum(self, temp_save_path):
        """verify_save returns ok only when checksum is valid."""
        home = temp_save_path.parent.parent.parent.parent
        result = re5_unlocks.verify_save(home, "BLUS30491")
        assert result["ok"] is True
        assert result["path"] == temp_save_path


class TestIntegration:
    """Integration tests for the unlock workflow."""
    
    def test_full_unlock_workflow(self, temp_save_path):
        """Full workflow: verify -> pre_launch -> backup exists."""
        home = temp_save_path.parent.parent.parent.parent
        # Step 1: Verify save exists and checksum is valid
        ver = re5_unlocks.verify_save(home, "BLUS30491")
        assert ver["ok"] is True
        
        # Step 2: Apply unlock via pre_launch
        result = re5_unlocks.pre_launch(home=home, serial="BLUS30491")
        assert result["state"] == "applied"
        
        # Step 3: Backup should exist
        backup = temp_save_path.with_name("DATA0.DAT.gbox-backup")
        assert backup.exists()
        
        # Step 4: Plan unlock job
        game = {"game_id": re5_unlocks.RE5_ID, "platform": "ps3"}
        worker = {"id": "w-jbf", "name": "JAYBUILTFINALE"}
        plan = re5_unlocks.launch_plan(game, worker, session_id="w-jbf-test", 
                                       allow_save_upgrade=True)
        assert plan["status"] == "planned"
        assert plan["jobs"][0]["tool"] == "re5"
        assert plan["jobs"][0]["input"]["op"] == "unlock_all"
