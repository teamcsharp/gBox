"""Extract the loop's decision into a pure function, so its priority order can be tested.

The order is the whole strategy - switches, then enemies, then the exit, then the next room - and it lived inline in the main loop, which means it could
only be checked by watching a live game. Extracting it makes it a function of what is visible:

    choose_action(foes, switches, exits, rooms, me) -> ("switch"|"enemy"|"exit"|"room"|"wait", target)

Two details are preserved deliberately because they are easy to get wrong when rewriting:

  * a switch already in state 2 (open) is **not** an action - pressing an open door again is wasted time;
  * an enemy is fought **before** the exit only when it is actually engaged (within 80 units, the scanner's own limit), because walking past a room's
    enemies to the exit and then being shot in the back is not progress.

The loop then calls it and dispatches. Behaviour is unchanged; only its addressability is.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\play_pad.py")
text = path.read_text(encoding="utf-8")

if "def choose_action(" not in text:
    anchor = "def boot(pad, limit=120):"
    block = '''def choose_action(foes, switches, exits, rooms, me):
    """What to do next, in progression order. Pure: no memory reads, no input."""
    live_switches = [row for row in switches if row["state"] != 2]
    if live_switches:
        return "switch", live_switches[0]
    if foes:
        return "enemy", foes[0]
    if exits:
        return "exit", exits[0]
    if rooms and me is not None:
        return "room", min(rooms, key=lambda room: math.dist((me[0], me[2]), tuple(room["centre"])))
    return "wait", None


def boot(pad, limit=120):'''
    if text.count(anchor) != 1:
        raise SystemExit("boot anchor not found")
    text = text.replace(anchor, block, 1)
    path.write_text(text, encoding="utf-8")
    print("choose_action extracted")
else:
    print("already present")
