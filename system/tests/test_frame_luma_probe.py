"""#1546: a brightness probe must never fail a capture, and mean_luma must be full range (black ~0).

The PSO observer's get_frame job dcad3153a9564007 failed with "TimeoutExpired: ffmpeg ... signalstats ... timed out
after 30 seconds" on the operator PC, so the read-only observation had no frame. ffmpeg's YAVG is also
limited-range for RGB PNGs (black 16, white 235), so the server's `< 6` / `<= 3` black-screen guards never fired.
"""
import io
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image

from gbox import tools


def png(mode='RGB', size=(64, 48), color=(0, 0, 0)):
    stream = io.BytesIO()
    Image.new(mode, size, color).save(stream, format='PNG')
    return stream.getvalue()


def gradient_png():
    g = Image.linear_gradient('L').resize((160, 120))
    stream = io.BytesIO()
    Image.merge('RGB', (g, g.transpose(Image.Transpose.ROTATE_90).resize((160, 120)), Image.new('L', (160, 120), 77))
                ).save(stream, format='PNG')
    return stream.getvalue()


def no_subprocess(*args, **kwargs):
    raise AssertionError('mean_luma must not spawn a process when Pillow can decode the frame')


@pytest.mark.parametrize('mode, color, expected', [
    ('RGB', (0, 0, 0), 0.0), ('RGB', (255, 255, 255), 255.0), ('RGB', (128, 128, 128), 128.0),
    ('RGB', (255, 0, 0), 76.0), ('RGBA', (0, 0, 0, 255), 0.0), ('L', 100, 100.0), ('P', 7, None)])
def test_mean_luma_is_full_range_and_in_process(monkeypatch, mode, color, expected):
    monkeypatch.setattr(tools.subprocess, 'run', no_subprocess)
    data = png(mode, color=color)
    value = tools.mean_luma(data)
    if expected is None:                           # palette entry 7 of Pillow's default palette, via its RGB value
        r, g, b = Image.open(io.BytesIO(data)).convert('RGB').getpixel((0, 0))
        expected = round((r * 299 + g * 587 + b * 114) / 1000)
    assert value == pytest.approx(expected, abs=0.6)


def test_observed_all_black_pso_frame_now_trips_black_screen_guards(monkeypatch):
    # The observer's 960x659 PSO frame 6e0062e5... was all zero pixels; ffmpeg reported YAVG 16.0 for it.
    monkeypatch.setattr(tools.subprocess, 'run', no_subprocess)
    black = tools.mean_luma(png(size=(960, 659)))
    assert black == 0.0 and black < 6 and black <= 3          # server.py mod-picture and swap-verification guards
    assert tools.mean_luma(gradient_png()) > 6


def test_get_frame_succeeds_when_the_luma_probe_times_out(monkeypatch):
    data = png(color=(10, 20, 30))
    ad = SimpleNamespace(proc=None, get_frame=lambda: data)
    monkeypatch.setitem(tools.SESSIONS, 'pso-observer', (ad, {'game_id': '436e0bb84d5337d1'}))
    monkeypatch.setattr(tools, 'HOST_OS', 'linux')
    monkeypatch.setattr(Image, 'open', lambda *a, **k: (_ for _ in ()).throw(OSError('simulated decoder failure')))
    monkeypatch.setattr(tools.shutil, 'which', lambda name: '/usr/bin/ffmpeg')
    calls = []

    def hung_ffmpeg(cmd, **kwargs):
        calls.append((cmd, kwargs))
        raise subprocess.TimeoutExpired(cmd, kwargs.get('timeout'))
    monkeypatch.setattr(tools.subprocess, 'run', hung_ffmpeg)
    artifacts = []
    ctx = SimpleNamespace(artifact=lambda *args, **kwargs: artifacts.append((args, kwargs)))
    out = tools.FrameOut.model_validate(tools.get_frame(tools.FrameIn(session_id='pso-observer'), ctx))
    assert out.mean_luma is None and (out.width, out.height) == (64, 48)
    assert artifacts[0][0][:2] == ('frame.png', data) and tools._png_validate(out, {'frame.png': data}) == []
    (cmd, kwargs), = calls
    assert '-nostdin' in cmd and kwargs['stdin'] is subprocess.DEVNULL and kwargs['timeout'] <= 10


@pytest.mark.parametrize('stderr, mode, expected', [
    ('[Parsed_metadata_1 @ 0x1] lavfi.signalstats.YAVG=16.000000', 'RGB', 0.0),
    ('lavfi.signalstats.YAVG=235', 'RGB', 255.0),
    ('lavfi.signalstats.YAVG=100.000000', 'L', 100.0),         # grey PNGs already measure full range
    ('lavfi.signalstats.YAVG=garbage', 'RGB', None),
    ('no statistics', 'RGB', None)])
def test_ffmpeg_fallback_is_hardened_and_full_range(monkeypatch, stderr, mode, expected):
    monkeypatch.setattr(tools.shutil, 'which', lambda name: '/usr/bin/ffmpeg')
    monkeypatch.setattr(tools.subprocess, 'run',
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, '', stderr))
    assert tools._ffmpeg_luma(png(mode, color=0 if mode == 'L' else (0, 0, 0))) == expected


def test_ffmpeg_fallback_without_ffmpeg_or_png_is_none(monkeypatch):
    monkeypatch.setattr(tools.subprocess, 'run', no_subprocess)
    monkeypatch.setattr(tools.shutil, 'which', lambda name: None)
    assert tools._ffmpeg_luma(png()) is None
    monkeypatch.setattr(tools.shutil, 'which', lambda name: '/usr/bin/ffmpeg')
    assert tools._ffmpeg_luma(b'not a png') is None


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='real ffmpeg not on PATH')
@pytest.mark.parametrize('data', [png(color=(0, 0, 0)), png(color=(255, 255, 255)), png(color=(0, 0, 255)),
                                  png('L', color=100), gradient_png()])
def test_real_ffmpeg_fallback_agrees_with_pillow(data):
    assert tools._ffmpeg_luma(data) == pytest.approx(tools.mean_luma(data), abs=1.5)
