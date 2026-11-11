"""Give the bot its ranged attack: cast techniques (B) at distance, attack (A) in melee.

The operator's kills at 36.3 and 69.3 units cannot be melee - a technique is the only action with that reach, and the measured test confirmed B
casts and damages ("B x1: hp gone"). The character carries four techniques (slots 1, 5, 5, 18 in the technique array).

`pursue` currently only steps and swings, which is why a 180 HP Moja at 35 units stalled for minutes. This adds casting: beyond melee reach it casts
B repeatedly (the technique reaches), and inside melee it keeps the attack-while-stepping pattern.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\selfplay2.py")
text = path.read_text(encoding="utf-8")

old = '''    gap = math.dist(point, (locked["x"], locked["z"]))
    swing_rounds = 1 if gap > MELEE else 2
    for _ in range(swing_rounds):
        if not pso_input.allowed():
            return False
        MB.attack_while_stepping((locked["x"], locked["z"]), swings=3)
    return True'''
new = '''    gap = math.dist(point, (locked["x"], locked["z"]))
    if not pso_input.allowed():
        return False
    if gap > MELEE:
        # beyond melee reach: cast, because techniques carry that far and the operator one-shots at 36-69 units this way
        pso_input.hold("b", 0.25)
        time.sleep(0.45)
        return True
    MB.attack_while_stepping((locked["x"], locked["z"]), swings=3)
    return True'''
if text.count(old) != 1:
    raise SystemExit(f"pattern count {text.count(old)}")
text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
print("pursue now casts B beyond melee range")
