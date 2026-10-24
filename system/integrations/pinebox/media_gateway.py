"""Independent Pine media listeners; never import the station's app.py.

8097 forwards the existing public door (moved to loopback 18097), except HLS
and its pinned assets which go straight to gBox. 18098 serves only these media
routes for the private studio. No encoder or station scheduler starts here.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException

import gbox_hls

TRUTH = {"1", "true", "yes", "on"}
HOP_HEADERS = {b"connection", b"keep-alive", b"proxy-authenticate",
               b"proxy-authorization", b"te", b"trailer", b"transfer-encoding",
               b"upgrade", b"proxy-connection"}
MEDIA_PREFIX = "/gbox-hls/"


def _origin(value):
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username \
            or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Expected an HTTP origin without credentials or a path")
    # Accessing .port also rejects invalid ports.
    parsed.port
    return value.rstrip("/")


@dataclass(frozen=True)
class Config:
    data_dir: Path
    api_key: str = field(repr=False)
    lock_reads: bool = False
    backend: str = "http://127.0.0.1:18097"
    gbox_url: str = "http://127.0.0.1:8765"
    private_origins: tuple[str, ...] = ()
    public_port: int = 8097
    private_port: int = 18098

    def __post_init__(self):
        if not self.data_dir.is_absolute():
            raise ValueError("Pine data directory must be absolute")
        for value in (self.backend, self.gbox_url, *self.private_origins):
            _origin(value)
        if urlsplit(self.backend).hostname not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("The public-door backend must be loopback")
        if urlsplit(self.backend).port != 18097:
            raise ValueError("The existing public door must move to loopback port 18097")
        if len(set((self.public_port, self.private_port, 18097))) != 3 \
                or any(type(p) is not int or not 1024 <= p <= 65535
                       for p in (self.public_port, self.private_port)):
            raise ValueError("Media listeners need distinct unprivileged ports")

    @classmethod
    def environment(cls):
        data = os.environ.get("SPARK_AGENT_DATA_DIR")
        if not data:
            raise ValueError("Set the actual mounted SPARK_AGENT_DATA_DIR explicitly")
        return cls(Path(data).expanduser(), os.getenv("SPARK_AGENT_API_KEY", ""),
                   os.getenv("SPARK_AGENT_LOCK_READS", "false").lower() in TRUTH,
                   os.getenv("PINE_MEDIA_BACKEND", "http://127.0.0.1:18097"),
                   os.getenv("GBOX_URL", "http://127.0.0.1:8765"),
                   tuple(x.strip() for x in os.getenv("PINE_MEDIA_PRIVATE_ORIGINS", "").split(",") if x.strip()),
                   int(os.getenv("PINE_MEDIA_PUBLIC_PORT", "8097")),
                   int(os.getenv("PINE_MEDIA_PRIVATE_PORT", "18098")))


class JsonFile:
    """Bounded, coherent local reads; unreadable/changed files never reuse grants."""
    def __init__(self, path, limit):
        self.path, self.limit = Path(path), limit
        self.lock, self.key, self.value = threading.Lock(), None, None

    @staticmethod
    def identity(st):
        return st.st_ino, st.st_mtime_ns, st.st_ctime_ns, st.st_size

    def read(self):
        with self.lock:
            try:
                before = self.path.stat()
                if not self.path.is_file() or before.st_size > self.limit:
                    raise ValueError("State file unavailable")
                key = self.identity(before)
                if self.key != key:
                    with self.path.open("rb") as source:
                        raw = source.read(self.limit + 1)
                        opened = os.fstat(source.fileno())
                    if len(raw) > self.limit or self.identity(opened) != key \
                            or self.identity(self.path.stat()) != key:
                        raise ValueError("State changed while reading")
                    value = json.loads(raw)
                    if not isinstance(value, dict):
                        raise ValueError("State must be an object")
                    self.key, self.value = key, value
                return dict(self.value)
            except (OSError, ValueError, TypeError):
                self.key, self.value = None, None
                return None


class Authorization:
    def __init__(self, cfg, clock=time.time):
        self.cfg, self.clock = cfg, clock
        self.shares = JsonFile(cfg.data_dir / "shares.json", 1024 * 1024)

    def token_scope(self, token):
        if not isinstance(token, str) or not self.cfg.api_key or len(token) > 2048:
            return ""
        scope, raw = ("full", token[:-5]) if token.endswith(".full") else ("listen", token)
        try:
            expires, tag, sig = raw.split(".", 2)
            expiration = int(expires)
            now = self.clock()
            if not math.isfinite(now) or expiration < now:
                return ""
            state = self.shares.read()
            if state is None or not isinstance(state.get("revoked", []), list):
                return ""
            epoch = int(state.get("epoch") or 1)
            if tag in state.get("revoked", []):
                return ""
            body = f"{scope}:{expiration}:{tag}:{epoch}"
            wanted = hmac.new(self.cfg.api_key.encode(), body.encode(), hashlib.sha256).hexdigest()[:24]
            canonical = f"{expiration}.{tag}.{wanted}" + (".full" if scope == "full" else "")
            return scope if hmac.compare_digest(canonical, token) else ""
        except (ValueError, TypeError, OverflowError):
            return ""

    def listen_ok(self, token):
        return bool(self.token_scope(token))

    def media_sign(self, key):
        return hmac.new(self.cfg.api_key.encode(), key.encode(), hashlib.sha256).hexdigest()[:32] \
            if self.cfg.api_key else ""

    def require_read_auth(self, authorization):
        if not self.cfg.lock_reads:
            return
        if not self.cfg.api_key:
            raise HTTPException(500, "Station authentication is not configured")
        value = authorization or ""
        if hmac.compare_digest(value.encode(), ("Bearer " + self.cfg.api_key).encode()):
            return
        if value.startswith("Bearer ") and self.token_scope(value[7:]) == "full":
            return
        raise HTTPException(401, "Station read authentication required")


class PersistentRelay(gbox_hls.BoundedRelay):
    """Reuse bounded upstream connections as well as the existing single-flight cache."""
    def __init__(self):
        self.client = httpx.Client(timeout=httpx.Timeout(20, connect=3), trust_env=False,
                                   follow_redirects=False,
                                   limits=httpx.Limits(max_connections=4, max_keepalive_connections=4))
        super().__init__(self._download)

    def _download(self, url, headers, limit):
        with self.client.stream("GET", url, headers=headers) as response:
            if response.status_code != 200:
                raise RuntimeError("Gameplay media unavailable")
            data = bytearray()
            for part in response.iter_bytes(65536):
                data.extend(part)
                if len(data) > limit:
                    raise ValueError("HLS object too large")
            return bytes(data)

    def close(self):
        self.client.close()


def make_stream(cfg, stream_module=None):
    # gboxstream is a small independently tested module. app.py must not load.
    if stream_module is None:
        import gboxstream as stream_module

    class FreshGateway(stream_module.Gateway):
        def snapshot(self):
            value = super().snapshot()
            age = self.clock() - float(value.get("at") or 0)
            if not value.get("ok") or not math.isfinite(age) or not 0 <= age <= 15:
                return {"at": 0, "ok": False, "program": {}, "feeds": [], "pcs": []}
            return value

    class StrictHub(stream_module.Hub):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.state_file = JsonFile(cfg.data_dir / "gbox-stream.json", 65536)

        def settings(self):
            value = self.state_file.read()
            return stream_module.clamp_settings(value or {})

    token = stream_module.TokenFile(cfg.data_dir / "gbox_token")
    hub = StrictHub(None, FreshGateway(cfg.gbox_url, token), shrink=None, token_kind=token.kind)
    return SimpleNamespace(HUB=hub, Hub=StrictHub, PREVIEW_KEY=stream_module.PREVIEW_KEY,
                           KEY_RE=stream_module.KEY_RE)


def _clean_headers(headers, *, public):
    # Connection can name additional hop-by-hop fields. Never trust a caller's
    # routing or public-door identity, even when the backend would strip it too.
    nominated = set()
    for key, value in headers:
        if key.lower() == b"connection":
            nominated.update(x.strip().lower() for x in value.split(b","))
    denied = HOP_HEADERS | nominated
    if public:
        denied |= {b"authorization", b"x-pinebox-public", b"forwarded"}
    return [(k, v) for k, v in headers if k.lower() not in denied
            and not (public and k.lower().startswith(b"x-forwarded-"))]


class PublicProxy:
    """Fixed loopback target; request/response bodies remain streaming and bounded."""
    def __init__(self, backend, transport=None):
        self.base = httpx.URL(backend)
        self.transport = transport
        self.client = None

    async def start(self):
        self.client = httpx.AsyncClient(transport=self.transport, trust_env=False,
                                       follow_redirects=False,
                                       timeout=httpx.Timeout(10, connect=3, read=None),
                                       limits=httpx.Limits(max_connections=128, max_keepalive_connections=32))

    async def close(self):
        if self.client:
            await self.client.aclose()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            # Existing PublicListenerGate accepts no websocket traffic.
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            return
        raw_path = scope.get("raw_path", scope["path"].encode())
        if not raw_path.startswith(b"/") or b"\r" in raw_path or b"\n" in raw_path:
            await self.error(send, 400)
            return
        query = scope.get("query_string", b"")
        target = self.base.copy_with(raw_path=raw_path + (b"?" + query if query else b""))

        async def body():
            while True:
                event = await receive()
                if event["type"] == "http.disconnect":
                    raise asyncio.CancelledError()
                if event["type"] == "http.request":
                    if event.get("body"):
                        yield event["body"]
                    if not event.get("more_body"):
                        break

        response = None
        try:
            request = self.client.build_request(scope["method"], target,
                                                headers=self.request_headers(scope),
                                                content=body())
            response = await self.client.send(request, stream=True)
            await send({"type": "http.response.start", "status": response.status_code,
                        "headers": _clean_headers(response.headers.raw, public=False)})
            async for chunk in response.aiter_raw():
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            await send({"type": "http.response.body", "body": b""})
        except (httpx.HTTPError, OSError):
            if response is None:
                await self.error(send, 502)
            # A mid-body error terminates the stream; never fake an ENDLIST or
            # success payload. ASGI server closes the interrupted connection.
            else:
                raise
        finally:
            if response is not None:
                await response.aclose()

    @staticmethod
    def request_headers(scope):
        headers = _clean_headers(scope.get("headers", []), public=True)
        # Preserve the original Host for absolute listener links. The TCP
        # destination is still the immutable loopback URL above. Forwarded
        # identity comes from this socket, never caller-supplied headers.
        client = scope.get("client")
        if client:
            headers.append((b"x-forwarded-for", str(client[0]).encode("ascii")))
        headers.append((b"x-forwarded-proto", scope.get("scheme", "http").encode("ascii")))
        return headers

    @staticmethod
    async def error(send, status):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain"), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": b"Listener backend unavailable"})


class PublicGateway:
    def __init__(self, media, proxy):
        self.media, self.proxy = media, proxy

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self.media(scope, receive, send)
            return
        path = scope.get("path", "")
        if scope["type"] == "http" and (path == "/api/gbox/hls" or path.startswith(MEDIA_PREFIX)):
            headers = _clean_headers(scope.get("headers", []), public=True)
            headers.append((b"x-pinebox-public", b"1"))
            await self.media(dict(scope, headers=headers), receive, send)
        else:
            await self.proxy(scope, receive, send)


class PrivateGateway:
    """Only the same host's port8096 studio can use cross-origin media reads."""
    def __init__(self, inner, origins):
        self.inner, self.origins = inner, set(origins)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.inner(scope, receive, send)
            return
        values = [v.decode("latin1") for k, v in scope.get("headers", []) if k.lower() == b"origin"]
        origin = values[0] if len(values) == 1 else None
        allowed = not values
        if origin:
            try:
                parsed = urlsplit(origin)
                host = next((v.decode("latin1") for k, v in scope["headers"] if k.lower() == b"host"), "")
                expected = urlsplit("http://" + host)
                allowed = origin == _origin(origin) and parsed.scheme == "http" and parsed.port == 8096 \
                    and parsed.hostname == expected.hostname and (not self.origins or origin in self.origins)
            except ValueError:
                allowed = False
        if not allowed:
            await PublicProxy.error(send, 403)
            return
        if scope["method"] == "OPTIONS":
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            method = headers.get(b"access-control-request-method", b"").upper()
            requested = {x.strip().lower() for x in headers.get(b"access-control-request-headers", b"").split(b",") if x.strip()}
            if not origin or method not in (b"GET", b"HEAD") \
                    or not requested <= {b"authorization", b"range", b"if-none-match"}:
                await PublicProxy.error(send, 403)
                return
            await send({"type": "http.response.start", "status": 204, "headers": [
                (b"access-control-allow-origin", origin.encode("ascii")),
                (b"access-control-allow-methods", b"GET, HEAD"),
                (b"access-control-allow-headers", b"Authorization, Range, If-None-Match"),
                (b"access-control-max-age", b"600"), (b"vary", b"Origin")]})
            await send({"type": "http.response.body", "body": b""})
            return

        async def cors_send(event):
            if event["type"] == "http.response.start" and origin:
                event = dict(event, headers=[*event.get("headers", []),
                    (b"access-control-allow-origin", origin.encode("ascii")),
                    (b"access-control-expose-headers", b"X-GBox-Transport, ETag"), (b"vary", b"Origin")])
            await send(event)
        await self.inner(scope, receive, cors_send)


def applications(cfg, *, stream=None, relay=None, proxy_transport=None):
    auth = Authorization(cfg)
    stream = stream or make_stream(cfg)
    relay = relay or PersistentRelay()
    proxy = PublicProxy(cfg.backend, proxy_transport)

    @asynccontextmanager
    async def lifecycle(_app):
        await proxy.start()
        try:
            yield
        finally:
            await proxy.close()
            if hasattr(relay, "close"):
                relay.close()

    public_media = FastAPI(lifespan=lifecycle, docs_url=None, redoc_url=None, openapi_url=None)
    private_media = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    globals_ = {"listen_ok": auth.listen_ok, "media_sign": auth.media_sign,
                "require_read_auth": auth.require_read_auth}
    for app in (public_media, private_media):
        gbox_hls.install(app, globals_, stream, relay)
    # A private caller cannot forge its way onto a broader public surface; it
    # has only the exact HLS/assets endpoints. CORS names explicit studio origins.
    private = PrivateGateway(private_media, cfg.private_origins)
    return PublicGateway(public_media, proxy), private


async def serve(cfg):
    import uvicorn
    public, private = applications(cfg)
    servers = [uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port,
                                            access_log=False, log_level="warning",
                                            timeout_keep_alive=75))
               for app, port in ((public, cfg.public_port), (private, cfg.private_port))]
    # One small process, no station tasks, two listeners. The public listener's
    # lifespan owns shared clients; it closes them after both listeners stop.
    tasks = [asyncio.create_task(server.serve()) for server in servers]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for server in servers:
            server.should_exit = True
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(serve(Config.environment()))
