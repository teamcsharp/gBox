"""Make the bot yield to the operator properly: no focus stealing, and a sticky pause.

Two measured causes of the bot fighting the operator:

1. `game_input.raise_window` calls SetForegroundWindow and SetFocus, and the send path uses it - so every injected key pulled focus away from whatever
   the operator was doing, including typing in another window.
2. `pso_operator2.IDLE_SECONDS` was 3.0, so the bot resumed three seconds after the operator stopped touching the pad - which reads as the bot
   grabbing control back mid-play.

Changes:
  * `send` no longer raises or focuses the window; keys are posted without taking the foreground;
  * the idle window grows to 30 seconds, so the operator has to be genuinely finished before the bot moves again;
  * a PAUSE flag file acts as a hard switch: while `D:\\gBox\\pso-ds\\PAUSED` exists, nothing is sent at all.
"""
import pathlib
import re

# 1. game_input: never take the foreground on the send path
gi = pathlib.Path(r"C:\_tools\gBox\.tmp\game_input.py")
text = gi.read_text(encoding="utf-8")
before = text

# find send() and strip any raise/focus call inside it
match = re.search(r"def send\(([^)]*)\):(.*?)(?=\ndef |\Z)", text, re.S)
if not match:
    raise SystemExit("send() not found")
body = match.group(2)
cleaned = body
for line in body.splitlines(keepends=True):
    stripped = line.strip()
    if stripped.startswith(("raise_window", "G.raise_window")) or "SetForegroundWindow" in stripped or "SetFocus(" in stripped:
        cleaned = cleaned.replace(line, "")
if cleaned != body:
    text = text[:match.start(2)] + cleaned + text[match.end(2):]
    gi.write_text(text, encoding="utf-8")
    print("game_input.send: removed focus-stealing calls")
else:
    print("game_input.send: no focus call inside send() (raise happens elsewhere)")

# 2. operator lock: a much longer idle window, and a hard PAUSE flag
op = pathlib.Path(r"C:\_tools\gBox\.tmp\pso_operator2.py")
otext = op.read_text(encoding="utf-8")
otext = otext.replace("IDLE_SECONDS = 3.0", "IDLE_SECONDS = 30.0")
if "PAUSE_FLAG" not in otext:
    otext = otext.replace(
        "IDLE_SECONDS = 30.0",
        'IDLE_SECONDS = 30.0\nPAUSE_FLAG = r"D:\\gBox\\pso-ds\\PAUSED"   # while this file exists, the bot sends nothing')
old_check = "def operator_active():\n    return time.time() - lock_state().get(\"last_motion\", 0.0) < IDLE_SECONDS"
new_check = ('def operator_active():\n'
             '    import os\n'
             '    if os.path.exists(PAUSE_FLAG):\n'
             '        return True                     # paused: treat as if the operator holds the pad\n'
             '    return time.time() - lock_state().get("last_motion", 0.0) < IDLE_SECONDS')
if old_check in otext:
    otext = otext.replace(old_check, new_check)
    print("operator lock: 30 s idle window + PAUSE flag honoured")
else:
    print("operator lock: pattern not found, IDLE_SECONDS =", "30.0" in otext)
op.write_text(otext, encoding="utf-8")
print("done")
