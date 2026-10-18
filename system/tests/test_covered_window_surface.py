"""#1057: a covered emulator window is captured from its own surface, not abandoned."""
import ctypes
import hashlib
import io
from ctypes import wintypes
from types import SimpleNamespace

import pytest
from PIL import Image, ImageGrab

from gbox import adapters

from test_emulation_issue import make_incident


def covered_window(monkeypatch, tmp_path, surface):
    monkeypatch.setenv('GBOX_GAME_FRAME_DIR', str(tmp_path))
    monkeypatch.setattr(adapters, '_last_grab', {'pid': 999, 'covered': 9, 'sha256': 'old'})
    def rect(hwnd, address):
        value = ctypes.cast(address, ctypes.POINTER(wintypes.RECT)).contents
        value.left, value.top, value.right, value.bottom = 0, 0, 40, 30
        return 1
    def pid(hwnd, address):
        ctypes.cast(address, ctypes.POINTER(wintypes.DWORD)).contents.value = 999
        return 1
    def from_point(point):
        return 2
    from_point.argtypes = from_point.restype = None
    user = SimpleNamespace(GetWindowRect=rect, WindowFromPoint=from_point, GetWindowThreadProcessId=pid)
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(user32=user), raising=False)
    monkeypatch.setattr(adapters, '_pid_window', lambda _: 1)
    monkeypatch.setattr(ImageGrab, 'grab', lambda *a, **k: pytest.fail('a covered window must not use the compositor'))
    sizes = []
    def print_window(hwnd, w, h):
        sizes.append((hwnd, w, h))
        return surface
    monkeypatch.setattr(adapters, '_print_window_png', print_window)
    return sizes


def png(color='blue'):
    buf = io.BytesIO()
    Image.new('RGB', (40, 30), color).save(buf, 'PNG')
    return buf.getvalue()


def test_covered_window_returns_its_own_surface_with_coverage(monkeypatch, tmp_path):
    data = png()
    sizes = covered_window(monkeypatch, tmp_path, data)
    assert adapters.win_grab(123) == data
    assert sizes == [(1, 40, 30)]
    assert adapters.win_grab_state() == {'pid': 123, 'covered': 9, 'source': adapters.WINDOW_SURFACE,
                                         'frame_age_s': 0, 'sha256': hashlib.sha256(data).hexdigest()}


def test_covered_window_without_surface_still_reports_occlusion(monkeypatch, tmp_path):
    covered_window(monkeypatch, tmp_path, None)
    with pytest.raises(RuntimeError, match='covered by another app'):
        adapters.win_grab(123)
    assert adapters.win_grab_state() == {}


def test_print_window_bitmap_rejects_empty_and_encodes_bgra():
    assert adapters.print_window_bitmap_png(bytes(4 * 6), 3, 2) is None          # all black: nothing rendered
    assert adapters.print_window_bitmap_png(b'\x00' * 7, 3, 2) is None             # truncated
    bgra = bytes([255, 0, 0, 0]) + bytes([0, 0, 255, 0]) + bytes(16)               # blue, red, black...
    image = Image.open(io.BytesIO(adapters.print_window_bitmap_png(bgra, 3, 2)))
    assert image.size == (3, 2) and image.getpixel((0, 0)) == (0, 0, 255) and image.getpixel((1, 0)) == (255, 0, 0)


def test_print_window_without_win32_is_none(monkeypatch):
    assert adapters._print_window_png(1, 0, 0) is None
    monkeypatch.delattr(ctypes, 'windll', raising=False)
    assert adapters._print_window_png(1, 10, 10) is None


def surface_incident(cfg, colors, coverage, sources):
    incident, calls = make_incident(cfg, colors, covered_points=coverage)
    run, it = incident.run_job, iter(sources)
    def tagged(tool, data, wid, wait):
        out = run(tool, data, wid, wait)
        if tool == 'get_frame':
            source = next(it, None)
            if source:
                out['capture_source'] = source
        return out
    incident.run_job = tagged
    return incident


def test_covered_window_surface_frames_prove_motion(cfg):
    incident = surface_incident(cfg, ['red', 'green', 'blue', 'white'], [9] * 4, ['window-surface'] * 4)
    assert incident.observe() == {'visible': True, 'motion': True}
    texts = [m['text'] for m in incident.store.get('request', incident.rid)['messages']
             if m.get('task_step', {}).get('action') == 'verify recovery frame']
    assert texts and "emulator's own window" in texts[0]


def test_static_covered_surface_is_visible_but_not_motion(cfg):
    incident = surface_incident(cfg, ['white'] * 4, [9] * 4, ['window-surface'] * 4)
    assert incident.observe() == {'visible': True, 'motion': False, 'errors': []}


def test_surface_and_screen_frames_are_never_compared(cfg):
    # The game appears to change only because the capture method changed.
    incident = surface_incident(cfg, ['red', 'white', 'red', 'white'], [9, 0, 9, 0],
                                ['window-surface', 'desktop-compositor', 'window-surface', 'desktop-compositor'])
    assert incident.observe()['motion'] is False


def test_compositor_covered_frames_still_do_not_prove_recovery(cfg):
    incident = surface_incident(cfg, ['red', 'green', 'blue', 'white'], [9] * 4, ['desktop-compositor'] * 4)
    observed = incident.observe()
    assert observed['visible'] is False and observed['motion'] is False


@pytest.mark.parametrize('source,covered',[(None,0),('cxbx-print-window',0),
    ('cxbx-print-window',9),('cxbx-desktop-compositor',0)])
def test_cxbx_popup_or_unverified_motion_never_proves_recovery(cfg,source,covered):
    incident=surface_incident(cfg,['red','green','blue','white'],[covered]*4,[source]*4)
    incident.session['adapter']='cxbx'
    observed=incident.observe()
    assert observed['visible'] is False and observed['motion'] is False
    assert observed['errors'] and 'unverified' in observed['errors'][0]
    messages=incident.store.get('request',incident.rid)['messages']
    captures=[m for m in messages if m.get('attachments')]
    assert len(captures)==4 and all('diagnostic capture' in m['text'] for m in captures)
