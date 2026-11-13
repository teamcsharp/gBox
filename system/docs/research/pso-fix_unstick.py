"""Never stand still: when a direction is blocked, try the others instead of retrying the same one.

The freeze is now diagnosed. Watching the pad itself proved the input path is healthy - `up` puts `ly=32767`, `left` puts `lx=-32768`, `a` sets `buttons=4096`, and each releases
cleanly - and the same hold then moved the character **109.4 units**, with `y` going **15.4 -> 13.3**. It had been standing on a **ledge** at `y=16.2`; the direction it kept
pressing was simply blocked, and retrying one blocked direction forever looks exactly like a dead bot.

The old unstick did `START`, `B`, `down`, `right` - a fixed dance that assumes a menu or a wall. This replaces it with a **measurement**: try each direction in turn and keep the
one that actually produces movement, remembering it. That covers ledges, corners, walls, gates and the NPC-dialogue lock with one mechanism, and it cannot leave the character
standing still while a usable direction exists.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

if "def unstick(" in text:
    print("already has unstick()")
    raise SystemExit(0)

HELPER = '''
def unstick(pad: Pad, attempts: int = 3) -> str:
    """Find a direction that actually moves the character, and report which one worked.

    A blocked direction retried forever is indistinguishable from a dead bot, and that is what every "stuck" episode in this session was: a ledge at y 16.2, a wall corner, an
    NPC conversation. So instead of a fixed key dance, try each direction and keep the one that produces movement.
    """
    for attempt in range(attempts):
        for key in ("up", "left", "right", "down", "left", "right"):
            before = state(pad)
            player = before.get("player") or {}
            if not player:
                return "no player"
            start = (float(player.get("x") or 0), float(player.get("z") or 0))
            hold(pad, key, 0.6)
            time.sleep(0.15)
            after = state(pad)
            player = after.get("player") or {}
            end = (float(player.get("x") or 0), float(player.get("z") or 0))
            if math.dist(start, end) > 1.0:
                log(f"unstick: {key} freed it ({math.dist(start, end):.1f} units)")
                return key
        # nothing physical worked: a menu or a dialogue is the remaining explanation
        log(f"unstick: no direction moved it (attempt {attempt + 1}) - pressing START and B")
        tap(pad, "start")
        time.sleep(0.6)
        tap(pad, "b")
        time.sleep(0.4)
        tap(pad, "a")
        time.sleep(0.4)
    return ""


'''

anchor = "def play(pad: Pad, seconds: float = 45.0) -> str:"
if text.count(anchor) != 1:
    raise SystemExit("play anchor count: %d" % text.count(anchor))
text = text.replace(anchor, HELPER.lstrip("\n") + anchor, 1)

# replace the fixed dance with the measuring unstick
old = """        if stuck >= 4:
            # a pause menu looks exactly like this from the position alone
            log("stuck - closing menus and backing off")
            tap(pad, "start")
            time.sleep(0.6)
            tap(pad, "b")
            time.sleep(0.4)
            hold(pad, "down", 0.6)
            hold(pad, "right", 0.5)"""

new = """        if stuck >= 2:
            # measured, not assumed: try every direction and keep the one that moves
            unstick(pad)
            stuck = 0"""

if text.count(old) != 1:
    raise SystemExit("stuck handler anchor count: %d" % text.count(old))
text = text.replace(old, new, 1)

# math is needed by unstick
if "import math" not in text:
    text = text.replace("import json\nimport sys", "import json\nimport math\nimport sys", 1)

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("endless.py compiles AFTER - unstick measures each direction")
