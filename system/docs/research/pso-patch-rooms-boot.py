"""Give play_rooms a boot step: press through the title until a character exists.

`play_pad.py` begins with `boot()`; `play_rooms.py` did not - it starts its loop and waits for `player()`, which is null at the title screen. So on a fresh
launch it would sit there logging nothing while the game waited at the title. That is the same silent idle the boot step was written to prevent, just in the
other loop.

This adds the same behaviour: press START and A in alternation (through `pso_input.hold`, so it uses whatever input path works) until `player()` returns an
actor, bounded and logged so a stall says where it stopped. It runs before the room loop, so the order is boot -> play.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\play_rooms.py")
text = path.read_text(encoding="utf-8")

if "def boot(" not in text:
    anchor = "def main(seconds=3600.0):"
    block = '''def boot(limit=120):
    """Press START/A until a character exists. Returns True when the game is in the field."""
    if player() is not None:
        return True
    log("no character yet - pressing through the title")
    for attempt in range(limit):
        pso_input.hold("start", 0.25)
        time.sleep(0.9)
        pso_input.hold("a", 0.25)
        time.sleep(0.7)
        if player() is not None:
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

# call it at the top of main
old_open = '''    log("=== room-to-room play")'''
new_open = '''    log("=== room-to-room play")
    if not boot():
        log("no character to play - stopping")
        return'''
if text.count(old_open) == 1:
    text = text.replace(old_open, new_open, 1)
    print("boot added and wired in")
else:
    print("open anchor count", text.count(old_open))

path.write_text(text, encoding="utf-8")
print("done")
