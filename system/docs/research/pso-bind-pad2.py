"""Point the emulator's controller port 1 at XInput slot 2 - where the bot's virtual pad lives.

Measured this round with `XInputGetState` on all four slots:

    before the bot's pad exists:  slot 0 connected, slot 1 connected, slot 2 not, slot 3 not
    after creating vpad:          slot 2 CONNECTED
    while pressing A + stick up:  slot 2  buttons=0x1000  LY=32767   (A down, stick up)

and the emulator's own config binds controller port 1 to **XInput slot 1**:

    [GCPad1]
    Device = XInput/1/Gamepad

Slot 1 is one of the operator's real controllers, so the bot's pad on slot 2 is never read. Rebinding `GCPad1` to `XInput/2/Gamepad` is what lets the
bot drive, and the file is backed up first so the change is reversible.

Dolphin reads this at startup, so it takes effect on the next launch - which is also the launch that resets the broken keyboard path.

One consequence stated plainly: with port 1 on slot 2, the **operator's** controller (slot 1) no longer drives player 1. That is the trade for a bot that
can play without a keyboard, and the backup restores the previous binding in one copy.
"""
import pathlib
import shutil
import time

CONFIG = pathlib.Path(r"D:\gBox\runtime\dolphin\Dolphin-x64\User\Config\GCPadNew.ini")
BACKUP = CONFIG.with_name(f"GCPadNew.ini.bak-before-slot2-{time.strftime('%H%M%S')}")

text = CONFIG.read_text(encoding="utf-8", errors="replace")
print("current GCPad1 binding:", [line.strip() for line in text.splitlines()
                                  if line.startswith("Device =") or line.startswith("[GCPad")][:4])

if "XInput/2/Gamepad" in text:
    print("already bound to slot 2")
else:
    shutil.copyfile(CONFIG, BACKUP)
    print("backup written:", BACKUP.name)
    old = "Device = XInput/1/Gamepad"
    if text.count(old) != 1:
        raise SystemExit(f"XInput/1 binding count {text.count(old)} - not changing anything")
    text = text.replace(old, "Device = XInput/2/Gamepad", 1)
    CONFIG.write_text(text, encoding="utf-8")
    print("GCPad1 now binds XInput slot 2 (the bot's virtual pad)")

print("result:", [line.strip() for line in CONFIG.read_text(encoding='utf-8').splitlines()
                  if line.startswith("Device =") or line.startswith("[GCPad")][:4])
