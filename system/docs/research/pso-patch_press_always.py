"""Press constantly while near a door, and defend yourself when something is hitting you.

The operator's rule: *"press the button any time this opportunity comes up, anytime they see an indicator for the switch, they need to press it."* The
screenshotted indicator is a glow around the character in the open, so the switch can be **within a couple of units** - and my code only pressed within 10
units *after* a walk, which is why it walked past the moment.

Two changes, both matching how the game is actually played:

  * **press A every cycle while a door is within 40 units**, not only in a dedicated step. Pressing costs nothing and the switch is often at the character's
    feet, where the indicator appears. The state is logged when it changes.
  * **fight first when something is close.** The log shows distances jumping 79 → 101 → 71 → 118 while the bot walked at a door: it was being knocked
    around by enemies and pressing nothing. A room is not opened while being hit, so an enemy within 15 units takes priority over a distant door.

Together these mean: defend yourself, then press what is under your feet, then travel.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\play_rooms.py")
text = path.read_text(encoding="utf-8")

# 1. enemies at close range come before the switch chase
old = """            if press_in_reach():
                continue
            if press_switches():
                continue
            foes, doors = entities()
            if foes:"""
new = """            foes_now, doors_now = entities()
            if foes_now and foes_now[0]["distance"] < 15:
                log(f"  {foes_now[0]['class']} at {foes_now[0]['distance']:.0f} units is on us - fighting")
                fight(foes_now[0])
                continue
            if doors_now and doors_now[0]["distance"] < 40:
                pso_input.hold("a", 0.3)
                log(f"  pressed A near {doors_now[0]['class']} (state {doors_now[0]['state']}, {doors_now[0]['distance']:.0f} units)")
                time.sleep(0.4)
            if press_in_reach():
                continue
            if press_switches():
                continue
            foes, doors = entities()
            if foes:"""
if text.count(old) == 1:
    text = text.replace(old, new, 1)
    print("close enemies take priority; A is pressed near any door")
else:
    print("cycle anchor count", text.count(old))

path.write_text(text, encoding="utf-8")
print("done")
