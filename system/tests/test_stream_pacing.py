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


def test_viewer_frame_rate_cap_sends_the_newest_frame_at_most_that_often():
    # operator 2026-10-27: the desktop PiP over Wi-Fi played for seconds, then stopped; a 57 fps source of 32 KB JPEGs is
    # ~15 Mbps per viewer, and the PiP asks for 30 (GET /api/sessions/{sid}/mjpeg?fps=30)
    async def run():
        lv, clock, slept = live(), [0.0], []

        async def sleep(seconds):
            slept.append(seconds)
            clock[0] += seconds + 1e-6
        gen = live_stream.async_mjpeg_parts(lv, clock=lambda: clock[0], max_fps=30, sleep=sleep)
        assert await anext(gen) == live_stream.part(b"first")          # the first picture at once
        clock[0] += .010; publish(lv, b"2", 2)
        clock[0] += .005; publish(lv, b"3", 3)                         # two pictures inside one 1/30 s step
        assert await anext(gen) == live_stream.part(b"3")               # the step waited out, then the newest
        assert slept == [pytest.approx(1 / 30 - .015)]
        assert lv["viewer_skips"] == 1 and lv["viewer_frames"] == 2
        clock[0] += .050; publish(lv, b"4", 4)                         # a picture a full step later: no wait
        assert await anext(gen) == live_stream.part(b"4")
        assert len(slept) == 1
        await gen.aclose()
        assert not lv["async_waiters"]
    asyncio.run(run())


def test_uncapped_viewer_still_gets_every_picture_it_can_take():
    async def run():
        lv, slept = live(), []

        async def sleep(seconds):
            slept.append(seconds)
        gen = live_stream.async_mjpeg_parts(lv, max_fps=0, sleep=sleep)
        assert await anext(gen) == live_stream.part(b"first")
        for seq in range(2, 6):
            publish(lv, str(seq).encode(), seq)
            assert await anext(gen) == live_stream.part(str(seq).encode())
        assert slept == [] and lv.get("viewer_skips", 0) == 0
        await gen.aclose()
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


def test_background_state_refresh_cannot_hold_frames_behind_a_slow_store():
    async def run():
        lv, clock = live(), [0.]
        released, started = asyncio.Event(), asyncio.Event()
        calls = []
        async def read_alive():
            calls.append(1)
            if len(calls)==1:
                return True
            started.set()
            await released.wait()
            return False
        check=live_stream.BackgroundCheck(read_alive)
        gen=live_stream.async_mjpeg_parts(lv,alive=check,clock=lambda:clock[0])
        assert await anext(gen)==live_stream.part(b'first')
        clock[0]=1.1;publish(lv,b'second',2)
        assert await asyncio.wait_for(anext(gen),.1)==live_stream.part(b'second')
        await started.wait()
        for seq in range(3,8):
            clock[0]+=1.1;publish(lv,str(seq).encode(),seq)
            assert await asyncio.wait_for(anext(gen),.1)==live_stream.part(str(seq).encode())
        assert len(calls)==2, 'a blocked state lookup must remain a single pending operation'
        released.set()
        await asyncio.sleep(0)
        clock[0]+=1.1
        with pytest.raises(StopAsyncIteration):await anext(gen)
        assert not lv['async_waiters']
        check.close()
    asyncio.run(run())


def test_background_state_initial_read_still_rejects_an_ended_session():
    async def run():
        async def ended():return False
        check=live_stream.BackgroundCheck(ended)
        assert [part async for part in live_stream.async_mjpeg_parts(live(),alive=check)]==[]
        check.close()
    asyncio.run(run())


def test_background_watch_renewal_coalesces_and_clear_follows_pending_write():
    async def run():
        released, started = asyncio.Event(), asyncio.Event()
        calls=[]
        async def renew():
            calls.append('renew started');started.set();await released.wait();calls.append('renew done')
        async def clear():calls.append('clear')
        lease=live_stream.BackgroundLease(renew,clear)
        assert lease.renew()
        await started.wait()
        assert not lease.renew()
        closing=asyncio.create_task(lease.close())
        await asyncio.sleep(0)
        assert not closing.done() and not lease.renew()
        released.set();await closing
        assert calls==['renew started','renew done','clear']
    asyncio.run(run())


def test_cancelled_view_still_clears_watch_after_a_delayed_renewal():
    async def run():
        released,started=asyncio.Event(),asyncio.Event()
        calls=[]
        async def renew():
            started.set();await released.wait();calls.append('renew')
        async def clear():calls.append('clear')
        lease=live_stream.BackgroundLease(renew,clear)
        lease.renew();await started.wait()
        closing=asyncio.create_task(lease.close());await asyncio.sleep(0)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):await closing
        released.set()
        for _ in range(5):await asyncio.sleep(0)
        assert calls==['renew','clear']
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
