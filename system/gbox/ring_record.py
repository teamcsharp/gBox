"""Background gameplay ring recording (#1084): clip the last three minutes of play after the fact.

While the operator's pad was used within the last `idle_s` (20 s), the worker records the session's picture into a
ring of short MPEG-TS segments on local disk (ffmpeg's segment muxer with -segment_wrap); 20 s without pad activity
stops ffmpeg, the next press starts it again. A live autoplay controller also keeps its ring active. Idle sessions
cost nothing. `export(in_s, out_s, target_mb)` picks the segments covering the range, concatenates them,
trims to the exact range and re-encodes to the requested file size (an MP4 artifact the client offers or attaches).

    capture   Windows: gdigrab of the emulator window's area on screen (what win_grab's desktop path shows), the
              window's own surface (hwnd= / title=) when it is parked off-screen, or ddagrab (GPU zero-copy) when
              [recording] capture = "ddagrab" and NVENC is in use. The Spark: x11grab of the session's Xvfb display.
    encoder   h264_nvenc when this ffmpeg has it AND a test encode works (the NVIDIA GPU does the work; the RGB->YUV
              conversion happens there too), else libx264 ultrafast with 2 threads. The choice and why is reported.
    activity  the pad signal gBox already has, no second poller: on Windows padstate.watch_xinput's PLAYER_TOUCH (the
              XInput poll that feeds the controller glyph); streamed sessions (the Spark) the operator's pad events
              passing through tools._pump (touch(), called next to rewind.feed). Events without a `player` number
              (agent, autoplay, on-screen buttons) do not count.
    disk      at most `seconds` (+ one segment) and `max_mb` per ring; ffmpeg itself wraps within a run and the ring
              deletes the oldest segments across runs. Rings of ended sessions are kept (keep_ended, default 1) so a
              crash can still be clipped, and swept on the next worker start.

The ring is cheap on purpose (the Spark's checkpoint ring stalled Flycast): ffmpeg runs at below-normal priority,
one monitor thread ticks once a second and reads ffmpeg's segment list incrementally; no frame passes through Python.
Docs: docs/ring_recording.md.
"""
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .config import HOST_OS

TS_PACKET = 188
HEIGHTS = (1080, 900, 720, 540, 480, 360, 240)      # export resolution steps when the size target leaves too few bits
MIN_BPP = 0.04                                      # H.264 bits per pixel per frame below which the picture turns to mush
MP4_OVERHEAD = 0.03                                 # container share of the file the bitrate math leaves free
MIN_KBPS, MAX_TARGET_MB = 150, 200
NVENC = ("h264_nvenc", "hevc_nvenc")

ACTIVE: dict[str, "SessionRing"] = {}               # live and recently ended sessions (worker process)
ENDED: list[str] = []                               # ended session ids, oldest first (bounded by keep_ended)
TOUCH: dict[str, float] = {}                        # sid -> last operator pad event seen on the streamed input channel
_ENCODERS: dict[tuple, dict] = {}                   # (ffmpeg, preference) -> pick_encoder result (one test encode per run)
_LOCK = threading.Lock()


def ffmpeg_cmd() -> list[str]:
    return [_unshim(os.environ.get("GBOX_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg")]


def _unshim(path: str) -> str:
    """Chocolatey's ffmpeg on PATH is a shim that starts the real ffmpeg as a child: 'q' and a kill would reach the
    shim only (the capture would be orphaned). Use the real executable behind it."""
    p = Path(path)
    if p.parent.name.lower() == "bin" and p.parent.parent.name.lower() == "chocolatey":
        for real in sorted((p.parent.parent / "lib").glob("ffmpeg*/tools/ffmpeg*/bin/ffmpeg.exe")):
            return str(real)
    return path


# --- pad activity --------------------------------------------------------------------------------

def touch(sid: str, events, now: float | None = None) -> bool:
    """Streamed pad events (tools._pump): the operator's own pad carries a player number; gBox's presses do not."""
    for ev in events or []:
        if isinstance(ev, dict) and "rpc" not in ev and "player" in ev and (ev.get("key") or ev.get("stick")):
            TOUCH[sid] = time.time() if now is None else now
            return True
    return False


def last_touch(sid: str) -> float:
    t = TOUCH.get(sid, 0.0)
    try:
        from .padstate import PLAYER_TOUCH            # Windows: watch_xinput's XInput poll (the controller glyph's)
        t = max(t, PLAYER_TOUCH.get(sid, 0.0))
    except Exception:                                  # noqa: BLE001
        pass
    return t


def autoplay_active(sid: str) -> bool:
    """The worker's actual live controller, without importing its tool registry."""
    module = sys.modules.get('gbox.tools')
    run = getattr(module, 'AUTOPLAY', {}).get(sid) if module else None
    thread = (run or {}).get('thread')
    return bool(thread is not None and thread.is_alive() and not getattr((run or {}).get('driver'), 'stopped', False))


def audio_tap_for(ad, process_pid=None):
    """Copy one owned emulator playback stream; absence is reported, never replaced by a mic or mix."""
    if HOST_OS == 'windows':
        return None  # no verified process-loopback capture on Windows; do not record the desktop mix
    from .broadcast import AudioTap, sink_input_for
    display = getattr(getattr(ad, 'display', None), 'name', '')
    pid = process_pid or getattr(getattr(ad, 'proc', None), 'pid', None)
    index = sink_input_for(display, pid=pid)
    return AudioTap(index) if index is not None else None


# --- encoder choice ------------------------------------------------------------------------------

def _run(run, argv, timeout=20):
    try:
        return run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(argv, 1, "", f"{type(exc).__name__}: {exc}")


def pick_encoder(pref: str = "auto", ffmpeg: list[str] | None = None, run=subprocess.run, cache: bool = True) -> dict:
    """{"encoder", "requested", "gpu", "note"}: NVENC when listed and a 5-frame test encode passes, else libx264."""
    ffmpeg = list(ffmpeg or ffmpeg_cmd())
    pref = (pref or "auto").strip().lower()
    key = (tuple(ffmpeg), pref)
    if cache and key in _ENCODERS:
        return dict(_ENCODERS[key])
    if pref == "libx264":
        out = {"encoder": "libx264", "requested": pref, "gpu": False, "note": "libx264 (CPU), as configured"}
    else:
        want = "h264_nvenc" if pref == "auto" else pref
        listing = _run(run, [*ffmpeg, "-hide_banner", "-encoders"])
        if want not in (listing.stdout or ""):
            why = f"{want} is not in this ffmpeg build"
        else:
            probe = _run(run, [*ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=256x144:r=30",
                               "-frames:v", "5", "-c:v", want, "-f", "null", "-"])
            if probe.returncode == 0:
                why = None
            else:
                tail = ((probe.stderr or "").strip().splitlines() or ["no error text"])[-1][:200]
                why = f"{want} failed its test encode ({tail})"
        out = ({"encoder": want, "requested": pref, "gpu": True, "note": f"{want} (NVIDIA GPU)"} if why is None else
               {"encoder": "libx264", "requested": pref, "gpu": False, "note": f"libx264 (CPU): {why}"})
    if cache:
        _ENCODERS[key] = dict(out)
    return out


def encoder_args(encoder: str, kbps: int, fps: int, gop: int | None = None, live: bool = True) -> list[str]:
    """Rate-controlled encode. live: the ring (fastest settings); else the export (quality settings, same bitrate)."""
    k = max(1, int(kbps))
    rate = ["-b:v", f"{k}k", "-maxrate", f"{k}k", "-bufsize", f"{2 * k}k"]
    gop_args = ["-g", str(gop)] if gop else []
    if encoder in NVENC:
        return ["-c:v", encoder, "-preset", "p1" if live else "p5", *(["-tune", "ll"] if live else []), "-rc", "cbr", *rate,
                *gop_args, "-bf", "0" if live else "2", *([] if live else ["-pix_fmt", "yuv420p"])]
    return ["-c:v", "libx264", "-preset", "ultrafast" if live else "veryfast", *(["-tune", "zerolatency"] if live else []),
            "-threads", "2", "-pix_fmt", "yuv420p", *rate, *gop_args,
            *(["-sc_threshold", "0"] if live else [])]


# --- size math -----------------------------------------------------------------------------------

def video_kbps(target_mb: float, seconds: float, cap_kbps: int | None = None, audio_kbps: int = 0) -> int:
    """Video bitrate that lands a `seconds` long MP4 at `target_mb` (MiB) with the container's share left free."""
    seconds = max(0.5, float(seconds))
    k = int(float(target_mb) * 8 * 2**20 * (1 - MP4_OVERHEAD) / seconds / 1000) - int(audio_kbps)
    if cap_kbps:
        k = min(k, int(cap_kbps))
    return max(MIN_KBPS, k)


def fit_height(kbps: int, width: int, height: int, fps: int) -> int:
    """The tallest step (never above the source) where kbps still gives MIN_BPP bits per pixel per frame."""
    width, height = max(2, int(width)), max(2, int(height))
    steps = [height] + [h for h in HEIGHTS if h < height]
    for h in steps:
        w = width * h / height
        if kbps * 1000 / (w * h * max(1, fps)) >= MIN_BPP:
            return h - h % 2
    return steps[-1] - steps[-1] % 2


def wrap_count(seconds: float, segment_s: float, kbps: int, max_mb: float) -> int:
    """Segments ffmpeg cycles through within one run: the reach plus margin, never more than max_mb allows."""
    want = math.ceil(float(seconds) / float(segment_s)) + 3
    per_seg = max(1.0, kbps * 125 * float(segment_s))                 # bytes of one segment at the capture bitrate
    fits = int(float(max_mb) * 2**20 // per_seg) if max_mb else want
    return max(3, min(want, fits))


# --- range -> segments ---------------------------------------------------------------------------

def select_range(segments: list[dict], in_s: float | None, out_s: float = 0.0) -> dict:
    """Pieces covering [newest_end - in_s, newest_end - out_s] in recorded time (idle gaps are skipped, not filled).

    segments: oldest first, {"file", "start", "end"} in wall-clock seconds. Returns {"pieces": [{"file", "from", "to"}]
    (offsets inside each segment), "seconds", "in_s", "out_s", "offset" (trim into the first piece)}."""
    segs = [s for s in segments if s["end"] > s["start"]]
    if not segs:
        raise ValueError("nothing recorded yet: the ring records while the controller is in use")
    # recorded time runs backwards from the newest moment, across the idle gaps (gaps are not part of the timeline)
    total = sum(s["end"] - s["start"] for s in segs)
    in_s = total if in_s is None else min(float(in_s), total)
    out_s = max(0.0, float(out_s))
    if in_s - out_s < 0.5:
        raise ValueError(f"the range is empty: in {in_s:.1f} s, out {out_s:.1f} s before the newest moment")
    pieces, back = [], 0.0
    for s in reversed(segs):
        dur = s["end"] - s["start"]
        lo, hi = back, back + dur                               # this segment covers [lo, hi) seconds back
        back = hi
        a, b = max(lo, out_s), min(hi, in_s)
        if b - a <= 1e-6:
            continue
        pieces.append({"file": s["file"], "from": round(hi - b, 3), "to": round(hi - a, 3), "dur": dur})
        if hi >= in_s:
            break
    pieces.reverse()
    return {"pieces": pieces, "seconds": round(in_s - out_s, 3), "in_s": round(in_s, 3), "out_s": round(out_s, 3),
            "offset": pieces[0]["from"]}


def timeline(segments: list[dict]) -> list[list[float]]:
    """[[ago_start, ago_end]] per segment in recorded time back from the newest moment, newest first (the pop-up's bar)."""
    out, back = [], 0.0
    for s in reversed(segments):
        dur = max(0.0, s["end"] - s["start"])
        out.append([round(back + dur, 2), round(back, 2)])
        back += dur
    return out


# --- capture source ------------------------------------------------------------------------------

def window_rect(pid: int):
    """(hwnd, left, top, right, bottom) of the emulator's visible window, or None."""
    if HOST_OS != "windows" or not pid:
        return None
    import ctypes
    from ctypes import wintypes
    from .adapters import _pid_window
    h = _pid_window(int(pid))
    if not h:
        return None
    r = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(h, ctypes.byref(r))
    return int(h), r.left, r.top, r.right, r.bottom


def virtual_screen():
    """(left, top, right, bottom) of the whole desktop, and the primary monitor's (right, bottom)."""
    import ctypes
    m = ctypes.windll.user32.GetSystemMetrics
    x, y = m(76), m(77)
    return (x, y, x + m(78), y + m(79)), (m(0), m(1))


def _even(v: int) -> int:
    return max(2, int(v) - int(v) % 2)


def resolve_source(ad, rc, encoder: str, fps: int, rect_fn=window_rect, screen_fn=virtual_screen, ffmpeg=None,
                   run=subprocess.run) -> dict:
    """{"kind", "args" (ffmpeg input arguments), "size": [w, h], "note"} for this session's picture right now."""
    want = (getattr(rc, "capture", "auto") or "auto").lower()
    disp = getattr(getattr(ad, "display", None), "name", None)
    if disp and (HOST_OS != "windows" or want == "x11grab"):
        w, h = _even(ad.display.w), _even(ad.display.h)
        return {"kind": "x11grab", "size": [w, h], "note": f"session display {disp}",
                "args": ["-f", "x11grab", "-draw_mouse", "0", "-framerate", str(fps), "-video_size", f"{w}x{h}", "-i", disp]}
    if HOST_OS != "windows":
        raise RuntimeError("recording needs a session display (Spark sessions run on their own Xvfb display)")
    pid = getattr(getattr(ad, "proc", None), "pid", None)
    got = rect_fn(pid) if pid else None
    if not got:
        raise RuntimeError("the game window isn't open")
    hwnd, l, t, r, b = got
    (vl, vt, vr, vb), (pw, ph) = screen_fn()
    cl, ct, cr, cb = max(l, vl), max(t, vt), min(r, vr), min(b, vb)       # the part of the window that is on screen
    on_screen = max(0, cr - cl) * max(0, cb - ct)
    whole = max(1, (r - l) * (b - t))
    if on_screen >= 0.5 * whole and cr - cl >= 64 and cb - ct >= 64:
        w, h = _even(cr - cl), _even(cb - ct)
        if want == "ddagrab" and encoder in NVENC and cl >= 0 and ct >= 0 and cl + w <= pw and ct + h <= ph:
            return {"kind": "ddagrab", "size": [w, h], "note": "Desktop Duplication on the GPU (primary monitor)",
                    "args": ["-f", "lavfi", "-i", f"ddagrab=output_idx=0:framerate={fps}:draw_mouse=0:"
                             f"offset_x={cl}:offset_y={ct}:video_size={w}x{h}"]}
        note = "the game window's area on screen" + (" (ddagrab needs NVENC and the primary monitor)" if want == "ddagrab" else "")
        return {"kind": "gdigrab", "size": [w, h], "note": note,
                "args": ["-f", "gdigrab", "-draw_mouse", "0", "-framerate", str(fps), "-offset_x", str(cl), "-offset_y", str(ct),
                         "-video_size", f"{w}x{h}", "-i", "desktop"]}
    # parked off-screen (shown through the app's GPU surface): the window's own surface
    help_ = _run(run, [*(ffmpeg or ffmpeg_cmd()), "-hide_banner", "-h", "demuxer=gdigrab"]).stdout or ""
    if "hwnd" in help_:
        target, note = f"hwnd={hwnd}", "the game window's own surface (off-screen; GPU windows may record black)"
    else:
        target, note = f"title={_window_title(hwnd)}", "the game window by title (off-screen; GPU windows may record black)"
    w, h = _even(r - l), _even(b - t)
    return {"kind": "gdigrab-window", "size": [w, h], "note": note,
            "args": ["-f", "gdigrab", "-draw_mouse", "0", "-framerate", str(fps), "-i", target]}


def _window_title(hwnd) -> str:
    try:
        from .adapters import _win_title
        return _win_title(hwnd)
    except Exception:                                  # noqa: BLE001
        return ""


def _low_priority(level: str = "low") -> dict:
    """Popen kwargs: ffmpeg yields to the emulator (below-normal class on Windows, nice 10 elsewhere); "normal" keeps
    the default (a PC whose CPU is saturated by other work can starve a below-normal capture on Windows)."""
    hidden = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if str(level).lower() == "normal":
        return {"creationflags": hidden} if os.name == "nt" else {}
    if os.name == "nt":
        return {"creationflags": 0x00004000 | hidden}
    return {"preexec_fn": lambda: os.nice(10)}


# --- one session's ring --------------------------------------------------------------------------

_LINE = re.compile(r"^(?P<name>[^,]+),(?P<start>-?[\d.]+),(?P<end>-?[\d.]+)\s*$")


class SessionRing:
    """The ring of one session: ffmpeg runs while the pad is in use, its finished segments are indexed in wall time."""

    def __init__(self, sid: str, directory: Path, rc, source_fn, ffmpeg: list[str] | None = None, activity=None,
                 clock=time.time, popen=subprocess.Popen, run=subprocess.run, meta: dict | None = None, audio_fn=None):
        self.sid, self.dir, self.rc, self.source_fn = sid, Path(directory), rc, source_fn
        self.ffmpeg = list(ffmpeg or ffmpeg_cmd())
        self.activity = activity or (lambda: last_touch(sid))
        self.clock, self.popen, self.run = clock, popen, run
        self.meta = dict(meta or {})
        self.audio_fn, self.audio_tap, self.audio_checked = audio_fn, None, -math.inf
        self.audio_note = 'Waiting for isolated emulator playback' if audio_fn else 'Isolated emulator audio unavailable'
        self.enabled = bool(getattr(rc, "enabled", True))
        self.seconds = max(10.0, float(getattr(rc, "seconds", 180)))
        self.segment_s = max(1.0, float(getattr(rc, "segment_s", 5)))
        self.idle_s = max(1.0, float(getattr(rc, "idle_s", 20.0)))
        self.fps = max(5, int(getattr(rc, "fps", 30)))
        self.kbps = max(500, int(getattr(rc, "bitrate_kbps", 8000)))
        self.max_bytes = max(16, int(getattr(rc, "max_mb", 512))) * 2**20
        self.encoder: dict | None = None
        self.source: dict | None = None
        self.segments: list[dict] = []          # oldest first: {"file", "start", "end", "bytes", "run", "idx", "size"}
        self.proc = None
        self.cur: dict | None = None            # the running ffmpeg's run: {"no", "prefix", "list", "pos", "wrap", "t0", "last"}
        self.runs = self.failures = 0
        self.retry_at = 0.0
        self.error: str | None = None
        self.ended = False
        self.lock = threading.RLock()
        self.dir.mkdir(parents=True, exist_ok=True)

    # --- the gate ---
    def active(self, now: float) -> bool:
        return self.enabled and not self.ended and (now - self.activity() < self.idle_s or autoplay_active(self.sid))

    def tick(self, now: float | None = None) -> None:
        """One monitor step (once a second): start / stop ffmpeg on pad activity, index finished segments, trim."""
        now = self.clock() if now is None else now
        with self.lock:
            if self.proc is not None and self.proc.poll() is not None:
                self._collect(now)
                self._died(now)
            want = self.active(now)
            if want and self.proc is not None and self.audio_fn and now - self.audio_checked >= 5:
                self.audio_checked = now
                if self.audio_tap is not None and not self.audio_tap.alive():
                    self._stop(now)
                elif self.audio_tap is None:
                    try:
                        tap = self.audio_fn()
                    except Exception as exc:
                        self.audio_note = f'Isolated emulator audio unavailable: {type(exc).__name__}'
                        tap = None
                    if tap is not None:
                        self._stop(now)
                        self.audio_tap = tap
            if want and self.proc is None and now >= self.retry_at:
                self._start(now)
            elif not want and self.proc is not None:
                self._stop(now)
            self._collect(now)
            self._trim()

    # --- ffmpeg runs ---
    def _start(self, now: float) -> None:
        try:
            if self.encoder is None:
                self.encoder = pick_encoder(getattr(self.rc, "encoder", "auto"), self.ffmpeg, self.run)
            self.source = self.source_fn(self.encoder["encoder"], self.fps)
        except Exception as exc:                          # noqa: BLE001 - no window yet / no ffmpeg: try again later
            self.error = f"{exc}"
            self.retry_at = now + 10.0
            self._close_audio()
            return
        self.runs += 1
        no = self.runs
        prefix = f"r{no:03d}-"
        wrap = wrap_count(self.seconds, self.segment_s, self.kbps, self.max_bytes / 2**20)
        lst = self.dir / f"r{no:03d}.csv"
        gop = int(self.fps * min(self.segment_s, 2.0))
        audio_r = audio_w = None
        if self.audio_tap is None and self.audio_fn and now - self.audio_checked >= 5:
            self.audio_checked = now
            try:
                self.audio_tap = self.audio_fn()
            except Exception as exc:
                self.audio_note = f'Isolated emulator audio unavailable: {type(exc).__name__}'
        if self.audio_tap is not None and os.name == 'posix':
            audio_r, audio_w = os.pipe()
            self.audio_note = 'Isolated emulator playback (48 kHz stereo)'
        audio_args = ['-thread_queue_size', '512', '-f', 's16le', '-ar', '48000', '-ac', '2', '-i', f'pipe:{audio_r}'] if audio_r is not None else []
        audio_encode = ['-map', '0:v:0', '-map', '1:a:0', '-c:a', 'aac', '-b:a', '128k', '-ar', '48000', '-ac', '2'] if audio_r is not None else ['-an']
        argv = [*self.ffmpeg, "-hide_banner", "-loglevel", "error", "-filter_threads", "1", "-y", *self.source["args"],
                *audio_args,
                *encoder_args(self.encoder["encoder"], self.kbps, self.fps, gop, live=True),
                "-force_key_frames", f"expr:gte(t,n_forced*{self.segment_s:g})", *audio_encode,
                "-f", "segment", "-segment_time", f"{self.segment_s:g}", "-segment_wrap", str(wrap),
                "-segment_format", "mpegts", "-reset_timestamps", "1",
                "-segment_list", str(lst), "-segment_list_type", "csv", "-segment_list_size", "0",
                str(self.dir / f"{prefix}%03d.ts")]
        log = open(self.dir / f"r{no:03d}.log", "wb")
        try:
            self.proc = self.popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log,
                                   **({'pass_fds': (audio_r,)} if audio_r is not None else {}),
                                   **_low_priority(getattr(self.rc, "priority", "low")))
        except Exception as exc:                          # noqa: BLE001
            log.close()
            self.error, self.retry_at = f"ffmpeg did not start: {exc}", now + 30.0
            if audio_w is not None:
                os.close(audio_w)
            self._close_audio()
            return
        finally:
            if audio_r is not None:
                os.close(audio_r)
            if self.proc is None:
                log.close()
        self._log = log
        self.cur = {"no": no, "prefix": prefix, "list": lst, "pos": 0, "wrap": wrap, "t0": now, "last": None,
                    "argv": argv, "size": list(self.source["size"]), 'audio': audio_r is not None}
        if audio_w is not None:
            threading.Thread(target=self._write_audio, args=(self.proc, audio_w, self.audio_tap), daemon=True,
                             name=f'ring-audio-{self.sid}').start()

    def _write_audio(self, proc, fd, tap):
        """Only actual PCM received from the selected playback stream enters the ring."""
        try:
            with os.fdopen(fd, 'wb', buffering=0) as out:
                while self.proc is proc and tap.alive():
                    data = tap.take(8192)
                    if not data:
                        time.sleep(.01)
                        continue
                    view = memoryview(data)
                    while view:
                        view = view[out.write(view):]
        except (BrokenPipeError, OSError, ValueError, TypeError):
            pass

    def _close_audio(self):
        tap, self.audio_tap = self.audio_tap, None
        if tap is not None:
            tap.close()

    def _stop(self, now: float) -> None:
        proc, self.proc = self.proc, None
        try:
            if proc.stdin:
                proc.stdin.write(b"q")                    # 'q' lets ffmpeg close the last segment cleanly
                proc.stdin.flush()
                proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            proc.wait(timeout=8)
        except Exception:                                 # noqa: BLE001 - deaf to 'q': the whole tree goes
            pid = getattr(proc, "pid", None)
            if os.name == "nt" and pid:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
            else:
                proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:                             # noqa: BLE001
                pass
        self._collect(now, final=True)
        self._close_log()
        self._close_audio()
        self.cur = None
        self.failures = 0

    def _died(self, now: float) -> None:
        code = self.proc.poll()
        self.proc = None
        self._close_log()
        self._close_audio()
        tail = ""
        if self.cur:
            try:
                tail = (self.dir / f"r{self.cur['no']:03d}.log").read_text(errors="replace").strip().splitlines()[-1][:300]
            except (OSError, IndexError):
                pass
        self.cur = None
        self.failures += 1
        self.error = f"ffmpeg exited ({code}){': ' + tail if tail else ''}"
        if self.encoder and self.encoder["encoder"] in NVENC and self.failures >= 2:
            self.encoder = {"encoder": "libx264", "requested": self.encoder["requested"], "gpu": False,
                            "note": f"libx264 (CPU): {self.encoder['encoder']} stopped twice ({self.error})"}
        self.retry_at = now + min(60.0, 5.0 * 2 ** min(self.failures, 4))

    def _close_log(self) -> None:
        log = getattr(self, "_log", None)
        if log is not None:
            try:
                log.close()
            except OSError:
                pass
            self._log = None

    # --- the index ---
    def _collect(self, now: float, final: bool = False) -> None:
        """Index the segments ffmpeg finished since the last look (its csv list grows one line per segment)."""
        cur = self.cur
        if not cur:
            return
        try:
            with open(cur["list"], "rb") as f:
                f.seek(cur["pos"])
                data = f.read()
        except OSError:
            return
        if not data:
            return
        complete = data if data.endswith(b"\n") else data[:data.rfind(b"\n") + 1]
        cur["pos"] += len(complete)
        for raw in complete.decode(errors="replace").splitlines():
            m = _LINE.match(raw.strip())
            if not m:
                continue
            path = self.dir / Path(m["name"]).name
            try:
                st = path.stat()
            except OSError:
                continue
            # media time from ffmpeg's list; the wall clock (the file's last write) only orders the segments and ages
            # them: a busy ffmpeg writes in bursts, so wall-clock gaps between segments are not their length
            dur = max(0.0, float(m["end"]) - float(m["start"]))
            if dur <= 0:
                continue
            end = min(st.st_mtime, now)
            start = end - dur
            idx = int(re.search(r"(\d+)\.ts$", path.name)[1]) if re.search(r"(\d+)\.ts$", path.name) else 0
            nxt = self.dir / f"{cur['prefix']}{(idx + 1) % cur['wrap']:03d}.ts"
            # ffmpeg reopens the next file of the wrap right away: an older entry for that file is being overwritten
            self.segments = [s for s in self.segments if s["file"] != path and (final or s["file"] != nxt)]
            seg = {"file": path, "start": start, "end": end, "bytes": st.st_size, "run": cur["no"], "idx": idx,
                   "size": cur["size"], 'audio': cur.get('audio', False)}
            self.segments.append(seg)
            cur["last"] = seg
        self.segments.sort(key=lambda s: s["end"])

    def _trim(self) -> None:
        def span():
            return sum(s["end"] - s["start"] for s in self.segments)
        while len(self.segments) > 1 and (span() - (self.segments[0]["end"] - self.segments[0]["start"]) >= self.seconds
                                          or sum(s["bytes"] for s in self.segments) > self.max_bytes):
            old = self.segments.pop(0)
            if not (self.cur and old["run"] == self.cur["no"]):       # the running ffmpeg rewrites its own files
                try:
                    Path(old["file"]).unlink(missing_ok=True)
                except OSError:
                    pass
        live = {self.cur["no"]} if self.cur else set()
        keep = {Path(s["file"]).name for s in self.segments}
        for f in self.dir.glob("r*-*.ts"):                            # files of finished runs nothing points at
            try:
                if f.name not in keep and int(f.name[1:4]) not in live:
                    f.unlink(missing_ok=True)
            except (OSError, ValueError):
                pass

    def live_piece(self, now: float) -> dict | None:
        """The segment ffmpeg is writing right now (exports include it: a copy cut at a whole TS packet)."""
        cur = self.cur
        if not cur or self.proc is None:
            return None
        idx = (cur["last"]["idx"] + 1) % cur["wrap"] if cur["last"] else 0
        path = self.dir / f"{cur['prefix']}{idx:03d}.ts"
        try:
            st = path.stat()
        except OSError:
            return None
        begun = cur["last"]["end"] if cur["last"] else cur["t0"]
        end = min(now, st.st_mtime)
        dur = min(self.segment_s, end - begun)               # media time of an unfinished segment: the wall estimate
        if st.st_size < TS_PACKET * 8 or dur < 0.5:
            return None
        start = end - dur
        return {"file": path, "start": start, "end": end, "bytes": st.st_size, "run": cur["no"], "idx": idx,
                "size": cur["size"], "live": True, 'audio': cur.get('audio', False)}

    # --- the operator's side ---
    def set_enabled(self, on: bool) -> None:
        with self.lock:
            self.enabled = bool(on)
            if not on and self.proc is not None:
                self._stop(self.clock())

    def end(self) -> None:
        """The session ended: ffmpeg stops, the ring stays for a late export (until the next sweep / keep_ended)."""
        with self.lock:
            if self.proc is not None:
                self._stop(self.clock())
            self.ended = True

    def delete(self) -> None:
        with self.lock:
            if self.proc is not None:
                self._stop(self.clock())
            self.ended = True
            self.segments = []
            shutil.rmtree(self.dir, ignore_errors=True)

    def state(self, now: float) -> str:
        if self.ended:
            return "ended"
        if not self.enabled:
            return "off"
        if self.proc is not None:
            return "recording"
        return "waiting" if self.retry_at <= now else "retrying"

    def status(self, now: float | None = None) -> dict:
        now = self.clock() if now is None else now
        with self.lock:
            segs = list(self.segments)
            live = self.live_piece(now)
            if live:
                segs.append(live)
            touch_age = now - self.activity()
            span = sum(s["end"] - s["start"] for s in segs)
            d = {"session_id": self.sid, "state": self.state(now), "enabled": self.enabled, "recording": self.proc is not None,
                 "encoder": (self.encoder or {}).get("encoder"), "encoder_note": (self.encoder or {}).get("note"),
                 "gpu": bool((self.encoder or {}).get("gpu")),
                 "source": (self.source or {}).get("kind"), "source_note": (self.source or {}).get("note"),
                 "size": (self.source or {}).get("size"), "fps": self.fps, "bitrate_kbps": self.kbps,
                 "span_s": round(span, 1), "reach_s": self.seconds, "segment_s": self.segment_s,
                 "segments": timeline(segs), "newest_age_s": round(now - segs[-1]["end"], 1) if segs else None,
                 "bytes": sum(s["bytes"] for s in segs), "max_mb": self.max_bytes // 2**20, "idle_s": self.idle_s,
                 "last_touch_age_s": round(touch_age, 1) if touch_age < 1e8 else None,
                 "stops_in_s": round(max(0.0, self.idle_s - touch_age), 1) if self.proc is not None else None,
                 "runs": self.runs, "error": self.error}
            d.update(audio=bool(self.cur and self.cur.get('audio')), audio_note=self.audio_note,
                     av_span_s=round(sum(s['end']-s['start'] for s in segs if s.get('audio')), 1),
                     activity='autoplay' if autoplay_active(self.sid) else 'controller')
            d.update({k: v for k, v in self.meta.items() if k in ("game_id", "title")})
            return d

    # --- export ---
    def snapshot(self, in_s: float | None, out_s: float, workdir: Path) -> dict:
        """Copy the segments of the range into workdir (ffmpeg may overwrite the ring while the export encodes)."""
        now = self.clock()
        with self.lock:
            self._collect(now)
            segs = list(self.segments)
            live = self.live_piece(now)
            if live:
                segs.append(live)
            # A pre-audio boot prefix cannot be concatenated as though it contained sound.
            av = [s for s in segs if s.get('audio')]
            if av:
                segs = av
            sel = select_range(segs, in_s, out_s)
            sel['audio'] = bool(av)
            size = None
            files = []
            by_file = {str(s["file"]): s for s in segs}
            for i, p in enumerate(sel["pieces"]):
                src = Path(p["file"])
                dst = workdir / f"p{i:03d}.ts"
                seg = by_file.get(str(src), {})
                if seg.get("live"):
                    with open(src, "rb") as f, open(dst, "wb") as o:
                        n = seg["bytes"] - seg["bytes"] % TS_PACKET
                        o.write(f.read(n))
                else:
                    shutil.copyfile(src, dst)
                files.append(dst)
                size = seg.get("size") or size
        sel["files"], sel["size"] = files, size or [1280, 720]
        return sel

    def export(self, in_s: float | None, out_s: float = 0.0, target_mb: float = 20.0, out_dir: Path | None = None,
               progress=None) -> dict:
        """MP4 of the range at about target_mb: concat the copied segments, trim exactly, re-encode to the bitrate."""
        target_mb = max(1.0, min(float(target_mb), MAX_TARGET_MB))
        if self.encoder is None:
            self.encoder = pick_encoder(getattr(self.rc, "encoder", "auto"), self.ffmpeg, self.run)
        work = Path(tempfile.mkdtemp(prefix="ring-export-", dir=str(self.dir)))
        try:
            sel = self.snapshot(in_s, out_s, work)
            seconds = sel["seconds"]
            kbps = video_kbps(target_mb, seconds, cap_kbps=self.kbps, audio_kbps=128 if sel['audio'] else 0)
            w, h = sel["size"]
            height = fit_height(kbps, w, h, self.fps)
            width = _even(round(w * height / max(1, h)))
            lst = work / "concat.txt"
            lst.write_text("".join(f"file '{f.name}'\n" for f in sel["files"]), encoding="utf-8")
            out_dir = Path(out_dir or self.dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            name = f"replay-{self.meta.get('game_id') or self.sid}-{time.strftime('%Y%m%d-%H%M%S')}.mp4"
            out = out_dir / name
            target_bytes = target_mb * 2**20
            enc = self.encoder["encoder"]
            attempts, resized = [], False
            while True:
                vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                      f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1")
                argv = [*self.ffmpeg, "-hide_banner", "-loglevel", "error", "-filter_threads", "1", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-ss", f"{sel['offset']:.3f}", "-t", f"{seconds:.3f}", "-vf", vf, "-r", str(self.fps),
                        *encoder_args(enc, kbps, self.fps, self.fps * 2, live=False),
                        *(['-map', '0:v:0', '-map', '0:a:0', '-c:a', 'aac', '-b:a', '128k'] if sel['audio'] else ['-an']),
                        "-movflags", "+faststart", str(out)]
                if progress:
                    progress(30 + 30 * len(attempts), f"Encoding {seconds:.0f} s at {kbps} kb/s ({enc}, {height}p)")
                out.unlink(missing_ok=True)
                r = _run(self.run, argv, timeout=900)
                if r.returncode != 0 or not out.is_file():
                    tail = ((r.stderr or "").strip().splitlines() or ["no error text"])[-1][:300]
                    attempts.append({"encoder": enc, "kbps": kbps, "error": tail})
                    if enc in NVENC:                      # the GPU path failed here: the CPU one, reported
                        enc = "libx264"
                        continue
                    raise RuntimeError(f"ffmpeg export failed: {tail}")
                got = out.stat().st_size
                attempts.append({"encoder": enc, "kbps": kbps, "bytes": got})
                if got <= target_bytes * 1.02 or resized:
                    break
                resized = True                            # overshot: once more, proportionally lower
                kbps = max(MIN_KBPS, int(kbps * target_bytes / got * 0.95))
                height = fit_height(kbps, w, h, self.fps)
                width = _even(round(w * height / max(1, h)))
            return {"file": out, "name": name, "bytes": out.stat().st_size, "seconds": seconds, "in_s": sel["in_s"],
                    "out_s": sel["out_s"], "target_mb": target_mb, "kbps": kbps, "width": width, "height": height,
                    "encoder": enc, "encoder_note": self.encoder["note"] if enc == self.encoder["encoder"] else
                    f"libx264 (CPU): {self.encoder['encoder']} failed on the export", "attempts": attempts,
                    "pieces": len(sel["files"]), "fits": out.stat().st_size <= target_bytes * 1.02,
                    'audio': sel['audio'], 'audio_source': 'isolated emulator playback' if sel['audio'] else None}
        finally:
            shutil.rmtree(work, ignore_errors=True)


# --- the worker's sessions -----------------------------------------------------------------------

def ring_dir(config, sid: str) -> Path:
    return Path(config.runtime) / "ring_record" / sid


def sweep(config) -> None:
    """Rings nothing points at (a previous worker run): deleted."""
    root = Path(config.runtime) / "ring_record"
    try:
        for d in root.iterdir() if root.is_dir() else ():
            if d.name not in ACTIVE:
                shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


def start(sid: str, ad, config, game: dict | None = None, alive=None, threads: bool = True, **kw) -> dict:
    """Attach a ring to a session that just launched; returns its status (or why it cannot record)."""
    rc = getattr(config, "recording", None)
    if rc is None:
        from .config import RecordingConfig
        rc = RecordingConfig()
    if hasattr(rc, 'model_copy'):
        rc = rc.model_copy(update={'seconds': max(180, rc.seconds)})
    ffmpeg = kw.pop("ffmpeg", None) or ffmpeg_cmd()
    if not shutil.which(ffmpeg[0]) and not Path(ffmpeg[0]).is_file():
        return {"state": "unsupported", "reason": "ffmpeg not on PATH"}
    if HOST_OS != "windows" and not getattr(getattr(ad, "display", None), "name", None):
        return {"state": "unsupported", "reason": "no session display to record"}
    if HOST_OS == "windows" and not getattr(getattr(ad, "proc", None), "pid", None):
        return {"state": "unsupported", "reason": "no emulator window to record"}
    with _LOCK:
        if not ACTIVE:
            sweep(config)
        old = ACTIVE.pop(sid, None)
        if old is not None:
            old.delete()
    run = kw.get("run", subprocess.run)
    process_pid = kw.pop('process_pid', None)
    ring = SessionRing(sid, ring_dir(config, sid), rc,
                       source_fn=kw.pop("source_fn", None) or (lambda enc, fps: resolve_source(ad, rc, enc, fps, ffmpeg=ffmpeg, run=run)),
                       ffmpeg=ffmpeg, meta={"game_id": (game or {}).get("game_id"), "title": (game or {}).get("title")},
                       audio_fn=kw.pop('audio_fn', None) or ((lambda: audio_tap_for(ad, process_pid)) if getattr(rc, 'audio', True) else None), **kw)
    with _LOCK:
        ACTIVE[sid] = ring
    if threads:
        alive = alive or (lambda: True)

        def loop():
            while ACTIVE.get(sid) is ring and not ring.ended:
                if not alive():
                    stop(sid)
                    break
                try:
                    ring.tick()
                except Exception as exc:                  # noqa: BLE001 - the monitor never dies with the game running
                    ring.error = f"{type(exc).__name__}: {exc}"
                time.sleep(1.0)
        threading.Thread(target=loop, daemon=True, name=f"ring-record-{sid}").start()
    st = ring.status()
    return {k: st[k] for k in ("state", "enabled", "reach_s", "idle_s", "max_mb", "fps", "bitrate_kbps")}


def stop(sid: str, keep: int | None = None) -> "SessionRing | None":
    """The session ended: ffmpeg stops; the ring is kept for a late export (the newest keep_ended rings)."""
    with _LOCK:
        ring = ACTIVE.get(sid)
        if ring is None or ring.ended:
            return ring
    ring.end()
    keep = int(getattr(ring.rc, "keep_ended", 1) if keep is None else keep)
    with _LOCK:
        if sid in ENDED:
            ENDED.remove(sid)
        ENDED.append(sid)
        while len(ENDED) > max(0, keep):
            old = ACTIVE.pop(ENDED.pop(0), None)
            if old is not None:
                old.delete()
    return ring


def get(sid: str) -> "SessionRing":
    ring = ACTIVE.get(sid)
    if ring is None:
        raise KeyError(f"no gameplay ring for session {sid} on this worker (it records sessions launched here)")
    return ring


def status(sid: str) -> dict | None:
    ring = ACTIVE.get(sid)
    return ring.status() if ring is not None else None
