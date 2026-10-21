"""gBox never swallows or reacts to input aimed at another application (docs/hotkeys.md).

winembed.py: the low-level mouse/keyboard hooks act only when the window under the cursor is gBox / its docked game
(WindowFromPoint -> GA_ROOTOWNER), never by screen rectangle; modifier gestures also need gBox in front; the foreground
watcher reports gBox gaining/losing the front so main.js can release its global shortcuts.
gbox/tools.py: keypad minus (RetroArch rewind) and F4 (RPCS3 load) are held only while the emulator is in front."""
import ast
import ctypes
import re
import sys
import time
from pathlib import Path

import pytest

WINEMBED = Path(__file__).resolve().parents[1] / "clients" / "desktop" / "winembed.py"
APP, GAME, BLENDER, BLENDER_CHILD = 100, 200, 300, 301


def winembed_functions(*names, **namespace):
    """The named top-level functions of winembed.py (which installs real hooks on import), compiled alone."""
    tree = ast.parse(WINEMBED.read_text(encoding="utf-8"))
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in body} == set(names)
    namespace.setdefault("GA_ROOTOWNER", 3)
    exec(compile(ast.Module(body=body, type_ignores=[]), str(WINEMBED), "exec"), namespace)
    return namespace


# ---------------------------------------------------------------- winembed: pure decisions
def test_gbox_in_front_only_for_gbox_or_its_docked_game():
    f = winembed_functions("gbox_in_front")["gbox_in_front"]
    assert f(APP, APP, APP, GAME)                       # the gBox window (a docked child with the keyboard reports this)
    assert f(GAME, GAME, APP, GAME)                     # a GPU-captured source window
    assert f(555, APP, APP, GAME)                       # some window rooted in gBox
    assert not f(BLENDER, BLENDER, APP, GAME)           # Blender in front
    assert not f(BLENDER_CHILD, BLENDER, APP, GAME)
    assert not f(None, None, APP, GAME)                 # nothing in front (desktop switch, lock screen)
    assert not f(APP, APP, None, GAME)                  # gBox's window not known yet: never claim the front
    assert f(APP, APP, APP, None)                       # in front, no game: True (main.js also needs a docked game)


def test_gesture_target_uses_the_window_under_the_point_not_the_rectangle():
    g = winembed_functions("gesture_target")["gesture_target"]
    # Blender covers the docked game's screen area: inside the game rectangle, but Blender is what's under the cursor
    assert g(BLENDER, True, APP, GAME, front=False, needs_front=False) is None
    assert g(BLENDER, True, APP, GAME, front=True, needs_front=True) is None
    assert g(BLENDER, False, APP, GAME, front=False, needs_front=True) is None     # over gBox's sidebar area: Alt+drag
    # gBox visible under the cursor
    assert g(APP, True, APP, GAME, front=True, needs_front=False, game_hit=True) == "game"        # right-click on the game
    assert g(APP, True, APP, GAME, front=False, needs_front=False, game_hit=True) == "game"       # plain right-click on a visible gBox
    assert g(APP, False, APP, GAME, front=True, needs_front=True) == "app"         # Alt+drag from the sidebar
    # Ctrl+click / Alt+drag while another app has the keyboard: not gBox's gesture
    assert g(APP, True, APP, GAME, front=False, needs_front=True) is None
    # no gBox window / nothing under the point
    assert g(None, True, APP, GAME, front=True, needs_front=False) is None
    assert g(APP, True, None, GAME, front=True, needs_front=False) is None


def test_foreground_reports_changes_once_and_watch_answers_the_current_state():
    fg = [APP]
    emitted = []

    class U:
        def GetForegroundWindow(self): return fg[0]
        def GetAncestor(self, h, flag): return {APP: APP, GAME: GAME, BLENDER: BLENDER}.get(h, h)
        def IsWindow(self, h): return h in (APP, GAME)
    state = {"app": None, "front": None, "parent": None, "hwnd": None}
    ns = winembed_functions("gbox_in_front", "front_now", "report_front", "watch",
                            u32=U(), state=state, emit=emitted.append)
    assert ns["report_front"]() is None and emitted == []             # gBox's window not known: silent
    assert ns["watch"](APP) == {"ok": True, "front": True}
    assert emitted == [], "the watch reply carries the state; no duplicate event"
    ns["report_front"](); assert emitted == []
    fg[0] = BLENDER
    ns["report_front"](); ns["report_front"]()
    assert emitted == [{"event": "foreground", "front": False}]
    fg[0] = APP
    ns["report_front"]()
    assert emitted[-1] == {"event": "foreground", "front": True}
    assert ns["watch"](0) == {"ok": False, "front": False}


def test_hooks_have_no_rectangle_only_paths_left():
    src = WINEMBED.read_text(encoding="utf-8")
    hook = src[src.index("def rclick_hook():"):src.index("def ptt_hook():")]
    assert "over_app" not in hook, "the gBox-window test was a pure rectangle: Blender on top lost its Alt+clicks"
    assert "WindowFromPoint" in hook and "gesture_target(" in hook
    assert "target(m.pt, needs_front=True)" in hook                    # Alt+drag
    assert "over(m.pt, needs_front=bool(ctrl))" in hook               # Ctrl+click needs the front, right-click the window
    ptt = src[src.index("def ptt_hook():"):]
    assert "gbox_in_front(" in ptt
    swallow = ptt.index("return 1")
    assert ptt.index("if gbox_in_front(") < swallow, "~ is swallowed only while gBox is in front"


# ---------------------------------------------------------------- tools.py: emulator hotkeys
def test_emulator_in_front_decision():
    from gbox.tools import _emulator_in_front as f
    emu = {10, 11}                                                     # emulator + a child process
    assert f(10, set(), emu, docked_ok=False)
    assert f(11, set(), emu, docked_ok=False)
    assert not f(BLENDER, set(), emu, docked_ok=True)                  # Blender in front: never
    assert not f(BLENDER, {BLENDER}, emu, docked_ok=True)
    assert f(42, {42, 10}, emu, docked_ok=True)                        # gBox in front with RetroArch docked in it
    assert not f(42, {42, 10}, emu, docked_ok=False)                   # F4: gBox's own F4 handles a docked RPCS3
    assert f(42, set(), emu, docked_ok=True, fg_is_gbox=True)          # gBox.exe in front (GPU capture)
    assert not f(42, set(), emu, docked_ok=False, fg_is_gbox=True)
    assert not f(None, set(), emu, docked_ok=True)
    assert not f(10, set(), set(), docked_ok=True)                     # no emulator running


@pytest.mark.skipif(sys.platform != "win32", reason="ctypes.wintypes MSG")
def test_scoped_hotkey_registers_only_while_the_emulator_is_in_front(monkeypatch):
    from gbox import tools

    class Proc:
        pid = 10

    class Ad:
        proc = Proc()
    script = [10, 10, BLENDER, BLENDER, 10]                            # foreground process per loop turn
    pending = {1: 1, 2: 1}                                              # WM_HOTKEY waiting in turn 1 (front) and 2 (gap)
    turn, calls, fired = [-1], [], []

    class U:
        def RegisterHotKey(self, hwnd, hk, mods, vk): calls.append(("reg", vk)); return 1
        def UnregisterHotKey(self, hwnd, hk): calls.append(("unreg",)); return 1
        def PeekMessageW(self, *a):
            if pending.get(turn[0]):
                pending[turn[0]] -= 1
                return 1
            return 0
        def MapVirtualKeyW(self, vk, t): return 0x4A
        def keybd_event(self, vk, sc, flags, extra): calls.append(("replay", vk, flags))

    class Win:
        user32 = U()
    monkeypatch.setattr(ctypes, "windll", Win(), raising=False)
    monkeypatch.setattr(tools, "_process_tree", lambda pids: set(pids))
    monkeypatch.setattr(tools, "_exe_name", lambda pid: "")
    monkeypatch.setattr(tools, "_foreground_pids", lambda user32, children=True: (script[turn[0]], set()))

    def sessions():
        turn[0] += 1
        return [Ad()] if turn[0] < len(script) else []
    t = tools._scoped_hotkey("test-hotkey", 0xB0FF, 0x6D, sessions, lambda targets: fired.append(len(targets)), docked_ok=True)
    t.join(5)
    assert not t.is_alive()
    assert fired == [1], "the press while the emulator was in front fired once"
    assert calls == [("reg", 0x6D),                                     # emulator in front
                     ("unreg",),                                        # Blender in front: released at once
                     ("replay", 0x6D, 0), ("replay", 0x6D, 2),          # the press caught in the gap goes to Blender
                     ("reg", 0x6D),                                     # back to the emulator
                     ("unreg",)], calls                                 # session over: released


def test_scoped_hotkeys_are_wired_with_the_right_scope():
    src = (Path(__file__).resolve().parents[1] / "gbox" / "tools.py").read_text(encoding="utf-8")
    rewind = src[src.index("def _ensure_rewind_hotkey"):src.index("def _ensure_ps3_load_hotkey")]
    ps3 = src[src.index("def _ensure_ps3_load_hotkey"):src.index("def _stage_for_launch")]
    assert "_scoped_hotkey(" in rewind and "docked_ok=True" in rewind and "RegisterHotKey" not in rewind
    assert "_scoped_hotkey(" in ps3 and "docked_ok=False" in ps3 and "RegisterHotKey" not in ps3
    assert len(re.findall(r"\.RegisterHotKey\(", src)) == 1, "every hotkey goes through _scoped_hotkey"


@pytest.mark.parametrize("hit,root,is_child,expected", [
    (555, APP, False, []),             # Chromium popup revealed through the native game's clipped hole
    (APP, APP, False, []),             # app canvas inside the old game bounding rectangle
    (GAME, APP, False, [{"event": "gameclick"}]),
    (201, APP, True, [{"event": "gameclick"}]),  # actual control owned by the game
    (BLENDER_CHILD, BLENDER, False, []),
])
def test_actual_mouse_hook_does_not_dismiss_popups_through_game_region_holes(hit, root, is_child, expected):
    """Run the real nested target/over/proc functions; install no native hook."""
    proc, emitted, MS, w = mouse_hook(hit, root, is_child)
    event = MS(w.POINT(75, 75), 0, 0, 1, 0)
    assert proc(0, 0x201, ctypes.addressof(event)) == 73
    assert emitted == expected


def test_triple_click_on_the_docked_game_asks_for_picture_in_picture_and_passes_every_click_through():
    """Operator 2026-10-21: triple-click the game display -> PiP. The hook reports it ("piptriple"), never swallows."""
    proc, emitted, MS, w = mouse_hook(GAME, APP, False)
    def click(t):
        event = MS(w.POINT(75, 75), 0, 0, t, 0)                   # a name keeps it alive while proc reads its address
        return proc(0, 0x201, ctypes.addressof(event))
    for t in (1000, 1150, 1300):
        assert click(t) == 73, "the game gets the click"
    assert emitted == [{"event": "gameclick"}] * 2 + [{"event": "piptriple"}, {"event": "gameclick"}]
    emitted.clear()                                               # a slow third click starts a new run
    for t in (5000, 5150, 6000):
        click(t)
    assert {"event": "piptriple"} not in emitted


def test_triple_click_is_not_counted_in_compact_mode_or_off_the_game():
    for args, kw in (((GAME, APP, False), {"compact_on": True}), ((555, APP, False), {})):   # PiP on / a popup over the game
        proc, emitted, MS, w = mouse_hook(*args, **kw)
        events = [MS(w.POINT(75, 75), 0, 0, t, 0) for t in (1000, 1150, 1300)]               # kept alive while proc reads them
        for e in events:
            proc(0, 0x201, ctypes.addressof(e))
        assert {"event": "piptriple"} not in emitted, (args, kw, emitted)
    assert emitted == [], "nothing at all for a click on a popup"


def mouse_hook(hit, root, is_child, compact_on=False):
    from ctypes import wintypes as w
    tree = ast.parse(WINEMBED.read_text(encoding="utf8"))
    outer = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "rclick_hook")
    body = [n for n in outer.body if isinstance(n, ast.FunctionDef) and n.name in {"target", "over", "proc"}]
    for n in body:
        n.decorator_list = []
    assert len(body) == 3

    class MS(ctypes.Structure):
        _fields_ = [("pt", w.POINT), ("mouseData", w.DWORD), ("flags", w.DWORD),
                    ("time", w.DWORD), ("extra", ctypes.c_size_t)]

    class U:
        def IsWindow(self, h): return True
        def WindowFromPoint(self, pt): return hit
        def GetAncestor(self, h, mode): return root
        def IsChild(self, parent, child):
            assert (parent, child) == (GAME, hit)
            return is_child
        def GetAsyncKeyState(self, key): return 0
        def GetDoubleClickTime(self): return 500
        def GetSystemMetrics(self, index): return 4
        def CallNextHookEx(self, *args): return 73

    emitted = []
    ns = winembed_functions("gesture_target", "triple_click")
    ns.update(u32=U(), ctypes=ctypes, wintypes=w, MS=MS,
              state={"parent": APP, "hwnd": GAME, "compact": compact_on},
              in_game_rect=lambda pt: True, front_now=lambda: True,
              compact={"click": None, "release": False, "hover": False, "run": None}, whip={"on": False},
              compact_click=lambda *args: (None, False), emit=emitted.append,
              WM_LBUTTONDOWN=0x201, WM_LBUTTONUP=0x202, WM_RBUTTONDOWN=0x204, WM_RBUTTONUP=0x205)
    exec(compile(ast.Module(body=body, type_ignores=[]), str(WINEMBED), "exec"), ns)
    return ns["proc"], emitted, MS, w
