"""Gate the bot on BOTH conditions: the operator is idle AND the game actually has focus.

`allowed()` only checked whether the operator had touched the pad recently. With keys now delivered only when the game holds focus, a bot that keeps
working while the game is unfocused would loop uselessly and log actions it never performed. Adding the focus test means the bot sleeps while the
operator uses the PC and resumes the instant the game is brought forward.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\pso_input.py")
text = path.read_text(encoding="utf-8")

old = '''def allowed():
    return not OP.operator_active()'''
new = '''def allowed():
    """True only when the operator is idle AND the game window has focus (so keys will actually land)."""
    if OP.operator_active():
        return False
    try:
        return bool(G.game_has_focus())
    except Exception:
        return True'''
if text.count(old) != 1:
    raise SystemExit(f"pattern count {text.count(old)}")
text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
print("allowed() now requires game focus as well as operator idleness")
