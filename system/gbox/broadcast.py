"""Broadcast: stable gameplay feeds from every gBox PC for Pine Box and any media-source software (docs/broadcast.md).

Operator, 2026-10-20: "I need pine box to be able to connect to the active gbox feed of any instance of gbox on the
network showing gameplay and be able to stream and pick up stable streaming video via pine box as a media source."

FEEDS
  program        what is on air: the session the operator watches in gBox (their app reports it), switched with
                 POST /api/broadcast/program {session_id | pc | "auto"} or the On air button in the clients
  pc/<name>      whatever game that PC runs now, across relaunches and swaps (lilspark, i9-NUC, JAYBUILTFINALE, and
                 Pine Box's own names for them: spark1, i9nuc, jaybuilt)
  session/<sid>  one session (it follows a swap or reset relaunch of that session)
each as
  .mjpg          MJPEG at a constant frame rate: the newest frame every tick, so a quiet source repeats its picture.
                 It never ends on a switch, a stall or a session end: the last frame holds, then a slate.
  .jpg           the newest picture
  .ts            H.264 (+ AAC) in MPEG-TS over HTTP: one ffmpeg per watched feed, at nice 10, only while watched
  /hls/index.m3u8  the same encode as HLS
SOURCES (what the control plane already receives; nothing new runs on the PCs)
  spark_capture   a Spark session's x11grab stream (POST /api/sessions/{sid}/stream, up to 60 fps)
  windows_stream  a Windows session its worker streams (gdigrab: RPCS3, RocketLauncher)
  desktop_crop    a native Windows game: that PC's desktop stream cut to the game's own window (8 fps, while watched)
  stills          a native Windows game's window stills (one every 4 s while that PC's screen shows the game)
  Only a game's own picture goes on air, never a PC's desktop or the gBox window.
SOUND  a Spark session's own PipeWire playback stream (Dolphin's), copied with parec --monitor-stream into the H.264
       feeds; silence otherwise, so the track never has a gap.
AUTH  gbb_ broadcast tokens: read-only ("view"), or "control" (may also switch the program); made and revoked by the
      operator; accepted by these routes only; meant for URLs (?token=). The main api_token works in the
      Authorization header and is refused in a URL.
"""
from __future__ import annotations

import asyncio
import collections
import hashlib
import hmac
import io
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

BOUNDARY = "gboxframe"
MEDIA_MJPEG = f"multipart/x-mixed-replace; boundary={BOUNDARY}"
MAX_FPS = 60
TICK_S = 0.1                 # the hub's housekeeping rate: which session, which source, stalls, crops, slates
SESSIONS_TTL_S = 1.0         # running sessions are re-read from the store at most this often
FEED_IDLE_S = 10.0           # a feed nobody reads (no viewer, no encoder) is dropped after this
SWITCH_WAIT_S = 4.0          # a switched-to source without a picture yet: the previous picture holds this long
CROP_STALE_S = 3.0           # a desktop crop older than this gives way to the game's stills
STILLS_STALE_S = 15.0        # stills come every 4 s; older than this the game is not on its PC's screen
DESKTOP_RENEW_S = 8.0        # as the Other PC view: the worker captures its screen while the watch is in the future
DESKTOP_FRESH_S = 5.0        # = remote_desktop.FRESH_S: an older desktop frame is never cut
CROP_MAX_W = 1280            # a game window cut out of a desktop frame is at most this wide
WORKER_TTL_S = 30.0          # = server.WORKER_TTL
OWNER_TTL_S = 30.0           # a session's agent ownership is looked up again this often
TOKEN_PREFIX = "gbb_"
TOKEN_KIND = "broadcast_token"
PROGRAM_SETTING = "broadcast_program"
AUTOMATION = ("agent", "hermes", "mcp")    # actors that never move the program (the operator, or Pine Box, does)
TS = 188
VIDEO_PID = 0x100            # ffmpeg's first PID (mpegts_start_pid); the video stream is mapped first
GOP_CACHE_MAX = 8 << 20
SUB_QUEUE = 512              # MPEG-TS pieces queued per viewer before it counts as lagging
AUDIO_RATE, AUDIO_CH = 48000, 2
AUDIO_BYTES_S = AUDIO_RATE * AUDIO_CH * 2
AUDIO_BUFFER_S = 0.4         # captured sound kept ahead of the encoder; more is dropped (a late tap never adds delay)
AUDIO_RECHECK_S = 3.0        # a session without a sound stream is looked at again this often (Dolphin opens it late)
SEGMENT_RE = re.compile(r"seg_(\d{5,})\.ts")
SESSION_ID_RE = re.compile(r"[\w-]{1,100}")


# --- small pure helpers ------------------------------------------------------------------------------------------

def jpeg_size(data: bytes | None) -> tuple[int, int] | None:
    """(width, height) from a JPEG's frame header, without decoding it."""
    if not data or data[:2] != b"\xff\xd8":
        return None
    i, n = 2, len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF:                                   # fill byte
            i += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:          # markers without a length
            i += 2
            continue
        if marker in (0xDA, 0xD9):                            # scan data, or the end, before any frame header
            return None
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = int.from_bytes(data[i + 5:i + 7], "big"), int.from_bytes(data[i + 7:i + 9], "big")
            return (w, h) if w and h else None
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return None


def part(frame: bytes) -> bytes:
    """One multipart/x-mixed-replace part (Content-Length lets OBS / ffmpeg's mpjpeg demuxer skip the scan)."""
    return (b"--" + BOUNDARY.encode() + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
            + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")


def slug(name: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def parse_size(text: str, default: tuple[int, int] = (1280, 720)) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{2,4})\s*[xX:]\s*(\d{2,4})\s*", str(text or ""))
    if not m:
        return default
    w, h = int(m.group(1)), int(m.group(2))
    return (w - w % 2, h - h % 2) if 64 <= w <= 3840 and 64 <= h <= 2160 else default


def clamp_fps(value: Any, default: int) -> int:
    try:
        fps = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return default if fps <= 0 else min(MAX_FPS, fps)


def feed_key(params: dict) -> str:
    """The feed a route's path names: program | pc:<slug> | session:<sid>."""
    if params.get("sid"):
        return "session:" + params["sid"]
    if params.get("pc"):
        return "pc:" + slug(params["pc"])
    return "program"


def feed_paths(key: str) -> dict[str, str]:
    """A feed's URLs (paths on the control plane), by format."""
    if key == "program":
        base = "/api/broadcast/program"
    elif key.startswith("pc:"):
        base = "/api/broadcast/pc/" + key[3:]
    else:
        base = "/api/broadcast/session/" + key.split(":", 1)[1]
    return {"mjpeg": base + ".mjpg", "jpeg": base + ".jpg", "ts": base + ".ts", "hls": base + "/hls/index.m3u8"}


def absolute(paths: dict[str, str], base: str, token: str = "") -> dict[str, str]:
    if not base:
        return {}
    q = ("?token=" + token) if token else ""
    return {k: base.rstrip("/") + v + q for k, v in paths.items()}


# --- MPEG-TS: where a new viewer can join ------------------------------------------------------------------------

class TsGop:
    """Cuts ffmpeg's MPEG-TS output into pieces, each flagged when it starts a GOP: the PAT/PMT ffmpeg writes right
    before every video keyframe (mpegts_flags=+pat_pmt_at_frames), else the keyframe's own packet (random access
    indicator on the video PID). A viewer that joins on such a piece decodes a picture at once instead of waiting for
    the next keyframe with a broken one. The newest `lookback` packets are held back so a PAT just before a keyframe
    that has not arrived yet can still open its piece."""

    def __init__(self, video_pid: int = VIDEO_PID, lookback: int = 4):
        self.video_pid, self.lookback = video_pid, lookback * TS
        self.buf, self.scanned, self.pat, self.key = bytearray(), 0, None, False

    def feed(self, data: bytes) -> list[tuple[bytes, bool]]:
        out: list[tuple[bytes, bool]] = []
        p = self.buf
        p += data
        off = self.scanned
        while off + TS <= len(p):
            if p[off] != 0x47:                               # out of step (never for ffmpeg's own output): resync
                nxt = p.find(b"\x47", off + 1)
                del p[off:nxt if nxt >= 0 else len(p)]
                continue
            b1 = p[off + 1]
            pid = ((b1 & 0x1F) << 8) | p[off + 2]
            if pid == 0:
                self.pat = off
            elif pid == self.video_pid and b1 & 0x40 and p[off + 3] & 0x20 and p[off + 4] and p[off + 5] & 0x40:
                cut = self.pat if self.pat is not None and off - self.pat <= self.lookback else off
                if cut > 0:
                    out.append((bytes(p[:cut]), self.key))
                    del p[:cut]
                    off -= cut
                self.key, self.pat = True, None
            off += TS
        self.scanned = off
        safe = self.scanned - self.lookback
        if safe > 0:
            out.append((bytes(p[:safe]), self.key))
            del p[:safe]
            self.scanned -= safe
            self.pat = self.pat - safe if self.pat is not None and self.pat >= safe else None
            self.key = False
        return out

    def flush(self) -> list[tuple[bytes, bool]]:
        rest, key = bytes(self.buf), self.key
        self.buf, self.scanned, self.pat, self.key = bytearray(), 0, None, False
        return [(rest, key)] if rest else []


# --- broadcast tokens ----------------------------------------------------------------------------------------------

def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class Tokens:
    """Read-only (scope "view") or "control" tokens for media sources. Only a SHA-256 of each is stored; the secret is
    shown once, when it is made. Revoking one ends its access at once (the lookup table is rebuilt)."""
    SCOPES = ("view", "control")
    TOUCH_S = 60.0

    def __init__(self, store, clock: Callable[[], float] = time.time):
        self.store, self.clock = store, clock
        self.lock = threading.Lock()
        self._by_hash: dict[str, dict] | None = None

    def _table(self) -> dict[str, dict]:
        with self.lock:
            if self._by_hash is None:
                self._by_hash = {r["hash"]: r for r in self.store.all(TOKEN_KIND)
                                 if r.get("hash") and not r.get("revoked")}
            return self._by_hash

    def create(self, name: str, scope: str = "view", by: str = "operator") -> dict:
        name = re.sub(r"\s+", " ", str(name or "")).strip()[:60] or "media source"
        if scope not in self.SCOPES:
            raise ValueError(f"scope must be one of {list(self.SCOPES)}")
        secret = TOKEN_PREFIX + secrets.token_urlsafe(24)
        row = {"id": secrets.token_hex(6), "name": name, "scope": scope, "hash": _digest(secret),
               "created": self.clock(), "by": by, "last_used": None, "last_from": None, "uses": 0}
        self.store.put(TOKEN_KIND, row["id"], row)
        with self.lock:
            self._by_hash = None
        return self.public(row) | {"token": secret}

    def revoke(self, tid: str, by: str = "operator") -> dict | None:
        row = self.store.get(TOKEN_KIND, tid)
        if not row:
            return None
        row = {k: v for k, v in row.items() if k != "hash"} | {"revoked": row.get("revoked") or self.clock(),
                                                               "revoked_by": row.get("revoked_by") or by}
        self.store.put(TOKEN_KIND, tid, row)
        with self.lock:
            self._by_hash = None
        return self.public(row)

    @staticmethod
    def public(row: dict) -> dict:
        return {k: v for k, v in row.items() if k != "hash"}

    def list(self) -> list[dict]:
        return sorted((self.public(r) for r in self.store.all(TOKEN_KIND)), key=lambda r: -(r.get("created") or 0))

    def check(self, secret: str, remote: str = "") -> dict | None:
        if not secret or not secret.startswith(TOKEN_PREFIX) or len(secret) > 200:
            return None
        row = self._table().get(_digest(secret))
        if row is None:
            return None
        now = self.clock()
        if not row.get("last_used") or now - row["last_used"] >= self.TOUCH_S:      # bounded writes
            row["last_used"], row["last_from"], row["uses"] = now, remote[:64], int(row.get("uses") or 0) + 1
            try:
                self.store.put(TOKEN_KIND, row["id"], row)
            except Exception:                                    # noqa: BLE001 - a busy store never refuses a viewer
                pass
        return row


# --- pictures: slates and game-window crops ------------------------------------------------------------------------

_FONTS: dict[int, Any] = {}
LOGO = Path(__file__).resolve().parents[1] / "assets" / "brand" / "gbox-128.png"


def _font(size: int):
    from PIL import ImageFont
    if size not in _FONTS:
        try:
            _FONTS[size] = ImageFont.load_default(size=size)          # Pillow >= 10.1: a scalable built-in face
        except TypeError:
            _FONTS[size] = ImageFont.load_default()
    return _FONTS[size]


def _fit(draw, text: str, size: int, max_w: int):
    while size > 10:
        font = _font(size)
        if draw.textlength(text, font=font) <= max_w:
            return font
        size = int(size * 0.88)
    return _font(10)


def _centered(draw, w: int, y: int, text: str, font, fill):
    x = (w - draw.textlength(text, font=font)) / 2
    draw.text((max(0, x), y), text, font=font, fill=fill)


def render_slate(title: str, line: str = "", size: tuple[int, int] = (1280, 720), background: bytes | None = None,
                 quality: int = 80) -> bytes:
    """A slate: the last picture blurred and dimmed (or a dark field), the gBox mark, a title and one line under it."""
    from PIL import Image, ImageDraw, ImageFilter
    w, h = size
    image = None
    if background:
        try:
            with Image.open(io.BytesIO(background)) as src:
                src.draft("RGB", (max(1, w // 4), max(1, h // 4)))
                image = src.convert("RGB").resize((w, h)).filter(ImageFilter.GaussianBlur(max(2, w // 160)))
            image = Image.blend(image, Image.new("RGB", (w, h), (8, 8, 12)), 0.72)
        except Exception:                                        # noqa: BLE001 - a bad frame never breaks the slate
            image = None
    if image is None:
        image = Image.new("RGB", (w, h), (16, 16, 22))
    draw = ImageDraw.Draw(image)
    if LOGO.is_file():
        try:
            with Image.open(LOGO) as logo:
                side = max(24, h // 9)
                mark = logo.convert("RGBA").resize((side, side))
                image.paste(mark, (max(8, w // 40), max(8, h // 30)), mark)
        except Exception:                                        # noqa: BLE001
            pass
    title_font = _fit(draw, title, max(14, h // 13), int(w * 0.9))
    line_font = _fit(draw, line, max(12, h // 26), int(w * 0.9)) if line else None
    th = getattr(title_font, "size", 12)
    lh = getattr(line_font, "size", 12) if line_font else 0
    top = (h - th - (lh + th // 2 if line_font else 0)) // 2
    _centered(draw, w, top, title, title_font, (236, 236, 242))
    if line_font:
        _centered(draw, w, top + th + th // 2, line, line_font, (168, 168, 182))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=quality)
    return out.getvalue()


def crop_game(image: bytes, rect, max_w: int = CROP_MAX_W, quality: int = 82) -> bytes | None:
    """The game window (rect: x, y, w, h as fractions of the desktop) cut out of a desktop JPEG. The JPEG is decoded at
    1/2, 1/4 or 1/8 scale when the window still comes out about max_w wide, which makes a 3200 px desktop several
    times cheaper to cut than a full decode (remote_desktop.crop_jpeg decodes it whole, for each viewer)."""
    from PIL import Image
    if rect is None or len(rect) != 4:
        return None
    x, y, rw, rh = rect
    if not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in rect) or rw <= 0 or rh <= 0:
        return None
    try:
        with Image.open(io.BytesIO(image)) as src:
            full_w, full_h = src.size
            if rw * full_w < 100 or rh * full_h < 75:
                return None
            crop_w = rw * full_w
            want = 0.9 * min(crop_w, max_w)
            scale = next((s for s in (8, 4, 2) if crop_w / s >= want), 1)
            if scale > 1:
                src.draft("RGB", (max(1, full_w // scale), max(1, full_h // scale)))
            width, height = src.size
            box = (max(0, round(x * width)), max(0, round(y * height)),
                   min(width, round((x + rw) * width)), min(height, round((y + rh) * height)))
            if box[2] - box[0] < 32 or box[3] - box[1] < 24:
                return None
            piece = src.convert("RGB").crop(box)
        if piece.width > max_w:
            piece = piece.resize((max_w, max(2, round(piece.height * max_w / piece.width))))
        out = io.BytesIO()
        piece.save(out, format="JPEG", quality=quality)
        return out.getvalue()
    except Exception:                                            # noqa: BLE001 - a broken desktop frame: no crop
        return None


def _blank() -> bytes:
    """A 16x16 black JPEG for the instant before a feed's first slate exists."""
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (16, 16)).save(out, format="JPEG", quality=50)
    return out.getvalue()


BLANK = _blank()


# --- which session is on air ---------------------------------------------------------------------------------------

def choose(pin: dict, watch: dict | None, rows: list[dict], *, current: str | None, now: float, watch_ttl_s: float,
           auto_agents: bool = True, pc_match: Callable[[dict, str], bool] = lambda r, s: False,
           successor: Callable[[str], str | None] = lambda sid: None) -> tuple[str | None, str]:
    """(the session on air, why) for the program.

    rows: the running sessions as Hub.refresh() gives them ({session_id, pc, agent_owned, fresh, started, ...});
    pin: {mode: auto | session | pc, target}; watch: the operator's newest {session_id, at} from their app;
    successor(sid): the running session a swap or reset relaunch put in an ended session's place."""
    running = {r["session_id"]: r for r in rows}
    mode, target = (pin or {}).get("mode") or "auto", (pin or {}).get("target") or ""
    why = ""
    if mode == "session" and target:
        if target in running:
            return target, "pinned"
        nxt = successor(target)
        if nxt in running:
            return nxt, "pinned (its relaunch)"
        why = "the pinned session ended; following what you watch"
    elif mode == "pc" and target:
        mine = [r for r in rows if pc_match(r, target)]
        if not mine:
            return None, f"{target} is not running a game"
        best = max(mine, key=lambda r: (bool(r.get("fresh")), r.get("started") or 0))
        return best["session_id"], f"pinned to {best.get('pc') or target}"
    watched = (watch or {}).get("session_id")
    if watched and now - ((watch or {}).get("at") or 0) <= watch_ttl_s:
        if watched not in running:
            watched = successor(watched)
        if watched in running:
            return watched, why or "following what you watch"
    pool = [r for r in rows if auto_agents or not r.get("agent_owned")]
    if current in running and (running[current].get("fresh") or not any(r.get("fresh") for r in pool)):
        return current, why or "still on air"          # stays while it has a picture, or while nothing else does
    if not pool:
        return None, why or "no game is running"
    best = max(pool, key=lambda r: (bool(r.get("fresh")), not r.get("agent_owned"), r.get("started") or 0))
    return best["session_id"], why or ("newest game with a picture" if best.get("fresh") else "newest game")


# --- one feed while someone reads it -------------------------------------------------------------------------------

class Feed:
    """One feed (program, a PC, a session) while it is read. The hub's thread decides what it shows each tick (which
    session, which source, live / hold / slate); viewers and the H.264 writer call read() at their own frame rate,
    which only returns bytes: no store, no decode, no lock."""

    def __init__(self, key: str, clock: Callable[[], float]):
        self.key, self.clock = key, clock
        self.sid: str | None = None
        self.row: dict | None = None
        self.kind = "none"
        self.mode = "slate"                  # live | hold | slate
        self.why = ""
        self.reader: Callable[[], bytes | None] | None = None
        self.last: bytes | None = None       # the newest real picture shown
        self.slate: bytes | None = None
        self.slate_key: tuple | None = None
        self.resolved = False
        self.viewers = 0
        self.encoders = 0
        self.seen = clock()
        self.switched_at = clock()
        self.ended_at: float | None = None
        self.since: float | None = None      # wall clock: when the current session went on this feed
        self.frames_out = 0

    def read(self) -> bytes:
        if self.mode == "live" and self.reader is not None:
            frame = self.reader()
            if frame:
                self.last = frame
                return frame
        if self.mode in ("live", "hold") and self.last:
            return self.last
        return self.slate or self.last or BLANK

    def users(self) -> int:
        return self.viewers + self.encoders


# --- sound: a Spark session's own PipeWire stream --------------------------------------------------------------------

def _pulse_env() -> dict:
    env = dict(os.environ)
    if not env.get("XDG_RUNTIME_DIR") and hasattr(os, "getuid"):
        env["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"
    return env


def sink_input_for(display: str, run=subprocess.run, which=shutil.which, *, pid: int | None = None) -> int | None:
    """Find one owned emulator playback stream, never a microphone or the desktop mix.

    Cubeb does not always publish window.x11.display. Its application.process.id
    still identifies the emulator. Prefer that exact PID and refuse ambiguous
    display matches or a stream explicitly belonging to a different process.
    """
    if not (display or pid) or not which("pactl"):
        return None
    try:
        r = run(["pactl", "-f", "json", "list", "sink-inputs"], capture_output=True, timeout=5, env=_pulse_env())
        items = json.loads(r.stdout or b"[]")
    except Exception:                                            # noqa: BLE001 - no sound server: no sound
        return None
    exact, by_display = [], []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        props = item.get("properties") or {}
        try:
            index = int(item["index"])
        except (KeyError, TypeError, ValueError):
            continue
        process = str(props.get("application.process.id") or "")
        if pid and process == str(pid):
            exact.append(index)
        elif display and str(props.get("window.x11.display") or "") == display:
            if not pid or not process:
                by_display.append(index)
    matches = exact or by_display
    return matches[0] if len(matches) == 1 else None


class AudioTap:
    """parec --monitor-stream: a copy of one playback stream (it keeps playing where it plays; nothing is moved)."""

    def __init__(self, index: int, popen=subprocess.Popen):
        self.index = index
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.proc = popen(["parec", f"--monitor-stream={index}", "--format=s16le", f"--rate={AUDIO_RATE}",
                           f"--channels={AUDIO_CH}", "--raw", "--latency-msec=40"],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_pulse_env())
        threading.Thread(target=self._read, daemon=True, name=f"broadcast-audio-{index}").start()

    def _read(self):
        cap = int(AUDIO_BYTES_S * AUDIO_BUFFER_S)
        cap -= cap % 4
        while True:
            try:
                data = self.proc.stdout.read1(16384)
            except (OSError, ValueError, AttributeError):
                break
            if not data:
                break
            with self.lock:
                self.buf += data
                extra = len(self.buf) - cap
                if extra > 0:                                    # never let captured sound fall behind the picture
                    del self.buf[:extra + (-extra) % 4]

    def take(self, n: int) -> bytes:
        n -= n % 4
        with self.lock:
            got = bytes(self.buf[:n])
            del self.buf[:n]
        return got

    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self):
        try:
            self.proc.kill()
        except Exception:                                        # noqa: BLE001
            pass


# --- H.264: one ffmpeg per watched feed -----------------------------------------------------------------------------

def ffmpeg_path() -> str:
    from .ring_record import ffmpeg_cmd
    return ffmpeg_cmd()[0] or "ffmpeg"


class Sub:
    """One MPEG-TS viewer: pieces queued on its event loop; a viewer that falls behind skips to the next GOP."""

    def __init__(self, loop):
        self.loop, self.q = loop, asyncio.Queue()
        self.lagging, self.dropped = False, 0

    def offer(self, piece: bytes | None, key: bool = False):
        if piece is None:
            self.q.put_nowait(None)
            return
        if self.lagging:
            if not key or self.q.qsize() > SUB_QUEUE // 2:
                self.dropped += 1
                return
            self.lagging = False
        if self.q.qsize() >= SUB_QUEUE:
            self.lagging, self.dropped = True, self.dropped + 1
            return
        self.q.put_nowait(piece)


class Encoder:
    """ffmpeg: the feed's pictures (written at ts_fps by a pacing thread) -> scale/pad to the canvas -> H.264 (+ AAC)
    -> tee: MPEG-TS on stdout (fanned out to viewers, each joining at a GOP) and HLS segments in its own folder.
    Runs at nice 10, only while someone reads it; restarted with backoff if it dies or stops taking pictures; viewers
    stay connected through a restart."""
    STALL_S = 10.0
    BACKOFF = (0.5, 10.0)

    def __init__(self, feed: Feed, settings, root: Path, *, audio_for: Callable[[Feed], int | None] | None = None,
                 popen=subprocess.Popen, clock: Callable[[], float] = time.monotonic, log: Callable[[str], None] = print,
                 ffmpeg: str | None = None):
        self.feed, self.s, self.clock, self.log = feed, settings, clock, log
        self.popen = popen
        self.ffmpeg = ffmpeg or ffmpeg_path()
        self.dir = root / re.sub(r"[^A-Za-z0-9_-]+", "_", feed.key)
        self.fps = clamp_fps(settings.ts_fps, 30)
        self.size = parse_size(settings.size)
        self.audio_for = audio_for if str(settings.audio).lower() != "off" and os.name == "posix" else None
        self.lock = threading.Lock()
        self.subs: set[Sub] = set()
        self.gop: list[bytes] = []
        self.gop_bytes = 0
        self.proc = None
        self.state = "stopped"
        self.closed = False
        self.started_at = self.left_at = clock()
        self.hls_at = 0.0
        self.restarts, self._fails, self._next_spawn = 0, 0, 0.0
        self.errors: collections.deque = collections.deque(maxlen=12)
        self.frames_in = self.bytes_out = self.late = 0
        self.last_write = clock()
        self.tap: AudioTap | None = None
        self.tap_sid: str | None = None
        self.tap_checked = -1e9
        self.next_segment = 0
        self._media = None

    # argv -----------------------------------------------------------------------------------------------------
    def argv(self, audio_fd: int | None = None, start_number: int = 0) -> list[str]:
        w, h = self.size
        kbps, fps = int(self.s.video_kbps), self.fps
        nice = (["nice", "-n", str(int(self.s.nice))]
                if os.name == "posix" and int(self.s.nice) and shutil.which("nice") else [])
        a = [*nice, self.ffmpeg, "-hide_banner", "-loglevel", "error", "-threads", "1", "-thread_queue_size", "64",
             "-f", "mjpeg", "-framerate", str(fps), "-i", "pipe:0"]
        if audio_fd is not None:
            a += ["-thread_queue_size", "256", "-f", "s16le", "-ar", str(AUDIO_RATE), "-ac", str(AUDIO_CH), "-i", f"pipe:{audio_fd}"]
        a += ["-map", "0:v"] + (["-map", "1:a"] if audio_fd is not None else [])
        a += ["-filter_threads", "1", "-vf",
              f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=bilinear,"
              f"pad={w}:{h}:-1:-1:color=black,format=yuv420p"]
        if str(self.s.encoder) == "h264_nvenc":
            a += ["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ll", "-rc", "cbr", "-b:v", f"{kbps}k"]
        else:
            a += ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-b:v", f"{kbps}k",
                  "-maxrate", f"{kbps}k", "-bufsize", f"{kbps}k", "-threads", "1"]
        a += ["-g", str(fps), "-keyint_min", str(fps), "-sc_threshold", "0", "-bf", "0"]
        if audio_fd is not None:
            a += ["-c:a", "aac", "-b:a", f"{int(self.s.audio_kbps)}k", "-ar", str(AUDIO_RATE), "-ac", str(AUDIO_CH)]
        seg = max(1, int(self.s.hls_segment_s))
        window = max(6, min(60, int(self.s.hls_window_segments)))
        retained = max(2, min(120, int(self.s.hls_retained_segments)))
        flags = "delete_segments+omit_endlist+independent_segments+temp_file" + ("+discont_start" if start_number else "")
        a += ["-f", "tee",
              f"[f=mpegts:mpegts_flags=+pat_pmt_at_frames:mpegts_start_pid={VIDEO_PID}]pipe:1|"
              f"[f=hls:hls_time={seg}:hls_list_size={window}:hls_delete_threshold={retained}:hls_flags={flags}:start_number={start_number}"
              f":hls_segment_filename=seg_%05d.ts]index.m3u8"]
        return a

    # lifecycle ------------------------------------------------------------------------------------------------
    def start(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state = "starting"
        self._spawn()
        threading.Thread(target=self._supervise, daemon=True, name=f"broadcast-enc-{self.feed.key}").start()

    def _spawn(self):
        start = self.next_segment
        for old in self.dir.glob("*"):                           # a restart continues the numbering, marked as a cut
            m = SEGMENT_RE.fullmatch(old.name)
            if m:
                start = max(start, int(m.group(1)) + 1)
            try:
                old.unlink()
            except OSError:
                pass
        self.next_segment = start
        audio_r = audio_w = None
        if self.audio_for is not None:
            audio_r, audio_w = os.pipe()
        try:
            proc = self.popen(self.argv(audio_r, start), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, cwd=str(self.dir),
                              **({"pass_fds": (audio_r,)} if audio_r is not None else {}))
        except BaseException:
            if audio_w is not None:
                os.close(audio_w)
            raise
        finally:
            if audio_r is not None:
                os.close(audio_r)
        self.proc, self.last_write = proc, self.clock()
        self._reset_media(proc)
        self.state = "running"
        name = self.feed.key
        threading.Thread(target=self._write_video, args=(proc,), daemon=True, name=f"broadcast-v-{name}").start()
        threading.Thread(target=self._read_ts, args=(proc,), daemon=True, name=f"broadcast-ts-{name}").start()
        threading.Thread(target=self._read_err, args=(proc,), daemon=True, name=f"broadcast-err-{name}").start()
        if audio_w is not None:
            threading.Thread(target=self._write_audio, args=(proc, audio_w), daemon=True,
                             name=f"broadcast-a-{name}").start()

    def _write_video(self, proc):
        """Constant frame rate against the monotonic clock: a frame every 1/fps (the newest picture, repeated while
        the source is quiet). Behind by up to a second: catch up with repeats so ffmpeg's frame count stays on the
        wall clock; further behind (ffmpeg starved): start counting again from now."""
        period = 1.0 / self.fps
        next_t = self.clock()
        while not self.closed and proc is self.proc:
            frame = self.feed.read()
            try:
                proc.stdin.write(frame)
                proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError, AttributeError):
                return
            if not self._accept_video(proc):
                return
            next_t += period
            delay = next_t - self.clock()
            if delay > 0:
                time.sleep(delay)
            elif delay < -1.0:
                self.late += 1
                next_t = self.clock()

    def _reset_media(self, proc):
        with self.lock:
            self._media={'proc':proc,'video_frames':0,'audio_samples':0,'last_video_at':self.clock(),
                         'last_audio_at':None,'last_output_at':None,'audio_discarded_bytes':0}

    def _accept_video(self, proc):
        """Advance only after the entire JPEG has entered this process's pipe."""
        with self.lock:
            media=self._media
            if proc is not self.proc or media is None or media['proc'] is not proc:
                return False
            media['video_frames']+=1
            media['last_video_at']=self.last_write=self.clock()
            self.frames_in+=1
            return True

    def _write_audio(self, proc, fd: int):
        """PCM duration follows accepted video frames, not an independent wall clock.

        A starved video writer pauses both encoded timelines. Writes remain at
        most 20 ms; audio cannot accumulate a permanent lead after video resets
        its wall-clock pacing, and old writers cannot advance a new process.
        """
        try:
            out = os.fdopen(fd, "wb", buffering=0)
        except OSError:
            return
        written = 0
        try:
            while not self.closed and proc is self.proc:
                with self.lock:
                    media=self._media
                    if media is None or media['proc'] is not proc:
                        return
                    target=media['video_frames']*AUDIO_RATE//self.fps
                    video_age=self.clock()-media['last_video_at']
                need=min(AUDIO_RATE//50,target-written)
                if need <= 0:
                    if video_age>.1 and self.tap is not None:
                        # The tap's ring is bounded, but even .4 s of old sound
                        # should not replay against the newest picture on resume.
                        discarded=self.tap.take(int(AUDIO_BYTES_S*AUDIO_BUFFER_S))
                        with self.lock:
                            if self._media is media:media['audio_discarded_bytes']+=len(discarded)
                    time.sleep(0.02)
                    continue
                tap = self.tap
                data = tap.take(need * 4) if tap else b""
                if len(data) < need * 4:
                    data += bytes(need * 4 - len(data))
                view = memoryview(data)
                while view:
                    count=out.write(view)
                    if not count:raise BrokenPipeError('PCM pipe made no progress')
                    view = view[count:]
                written += need
                with self.lock:
                    if self._media is not media or proc is not self.proc:return
                    media['audio_samples']=written
                    media['last_audio_at']=self.clock()
        except (BrokenPipeError, OSError, ValueError, TypeError):
            pass
        finally:
            try:
                out.close()
            except OSError:
                pass

    def retap(self, now: float):
        """Hub tick: keep the sound on the session the feed shows (looked for again every few seconds while there is
        none: Dolphin can open its stream after the picture starts)."""
        if self.audio_for is None or self.closed:
            return
        sid = self.feed.sid if self.feed.mode in ("live", "hold") else None
        if sid != self.tap_sid:
            self._close_tap()
            self.tap_sid, self.tap_checked = sid, -1e9
        if sid is None or (self.tap is not None and self.tap.alive()) or now - self.tap_checked < AUDIO_RECHECK_S:
            return
        self.tap_checked = now
        self._close_tap()
        index = self.audio_for(self.feed)
        if index is not None:
            try:
                self.tap = AudioTap(index, popen=self.popen)
            except Exception as e:                               # noqa: BLE001 - no sound is never a broken feed
                self.errors.append(f"audio tap: {type(e).__name__}: {e}"[:200])

    def _close_tap(self):
        if self.tap is not None:
            self.tap.close()
            self.tap = None

    def _read_ts(self, proc):
        scan = TsGop()
        while True:
            try:
                data = proc.stdout.read1(65536)
            except (OSError, ValueError, AttributeError):
                break
            if not data:
                break
            self.bytes_out += len(data)
            with self.lock:
                if self._media is not None and self._media['proc'] is proc:
                    self._media['last_output_at']=self.clock()
            for piece, key in scan.feed(data):
                self._deliver(piece, key)
        for piece, key in scan.flush():
            self._deliver(piece, key)

    def _deliver(self, piece: bytes, key: bool):
        with self.lock:
            if key:
                self.gop, self.gop_bytes = [piece], len(piece)
            elif self.gop:
                self.gop.append(piece)
                self.gop_bytes += len(piece)
                if self.gop_bytes > GOP_CACHE_MAX:
                    self.gop, self.gop_bytes = [], 0
            subs = list(self.subs)
        for sub in subs:
            try:
                sub.loop.call_soon_threadsafe(sub.offer, piece, key)
            except RuntimeError:                                 # its loop is gone
                with self.lock:
                    self.subs.discard(sub)

    def _read_err(self, proc):
        try:
            for raw in proc.stderr:
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    self.errors.append(line[:300])
        except (OSError, ValueError, AttributeError):
            pass

    def _supervise(self):
        while not self.closed:
            time.sleep(0.5)
            try:
                self.check()
            except Exception as e:                               # noqa: BLE001 - keep supervising
                self.log(f"gBox broadcast: encoder {self.feed.key} supervisor error {type(e).__name__}: {e}")

    def check(self, now: float | None = None) -> str | None:
        """One supervision step: restart a dead encoder, or one that stopped taking pictures (with backoff)."""
        now = self.clock() if now is None else now
        if self.closed:
            return None
        proc = self.proc
        if proc is None:
            if now >= self._next_spawn:
                self.restarts += 1
                self.log(f"gBox broadcast: restarting the {self.feed.key} encoder (restart {self.restarts})")
                try:
                    self._spawn()
                except OSError as e:
                    self.errors.append(f"ffmpeg did not start: {e}"[:200])
                    self._next_spawn = now + self.BACKOFF[1]
                    return "failed"
                return "restarted"
            return None
        if proc.poll() is not None:
            reason = f"ffmpeg exited ({proc.poll()})"
        elif now - self.last_write >= self.STALL_S:
            reason = f"ffmpeg took no picture for {now - self.last_write:.0f} s"
            self._kill(proc)
        else:
            if self.frames_in:
                self._fails = 0
            return None
        tail = " | ".join(list(self.errors)[-3:])
        self.log(f"gBox broadcast: {self.feed.key} encoder: {reason}" + (f": {tail}" if tail else ""))
        self.state, self.proc = "restarting", None
        first, cap = self.BACKOFF
        self._next_spawn = now + min(cap, first * 2 ** min(self._fails, 6))
        self._fails += 1
        return "scheduled"

    @staticmethod
    def _kill(proc):
        try:
            proc.kill()
        except Exception:                                        # noqa: BLE001
            pass

    def stop(self):
        self.closed, self.state = True, "stopped"
        proc, self.proc = self.proc, None
        if proc is not None:
            try:
                proc.stdin.close()
            except Exception:                                    # noqa: BLE001
                pass
            self._kill(proc)
        self._close_tap()
        with self.lock:
            subs, self.subs = list(self.subs), set()
        for sub in subs:
            try:
                sub.loop.call_soon_threadsafe(sub.offer, None)
            except RuntimeError:
                pass
        shutil.rmtree(self.dir, ignore_errors=True)

    # viewers --------------------------------------------------------------------------------------------------
    def subscribe(self, loop) -> Sub:
        sub = Sub(loop)
        with self.lock:
            cached = b"".join(self.gop)
            self.subs.add(sub)
        if cached:
            sub.q.put_nowait(cached)
        return sub

    def unsubscribe(self, sub: Sub):
        with self.lock:
            self.subs.discard(sub)
            if not self.subs:
                self.left_at = self.clock()

    def touch_hls(self):
        self.hls_at = self.clock()

    def wanted(self, now: float, linger_s: float) -> bool:
        with self.lock:
            if self.subs:
                return True
        return now - max(self.hls_at, self.left_at, self.started_at) < linger_s

    def playlist(self) -> str | None:
        try:
            return (self.dir / "index.m3u8").read_text(encoding="utf-8")
        except OSError:
            return None

    def status(self) -> dict:
        with self.lock:
            viewers = len(self.subs)
            media=dict(self._media or {})
        video_s=media.get('video_frames',0)/self.fps
        audio_s=media.get('audio_samples',0)/AUDIO_RATE
        return {"feed": self.feed.key, "state": self.state, "pid": getattr(self.proc, "pid", None),
                "ts_viewers": viewers, "hls_active": bool(self.hls_at) and self.clock() - self.hls_at < 30,
                "frames_in": self.frames_in, "bytes_out": self.bytes_out, "late": self.late,
                'media_video_s':round(video_s,3),'media_audio_s':round(audio_s,3),
                'audio_lead_s':round(audio_s-video_s,3),
                'audio_write_age_s':round(self.clock()-media['last_audio_at'],3) if media.get('last_audio_at') is not None else None,
                'output_age_s':round(self.clock()-media['last_output_at'],3) if media.get('last_output_at') is not None else None,
                "restarts": self.restarts, "audio": bool(self.tap and self.tap.alive()),
                "audio_session": self.tap_sid if self.tap else None, "errors": list(self.errors)[-3:],
                "size": "%dx%d" % self.size, "fps": self.fps, "kbps": int(self.s.video_kbps),
                "hls_window_segments": self.s.hls_window_segments,
                "hls_retained_segments": self.s.hls_retained_segments,
                "encoder": str(self.s.encoder)}


# --- the hub ---------------------------------------------------------------------------------------------------------

class Hub:
    """Every feed being read, the program's choice and the H.264 encoders; one thread does the housekeeping at 10 Hz
    while anything is read and ends when nothing is."""

    def __init__(self, store, settings, *, live: dict, desktop_frames: dict | None = None,
                 desktop_watch: dict | None = None, host: str | None = None,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
                 popen=subprocess.Popen, tmp_root: Path | None = None, log: Callable[[str], None] = print,
                 agent_owned: Callable[[str], bool] | None = None,
                 find_sink: Callable[[str], int | None] = sink_input_for, autostart: bool = True):
        self.store, self.s = store, settings
        self.autostart = autostart                             # tests drive tick() themselves
        self.live = live
        self.desktop_frames = desktop_frames if desktop_frames is not None else {}
        self.desktop_watch = desktop_watch if desktop_watch is not None else {}
        self.host = slug(host if host is not None else platform.node())
        self.clock, self.wall, self.popen, self.log = clock, wall, popen, log
        self.find_sink = find_sink
        base = Path("/dev/shm") if Path("/dev/shm").is_dir() else Path(tempfile.gettempdir())
        self.root = tmp_root or base / f"gbox-broadcast-{os.getpid()}"
        self.lock = threading.RLock()
        self.feeds: dict[str, Feed] = {}
        self.encoders: dict[str, Encoder] = {}
        self.crops: dict[str, tuple[bytes, float]] = {}        # sid -> (game window JPEG, wall time of its desktop frame)
        self.crop_seq: dict[str, int] = {}                     # worker id -> desktop frame seq already cut
        self.crop_times: dict[str, collections.deque] = {}
        self._agent_owned = agent_owned or (lambda sid: False)
        self._owned: dict[str, tuple[bool, float]] = {}
        self._rows: list[dict] = []
        self._workers: dict[str, dict] = {}
        self._rows_at = -1e9
        self.watch: dict | None = None
        self.pin = self._load_pin()
        self.program_sid: str | None = None
        self.thread: threading.Thread | None = None
        self.stopping = False
        self.wake = threading.Event()                          # a switch or a watch report: tick now, not in 100 ms
        self.ticks = 0

    # program choice, persisted --------------------------------------------------------------------------------------
    def _load_pin(self) -> dict:
        try:
            pin = self.store.get("setting", PROGRAM_SETTING) or {}
        except Exception:                                        # noqa: BLE001
            pin = {}
        return pin if pin.get("mode") in ("auto", "session", "pc") else {"mode": "auto"}

    def set_program(self, mode: str, target: str = "", by: str = "operator") -> dict:
        pin = {"mode": mode, "target": target if mode != "auto" else "", "set_at": self.wall(), "by": by}
        with self.lock:
            self.pin = pin
        self.store.put("setting", PROGRAM_SETTING, pin)
        self.ensure_thread()
        self.wake.set()
        return pin

    def report_watch(self, sid: str | None, client: str = "", remote: str = "") -> dict:
        with self.lock:
            self.watch = {"session_id": sid or None, "at": self.wall(), "client": client[:40], "remote": remote[:64]}
            watch = dict(self.watch)
        self.wake.set()
        return watch

    def wait_tick(self, timeout: float = 0.5):
        """Until the hub has run a full tick after now (a switch shows in the answer), at most `timeout`."""
        thread = self.thread
        if thread is None or not thread.is_alive():
            return
        target, end = self.ticks + 2, time.monotonic() + timeout
        while self.ticks < target and time.monotonic() < end:
            time.sleep(0.02)

    def successor(self, sid: str) -> str | None:
        """The running session a swap or reset relaunch put in place of `sid` (its replaced_by chain)."""
        seen = set()
        while sid and sid not in seen:
            seen.add(sid)
            try:
                s = self.store.get("session", sid) or {}
            except Exception:                                    # noqa: BLE001
                return None
            if s.get("state") == "running":
                return sid
            sid = s.get("replaced_by") or ""
        return None

    # sessions -----------------------------------------------------------------------------------------------------
    def pc_match(self, row: dict, want: str) -> bool:
        want = slug(want)
        aliases = {slug(k): slug(v) for k, v in (self.s.pc_aliases or {}).items()}
        return slug(row.get("pc")) in (want, aliases.get(want, want))

    def refresh(self, force: bool = False) -> list[dict]:
        now = self.clock()
        with self.lock:
            if not force and now - self._rows_at < SESSIONS_TTL_S:
                return self._rows
        try:
            sessions = self.store.running_sessions()
            workers = {w["id"]: w for w in self.store.all("worker")}
        except Exception as e:                                   # noqa: BLE001 - keep the last good picture of things
            self.log(f"gBox broadcast: session read failed: {type(e).__name__}: {e}")
            return self._rows
        wall = self.wall()
        rows = []
        for s in sessions:
            sid = s.get("session_id") or ""
            if not sid:
                continue
            wid = sid.split("-", 1)[0]
            w = workers.get(wid) or {}
            owned = self._owned.get(sid)
            if owned is None or now - owned[1] > OWNER_TTL_S:     # the operator can claim an agent's session
                try:
                    owned = (bool(self._agent_owned(sid)), now)
                except Exception:                                # noqa: BLE001
                    owned = (False, now)
                self._owned[sid] = owned
            detail = s.get("detail") if isinstance(s.get("detail"), dict) else {}
            row = {"session_id": sid, "game_id": s.get("game_id"), "title": s.get("title") or s.get("game_id") or "a game",
                   "adapter": s.get("adapter"), "started": s.get("started") or 0, "detail": detail, "pc_id": wid,
                   "pc": str(w.get("name") or detail.get("staged_on") or detail.get("worker_name") or wid),
                   "os": w.get("os") or "", "pc_online": bool(w) and wall - (w.get("last_seen") or 0) < WORKER_TTL_S,
                   "agent_owned": owned[0], "federation": s.get("federation") or {}}
            row["kind"], row["age"] = self.source_kind(row)
            row["fresh"] = row["age"] is not None and row["age"] <= self._stale_after(row["kind"])
            rows.append(row)
        alive = {r["session_id"] for r in rows}
        for sid in [k for k in self._owned if k not in alive]:
            self._owned.pop(sid, None)
        with self.lock:
            self._rows, self._workers, self._rows_at = rows, workers, now
        return rows

    def workers(self) -> dict[str, dict]:
        return self._workers

    def _stale_after(self, kind: str) -> float:
        return {"desktop_crop": CROP_STALE_S, "stills": STILLS_STALE_S}.get(kind, float(self.s.hold_s))

    def source_kind(self, row: dict) -> tuple[str, float | None]:
        """The best picture of a session now: (kind, age of its newest frame in seconds, or None)."""
        sid, wall = row["session_id"], self.wall()
        lv = self.live.get(sid) or {}
        lv_age = wall - lv["ts"] if lv.get("ts") and lv.get("frame") else None
        streamed = lv.get("source") == "stream" or bool(lv.get("uploads"))
        if streamed:
            return ("spark_capture" if row.get("os") == "linux" else "windows_stream"), lv_age
        crop = self.crops.get(sid)
        crop_age = wall - crop[1] if crop else None
        if crop_age is not None and crop_age <= CROP_STALE_S:
            return "desktop_crop", crop_age
        if lv_age is not None:
            return "stills", lv_age
        if row.get("os") == "windows" and (row.get("detail") or {}).get("local_window") \
                and (row.get("federation") or {}).get("media") != "session_stream":
            return "desktop_crop", crop_age                      # nothing yet: a crop is what gets asked for
        return ("spark_capture" if row.get("os") == "linux" else "windows_stream"), None

    # feeds ----------------------------------------------------------------------------------------------------------
    def feed(self, key: str) -> Feed:
        with self.lock:
            f = self.feeds.get(key)
            if f is None:
                f = self.feeds[key] = Feed(key, self.clock)
            f.seen = self.clock()
        self.ensure_thread()
        return f

    def attach(self, key: str) -> Feed:
        with self.lock:
            f = self.feed(key)
            f.viewers += 1
        return f

    def detach(self, f: Feed):
        with self.lock:
            f.viewers = max(0, f.viewers - 1)
            f.seen = self.clock()

    def encoder(self, key: str) -> Encoder:
        with self.lock:
            enc = self.encoders.get(key)
            if enc is not None and not enc.closed:
                return enc
            if len([e for e in self.encoders.values() if not e.closed]) >= int(self.s.max_encoders):
                raise RuntimeError(f"{self.s.max_encoders} H.264 feeds are being encoded already; "
                                   "watch one of those, or this feed's MJPEG")
            f = self.feed(key)
            f.encoders += 1
            enc = Encoder(f, self.s, self.root, audio_for=self._sink_for, popen=self.popen, clock=self.clock, log=self.log)
            self.encoders[key] = enc
        try:
            enc.start()
        except BaseException:
            with self.lock:
                self.encoders.pop(key, None)
                f.encoders = max(0, f.encoders - 1)
            enc.closed = True
            raise
        self.log(f"gBox broadcast: H.264 encoder for {key} started (pid {getattr(enc.proc, 'pid', None)})")
        return enc

    def _sink_for(self, feed: Feed) -> int | None:
        """A Spark session's PipeWire stream, when the feed shows one that plays on this machine."""
        row = feed.row or {}
        detail = row.get("detail") or {}
        display, pid = detail.get("display"), detail.get("pid")
        if row.get("os") != "linux" or slug(row.get("pc")) != self.host or not (display or pid):
            return None
        return self.find_sink(str(display or ""), pid=pid)

    def ensure_thread(self):
        with self.lock:
            if not self.autostart or self.stopping or (self.thread is not None and self.thread.is_alive()):
                return
            self.thread = threading.Thread(target=self._run, daemon=True, name="broadcast-hub")
            self.thread.start()

    def _run(self):
        while not self.stopping:
            try:
                busy = self.tick()
            except Exception as e:                               # noqa: BLE001 - housekeeping must go on
                self.log(f"gBox broadcast: hub error {type(e).__name__}: {e}")
                busy = True
            if not busy:
                with self.lock:                                  # nothing is read: the thread ends (restarts on demand)
                    if not self.feeds and not self.encoders:
                        self.thread = None
                        return
            self.wake.wait(TICK_S)
            self.wake.clear()

    def tick(self) -> bool:
        """One housekeeping step. False when nothing is read any more."""
        now, wall = self.clock(), self.wall()
        rows = self.refresh()
        with self.lock:
            feeds = list(self.feeds.values())
            encoders = list(self.encoders.items())
        for key, enc in encoders:
            if enc.closed or not enc.wanted(now, float(self.s.linger_s)):
                if not enc.closed:
                    self.log(f"gBox broadcast: H.264 encoder for {key} stopped (nobody reads it)")
                    enc.stop()
                with self.lock:
                    if self.encoders.get(key) is enc:
                        self.encoders.pop(key, None)
                    enc.feed.encoders = max(0, enc.feed.encoders - 1)
        for f in feeds:
            if f.users() == 0 and now - f.seen > FEED_IDLE_S:
                with self.lock:
                    if f.users() == 0:
                        self.feeds.pop(f.key, None)
                        continue
            self._update(f, rows, now, wall)
        self._cut_desktops(feeds, wall)
        for _, enc in encoders:
            if not enc.closed:
                enc.retap(now)
        self.ticks += 1
        with self.lock:
            return bool(self.feeds or self.encoders)

    def resolve(self, f: Feed, rows: list[dict]) -> tuple[str | None, str]:
        if f.key == "program":
            with self.lock:
                pin, watch, current = dict(self.pin), dict(self.watch) if self.watch else None, self.program_sid
            sid, why = choose(pin, watch, rows, current=current, now=self.wall(), watch_ttl_s=float(self.s.watch_ttl_s),
                              auto_agents=bool(self.s.auto_agents), pc_match=self.pc_match, successor=self.successor)
            if pin.get("mode") == "session" and sid and why == "pinned (its relaunch)":
                self.set_program("session", sid, by="gbox-broadcast")      # the pin follows the relaunch from now on
            elif pin.get("mode") == "session" and why.startswith("the pinned session ended"):
                self.set_program("auto", by="gbox-broadcast")              # a pinned game that ended hands back to auto
            with self.lock:
                self.program_sid = sid
            return sid, why
        if f.key.startswith("pc:"):
            want = f.key[3:]
            mine = [r for r in rows if self.pc_match(r, want)]
            if not mine:
                return None, f"{want} is not running a game"
            best = max(mine, key=lambda r: (bool(r.get("fresh")), r.get("started") or 0))
            return best["session_id"], f"what {best['pc']} runs now"
        sid = f.key.split(":", 1)[1]
        if any(r["session_id"] == sid for r in rows):
            return sid, "this session"
        nxt = self.successor(sid)
        if nxt and any(r["session_id"] == nxt for r in rows):
            return nxt, "its relaunch"
        return None, "this session has ended"

    def _update(self, f: Feed, rows: list[dict], now: float, wall: float):
        by_id = {r["session_id"]: r for r in rows}
        if f.sid and f.sid not in by_id:                         # the session on this feed ended: its last picture
            if f.ended_at is None:                               # holds a moment before the feed moves on
                f.ended_at = now
            if now - f.ended_at < float(self.s.end_hold_s) and f.last:
                f.mode, f.reader, f.resolved = "hold", None, True
                return
        target, why = self.resolve(f, rows)
        if target != f.sid:
            f.sid, f.switched_at, f.since, f.ended_at = target, now, wall, None
        f.row, f.why = by_id.get(target) if target else None, why
        row = f.row
        if row is None:
            f.kind, f.reader = "none", None
            if f.key == "program":
                self._slate(f, "gBox", why or "no game is running")
            elif f.key.startswith("pc:"):
                self._slate(f, f.key[3:], "is not running a game")
            else:
                self._slate(f, "Session ended", why)
            return
        kind, age = self.source_kind(row)
        f.kind = kind
        if age is not None and age <= self._stale_after(kind):
            f.reader, f.mode, f.resolved = self._reader(row["session_id"], kind), "live", True
            return
        if f.last and now - f.switched_at < SWITCH_WAIT_S:       # switched: the previous picture holds a moment
            f.mode, f.reader, f.resolved = "hold", None, True
            return
        if not row.get("pc_online"):
            line = f"{row['pc']} is offline: waiting for it"
        elif kind in ("stills", "desktop_crop"):
            line = f"on {row['pc']}: waiting for the game to show on that PC's screen"
        else:
            line = f"on {row['pc']}: waiting for its picture"
        self._slate(f, row["title"], line)

    def _reader(self, sid: str, kind: str) -> Callable[[], bytes | None]:
        if kind == "desktop_crop":
            crops = self.crops
            return lambda: (crops.get(sid) or (None,))[0]
        live = self.live
        return lambda: (live.get(sid) or {}).get("frame")

    def _slate(self, f: Feed, title: str, line: str):
        size = jpeg_size(f.last) or parse_size(self.s.size)
        key = (title, line, size, id(f.last))
        if f.slate_key != key:
            try:
                f.slate = render_slate(title, line, size, f.last)
            except Exception as e:                               # noqa: BLE001 - a slate failure keeps the last picture
                self.log(f"gBox broadcast: slate failed: {type(e).__name__}: {e}")
                f.slate = f.last or BLANK
            f.slate_key = key
        # Publish initial readiness only after there are actual bytes to show.
        # Otherwise an HTTP reader can race slow slate rendering and emit the
        # tiny black bootstrap JPEG as a visible flash.
        f.mode, f.reader, f.resolved = "slate", None, True

    def _cut_desktops(self, feeds: list[Feed], wall: float):
        """Native Windows games that are read: keep their PC's screen coming (as the Other PC view does) and cut each
        new desktop frame to the game's window once, for every reader of it."""
        want: dict[str, set[str]] = {}
        for f in feeds:
            row = f.row
            if row and f.users() and row.get("os") == "windows" and (row.get("detail") or {}).get("local_window") \
                    and (row.get("federation") or {}).get("media") != "session_stream":
                want.setdefault(row["pc_id"], set()).add(row["session_id"])
        for wid, sids in want.items():
            self.desktop_watch[wid] = wall + DESKTOP_RENEW_S
            frame = self.desktop_frames.get(wid) or {}
            seq = frame.get("seq", 0)
            if not frame or seq == self.crop_seq.get(wid) or wall - frame.get("ts", 0) > DESKTOP_FRESH_S:
                continue
            self.crop_seq[wid] = seq
            for sid in sids:
                rect = (frame.get("game_rects") or {}).get(sid)
                cut = crop_game(frame["image"], rect) if rect else None
                if cut:
                    self.crops[sid] = (cut, frame.get("ts", wall))
                    self.crop_times.setdefault(sid, collections.deque(maxlen=32)).append(self.clock())
        wanted = set().union(*want.values()) if want else set()
        for sid in [s for s, c in self.crops.items() if s not in wanted and wall - c[1] > 60]:
            self.crops.pop(sid, None)
            self.crop_times.pop(sid, None)

    # what the routes report ---------------------------------------------------------------------------------------
    def fps_of(self, row: dict) -> float | None:
        sid = row["session_id"]
        if row.get("kind") == "desktop_crop":
            q = self.crop_times.get(sid)
            if not q or len(q) < 2 or self.clock() - q[-1] > CROP_STALE_S:
                return 0.0 if q else None
            span = q[-1] - q[0]
            return round((len(q) - 1) / span, 1) if span > 0 else None
        lv = self.live.get(sid) or {}
        fps, ts = lv.get("fps"), lv.get("ts")
        if fps is None or not ts:
            return None
        return 0.0 if self.wall() - ts > max(2.0, 3.0 / max(fps, 0.01)) else round(fps, 1)

    def resolution_of(self, row: dict) -> list[int] | None:
        sid = row["session_id"]
        frame = (self.crops.get(sid) or (None,))[0] if row.get("kind") == "desktop_crop" else \
            (self.live.get(sid) or {}).get("frame")
        size = jpeg_size(frame)
        return list(size) if size else None

    def describe(self, row: dict, bases: dict[str, str], token: str = "") -> dict:
        paths = feed_paths("session:" + row["session_id"])
        out = {"id": "session/" + row["session_id"], "session_id": row["session_id"], "title": row["title"],
               "game_id": row.get("game_id"), "adapter": row.get("adapter"), "pc": row["pc"], "pc_id": row["pc_id"],
               "os": row.get("os"), "pc_online": row.get("pc_online"), "kind": row["kind"],
               "agent_owned": row.get("agent_owned"), "started": row.get("started"),
               "on_air": row["session_id"] == self.program_sid,
               "resolution": self.resolution_of(row), "fps": self.fps_of(row),
               "last_frame_age_s": round(row["age"], 1) if row.get("age") is not None else None,
               "live": bool(row.get("fresh")), "paths": paths, "pc_paths": feed_paths("pc:" + slug(row["pc"]))}
        for name, base in bases.items():
            out[name] = absolute(paths, base, token)
        return out

    def feed_status(self, f: Feed) -> dict:
        row = f.row or {}
        return {"feed": f.key, "session_id": f.sid, "title": row.get("title"), "pc": row.get("pc"), "kind": f.kind,
                "state": f.mode, "why": f.why, "since": f.since, "viewers": f.viewers,
                "agent_owned": row.get("agent_owned")}

    def program_status(self) -> dict:
        f = self.feeds.get("program")
        with self.lock:
            pin, watch = dict(self.pin), dict(self.watch) if self.watch else None
        if f is None or not f.resolved:                          # nobody reads the program: what it would show now
            rows = self.refresh()
            sid, why = choose(pin, watch, rows, current=self.program_sid, now=self.wall(),
                              watch_ttl_s=float(self.s.watch_ttl_s), auto_agents=bool(self.s.auto_agents),
                              pc_match=self.pc_match, successor=self.successor)
            row = next((r for r in rows if r["session_id"] == sid), {})
            status = {"feed": "program", "session_id": sid, "title": row.get("title"), "pc": row.get("pc"),
                      "kind": row.get("kind") or "none", "state": "live" if row.get("fresh") else "slate",
                      "why": why, "since": None, "viewers": 0, "agent_owned": row.get("agent_owned")}
        else:
            status = self.feed_status(f)
        watching = None
        if watch:
            age = self.wall() - (watch.get("at") or 0)
            watching = watch | {"age_s": round(age, 1), "counts": age <= float(self.s.watch_ttl_s)}
        return status | {"mode": pin.get("mode", "auto"), "target": pin.get("target") or None,
                         "set_by": pin.get("by"), "watching": watching}

    def status(self) -> dict:
        with self.lock:
            feeds = [self.feed_status(f) for f in self.feeds.values()]
            encoders = [e.status() for e in self.encoders.values()]
        return {"program": self.program_status(), "feeds": feeds, "encoders": encoders,
                "settings": {"fps": self.s.fps, "ts_fps": self.s.ts_fps, "size": self.s.size,
                             "video_kbps": self.s.video_kbps, "encoder": self.s.encoder, "audio": self.s.audio,
                             "hold_s": self.s.hold_s, "max_encoders": self.s.max_encoders}}

    def close(self):
        self.stopping = True
        with self.lock:
            encoders, self.encoders = list(self.encoders.values()), {}
        for enc in encoders:
            enc.stop()
        shutil.rmtree(self.root, ignore_errors=True)


# --- routes ----------------------------------------------------------------------------------------------------------

def register(app, store, config, *, live: dict, desktop_frames: dict, desktop_watch: dict,
             agent_owned: Callable[[str], bool] | None = None, hub: Hub | None = None) -> Hub:
    """Mount /api/broadcast/* on the control plane (gbox/server.py) and return the hub."""
    settings = config.broadcast
    hub = hub or Hub(store, settings, live=live, desktop_frames=desktop_frames, desktop_watch=desktop_watch,
                     agent_owned=agent_owned)
    app.state.broadcast = hub
    tokens = Tokens(store)
    app.state.broadcast_tokens = tokens
    main_token = config.token()

    def bases() -> dict[str, str]:
        out = {}
        lan = settings.lan_url or config.public_url or ""
        if lan:
            out["lan"] = lan
        if settings.tailnet_url:
            out["tailnet"] = settings.tailnet_url
        return out

    def viewer(request: Request) -> dict:
        """Who reads a broadcast route: the operator's clients (main token, header only) or a broadcast token."""
        if not settings.enabled:
            raise HTTPException(404, "broadcast is off ([broadcast] enabled = false)")
        header = request.headers.get("authorization", "")
        bearer = header[7:].strip() if header[:7].lower() == "bearer " else ""
        query = request.query_params.get("token") or request.query_params.get("t") or ""
        remote = request.client.host if request.client else ""
        if bearer and hmac.compare_digest(bearer.encode(), main_token.encode()):
            return {"who": request.headers.get("x-gbox-actor", "operator"), "main": True, "scope": "control",
                    "token": ""}
        if query and hmac.compare_digest(query.encode(), main_token.encode()):
            raise HTTPException(401, "the gBox api_token never goes in a URL: make a broadcast token "
                                     "(Sessions > Broadcast, or POST /api/broadcast/tokens) and use ?token=gbb_...")
        for secret, in_url in ((bearer, False), (query, True)):
            row = tokens.check(secret, remote) if secret else None
            if row:
                return {"who": "broadcast:" + row["name"], "main": False, "scope": row.get("scope", "view"),
                        "token": secret if in_url else "", "token_id": row["id"]}
        raise HTTPException(401, "a broadcast token is required (?token=gbb_...)")

    def operator(v: dict = Depends(viewer)) -> dict:
        if not v["main"]:
            raise HTTPException(403, "broadcast tokens can only watch; this needs the gBox app (api_token)")
        return v

    # --- status, feeds, program ---------------------------------------------------------------------------------
    @app.get("/api/broadcast")
    def broadcast_status(v: dict = Depends(viewer)):
        """What is on air, the feeds being read, the H.264 encoders."""
        out = hub.status()
        out["urls"] = {"program": feed_paths("program")} | {
            name: absolute(feed_paths("program"), base, v["token"]) for name, base in bases().items()}
        return out

    @app.get("/api/broadcast/feeds")
    def broadcast_feeds(v: dict = Depends(viewer)):
        """Every live gameplay feed on every gBox PC, the program first; stable URLs for each."""
        rows = hub.refresh(force=True)
        b = bases()
        program = hub.program_status() | {"paths": feed_paths("program")} | {
            n: absolute(feed_paths("program"), base, v["token"]) for n, base in b.items()}
        pcs = []
        for w in hub.workers().values():
            name = str(w.get("name") or w.get("id"))
            mine = [r for r in rows if r["pc_id"] == w["id"]]
            best = max(mine, key=lambda r: (bool(r.get("fresh")), r.get("started") or 0)) if mine else None
            key = "pc:" + slug(name)
            pcs.append({"pc": name, "id": "pc/" + slug(name), "pc_id": w["id"], "os": w.get("os"),
                        "online": hub.wall() - (w.get("last_seen") or 0) < WORKER_TTL_S,
                        "aliases": sorted(k for k, val in (settings.pc_aliases or {}).items() if slug(val) == slug(name)),
                        "session_id": best["session_id"] if best else None, "title": best["title"] if best else None,
                        "paths": feed_paths(key)} | {n: absolute(feed_paths(key), base, v["token"]) for n, base in b.items()})
        feeds = [hub.describe(r, b, v["token"]) for r in sorted(rows, key=lambda r: (r["pc"].lower(), -(r.get("started") or 0)))]
        return {"program": program, "feeds": feeds, "pcs": sorted(pcs, key=lambda p: p["pc"].lower()), "bases": b,
                "formats": {"mjpeg": MEDIA_MJPEG, "jpeg": "image/jpeg", "ts": "video/mp2t",
                            "hls": "application/vnd.apple.mpegurl"},
                "mjpeg_fps": settings.fps,
                "h264": {"size": settings.size, "fps": settings.ts_fps, "kbps": settings.video_kbps,
                         "audio": settings.audio}}

    @app.post("/api/broadcast/program")
    def broadcast_program(body: Any = Body(default=None), v: dict = Depends(viewer)):
        """Switch the program: {"session_id": "<sid>"} | {"pc": "<name>"} | {"session_id": "auto"} | "auto"."""
        if v["scope"] != "control":
            raise HTTPException(403, "this broadcast token can only watch (make a control token to switch)")
        if v["main"] and v["who"] in AUTOMATION:
            raise HTTPException(403, "automation never switches the program: the operator (gBox app) or a "
                                     "control token (Pine Box) does")
        body = {"session_id": body} if isinstance(body, str) else (body or {})
        if not isinstance(body, dict):
            raise HTTPException(422, "expected {session_id} or {pc} or \"auto\"")
        sid, pc = str(body.get("session_id") or "").strip(), str(body.get("pc") or "").strip()
        if str(body.get("mode") or "") == "auto" or sid == "auto" or (not sid and not pc):
            pin = hub.set_program("auto", by=v["who"])
        elif sid:
            s = store.get("session", sid) if SESSION_ID_RE.fullmatch(sid) else None
            if not s or s.get("state") != "running":
                raise HTTPException(409, f"session {sid} is not running")
            pin = hub.set_program("session", sid, by=v["who"])
        else:
            hub.refresh(force=True)
            known = {slug(w.get("name")) for w in hub.workers().values()} | {slug(k) for k in settings.pc_aliases or {}}
            if slug(pc) not in known:
                raise HTTPException(404, f"no gBox PC called {pc}")
            pin = hub.set_program("pc", pc, by=v["who"])
        store.audit(v["who"], "broadcast.program", pin.get("target") or "auto", {"mode": pin["mode"]})
        hub.refresh(force=True)
        hub.wait_tick()
        return {"pin": pin, "program": hub.program_status()}

    @app.post("/api/broadcast/watching")
    def broadcast_watching(request: Request, body: Any = Body(default=None), v: dict = Depends(operator)):
        """The operator's app: the session it shows ({"session_id": null}: none). The program follows it in auto."""
        if v["who"] != "operator":
            return {"ignored": f"actor {v['who']} is not the operator"}
        sid = body.get("session_id") if isinstance(body, dict) else None
        sid = str(sid) if sid else None
        if sid and not SESSION_ID_RE.fullmatch(sid):
            raise HTTPException(422, "bad session id")
        watch = hub.report_watch(sid, request.headers.get("x-gbox-client", ""),
                                 request.client.host if request.client else "")
        from .operator_guard import report_watch
        report_watch(store, "app:" + (request.client.host if request.client else "") + ":" +
                     request.headers.get("x-gbox-client", ""), sid)
        hub.refresh(force=True)
        hub.wait_tick()
        return {"watch": watch, "program": hub.program_status()}

    # --- tokens ------------------------------------------------------------------------------------------------
    @app.get("/api/broadcast/tokens")
    def broadcast_tokens(v: dict = Depends(operator)):
        return tokens.list()

    @app.post("/api/broadcast/tokens")
    def broadcast_token_new(body: Any = Body(default=None), v: dict = Depends(operator)):
        """A broadcast token for a media source ({name, scope: view | control}); the secret is in this answer only."""
        if v["who"] in AUTOMATION:
            raise HTTPException(403, "only the operator makes broadcast tokens")
        body = body if isinstance(body, dict) else {}
        try:
            row = tokens.create(str(body.get("name") or "media source"), str(body.get("scope") or "view"), by=v["who"])
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        store.audit(v["who"], "broadcast.token.create", row["id"], {"name": row["name"], "scope": row["scope"]})
        b = bases()
        return row | {"program": {n: absolute(feed_paths("program"), base, row["token"]) for n, base in b.items()},
                      "feeds": {n: f"{base.rstrip('/')}/api/broadcast/feeds?token={row['token']}" for n, base in b.items()}}

    @app.delete("/api/broadcast/tokens/{tid}")
    def broadcast_token_revoke(tid: str, v: dict = Depends(operator)):
        row = tokens.revoke(tid, by=v["who"])
        if not row:
            raise HTTPException(404, "no such broadcast token")
        store.audit(v["who"], "broadcast.token.revoke", tid, {"name": row.get("name")})
        return row

    # --- pictures ----------------------------------------------------------------------------------------------
    def key_of(params: dict) -> str:
        key = feed_key(params)
        if key.startswith("session:") and not SESSION_ID_RE.fullmatch(key[8:]):
            raise HTTPException(404, "bad session id")
        if key.startswith("pc:") and not key[3:]:
            raise HTTPException(404, "bad PC name")
        return key

    async def wait_resolved(f: Feed):
        for _ in range(20):                                      # the hub resolves a new feed within a tick
            if f.resolved:
                return
            await asyncio.sleep(0.05)

    async def mjpeg(request: Request, fps: int = 0, v: dict = Depends(viewer)):
        """MJPEG at a constant rate (?fps=1..60, default [broadcast] fps); never ends while the reader stays."""
        key = key_of(request.path_params)
        rate = clamp_fps(fps, clamp_fps(settings.fps, 30))
        f = hub.attach(key)

        async def body():
            loop = asyncio.get_running_loop()
            period = 1.0 / rate
            try:
                await wait_resolved(f)
                next_t = loop.time()
                while True:
                    frame = f.read()
                    f.frames_out += 1
                    yield part(frame)
                    next_t += period
                    delay = next_t - loop.time()
                    if delay < -1.0:                             # far behind (a slow reader): count from now
                        next_t, delay = loop.time(), 0.0
                    await asyncio.sleep(max(0.0, delay))
            finally:
                hub.detach(f)
        return StreamingResponse(body(), media_type=MEDIA_MJPEG,
                                 headers={"cache-control": "no-store", "x-accel-buffering": "no",
                                          "x-gbox-fps": str(rate)})

    async def jpeg(request: Request, v: dict = Depends(viewer)):
        key = key_of(request.path_params)
        f = hub.feed(key)
        await wait_resolved(f)
        return Response(f.read(), media_type="image/jpeg",
                        headers={"cache-control": "no-store", "x-gbox-session": f.sid or "", "x-gbox-state": f.mode})

    async def get_encoder(key: str) -> Encoder:
        try:
            return await run_in_threadpool(hub.encoder, key)
        except RuntimeError as e:
            raise HTTPException(503, str(e), headers={"retry-after": "30"}) from None
        except OSError as e:
            raise HTTPException(503, f"ffmpeg could not start: {e}") from None

    async def ts(request: Request, v: dict = Depends(viewer)):
        """H.264 (+ AAC) in MPEG-TS; the first bytes start at a keyframe; stays open through switches and restarts."""
        key = key_of(request.path_params)
        enc = await get_encoder(key)
        sub = enc.subscribe(asyncio.get_running_loop())

        async def body():
            try:
                while True:
                    piece = await sub.q.get()
                    if piece is None:                            # the server is shutting down
                        return
                    yield piece
            finally:
                enc.unsubscribe(sub)
        return StreamingResponse(body(), media_type="video/mp2t",
                                 headers={"cache-control": "no-store", "x-accel-buffering": "no"})

    async def hls_playlist(request: Request, v: dict = Depends(viewer)):
        key = key_of(request.path_params)
        enc = await get_encoder(key)
        enc.touch_hls()
        text = None
        for _ in range(150):                                     # a fresh encoder needs a couple of segments first
            text = enc.playlist()
            if text and text.count("#EXTINF") >= 2:
                break
            await asyncio.sleep(0.1)
            enc.touch_hls()
        if not text or "#EXTINF" not in text:
            raise HTTPException(503, "the H.264 feed is starting; try again", headers={"retry-after": "2"})
        if v["token"]:                                           # segment URLs carry the viewer's token
            text = "\n".join(line + "?token=" + v["token"] if line and not line.startswith("#") else line
                             for line in text.splitlines()) + "\n"
        return PlainTextResponse(text, media_type="application/vnd.apple.mpegurl",
                                 headers={"cache-control": "no-store"})

    async def hls_segment(request: Request, v: dict = Depends(viewer)):
        key = key_of({k: val for k, val in request.path_params.items() if k != "name"})
        name = request.path_params.get("name", "")
        if not SEGMENT_RE.fullmatch(name):
            raise HTTPException(404, "no such segment")
        enc = hub.encoders.get(key)
        if enc is None or enc.closed:
            raise HTTPException(404, "this feed is not being encoded (load its playlist first)")
        enc.touch_hls()
        path = enc.dir / name
        if not path.is_file():
            raise HTTPException(404, "segment gone (the playlist moved on)")
        return FileResponse(path, media_type="video/mp2t", headers={"cache-control": "no-store"})

    for prefix in ("/api/broadcast/program", "/api/broadcast/pc/{pc}", "/api/broadcast/session/{sid}"):
        shown = prefix.endswith("program")
        app.add_api_route(prefix + ".mjpg", mjpeg, methods=["GET"], include_in_schema=shown)
        app.add_api_route(prefix + ".jpg", jpeg, methods=["GET"], include_in_schema=shown)
        app.add_api_route(prefix + ".ts", ts, methods=["GET"], include_in_schema=shown)
        app.add_api_route(prefix + "/hls/index.m3u8", hls_playlist, methods=["GET"], include_in_schema=False)
        app.add_api_route(prefix + "/hls/{name}", hls_segment, methods=["GET"], include_in_schema=False)

    @app.on_event("shutdown")
    async def _broadcast_stop():
        hub.close()

    return hub
