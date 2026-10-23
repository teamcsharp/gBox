"""Pine's authenticated HLS bridge to gBox's existing shared H.264/AAC encoder.

No encoder, microphone, token in a browser URL, or background task is created.
Install after gboxstream.install(app, globals()). Each playlist AND segment is
authorized against the current listener token and gboxstream.allowed_keys().
"""
from __future__ import annotations

import hashlib
import hmac
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import Header, HTTPException, Request
from fastapi.responses import Response

PUBLIC_GET = ("/api/gbox/hls", "/gbox-hls/pine-hls.js", "/gbox-hls/hls-1.7.3.min.js")
FILES = {"pine-hls.js": "pine-hls.js", "hls-1.7.3.min.js": "vendor/hls-1.7.3.min.js"}
SEGMENT = re.compile(r"seg_[0-9]{5,12}\.ts\Z")
UPSTREAM = re.compile(r"/api/broadcast/(?:program|pc/[A-Za-z0-9_-]{1,96}|session/[A-Za-z0-9_-]{1,96})\.mjpg\Z")
MAX_PLAYLIST = 64 * 1024
MAX_SEGMENT = 12 * 1024 * 1024
MAX_CACHE = 32 * 1024 * 1024


def relay_url(key: str, name: str = "index.m3u8", t: str = "", s: str = "") -> str:
    q = {"k": key, "name": name}
    if t:
        q["t"] = t
    if s:
        q["s"] = s
    return "/api/gbox/hls?" + urlencode(q)


def upstream_path(hub, key: str, name: str) -> str:
    if name != "index.m3u8" and not SEGMENT.fullmatch(name):
        raise ValueError("no such HLS object")
    path = hub.pictures().get(key, "")
    if not UPSTREAM.fullmatch(path):
        raise ValueError("no such gameplay feed")
    return path[:-5] + "/hls/" + name


def rewrite_playlist(raw: bytes, key: str, t: str = "", s: str = "") -> bytes:
    if len(raw) > MAX_PLAYLIST:
        raise ValueError("playlist too large")
    text = raw.decode("utf-8")
    if not text.startswith("#EXTM3U"):
        raise ValueError("invalid HLS playlist")
    lines = []
    for line in text.splitlines():
        if line.startswith("#"):
            # gBox emits one MPEG-TS media playlist; do not relay arbitrary
            # key/map/rendition URIs, even if an upstream response is corrupt.
            if "URI=" in line:
                raise ValueError("unexpected external HLS object")
            lines.append(line)
        elif line:
            if not SEGMENT.fullmatch(line):
                raise ValueError("unexpected HLS segment")
            lines.append(relay_url(key, line, t, s))
        else:
            lines.append("")
    return ("\n".join(lines) + "\n").encode()


class BoundedRelay:
    """Coalesce repeated segment reads, bounded in memory and upstream work.

    Authorization is intentionally outside this cache and runs on EVERY read.
    A sync FastAPI route runs blocking HTTP in its worker pool, not its loop.
    """
    def __init__(self, fetch=None, clock=time.monotonic):
        self.fetch = fetch or self._fetch
        self.clock = clock
        self.lock = threading.Lock()
        self.cache = OrderedDict()
        self.pending = {}
        self.slots = threading.BoundedSemaphore(4)
        self.bytes = 0

    @staticmethod
    def _fetch(url, headers, limit):
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=3.0), follow_redirects=False,
                          trust_env=False) as client:
            with client.stream("GET", url, headers=headers) as response:
                if response.status_code != 200:
                    raise RuntimeError("gameplay HLS unavailable")
                data = bytearray()
                for part in response.iter_bytes(65536):
                    data.extend(part)
                    if len(data) > limit:
                        raise ValueError("HLS object too large")
                return bytes(data)

    def read(self, hub, path: str, playlist: bool) -> bytes:
        key = (hub.gw.base, path)
        with self.lock:
            hit = self.cache.get(key)
            if hit and self.clock() - hit[0] < (0.35 if playlist else 15):
                self.cache.move_to_end(key)
                return hit[1]
            event = self.pending.get(key)
            owner = event is None
            if owner:
                event = self.pending[key] = threading.Event()
        if not owner:
            if not event.wait(21):
                raise RuntimeError("gameplay HLS busy")
            with self.lock:
                hit = self.cache.get(key)
                if hit and self.clock() - hit[0] < (1 if playlist else 15):
                    return hit[1]
            raise RuntimeError("gameplay HLS unavailable")
        try:
            if not self.slots.acquire(blocking=False):
                raise RuntimeError("gameplay HLS busy")
            try:
                limit = MAX_PLAYLIST if playlist else MAX_SEGMENT
                data = self.fetch(hub.gw.url(path), hub.gw.headers(), limit)
                if len(data) > limit:
                    raise ValueError("HLS object too large")
            finally:
                self.slots.release()
            with self.lock:
                old = self.cache.pop(key, None)
                self.bytes -= len(old[1]) if old else 0
                self.cache[key] = (self.clock(), data)
                self.bytes += len(data)
                while self.bytes > MAX_CACHE or len(self.cache) > 64:
                    _, old = self.cache.popitem(last=False)
                    self.bytes -= len(old[1])
            return data
        finally:
            with self.lock:
                self.pending.pop(key, None)
                event.set()


def install(app, app_globals, stream=None, relay=None):
    if stream is None:
        import gboxstream as stream
    relay = relay or BoundedRelay()
    folder = Path(__file__).resolve().parent / "frontend"
    original = stream.Hub.tile_view
    if not getattr(original, "_pine_hls", False):
        def tile_view(row, t, broadcast):
            tile = original(row, t, broadcast)
            tile.update(hls=relay_url(row["key"], t=t), hls_fps=30)
            return tile
        tile_view._pine_hls = True
        stream.Hub.tile_view = staticmethod(tile_view)

    def authorize(request, t, s, authorization):
        public = request.headers.get("x-pinebox-public") == "1"
        if t:
            if not app_globals["listen_ok"](t):
                raise HTTPException(403, "that tune-in link is not live")
            return True
        if s and not public:
            want = str(app_globals["media_sign"](stream.PREVIEW_KEY))
            if not want or not hmac.compare_digest(s, want):
                raise HTTPException(403, "invalid station preview")
            return False
        if public:
            raise HTTPException(403, "a tune-in link is required here")
        app_globals["require_read_auth"](authorization)
        return False

    @app.get("/gbox-hls/{name}")
    def hls_asset(name: str, request: Request):
        relative = FILES.get(name)
        if not relative:
            raise HTTPException(404)
        try:
            body = (folder / relative).read_bytes()
        except OSError:
            raise HTTPException(404) from None
        etag = '"' + hashlib.sha256(body).hexdigest()[:24] + '"'
        headers = {"Cache-Control": "no-cache", "ETag": etag,
                   "X-Content-Type-Options": "nosniff"}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return Response(body, media_type="application/javascript", headers=headers)

    @app.get("/api/gbox/hls")
    def gameplay_hls(request: Request, k: str = "", name: str = "index.m3u8",
                     t: str = "", s: str = "", authorization: str | None = Header(default=None)):
        guest = authorize(request, t, s, authorization)
        hub = stream.HUB
        if not hub or not stream.KEY_RE.fullmatch(k):
            raise HTTPException(404)
        if guest and k not in hub.allowed_keys():
            raise HTTPException(404, "not on the stage")
        try:
            path = upstream_path(hub, k, name)
        except ValueError:
            raise HTTPException(404) from None
        try:
            body = relay.read(hub, path, name == "index.m3u8")
            if name == "index.m3u8":
                body = rewrite_playlist(body, k, t, s)
        except Exception:
            raise HTTPException(503, "gameplay HLS is starting or unavailable; retry shortly",
                                headers={"Retry-After": "2"}) from None
        # A token may have been revoked while a fresh encoder was starting.
        authorize(request, t, s, authorization)
        if guest and k not in hub.allowed_keys():
            raise HTTPException(404, "not on the stage")
        hub.seen("hls")
        return Response(body, media_type=("application/vnd.apple.mpegurl" if name == "index.m3u8" else "video/mp2t"),
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "X-GBox-Transport": "shared-h264-aac"})

    return relay
