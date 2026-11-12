"""Point the supervisor at the pad loop: the keyboard path is dead, the pad path is not.

For three rounds every keyboard delivery failed while the controller worked, and `vpad.py` lets the bot be a controller. So when the background-input test
shows the keyboard does not reach the game, the supervisor should start `play_pad.py` - which drives the virtual pad and needs neither focus nor a
window - instead of `play_when_focused.py`, which would simply wait for a keyboard that never arrives.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\supervisor.py")
text = path.read_text(encoding="utf-8")

old = 'script = "play_background.py" if works else "play_when_focused.py"'
new = 'script = "play_background.py" if works else "play_pad.py"'
count = text.count(old)
print(f"pattern count: {count}")
if count == 1:
    path.write_text(text.replace(old, new), encoding="utf-8")
    print("supervisor now falls back to the pad loop")
else:
    for line in text.splitlines():
        if "script =" in line:
            print("found:", repr(line.strip()))
