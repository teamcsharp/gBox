"""Use the proven attack-while-stepping pattern in the fight loop instead of approach-then-swing.

`map_bot.attack_while_stepping` holds the closing direction and presses A three times during the movement - documented as "the pattern that lands
hits" - whereas self-play walked to a point and then swung from standstill, which repeatedly failed to close an 18-unit enemy. This calls it
directly for each swing round.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\selfplay.py")
text = path.read_text(encoding="utf-8")

old = """                if gap > 5:
                    RUN.run_to(player, (target["x"], target["z"]), tolerance=4.0, budget=5.0)
                pso_input.hold("a", 0.3)"""
new = """                import map_bot as MB
                MB.attack_while_stepping((target["x"], target["z"]), swings=3)"""
if text.count(old) != 1:
    raise SystemExit(f"pattern count {text.count(old)}")
text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
print("fight loop now uses attack_while_stepping")
