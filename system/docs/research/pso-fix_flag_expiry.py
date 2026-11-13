"""One relay, and a pause flag that cannot wedge the bot forever.

Two faults found by inspecting rather than guessing:

1. **Two relay processes were running** (PIDs 2156 and 40528), both reading the same controller and both injecting into the session - so every press was delivered **twice**. The bot's "stand down" was correct (the operator really was playing), but the duplicate injection can double-apply a directional press and make control feel wrong.
2. **The pause flag had no expiry.** The relay removes it after four idle seconds, which is right - but if the relay ever dies or hangs, the flag stays and the bot stands down **forever** with no way back except deleting the file by hand. That is exactly the class of failure that has cost this session time: a stale marker being trusted.

So:

* the loop now ignores the flag when it is older than `FLAG_STALE_S` seconds - the same "measure, do not assume" rule used everywhere else;
* a small helper kills duplicate relay processes so only one is ever injecting.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = """        if OPERATOR_PLAYING.exists():
            if not globals().get("_PAUSED_LOGGED"):
                log("  operator is playing - bot standing down")
                globals()["_PAUSED_LOGGED"] = True
            time.sleep(0.4)
            continue
        else:
            globals()["_PAUSED_LOGGED"] = False"""

new = """        # Stand down while the operator plays - but never trust a stale marker. If the relay dies with the flag set,
        # an endless stand-down is indistinguishable from a dead bot, so the flag expires on its own age.
        operator_active = False
        if OPERATOR_PLAYING.exists():
            try:
                operator_active = (time.time() - OPERATOR_PLAYING.stat().st_mtime) < FLAG_STALE_S
            except OSError:
                operator_active = False
        if operator_active:
            if not globals().get("_PAUSED_LOGGED"):
                log("  operator is playing - bot standing down")
                globals()["_PAUSED_LOGGED"] = True
            time.sleep(0.4)
            continue
        globals()["_PAUSED_LOGGED"] = False"""

count = text.count(old)
print("pause anchor count:", count)
if count != 1:
    raise SystemExit("pause block not unique")
text = text.replace(old, new, 1)

if "FLAG_STALE_S" not in text:
    text = text.replace(
        'OPERATOR_PLAYING = pathlib.Path(r"D:\\gBox\\pso-ds\\operator-playing.flag")',
        'OPERATOR_PLAYING = pathlib.Path(r"D:\\gBox\\pso-ds\\operator-playing.flag")\n'
        'FLAG_STALE_S = 15.0        # a pause flag older than this is a dead relay, not a playing operator', 1)
    print("FLAG_STALE_S declared")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
