"""#1293: the launch loader explains a queue wait on an offline/busy worker (runs test_launch_wait.cjs)."""
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_launch_wait_cjs():
    r = subprocess.run(["node", "--test", str(HERE / "test_launch_wait.cjs")],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
