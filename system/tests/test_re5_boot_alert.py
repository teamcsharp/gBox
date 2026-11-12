"""Pin the RE5 boot-path alert press (request cc70f6711fa04538).

LIVE 2026-11-11 15:50 (session 44fdcbbf798f4d5b-61dad841789f4452, RE5
Switch): the block hung on the "FEATURES / View episodes of the campaign
separately" prompt, telemetry screen='alert' (an unnamed uIdAlert00
dialog), rounds=0. The Navigator presses STEPS[where], so an unnamed
alert must be dismissed with 'b' (the Switch dismiss key, matching
alert_leaderboard and the RE6 precedent STEPS['alert']='b'), while the
named save/load alerts keep 'a'.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox.mercs.titles import re5_switch


def _aid(k):
    return k if isinstance(k, int) else (k[0] if isinstance(k, (bytes, bytearray)) else k)


def test_re5_unnamed_alert_press_is_b():
    assert re5_switch.STEPS["alert"] == "b"


def test_re5_named_alerts_unchanged():
    alerts = {_aid(k): v for k, v in re5_switch.ALERTS.items()}
    assert alerts[0x33] == "alert_leaderboard"
    assert re5_switch.STEPS["alert_leaderboard"] == "b"
    assert re5_switch.STEPS["alert_ok"] == "a"


def test_re5_boot_and_cursor_maps_intact():
    assert re5_switch.BOOT_KEY == "a"
    assert "extra_content" in re5_switch.CURSORED
