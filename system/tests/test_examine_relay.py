"""#971 stage 2: the Examine 3D panel's capture-session (relay) handling (runs test_examine_relay.cjs)."""
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_examine_relay_cjs():
    r = subprocess.run(["node", "--test", str(HERE / "test_examine_relay.cjs")],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
