"""#1385: the cast plan's replace ticks, donor chips and seeded "Deal ticked donors" (runs test_cast_swap_menu.cjs)."""
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_cast_swap_menu_cjs():
    r = subprocess.run(["node", "--test", str(HERE / "test_cast_swap_menu.cjs")],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
