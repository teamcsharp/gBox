"""Regression: #8929 - launch rejection while a connected stream/PiP view is still watching.

Jobs ee743d4f5e3c4573 (launch_game) and 72ccb3f247ad48d9 (session_reset) on
i9-NUC (worker 25f735de070b4aab) were both rejected with the exact string

    "Watching Resident Evil 4 in a connected stream or PiP. Close that view
     before loading another game on this PC."

That wording comes from operator_guard.watching_reason(). It matched no class
in launch_failures.CLASSES, so the failure landed in an opaque ``unknown:<sha1>``
bucket with no remedy guidance. The fix adds a ``stream_pip_watched`` class whose
diagnosis says the connected stream/PiP view must be closed by the operator, or
the watch lease must expire, before another game can load on that PC.

Pinned here:
  1. the exact rejection string from the live jobs classifies as ``stream_pip_watched``;
  2. the operator_guard source still emits that exact wording (guard/classifier tie);
  3. a multi-title variant classifies the same way (regex captures the title list);
  4. no other class is affected (content_timeout still matches, unrelated errors
     still fall through to ``unknown``);
  5. the class carries remedy ``none`` - no automatic relaunch while the
     operator's view is live (protects the operator's gameplay).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]  # .../339fbb42d5bb4aeb/system
sys.path.insert(0, str(_REPO))

import gbox  # noqa: E402

# Ensure we exercise the checkout, not a divergent site-packages copy.
_chk = Path(gbox.__file__).resolve().parent
if _chk != _REPO / "gbox":
    for name in ("launch_failures.py", "operator_guard.py"):
        a = (_chk / name).read_bytes()
        b = (_REPO / "gbox" / name).read_bytes()
        assert a == b, f"{name} differs between installed gbox and the checkout under test"

from gbox import launch_failures, operator_guard  # noqa: E402

EXACT_REJECTION = ("Watching Resident Evil 4 in a connected stream or PiP. "
                   "Close that view before loading another game on this PC.")
MULTI_TITLE_REJECTION = ("Watching Resident Evil 4, Resident Evil 5 in a connected stream or PiP. "
                         "Close that view before loading another game on this PC.")


class TestStreamPipWatchedClassification(unittest.TestCase):
    """#8929 - stream/PiP watch guard rejection must be classified, not unknown."""

    def test_exact_rejection_string_is_classified(self):
        c = launch_failures.classify(EXACT_REJECTION, adapter="re4")
        self.assertEqual(c["cls"], "stream_pip_watched")
        self.assertEqual(c["remedy"], "none")
        self.assertEqual(c["detail"].get("titles"), "Resident Evil 4")
        self.assertIn("closed by the operator", c["diagnosis"])
        self.assertIn("watch lease", c["diagnosis"])
        self.assertFalse(c["cls"].startswith("unknown"))

    def test_guard_source_still_emits_classified_wording(self):
        """Guard/classifier tie: the wording the guard emits is what we classify."""
        og_src = Path(operator_guard.__file__).read_text()
        self.assertIn("Watching", og_src)
        self.assertIn("in a connected stream or PiP", og_src)
        self.assertIn("Close that view", og_src)
        self.assertIn("before loading another game on this PC", og_src)

    def test_multi_title_variant_classifies(self):
        c = launch_failures.classify(MULTI_TITLE_REJECTION)
        self.assertEqual(c["cls"], "stream_pip_watched")
        self.assertEqual(c["detail"].get("titles"), "Resident Evil 4, Resident Evil 5")

    def test_other_classes_unaffected(self):
        self.assertEqual(launch_failures.classify(
            "Emulator started but content not running after 90 s (still on the loading screen)")["cls"],
            "content_timeout")
        self.assertTrue(launch_failures.classify("totally unrelated boom")["cls"].startswith("unknown:"))

    def test_no_automatic_remedy(self):
        """While the operator's view is live, no auto relaunch may be scheduled."""
        c = launch_failures.classify(EXACT_REJECTION, adapter="re4")
        self.assertEqual(c["remedy"], "none")


if __name__ == "__main__":
    unittest.main(verbosity=2)
