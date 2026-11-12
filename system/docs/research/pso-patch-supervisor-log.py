"""Log the supervisor's waiting state on change, not every ten seconds.

With the game closed the supervisor polls every ten seconds; logging each poll fills the file with identical lines and buries the interesting ones.
It now logs when the state changes, and then at most once every five minutes while it stays the same.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\supervisor.py")
text = path.read_text(encoding="utf-8")

old = """    log("=== supervisor starting")
    while True:
        if not session_alive():
            log("no live session - waiting for the game to be launched")
            time.sleep(10)
            continue"""

new = """    log("=== supervisor starting")
    last_note = 0.0
    was_waiting = False
    while True:
        if not session_alive():
            now = time.time()
            if not was_waiting or now - last_note > 300:
                log("no live session - waiting for the game to be launched")
                last_note = now
            was_waiting = True
            time.sleep(10)
            continue
        if was_waiting:
            log("session detected")
            was_waiting = False"""

if text.count(old) != 1:
    raise SystemExit(f"loop pattern count {text.count(old)}")
text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
print("supervisor logs on state change, then every five minutes")
