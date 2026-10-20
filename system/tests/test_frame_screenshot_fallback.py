"""A black or failed Windows window grab falls back to RetroArch's own SCREENSHOT (2026-10-19, i9-NUC: one identical
black frame for every game while its display slept)."""
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from gbox import adapters as A


def _png(color):
    out = io.BytesIO()
    Image.new("RGB", (32, 24), color).save(out, "PNG")
    return out.getvalue()


BLACK, GAME, SHOT = _png((2, 2, 2)), _png((90, 140, 60)), _png((200, 30, 30))


def _adapter(tmp_path, shot=SHOT):
    me = SimpleNamespace(proc=SimpleNamespace(pid=42), config=SimpleNamespace(runtime=tmp_path),
                         capture_backend=None, states_override=None, calls=[])

    def screenshot(folder, timeout=6.0):
        me.calls.append(folder)
        if shot is None:
            raise RuntimeError("RetroArch did not write a screenshot")
        return shot
    me._screenshot = screenshot
    return me


def test_black_grab_uses_retroarch_screenshot(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "HOST_OS", "windows")
    monkeypatch.setattr(A, "win_grab", lambda pid: BLACK)
    me = _adapter(tmp_path)
    assert A.RetroArchAdapter.get_frame(me) == SHOT
    assert me.calls == [tmp_path / "screenshots"]
    assert A._last_grab["source"] == "retroarch-screenshot" and A._last_grab["fallback_reason"] == "black window grab"


def test_a_real_frame_is_kept_and_no_screenshot_taken(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "HOST_OS", "windows")
    monkeypatch.setattr(A, "win_grab", lambda pid: GAME)
    me = _adapter(tmp_path)
    assert A.RetroArchAdapter.get_frame(me) == GAME and me.calls == []


def test_failed_grab_and_failed_screenshot_report_the_grab_error(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "HOST_OS", "windows")

    def gone(pid):
        raise RuntimeError("the game window isn't open")
    monkeypatch.setattr(A, "win_grab", gone)
    with pytest.raises(RuntimeError, match="window isn't open"):
        A.RetroArchAdapter.get_frame(_adapter(tmp_path, shot=None))
    monkeypatch.setattr(A, "win_grab", lambda pid: BLACK)
    assert A.RetroArchAdapter.get_frame(_adapter(tmp_path, shot=None)) == BLACK, "the black grab beats no frame"


def test_frame_is_black():
    assert A.frame_is_black(BLACK) and not A.frame_is_black(GAME) and not A.frame_is_black(b"not a png")
