"""Stop Dolphin from eating the operator's typing, and make it survive a session that dies mid-boot.

Two separate faults, both real:

1. **`Dolphin.ini [Interface] BackgroundInput = True`** - the emulator accepts keyboard/DInput while its window is *not* focused, so anything typed elsewhere in the desktop
   goes into the game. That is how the operator's typing exited the game. Setting it to `False` means the keyboard only drives the game when the game window is focused,
   which is what a person expects. **The bot is unaffected**: its input goes through gBox's virtual pad, an XInput device, which does not depend on focus at all - as does
   the operator's own controller relay.

2. **`endless.ensure_in_game` waits for a player without checking that the session still exists**, so when the session died it kept pressing into a dead session forever
   (the log sat on "boot attempt 2"). It now checks `live_sessions()` on every wait iteration and gives up at once, letting the outer loop relaunch.

Written with Python so the INI stays UTF-8/ANSI - a PowerShell redirect once filled a source file with null bytes in this session.
"""
import pathlib
import re

INI = pathlib.Path(r"D:\gBox\runtime\dolphin\Dolphin-x64\User\Config\Dolphin.ini")
ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")

# ---- 1. BackgroundInput = False -------------------------------------------------------------------------------------
text = INI.read_text(encoding="utf-8", errors="replace")
print("before:", [line for line in text.splitlines() if "BackgroundInput" in line])

if re.search(r"^BackgroundInput\s*=\s*True\s*$", text, re.M):
    text = re.sub(r"^BackgroundInput\s*=\s*True\s*$", "BackgroundInput = False", text, flags=re.M)
    INI.write_text(text, encoding="utf-8")
    print("set BackgroundInput = False - the game no longer reads the keyboard while unfocused")
elif re.search(r"^BackgroundInput\s*=\s*False\s*$", text, re.M):
    print("already False")
else:
    # no key at all means Dolphin's default; add it explicitly under [Interface]
    if "[Interface]" in text:
        text = text.replace("[Interface]", "[Interface]\nBackgroundInput = False", 1)
        INI.write_text(text, encoding="utf-8")
        print("added BackgroundInput = False under [Interface]")
    else:
        print("no [Interface] section - INI left alone")

print("after:", [line for line in INI.read_text(encoding='utf-8', errors='replace').splitlines()
                 if "BackgroundInput" in line])

# ---- 2. endless: notice a dead session while booting ----------------------------------------------------------------
source = ENDLESS.read_text(encoding="utf-8")
old = """        # the intro cutscene: no player entity exists until it ends
        for index in range(12):
            time.sleep(5)
            if state(pad).get("player"):
                log("character is in the world")
                return True
            if index in (2, 5, 8):
                tap(pad, "a")"""
new = """        # the intro cutscene: no player entity exists until it ends - but the session can also die, and waiting on a
        # session that no longer exists is what left the loop pressing into nothing
        for index in range(12):
            time.sleep(5)
            if not live_sessions():
                log("session ended while booting - letting the outer loop relaunch")
                return False
            if state(pad).get("player"):
                log("character is in the world")
                return True
            if index in (2, 5, 8):
                tap(pad, "a")"""

if source.count(old) == 1:
    ENDLESS.write_text(source.replace(old, new, 1), encoding="utf-8")
    print("endless.py: boot wait now aborts when the session is gone")
else:
    print("endless.py anchor count:", source.count(old))

import py_compile
py_compile.compile(str(ENDLESS), doraise=True)
print("endless.py compiles")
