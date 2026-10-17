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
