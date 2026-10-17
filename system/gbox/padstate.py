"""Pad glyph state: the buttons gBox itself (agent / autoplay / UI) currently holds on each live session.

The play view draws the console's controller and lights what is pressed. The player's own pad is read in the browser
(Gamepad API); everything gBox sends goes through POST /api/sessions/{sid}/input or the session_op `send_input` job and
is recorded here, so the overlay can show it too. In memory only: it's a live indicator, not a log.

    record(sid, events, source)        # server side (put_input): source = the request's actor or a plain source name
    report(ctx, sid, events, source)   # worker side (session_op send_input): posts to the control plane
    register(app, auth)                # GET/POST /api/sessions/{sid}/pad, GET /padglyph.js
"""
import threading
import time
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "clients" / "web"
STALE = 30.0            # a key held longer than this without news is dropped (lost key-up)
MIN_SHOW = 0.15         # taps shorter than this stay lit this long, so a 10 Hz poll still sees them
PAD_NAMES = {"a", "b", "x", "y", "l", "r", "l2", "r2", "l3", "r3", "start", "select", "up", "down", "left", "right",
             "lup", "ldown", "lleft", "lright", "rup", "rdown", "rleft", "rright",
             "z", "cup", "cdown", "cleft", "cright", "dup", "ddown", "dleft", "dright"}     # + Dolphin's extra pad keys
SOURCES = {"agent", "autoplay", "ui", "player"}

_lock = threading.Lock()
_pads: dict[str, dict] = {}      # sid -> {"held": {key: [source, t_down, show_until|None]}, "source", "ts"}
_meta: dict[str, dict] = {}      # sid -> {"platform", "adapter"} (from the session + catalog, cached)
_rev: dict[str, str] | None = None


def _keysyms() -> dict[str, str]:
    """X keysym -> pad button, the reverse of the RetroArch keyboard binding (keyboard players send keysyms)."""
    global _rev
    if _rev is None:
        try:
            from .adapters import PAD_KEYS
            _rev = {v: k for k, v in PAD_KEYS[1].items()}
        except Exception:
            _rev = {"Up": "up", "Down": "down", "Left": "left", "Right": "right", "Return": "start", "Shift_R": "select"}
        _rev.setdefault("BackSpace", "select")
    return _rev


def _norm(key) -> str | None:
    if not isinstance(key, str) or not key:
        return None
    if key.lower() in PAD_NAMES:
        return key.lower()
    return _keysyms().get(key)


def _source(actor: str, ev: dict) -> str:
    a = (actor or "").lower()
    if a in SOURCES:
        return a
    if "autoplay" in a:
        return "autoplay"
    if a == "operator":                       # the app: physical pads carry a player number, on-screen buttons don't
        return "player" if "player" in ev else "ui"
    return "agent"                            # gbox-agent, bridges, workers, scripts


def record(sid: str, events, source: str = "agent") -> None:
    """Apply pad events ({key, down, player?}) to the session's held set. Player 1 only; rpc entries are ignored."""
    now = time.time()
    with _lock:
        p = _pads.get(sid)
        if p is None:
            if len(_pads) > 512:                                      # forget the oldest sessions
                for old in sorted(_pads, key=lambda s: _pads[s]["ts"])[:128]:
                    _pads.pop(old, None)
            p = _pads[sid] = {"held": {}, "source": None, "ts": now}
        for ev in events or []:
            if not isinstance(ev, dict) or "rpc" in ev:
                continue
            try:
                if int(ev.get("player") or 1) != 1:
                    continue
            except (TypeError, ValueError):
                continue
            k = _norm(ev.get("key"))
            if not k:
                continue
            src = _source(source, ev)
            if ev.get("down", True):
                p["held"][k] = [src, now, None]
            elif k in p["held"]:
                t0 = p["held"][k][1]
                if now - t0 < MIN_SHOW:
                    p["held"][k][2] = t0 + MIN_SHOW
                else:
                    del p["held"][k]
            p["source"], p["ts"] = src, now


def record_stick(sid: str, stick: dict | None, rstick: dict | None = None) -> None:
    with _lock:
        p = _pads.setdefault(sid, {"held": {}, "source": None, "ts": time.time()})
        p["stick"], p["rstick"], p["stick_ts"] = stick, rstick, time.time()


def snapshot(sid: str) -> dict:
    now = time.time()
    with _lock:
        p = _pads.get(sid)
        if not p:
            return {"held": [], "sources": {}, "source": None, "ts": 0}
        for k, (src, t0, until) in list(p["held"].items()):
            if (until and until < now) or now - t0 > STALE:
                del p["held"][k]
        fresh = now - p.get("stick_ts", 0) < 1.0
        return {"held": sorted(p["held"]), "sources": {k: v[0] for k, v in p["held"].items()},
                "source": p["source"], "ts": p["ts"], "stick": p.get("stick") if fresh else None,
                "rstick": p.get("rstick") if fresh else None}


def report(ctx, sid: str, events, source: str = "agent") -> None:
    """Worker side: tell the control plane what gBox pressed (fire-and-forget; never slows the input down)."""
    server, headers = getattr(ctx, "server", None), getattr(ctx, "headers", None) or {}
    if not server:
        record(sid, events, source)
        return

    def post():
        try:
            import httpx
            httpx.post(f"{server}/api/sessions/{sid}/pad", json={"events": events or [], "source": source},
                       headers=headers, timeout=3)
        except Exception:
            pass
    threading.Thread(target=post, daemon=True).start()


# XInput (Xbox-layout pads) -> RetroPad names, the same positional mapping RetroArch's XInput autoconfig uses
_XI = {0x0001: "up", 0x0002: "down", 0x0004: "left", 0x0008: "right", 0x0010: "start", 0x0020: "select", 0x0040: "l3",
       0x0080: "r3", 0x0100: "l", 0x0200: "r", 0x1000: "b", 0x2000: "a", 0x4000: "y", 0x8000: "x"}


PLAYER_TOUCH: dict[str, float] = {}     # sid -> last time the operator pressed/moved their own pad (worker process)


def player_active(sid: str, within: float = 0.6) -> bool:
    return time.time() - PLAYER_TOUCH.get(sid, 0) < within


def watch_xinput(server: str, headers: dict, sid: str, alive) -> None:
    """Windows worker: stream the operator's own controller (pad 0) to the controller glyph while the session lives.
    The game reads the pad itself; this only mirrors it (XInput works whatever window has focus)."""
    import httpx
    from . import xinput
    get_state = xinput.load()      # the shared binding: a private ST class here died on an argtypes clash (#1638)
    if get_state is None:
        return
    st, held, last_pkt, last_stick = xinput.XInputState(), set(), -1, (0.0, 0.0, 0.0, 0.0)
    ax = lambda v: 0.0 if abs(v) < 7849 else round(max(-1.0, v / 32767), 2)      # XInput's recommended deadzone
    with httpx.Client(base_url=server, headers=headers, timeout=3) as c:
        while alive():
            time.sleep(1 / 30)
            if xinput.read(get_state, 0, st) is None or st.packet == last_pkt:
                continue                                    # empty slot or a failed call: keep mirroring
            last_pkt, g = st.packet, st.gamepad
            now = {name for bit, name in _XI.items() if g.buttons & bit} | ({"l2"} if g.lt > 30 else set()) | ({"r2"} if g.rt > 30 else set())
            stick = (ax(g.lx), -ax(g.ly), ax(g.rx), -ax(g.ry))
            ev = [{"key": k, "down": True} for k in now - held] + [{"key": k, "down": False} for k in held - now]
            if not ev and stick == last_stick:
                continue
            held, last_stick = now, stick
            if now or any(abs(v) > 0.3 for v in stick):
                PLAYER_TOUCH[sid] = time.time()                  # the operator is playing: autoplay hands control back
            try:
                c.post(f"/api/sessions/{sid}/pad", json={"events": ev, "source": "player",
                                                        "stick": {"x": stick[0], "y": stick[1]}, "rstick": {"x": stick[2], "y": stick[3]}})
            except Exception:
                time.sleep(1)


def _session_meta(app, sid: str) -> dict:
    m = _meta.get(sid)
    if m and m.get("platform"):
        return m
    m = {"platform": None, "adapter": None}
    store = getattr(app.state, "store", None)
    try:
        s = store.get("session", sid) or {}
        m["adapter"] = s.get("adapter")
        if s.get("game_id"):
            m["platform"] = (store.catalog_get(s["game_id"]) or {}).get("platform")
    except Exception:
        pass
    _meta[sid] = m
    return m


def register(app, auth_dependency) -> None:
    from fastapi import Depends, HTTPException
    from fastapi.responses import FileResponse
    from pydantic import BaseModel

    class PadEvents(BaseModel):
        events: list[dict] = []
        source: str = "agent"
        stick: dict | None = None
        rstick: dict | None = None

    @app.get("/api/sessions/{sid}/pad")
    def pad_state(sid: str, actor=Depends(auth_dependency)):
        """What gBox holds on this session's pad right now (player 1), plus the platform for the controller glyph."""
        return snapshot(sid) | _session_meta(app, sid)

    @app.post("/api/sessions/{sid}/pad")
    def pad_report(sid: str, p: PadEvents, actor=Depends(auth_dependency)):
        """Workers report inputs they applied directly (session_op send_input)."""
        record(sid, p.events, p.source if p.source in SOURCES else actor)
        if p.stick is not None or p.rstick is not None:
            record_stick(sid, p.stick, p.rstick)
        if p.source in ('player','ui') and hasattr(app.state,'capture_gameplay'):
            app.state.capture_gameplay(sid,'pad',{'events':p.events[:100],'stick':p.stick,'rstick':p.rstick,
                                               'timing':'server receipt time; not core-frame TAS input'})
        return {"ok": True}

    @app.get("/padglyph.js")
    def padglyph_js():
        return FileResponse(WEB / "padglyph.js", media_type="text/javascript", headers={"cache-control": "no-cache"})

    @app.get("/padglyph-test.html")
    def padglyph_test():
        f = WEB / "padglyph-test.html"
        if not f.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(f, headers={"cache-control": "no-cache"})
