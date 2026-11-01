"""Isolated, persistent PSO buddy campaign launch and Dolphin input configuration."""
from __future__ import annotations

import json
import platform
import re
import threading
from pathlib import Path

SPEEDS = (1, 2, 4, 8, 10)
# These keys do not overlap P1 or Dolphin's existing F1/F8/F10 state hotkeys.
PAD2 = {"up": "F2", "down": "F3", "left": "F4", "right": "F5",
        "lup": "F2", "ldown": "F3", "lleft": "F4", "lright": "F5",
        "a": "F6", "b": "F7", "x": "F9", "y": "F11", "start": "F12",
        "l": "u", "l2": "u", "r": "o", "r2": "o", "z": "p", "select": "p",
        "cup": "c", "cdown": "v", "cleft": "b", "cright": "n"}
P1_ALIASES = {"lup": "up", "ldown": "down", "lleft": "left", "lright": "right"}


def pad_ini(base: str, windows=False) -> str:
    """Add an independent keyboard-only second pad; keep P1's established layout."""
    device = "DInput/0/Keyboard Mouse" if windows else "XInput2/0/Virtual core pointer"
    fields = {"Buttons/A": "a", "Buttons/B": "b", "Buttons/X": "x", "Buttons/Y": "y",
              "Buttons/Z": "z", "Buttons/Start": "start", "Main Stick/Up": "up",
              "Main Stick/Down": "down", "Main Stick/Left": "left", "Main Stick/Right": "right",
              "C-Stick/Up": "cup", "C-Stick/Down": "cdown", "C-Stick/Left": "cleft",
              "C-Stick/Right": "cright", "Triggers/L": "l", "Triggers/R": "r",
              "Triggers/L-Analog": "l", "Triggers/R-Analog": "r"}
    return base.rstrip() + "\n\n[GCPad2]\nDevice = " + device + "\n" + "".join(
        f"{field} = `{PAD2[key].upper()}`\n" for field, key in fields.items())


def input_rows(events, player):
    if player not in (1, 2):
        raise ValueError("PSO buddy controls support players 1 and 2")
    out = []
    for event in events:
        key = event["key"]
        if player == 2 and key not in PAD2:
            raise ValueError(f"Unsupported second-pad control: {key}")
        out.append({"key": PAD2[key] if player == 2 else P1_ALIASES.get(key, key),
                    "down": bool(event.get("down", True))})
    return out


def verify_disc(rom):
    path = Path(rom)
    if path.suffix.lower() == '.gcz':
        from .gcz import GCZ
        reader = GCZ(str(path))
        try:
            header = reader.read(0, 8)
        finally:
            reader._f.close()
    elif path.suffix.lower() in ('.iso', '.gcm'):
        with path.open('rb') as stream:
            header = stream.read(8)
    else:
        raise ValueError('PSO buddy preflight requires an ISO, GCM or GCZ image')
    if header != b'GPOE8P\0\x02':
        raise ValueError('PSO buddy launch requires Plus US disc 0 revision 2 (3OE2)')


def prepare(ad, game, ctx, rom=None):
    from . import memory_card_emulators, pso_campaign
    if getattr(ad, 'name', None) != 'dolphin' or not pso_campaign.matches(ad, game):
        raise ValueError("PSO buddy launch requires supported GameCube PSO Episode I & II Plus")
    if not callable(getattr(ad, "send_input_player", None)):
        raise ValueError("This Dolphin adapter has no independent second pad")
    if rom is not None:
        verify_disc(rom)
    # One persistent campaign per worker/title. No operator-selected card is read,
    # borrowed, formatted, copied over, or selected globally.
    game_id = str(game['game_id'])
    if not re.fullmatch(r'[a-f0-9]{16}', game_id):
        raise ValueError('PSO buddy launch requires a catalog game identifier')
    host = re.sub(r'[^a-zA-Z0-9_-]', '_', platform.node())
    root = Path(ctx.config.data_dir) / "pso-buddies" / host / game_id
    card = root / "dolphin" / "A.USA.raw"
    card.parent.mkdir(parents=True, exist_ok=True)
    created = False
    if not card.exists():
        with card.open("xb") as stream:
            stream.write(memory_card_emulators.blank("gamecube"))
        created = True
    description = memory_card_emulators.describe(card.read_bytes(), "gamecube")
    if not description["formatted"]:
        raise ValueError("Buddy campaign card is invalid; refusing to reformat it")
    ad.coop_players = 2
    ad.autoplay_speed = 1.0
    ad._autoplay_speed_known = True
    ad._autoplay_speed_changing = False
    ad._autoplay_speed_lock = threading.Lock()
    ad.gameplay_demo_user = root / "User"
    ad._pso_coop_new_card = {"isolated": True, "path": str(root),
                           "session_id": f"{ctx.worker}-{ctx.job_id}", "created": created}
    ad.memory_card_context = {"platform": "gamecube", "work_dir": str(root),
                              "slots": {"A": {"path": str(card)}}, "closed": True, "sandbox": True}
    receipt = {"players": 2, "card": str(card), "new_card": created, "persistent": True,
               "speed_requested": 1, "campaign_validation": "not_run"}
    (root / "launch.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def speed_options(ad):
    if not getattr(ad, "_pso_coop_new_card", {}).get("isolated"):
        return {}
    return {"Dolphin.Core.SIDevice1": "6", "Dolphin.Core.EmulationSpeed": "1.0",
            "GFX.Hardware.VSync": "False"}


def set_speed(ad, multiplier, press):
    """Request Dolphin's native 0.1-step rate. Input receipt is not an FPS receipt."""
    if isinstance(multiplier, bool) or multiplier not in SPEEDS:
        raise ValueError("Autoplay speed must be 1, 2, 4, 8 or 10")
    if not getattr(ad, "_pso_coop_new_card", {}).get("isolated"):
        raise ValueError("Speed selection requires a dedicated PSO buddy session")
    with ad._autoplay_speed_lock:
        if not ad._autoplay_speed_known:
            raise RuntimeError("Speed input was interrupted; relaunch to restore a known 1x baseline")
        ad._autoplay_speed_changing = True
        ad._autoplay_speed_observed = None
        try:
            ad.normal_speed()
            delta = int(round((float(multiplier) - ad.autoplay_speed) * 10))
            for _ in range(abs(delta)):
                press("Increase" if delta > 0 else "Decrease")
            ad.autoplay_speed = float(multiplier)
        except Exception:
            ad._autoplay_speed_known = False
            raise
        finally:
            ad._autoplay_speed_changing = False
        return {"requested": multiplier, "input_delivered": True, "achieved_verified": False,
                "note": "Requested emulation rate; achieved speed and campaign completion are not verified."}
