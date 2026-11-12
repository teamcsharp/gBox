"""Start from the title: press through the menus until a character exists, then play.

An unattended run begins wherever the emulator is - usually the title screen - and every loop written so far assumed a player actor already existed and
simply idled otherwise. That is a silent failure mode: the bot "runs" for an hour and never leaves the title, with nothing in the log but a repeated
`no player`.

PSO's boot is a short, forgiving chain of confirms: title -> press START -> mode select -> character select -> Start Game. Pressing START and A in
alternation walks through all of it, so the loop does that until `player()` returns a real actor, logging each attempt count so the record shows whether
the game was at the title, in a menu, or already in the field.

The pad is used rather than the keyboard for the same reason as everywhere else: it needs no focus.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\play_pad.py")
text = path.read_text(encoding="utf-8")

if "def boot(" not in text:
    anchor = "def main(seconds=3600.0):"
    block = '''def boot(pad, limit=120):
    """Press through the title and menus until a character exists. Returns True when one does."""
    me = player()
    if me is not None:
        return True
    log("no character yet - pressing through the title and menus")
    for attempt in range(limit):
        pad.press("start", 0.2)
        time.sleep(1.0)
        pad.press("a", 0.25)
        time.sleep(0.8)
        me = player()
        if me is not None:
            log(f"character appeared after {attempt + 1} rounds of start+A")
            return True
        if attempt % 10 == 9:
            log(f"  still no character after {attempt + 1} attempts")
    log("gave up waiting for a character")
    return False


def main(seconds=3600.0):'''
    if text.count(anchor) != 1:
        raise SystemExit("main anchor not found")
    text = text.replace(anchor, block, 1)

# call it before calibrating: the stick cannot be calibrated without a character
old = '''    log("calibrating the stick against the character")'''
new = '''    if not boot(pad):
        log("no character to play - stopping")
        return 2
    log("calibrating the stick against the character")'''
if text.count(old) == 1:
    text = text.replace(old, new, 1)
    print("boot added and wired in")
else:
    print("calibration anchor count", text.count(old))

path.write_text(text, encoding="utf-8")
print("done")
