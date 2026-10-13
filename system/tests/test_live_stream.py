"""Report #1523: the operator's MJPEG game view went black while the emulator kept running."""
import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from gbox.live_stream import mjpeg_parts, part

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def live(frame=None, seq=0):
    return {"frame": frame, "seq": seq, "cond": threading.Condition()}


def test_paused_source_keeps_response_open_with_keepalive_frames():
    clock, lv = Clock(), live(b"\xff\xd8A\xff\xd9", 1)
    lv["cond"].wait_for = lambda pred, timeout: (setattr(clock, "t", clock.t + timeout), pred())[1]
    gen = mjpeg_parts(lv, keepalive=2.0, idle_limit=600.0, clock=clock)
    assert next(gen) == part(lv["frame"])
    # The old generator ended after 30 s without a new frame; the browser <img> then stayed dead.
    repeats = [next(gen) for _ in range(30)]
    assert all(r == part(lv["frame"]) for r in repeats)
    assert clock.t >= 60.0


def test_new_frames_are_streamed_and_ended_session_stops_stream():
    clock, lv, state = Clock(), live(), {"alive": True}

    def wait_for(pred, timeout):
        clock.t += timeout
        if lv["frame"] is None:
            lv["frame"], lv["seq"] = b"\xff\xd8B\xff\xd9", 1
        return pred()
    lv["cond"].wait_for = wait_for
    gen = mjpeg_parts(lv, keepalive=2.0, alive=lambda: state["alive"], clock=clock)
    assert next(gen) == part(b"\xff\xd8B\xff\xd9")
    lv["frame"], lv["seq"] = b"\xff\xd8C\xff\xd9", 2
    assert next(gen) == part(b"\xff\xd8C\xff\xd9")
    state["alive"] = False
    assert list(gen) == []


def test_long_silent_source_eventually_ends_for_client_reconnect():
    clock, lv = Clock(), live(b"\xff\xd8D\xff\xd9", 1)
    lv["cond"].wait_for = lambda pred, timeout: (setattr(clock, "t", clock.t + timeout), pred())[1]
    out = list(mjpeg_parts(lv, keepalive=2.0, idle_limit=20.0, clock=clock))
    assert out[0] == part(lv["frame"]) and 5 <= len(out) <= 12


def test_web_client_loads_stream_watchdog():
    html = (ROOT / "clients/web/index.html").read_text(encoding="utf-8")
    assert '<script src="/viz/stream-watchdog.js"></script>' in html


NODE = shutil.which("node") or next(iter(sorted(Path.home().glob(".hermes/tools/node-*/bin/node"))), None)


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_watchdog_reconnects_errored_and_blank_streams():
    script = r"""
const w = require(process.argv[1]);
let t = 0; const timers = [];
const setTimer = (fn, ms) => timers.push([t + ms, fn]);
const run = until => { while (true) { timers.sort((a, b) => a[0] - b[0]); if (!timers.length || timers[0][0] > until) break; const [at, fn] = timers.shift(); t = at; fn(); } t = until; };
const img = src => ({ tagName: 'IMG', isConnected: true, naturalWidth: 0, a: { src }, getAttribute(k) { return this.a[k]; }, setAttribute(k, v) { this.a[k] = v; } });
const errored = img('/api/sessions/w-s/mjpeg?token=x'), blank = img('/api/sessions/w-s2/mjpeg?token=y'),
      ok = img('/api/sessions/w-s3/mjpeg?token=z'), art = img('/api/media/g/best');
ok.naturalWidth = 640;
const listeners = {};
const doc = { addEventListener: (k, fn) => listeners[k] = fn, querySelectorAll: () => [errored, blank, ok, art] };
const dog = w.createStreamWatchdog({ doc, setTimer, now: () => t, interval: 4000, blankAfter: 8000 });
dog.start();
listeners.error({ target: errored }); listeners.error({ target: errored });
listeners.error({ target: art });
run(1500);
const afterError = errored.a.src;
run(20000);   // first seen at the 4 s sweep, blank for 8 s, reattached after the 1 s backoff
console.log(JSON.stringify({ afterError, blank: blank.a.src, ok: ok.a.src, art: art.a.src,
  url: w.reconnectUrl('/api/sessions/a-b/mjpeg?token=t&reconnect=1', 2) }));
"""
    out = subprocess.run([str(NODE), "-e", script, str(ROOT / "clients/web/viz/stream-watchdog.js")],
                         capture_output=True, text=True, timeout=30, check=True).stdout
    r = json.loads(out.strip().splitlines()[-1])
    assert r["afterError"] == "/api/sessions/w-s/mjpeg?token=x&reconnect=1"   # one reconnect for duplicate errors
    assert "reconnect=" in r["blank"]                                        # never got a picture: reattached
    assert r["ok"] == "/api/sessions/w-s3/mjpeg?token=z"                     # healthy view untouched
    assert r["art"] == "/api/media/g/best"                                   # non-stream images ignored
    assert r["url"] == "/api/sessions/a-b/mjpeg?token=t&reconnect=2"
