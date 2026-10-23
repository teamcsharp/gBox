"""A slow viewer skips old pictures and cannot queue frames or starve another viewer."""
import asyncio
import io
import shutil
import subprocess
import threading

import pytest

from gbox import adapters, live_stream


def live():
    return {"frame": b"first", "seq": 1, "cond": threading.Condition()}


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg is not installed')
def test_production_encoder_tolerates_duplicate_capture_timestamps():
    # X11 can repeat a PTS under host pressure. Pass actual production output options through a deterministic
    # duplicate-PTS source; passthrough timestamps fail with Invalid pts/exit255 after only a few pictures.
    encoder = type('Encoder', (), {'stdout': io.BytesIO(), 'poll': lambda self: 0})()
    stream = adapters.MjpegStream(':91', popen=lambda argv: encoder, kill=lambda proc: None, supervise=False)
    argv = list(stream.argv)
    start, end = argv.index('-f'), argv.index('-vf')
    argv[start:end] = ['-f', 'lavfi', '-i', 'color=black:s=64x64:r=60,setpts=floor(N/2)']
    argv[-1:-1] = ['-frames:v', '20']
    result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    stream.close()
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert result.stdout.count(b'\xff\xd8') == 20


def publish(lv, frame, seq):
    with lv["cond"]:
        lv["frame"], lv["seq"] = frame, seq
        live_stream.notify_frame(lv)


def test_backpressured_viewer_reads_newest_picture_without_a_frame_queue():
    async def run():
        lv = live()
        gen = live_stream.async_mjpeg_parts(lv)
        assert await anext(gen) == live_stream.part(b"first")
        # The HTTP send is blocked while a whole second of source pictures arrives.
        for seq in range(2, 62):
            publish(lv, str(seq).encode(), seq)
        assert await anext(gen) == live_stream.part(b"61")
        assert lv["viewer_skips"] == 59
        assert lv["viewer_frames"] == 2
        await gen.aclose()
        assert not lv["async_waiters"]
    asyncio.run(run())


def test_fast_viewer_receives_frames_while_other_viewer_is_backpressured():
    async def run():
        lv = live()
        slow, fast = (live_stream.async_mjpeg_parts(lv) for _ in range(2))
        await anext(slow)
        await anext(fast)
        pending = asyncio.create_task(anext(fast))
        await asyncio.sleep(0)
        publish(lv, b"next", 2)
        assert await asyncio.wait_for(pending, .5) == live_stream.part(b"next")
        assert len(lv["async_waiters"]) == 2
        await slow.aclose()
        await fast.aclose()
        assert not lv["async_waiters"]
    asyncio.run(run())


def test_cancelled_waiting_view_unregisters_without_waiting_for_a_source_frame():
    async def run():
        lv = live()
        gen = live_stream.async_mjpeg_parts(lv)
        await anext(gen)
        pending = asyncio.create_task(anext(gen))
        await asyncio.sleep(0)
        pending.cancel()
        try:
            await pending
        except asyncio.CancelledError:
            pass
        assert not lv["async_waiters"]
    asyncio.run(run())


def test_async_stream_repeats_last_picture_while_paused_and_ends_at_source_limit():
    async def run():
        lv = live()
        gen = live_stream.async_mjpeg_parts(lv, keepalive=.005, idle_limit=.025, wait=.005)
        frames = [frame async for frame in gen]
        assert 3 <= len(frames) <= 10
        assert all(frame == live_stream.part(b"first") for frame in frames)
        assert not lv["async_waiters"]
    asyncio.run(run())


def test_async_alive_check_can_await_store_lookup_and_stops_ended_session():
    async def run():
        lv = live()
        async def ended():
            await asyncio.sleep(0)
            return False
        assert [frame async for frame in live_stream.async_mjpeg_parts(lv, alive=ended)] == []
        assert not lv["async_waiters"]
    asyncio.run(run())


def test_source_pacing_reports_short_stutters_and_keeps_bounded_samples():
    lv = {"ts": 100.0}
    for gap in [1 / 60] * 29 + [.350]:
        now = lv["ts"] + gap
        live_stream.meter(lv, now, "stream")
        lv["ts"] = now
    h = live_stream.health(lv, "running", now=lv["ts"])
    assert h["pacing"]["gap_p50_ms"] == 16.67
    assert h["pacing"]["gap_max_ms"] == 350.0
    assert h["pacing"]["gaps_over_100ms"] == 1
    for _ in range(1000):
        now = lv["ts"] + 1 / 60
        live_stream.meter(lv, now, "stream")
        lv["ts"] = now
    assert live_stream.health(lv, "running")["pacing"]["samples"] == 600
