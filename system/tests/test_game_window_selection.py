"""A modal dialog must not replace the render window for capture/input/docking."""
import ctypes
from types import SimpleNamespace

from gbox import adapters


def test_render_window_wins_over_first_warning_and_larger_helpers(monkeypatch):
    # The warning was first in EnumWindows and minimized at (-32000,-32000).
    windows = {1: ('Warning', True, 516, 216),
               2: ('Dolphin 2609a | JIT64 DC | Direct3D 12 | Soulcalibur II', False, 898, 710),
               3: ('DIEmWin', False, 4000, 4000), 4: ('Settings', False, 1500, 1000)}
    def pid(h, out): out._obj.value = 42
    def title(h, out, count): out.value = windows[h][0]
    def rect(h, out):
        out._obj.left = out._obj.top = 0
        out._obj.right, out._obj.bottom = windows[h][2:]
    def enum(callback, arg):
        for h in windows: callback(h, arg)
    user = SimpleNamespace(GetWindowThreadProcessId=pid, IsWindowVisible=lambda h: True,
        IsIconic=lambda h: windows[h][1], GetWindowTextW=title, GetWindowRect=rect,
        EnumWindows=enum, EnumChildWindows=lambda h, cb, arg: None)
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(user32=user), raising=False)
    monkeypatch.setattr(ctypes, 'WINFUNCTYPE', lambda *a: lambda f: f, raising=False)
    assert adapters._pid_window(42) == 2
    del windows[2]
    assert adapters._pid_window(42) == 4


def test_native_replacement_scan_compares_against_existing_docked_render():
    import ast
    from pathlib import Path
    source = Path(__file__).resolve().parents[1] / 'clients/desktop/winembed.py'
    method = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == 'move')
    scans = []
    def find(pid, parent=None):
        scans.append((pid, parent))
        return 7 if parent == 9 else 8  # 8 is an owned Warning, 7 is the render child
    user = SimpleNamespace(IsWindow=lambda h: True, IsWindowVisible=lambda h: True,
        SetWindowPos=lambda *a: None, SetWindowRgn=lambda *a: None)
    ns = {'state': {'hwnd': 7, 'pid': 42, 'parent': 9, 'mode': 'native'}, 'u32': user,
          'time': SimpleNamespace(monotonic=lambda: 100), 'find_window': find,
          'attach': lambda *a: (_ for _ in ()).throw(AssertionError('must keep the rendering window'))}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), ns)
    assert ns['move'](0, 0, 640, 480)['ok']
    assert scans == [(42, 9)]


def _fake_user32(windows, shown):
    """EnumWindows-backed fake user32: windows maps hwnd -> (title, iconic, w, h)."""
    def pid(h, out): out._obj.value = 42
    def title(h, out, count): out.value = windows[h][0]
    def rect(h, out):
        out._obj.left = out._obj.top = 0
        out._obj.right, out._obj.bottom = windows[h][2:]
    def enum(callback, arg):
        for h in windows: callback(h, arg)
    from types import SimpleNamespace
    return SimpleNamespace(GetWindowThreadProcessId=pid, IsWindowVisible=lambda h: True,
        IsIconic=lambda h: windows[h][1], GetWindowTextW=title, GetWindowRect=rect,
        EnumWindows=enum, EnumChildWindows=lambda h, cb, arg: None,
        ShowWindow=lambda h, cmd: shown.append((h, cmd)))


def test_minimized_yuzu_window_is_seen_for_readiness(monkeypatch):
    """#3688: yuzu launched with hidden_start() is iconic until gBox docks it, so the
    launch readiness check must include minimized windows (it timed out before)."""
    import ctypes
    from gbox import adapters
    shown = []
    # 1 is the iconic yuzu game window, 2 a normal helper window of the same pid
    windows = {1: ('yuzu 1810 | Puyo Puyo Tetris (USA) | Vulkan', True, 1280, 720),
               2: ('QtMainWindowHelper', False, 100, 50)}
    user = _fake_user32(windows, shown)
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(user32=user), raising=False)
    monkeypatch.setattr(ctypes, 'WINFUNCTYPE', lambda *a: lambda f: f, raising=False)
    assert adapters._pid_window(42) == 2                       # default still skips iconic
    assert adapters._pid_window(42, include_minimized=True) == 1   # readiness sees the game window


def test_yuzu_launch_waits_with_include_minimized():
    """The YuzuAdapter wait loop must pass include_minimized=True (#3688)."""
    import ast, inspect
    from gbox import adapters
    import textwrap
    src = textwrap.dedent(inspect.getsource(adapters.YuzuAdapter.launch_game))
    call = next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.Call) and getattr(n.func, 'id', '') == '_pid_window')
    kw = {k.arg: getattr(k.value, 'value', None) for k in call.keywords}
    assert kw.get('include_minimized') is True


def test_keep_offscreen_give_up_unminimizes_parked_window():
    """#3688: the give-up restore must ShowWindow an iconic parked window, not just move it."""
    import ast, inspect
    from gbox import adapters
    import textwrap
    src = textwrap.dedent(inspect.getsource(adapters.keep_offscreen))
    tree = ast.parse(src)
    def attrs(node):
        return {getattr(c.func, 'attr', '') for c in ast.walk(node) if isinstance(c, ast.Call)}
    loop = next(n for n in ast.walk(tree) if isinstance(n, ast.For) and 'SetWindowPos' in attrs(n))
    a = attrs(loop)
    assert 'ShowWindow' in a and 'IsIconic' in a, a
