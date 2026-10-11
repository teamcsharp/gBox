"""#1296: this PC's worker panel explains why it is offline and reconnects it (runs test_worker_reconnect.cjs)."""
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_worker_reconnect_cjs():
    r = subprocess.run(["node", "--test", str(HERE / "test_worker_reconnect.cjs")],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
