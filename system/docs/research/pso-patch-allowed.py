"""Relax the input gate: the virtual pad needs no focus, so the bot must not wait for it.

`pso_input.allowed()` existed because keyboard input only lands while the game window owns the foreground. Input now goes through the plane's
`send_input`, which uses the virtual XInput pad when it exists - and the pad is polled every frame whether or not the window is focused, which is the
entire reason it exists.

So the gate keeps what still matters - **the operator's pad wins** - and drops the focus requirement, which would otherwise hold the bot still for no
reason while it is perfectly able to play.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\pso_input.py")
text = path.read_text(encoding="utf-8")

start = text.find("def allowed():")
if start < 0:
    raise SystemExit("allowed() not found")
end = text.find("\ndef ", start + 1)
end = len(text) if end < 0 else end

body = '''def allowed():
    """True while the operator is not on the pad.

    The focus test that used to be here applied to the keyboard path, whose presses only land while the game window owns the foreground. Input now goes
    through the plane's send_input, which uses the focus-independent virtual XInput pad when one exists, so focus no longer decides whether the bot can
    act - only whether the operator currently has the controls.
    """
    if OP.operator_active():
        return False
    return True

'''
text = text[:start] + body + text[end:]
path.write_text(text, encoding="utf-8")
print("allowed() now gates only on the operator's pad")
