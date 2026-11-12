"""Point the supervisor at the loop that works: play_rooms, not play_pad.

The supervisor currently does:

```python
script = "play_background.py" if works else "play_pad.py"
```

`play_pad.py` drives the **virtual pad**, and the pad is not available to the bot: `_setup_vpad` binds the app's own pad (which the bot cannot press), and
`send_input` falls back to the keyboard anyway. So if the background-input test failed - as it always has - the supervisor would start a loop that cannot
act, and the game would sit unplayed while the log said a loop was running.

`play_rooms.py` is the loop that actually played: it drives movement through `pso_input` → `game_input.send` → a `session_op` job, which uses whatever
input path the plane has working (pad if bound, keyboard otherwise). In round 22, on an operator-owned session, it booted into the field and walked between
rooms.

So the fallback becomes `play_rooms.py`, with `play_pad.py` kept for when the pad route is proven.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\supervisor.py")
text = path.read_text(encoding="utf-8")

old = 'script = "play_background.py" if works else "play_pad.py"'
new = 'script = "play_background.py" if works else "play_rooms.py"'

count = text.count(old)
print("anchor count:", count)
if count == 1:
    path.write_text(text.replace(old, new), encoding="utf-8")
    print("supervisor falls back to play_rooms (the loop that worked)")
else:
    for line in text.splitlines():
        if "script =" in line:
            print("  found:", line.strip())
