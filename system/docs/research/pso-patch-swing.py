"""Make the fight loop swing like the test that worked: a held A press, from inside melee range.

The verified kill (enemy HP 30 -> 0) used `hold("a", 0.3)` at 5 units, while self-play used `tap("a")` - a ~50 ms press that may not survive the
swing animation - from 8+ units. This changes the fight loop to hold the attack and to approach within 5 units, which is the range the kill was
measured at.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\selfplay.py")
text = path.read_text(encoding="utf-8")

replacements = [
    ('if gap > 4:\n                    RUN.run_to(player, (target["x"], target["z"]), tolerance=4.0, budget=5.0)',
     'if gap > 5:\n                    RUN.run_to(player, (target["x"], target["z"]), tolerance=4.0, budget=5.0)'),
    ('pso_input.tap("a", gap=0.28)', 'pso_input.hold("a", 0.3)'),
]
for old, new in replacements:
    count = text.count(old)
    if count != 1:
        print(f"SKIP (count {count}): {old.splitlines()[0][:60]}")
        continue
    text = text.replace(old, new)
    print(f"applied: {old.splitlines()[0].strip()[:60]}")

path.write_text(text, encoding="utf-8")
print("holds attack:", 'pso_input.hold("a", 0.3)' in text)
