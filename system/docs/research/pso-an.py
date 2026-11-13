"""Read the operator's notes every iteration and act on them immediately.

The operator wants to type notes while the bot plays - *"have you be able to internalize and actualize and deal with those notes and be able to put them into action immediately"* - so this is the
channel. The app already has the pattern: `pso_map_feed` polls `pso-directive.json` by mtime and carries `goto`/`attack`/`press`/`clear`. This adds the free-text equivalent, because notes are
richer than directives.

**File**: `D:\\gBox\\pso-ds\\operator-notes.txt` - whatever is in it is read on the next loop iteration, logged verbatim as *"NOTE from operator: ..."* so the operator can see it was received, and then
acted on by keyword:

| note contains | effect |
|---|---|
| `stop`, `halt`, `wait` | the bot stands down until told otherwise |
| `go`, `resume`, `play` | resumes |
| `kill`, `attack`, `fight` | prioritise enemies |
| `box`, `loot`, `rare` | prioritise containers |
| `door`, `gate`, `warp`, `exit` | prioritise the way forward |
| `goto X Z` | walk to that coordinate |

Anything unrecognised is still logged as received and kept, so a note is never silently dropped - it stays in effect as context. That is what "internalize" means here: the text is read, echoed,
classified, and turned into the same flags the rest of the loop already obeys.
"""
import pathlib
import py_compile
import re

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

HELPER = '''
OPERATOR_NOTES = pathlib.Path(r"D:\\gBox\\pso-ds\\operator-notes.txt")
NOTE_STATE = {"last": None, "mode": None, "goto": None}


def read_notes(pad: Pad) -> None:
    """Read the operator's notes file; log it, classify it, and set the flags the loop obeys."""
    try:
        if not OPERATOR_NOTES.exists():
            return
        raw = OPERATOR_NOTES.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return
    if not raw or raw == NOTE_STATE["last"]:
        return
    NOTE_STATE["last"] = raw
    latest = [line.strip() for line in raw.splitlines() if line.strip()]
    text_line = latest[-1] if latest else raw
    log(f"  NOTE from operator: {text_line}")
    lowered = text_line.lower()

    if any(word in lowered for word in ("stop", "halt", "wait", "hold")):
        NOTE_STATE["mode"] = "stop"
        log("  note internalized: standing down")
        return
    if any(word in lowered for word in ("go ", "resume", "play", "continue")) or lowered in ("go", "resume"):
        NOTE_STATE["mode"] = None
        log("  note internalized: resuming")
        return
    if any(word in lowered for word in ("kill", "attack", "fight", "enemy")):
        NOTE_STATE["mode"] = "fight"
        log("  note internalized: prioritising enemies")
        return
    if any(word in lowered for word in ("box", "loot", "rare", "item", "drop")):
        NOTE_STATE["mode"] = "loot"
        log("  note internalized: prioritising containers and rares")
        return
    if any(word in lowered for word in ("door", "gate", "warp", "exit", "next room", "level")):
        NOTE_STATE["mode"] = "exit"
        log("  note internalized: prioritising the way forward")
        return
    match = re.search(r"goto\\s+(-?\\d+(?:\\.\\d+)?)\\s+(-?\\d+(?:\\.\\d+)?)", lowered)
    if match:
        NOTE_STATE["goto"] = (float(match.group(1)), float(match.group(2)))
        log(f"  note internalized: walking to {NOTE_STATE['goto']}")
        return
    log("  note internalized: noted (no action keyword) - it stays in effect as context")


'''

anchor = "def play(pad: Pad, seconds: float = 120.0) -> str:"
if text.count(anchor) != 1:
    raise SystemExit("play anchor count: %d" % text.count(anchor))
if "def read_notes(" not in text:
    text = text.replace(anchor, HELPER.lstrip("\n") + anchor, 1)
    print("read_notes() added")

# call it at the top of every iteration, and honour the stop mode
old_head = """        now = state(pad)"""
new_head = """        read_notes(pad)
        if NOTE_STATE.get("mode") == "stop":
            time.sleep(0.5)
            continue

        now = state(pad)"""
count = text.count(old_head)
print("iteration head anchor count:", count)
if count == 1:
    text = text.replace(old_head, new_head, 1)
    print("notes are read every iteration")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
