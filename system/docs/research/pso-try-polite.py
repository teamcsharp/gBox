"""Try the polite input path: post the key messages straight to the window, no foreground needed.

The strict path refuses because a Windows shell window owns the foreground. `polite=True` posts messages to the target window instead of
relying on focus, which is the documented way around exactly this. The test presses START and checks whether the title menu appears.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_game as CG
import game_input as G
from gbox import adapters


def screenshot_bytes():
    CG.main()
    newest = sorted(Path(r"D:\gBox\pso-ds\demo").glob("*-game.png"), key=lambda p: p.stat().st_mtime)[-1]
    return newest


print("emulator pid:", G._pid())
G.raise_window()
time.sleep(0.3)
try:
    result = adapters.win_send_keys(G._pid(), [{"key": "start", "down": True},
                                              {"key": "start", "down": False}], polite=True)
    print("polite send returned:", result)
except Exception as exc:                                                # noqa: BLE001
    print("polite send failed:", type(exc).__name__, str(exc)[:160])
time.sleep(2.2)
print("capture:", screenshot_bytes())

time.sleep(0.5)
try:
    result = adapters.win_send_keys(G._pid(), [{"key": "ddown", "down": True},
                                              {"key": "ddown", "down": False}], polite=True)
    print("second polite send:", result)
except Exception as exc:                                                # noqa: BLE001
    print("second polite send failed:", type(exc).__name__, str(exc)[:160])
time.sleep(1.2)
print("capture:", screenshot_bytes())
