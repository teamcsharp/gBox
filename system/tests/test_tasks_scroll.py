"""#1289: run the desktop Tasks-panel scroll checks (tests/test_tasks_scroll.cjs) under pytest."""
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
@pytest.mark.parametrize("script", ["test_tasks_scroll.cjs", "test_desktop_polling.cjs"])
def test_desktop_tasks_panel(script):
    r = subprocess.run(["node", "--test", str(HERE / script)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
