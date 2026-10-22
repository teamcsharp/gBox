"""#2950: RPCS3Adapter.get_frame must not depend on a 30 s ffmpeg gdigrab desktop grab."""
from types import SimpleNamespace

from gbox import adapters
from gbox.config import Config


def _ad(tmp_path):
    ad = adapters.RPCS3Adapter(Config(data_dir=tmp_path))
    ad.proc = SimpleNamespace(pid=4242, poll=lambda: None)
    return ad


def test_windows_uses_win_grab_not_gdigrab(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, "HOST_OS", "windows")
    monkeypatch.setattr(adapters, "win_grab", lambda pid: b"\x89PNG-win%d" % pid)
    monkeypatch.setattr(adapters, "grab_png", lambda *a, **k: (_ for _ in ()).throw(AssertionError("gdigrab used")))
    assert _ad(tmp_path).get_frame() == b"\x89PNG-win4242"


def test_falls_back_to_gdigrab_and_records_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, "HOST_OS", "windows")

    def boom(pid):
        raise RuntimeError("the game window isn't open")
    monkeypatch.setattr(adapters, "win_grab", boom)
    monkeypatch.setattr(adapters, "grab_png", lambda display, region=None: b"fallback")
    ad = _ad(tmp_path)
    assert ad.get_frame() == b"fallback"
    assert "isn't open" in ad.frame_fallback_reason


def test_linux_keeps_desktop_grab(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, "HOST_OS", "linux")
    monkeypatch.setattr(adapters, "win_grab", lambda pid: (_ for _ in ()).throw(AssertionError("win_grab on linux")))
    monkeypatch.setattr(adapters, "grab_png", lambda display, region=None: b"x11")
    assert _ad(tmp_path).get_frame() == b"x11"
