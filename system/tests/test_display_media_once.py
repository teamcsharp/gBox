"""#1118: the desktop display-media handler answers Electron's one-time callback exactly once
(runs test_display_media_once.cjs)."""
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_display_media_once_cjs():
    r = subprocess.run(["node", "--test", str(HERE / "test_display_media_once.cjs")],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_desktop_main_still_parses():
    r = subprocess.run(["node", "--check", str(HERE.parent / "clients" / "desktop" / "main.js")],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
