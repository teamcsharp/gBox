"""adapters.grab_png on linux: the in-process X11 grab first, callers sharing one grab, ffmpeg (one thread) as fallback.

2026-11-10: a poller on lilspark started ~5 `ffmpeg -frames:v 1` a second, each 240-887% CPU (~10 cores in all)."""
from gbox import adapters as A


def test_the_inprocess_grab_is_used_and_shared_by_close_callers(monkeypatch):
    calls = []
    monkeypatch.setattr(A, "HOST_OS", "linux")
    monkeypatch.setattr(A, "_GRABS", {})
    monkeypatch.setattr(A, "_x11_grab_inprocess", lambda disp, region: calls.append((disp, region)) or b"PNG")
    ran = []
    monkeypatch.setattr(A.subprocess, "run", lambda *a, **k: ran.append(a))
    assert A.grab_png(":92") == b"PNG" and A.grab_png(":92") == b"PNG"
    assert calls == [(":92", None)] and not ran                 # one grab for both, no ffmpeg at all
    A._GRABS[(":92", None)] = (A.time.monotonic() - 1.0, b"OLD")
    assert A.grab_png(":92") == b"PNG" and len(calls) == 2       # an older picture is grabbed again
    assert A.grab_png(":92", [0, 0, 64, 32]) == b"PNG" and calls[-1] == (":92", [0, 0, 64, 32])


def test_a_display_that_refuses_the_inprocess_grab_falls_back_to_one_thread_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "HOST_OS", "linux")
    monkeypatch.setattr(A, "_GRABS", {})
    monkeypatch.setattr(A, "_x11_grab_inprocess", lambda disp, region: None)
    monkeypatch.setattr(A.tempfile, "mkdtemp", lambda: str(tmp_path))
    seen = []

    def run(cmd, **kw):
        seen.append(cmd)
        (tmp_path / "frame.png").write_bytes(b"FF")
    monkeypatch.setattr(A.subprocess, "run", run)
    assert A.grab_png(":100") == b"FF"
    assert seen and seen[0][:5] == ["ffmpeg", "-loglevel", "error", "-threads", "1"] and ":100" in seen[0]
