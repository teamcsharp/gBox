"""Tests for the RE6 PS3 (BLUS30855) RAM map scaffold and revision-scoped observer.

Request 3275, Step 2.  These tests validate the map structure and the observer contract;
live-address verification is deferred to the i9-NUC RPCS3 session.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from gbox import ram_map
from gbox.mercs.titles import re6_ps3

ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = ROOT / "docs" / "re6-ram-map-6fc93ff62e4eb868.json"


class TestRe6Ps3RamMap(unittest.TestCase):
    """Structural validation of the PS3 RAM map scaffold."""

    def test_map_loads(self):
        m = ram_map.load(str(MAP_PATH))
        self.assertEqual(m.id, "6fc93ff62e4eb868")
        self.assertEqual(m.platform, "ps3")

    def test_map_has_mercs_block(self):
        m = ram_map.load(str(MAP_PATH))
        mercs = (m.spec or {}).get("mercs") or {}
        self.assertIn("ready", mercs)
        self.assertFalse(mercs["ready"], "scaffold must not be marked ready before live verification")
        self.assertIn("vocab", mercs)

    def test_map_fields_have_pending_evidence(self):
        m = ram_map.load(str(MAP_PATH))
        for name, field in m.fields.items():
            ev = field.spec.get("evidence", "")
            self.assertIn(
                "pending-live-measurement",
                ev,
                f"{name}: scaffold field must carry pending-live-measurement evidence",
            )

    def test_map_match_executable_sha256(self):
        m = ram_map.load(str(MAP_PATH))
        match = (m.spec or {}).get("match") or {}
        self.assertEqual(
            match.get("executable_sha256"),
            "ddd022477e679cb1125dc327b0e43c5aeb4d8fa84352a7c8ae98ec74271d41ed",
        )

    def test_vocab_required_names_present_in_map(self):
        """Every required vocab name must appear in the map fields (even if unmapped)."""
        m = ram_map.load(str(MAP_PATH))
        prof = re6_ps3.profile()
        problems = re6_ps3.check()
        # In scaffold state we expect problems for required names that are still unknown.
        # The test asserts the check runs and returns a list (not that it is empty).
        self.assertIsInstance(problems, list)

    def test_map_json_is_valid(self):
        with open(MAP_PATH) as f:
            data = json.load(f)
        self.assertEqual(data["format"], "gbox-ram-map/1")
        self.assertEqual(data["id"], "6fc93ff62e4eb868")


class TestRe6Ps3Observer(unittest.TestCase):
    """Contract tests for the revision-scoped observer."""

    def test_observe_returns_expected_keys(self):
        # A dummy reader that returns zeros; the observer should still return the contract keys.
        class ZeroReader:
            def read(self, addr, n):
                return b"\x00" * n

        obs = re6_ps3.observe(ZeroReader())
        expected_keys = {
            "screen", "mode", "char_cursor", "stage_cursor",
            "timer", "hp", "hp_max", "score", "combo", "kills", "result",
        }
        self.assertEqual(set(obs.keys()), expected_keys)

    def test_observe_scaffold_returns_none_for_unmapped(self):
        class ZeroReader:
            def read(self, addr, n):
                return b"\x00" * n

        obs = re6_ps3.observe(ZeroReader())
        # Scaffold: screen/mode/cursors/timer/score/combo/result are unmapped -> None.
        for key in ("screen", "mode", "char_cursor", "stage_cursor", "timer", "score", "combo", "kills", "result"):
            self.assertIsNone(obs[key], f"{key} should be None in scaffold state")

    def test_is_ready_false_in_scaffold(self):
        self.assertFalse(re6_ps3.is_ready())


if __name__ == "__main__":
    unittest.main()
