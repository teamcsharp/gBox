"""#1982: the report-issue flow anchors to the last-closed game (runs test_last_closed.cjs)."""
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_last_closed_cjs():
    r = subprocess.run(["node", "--test", str(HERE / "test_last_closed.cjs")],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
