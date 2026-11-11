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


RELAY_STICK = 0.3          # the same push that counts as a touch: below it a stick is drift, not input
RELAY_MIN_EVENT_S = 0.02    # do not relay more often than the pad itself updates


RELAY: dict[str, bool] = {}       # sid -> relay the operator's physical pad into the session's input queue
RELAY_SEEN: dict[str, tuple] = {}   # sid -> the last relayed state, so a held button is not re-sent forever


PLAYER_TOUCH: dict[str, float] = {}     # sid -> last time the operator pressed/moved their own pad (worker process)
CHORD: dict[str, object] = {}           # sid -> callable run when the operator holds Select/View and presses A (autoplay)
CHORD_KEYS = frozenset({"select", "b"})  # physical Xbox A is RetroPad 'b' here (positional labels, see _XI)
# Per-session chord. PSO binds Select + L1 + R1 (RetroPad 'l' + 'r') to its equipment randomizer; every other
# title keeps the default Select + A.
CHORD_BY_SESSION: dict[str, frozenset] = {}


def chord_keys(sid: str) -> frozenset:
    """The keys that make up this session's operator chord (the default Select + A when none is set)."""
    return CHORD_BY_SESSION.get(sid) or CHORD_KEYS


def set_chord(sid: str, keys) -> frozenset:
    """Bind a session's chord and return the set in force. Every chord holds Select, so it cannot fire while
    playing without the operator deliberately holding it."""
    keys = frozenset(str(k).lower() for k in keys)
    if "select" not in keys or len(keys) < 2:
        raise ValueError("an operator chord is Select plus at least one other key")
    CHORD_BY_SESSION[sid] = keys
    return keys
ANCHOR: dict[str, object] = {}          # sid -> callable(at): save the screen the operator reacted to (gbox.imitate)


def player_active(sid: str, within: float = 0.6) -> bool:
    return time.time() - PLAYER_TOUCH.get(sid, 0) < within


def touched_after(sid: str, t: float) -> bool:
    """The operator pressed or moved their own pad after time t (the autoplay chord itself doesn't count)."""
    return PLAYER_TOUCH.get(sid, 0) > t


def chord_step(sid: str, before: set, now: set, moved: bool, chording: bool) -> tuple[bool, bool]:
    """One pad report: (fire the chord now, still chording). While the chord's own keys are held (and nothing else),
    the report is not a touch, so a chord's own action does not hand control straight back.

    The chord fires on the *press* that completes it, so holding Select and tapping the action keys repeats cleanly and
    holding the whole chord does not repeat. With a three-key chord (PSO's Select + L1 + R1) any one of the action keys
    completing the set fires it."""
    keys = chord_keys(sid)
    action = keys - {"select"}
    fire = bool(keys <= now) and bool(action - before)
    chording = (chording or fire) and bool(now) and now <= keys and not moved
    if not chording and (now or moved):
        PLAYER_TOUCH[sid] = time.time()                  # the operator is playing (a playing bot yields: pad_lease)
    return fire, chording


STICK_KEY_AT = 0.3                                       # the same push that counts as a touch (watch_xinput's moved)


def stick_keys(stick) -> set:
    """(lx, ly, rx, ry) as watch_xinput reads them (y down) -> the pushed directions as RetroPad analog names."""
    out = set()
    for side, x, y in (("l", stick[0], stick[1]), ("r", stick[2], stick[3])):
        out |= ({side + "left"} if x < -STICK_KEY_AT else set()) | ({side + "right"} if x > STICK_KEY_AT else set())
        out |= ({side + "up"} if y < -STICK_KEY_AT else set()) | ({side + "down"} if y > STICK_KEY_AT else set())
    return out


def pad_lease(sid: str, keys: set) -> None:
    """This PC's controller as it is now, for the session's pad takeover (gbox/pad_takeover.py): a press makes a playing
    bot let go for a moment, a key still held keeps it off, and it takes the pad back after the idle time."""
    try:
        from . import pad_takeover
        pad_takeover.local(sid, keys)
    except Exception:                                    # noqa: BLE001 - the controller mirror never stops over it
        pass


_LAST_SLOT: int | None = None


def reset_slot_memory() -> None:
    """Forget the remembered pad slot (tests, and a session restart where the pad may have moved)."""
    global _LAST_SLOT
    _LAST_SLOT = None


def operator_slot(get_state, st, *, samples: int = 12, gap: float = 0.05, read=None) -> int:
    """The XInput slot the operator's own pad is on.

    Slot 0 is not safe to assume. A leftover virtual pad from an earlier session holds slot 0 on this PC and
    sits at all zeros forever, so the operator's real controller enumerates on slot 1 and a watcher bound to
    slot 0 sees nothing at all (proven on the i9-NUC 2026-11-10: the operator's pad reported live packets and
    analog values on slot 1 while slot 0 stayed exactly zero).

    **The slot is remembered once found.** Detection needs movement, and the operator is idle most of the time, so a
    detection that runs again on a quiet pad falls back to slot 0 -- the dead virtual pad -- and the mirror then watches
    the wrong controller until the operator happens to move again. The worker log showed exactly that ("mirroring the
    operator's pad on XInput slot 0" on a restart while the pad was still). So: if a slot was found before and it still
    answers, it is used without waiting for movement.

    ``read`` is injected so this can be tested without a controller, and so the caller does not depend on how
    `gbox.xinput` happens to be bound -- the earlier version referenced a module name that only existed as a local
    inside `watch_xinput`, which raised `NameError` and killed the mirror thread on every start.
    """
    global _LAST_SLOT
    if read is None:
        from . import xinput as _xinput
        read = _xinput.read
    if _LAST_SLOT is not None and read(get_state, _LAST_SLOT, st) is not None:
        return _LAST_SLOT
    for _ in range(max(1, samples)):
        for s in range(4):
            if read(get_state, s, st) is None:
                continue
            g = st.gamepad
            if g.buttons or abs(g.lx) > 7849 or abs(g.ly) > 7849 or abs(g.rx) > 7849 or abs(g.ry) > 7849:
                _LAST_SLOT = s
                return s
        time.sleep(gap)
    return _LAST_SLOT if _LAST_SLOT is not None else 0


def watch_xinput(server: str, headers: dict, sid: str, alive) -> None:
    """Windows worker: stream the operator's own controller (pad 0) to the controller glyph while the session lives.
    The game reads the pad itself; this only mirrors it (XInput works whatever window has focus)."""
    import httpx
    from . import xinput
    get_state = xinput.load()      # the shared binding: a private ST class here died on an argtypes clash (#1638)
    if get_state is None:
        return
    st, held, last_pkt, last_stick, chording = xinput.XInputState(), set(), -1, (0.0, 0.0, 0.0, 0.0), False
    slot = operator_slot(get_state, st)          # the operator's pad: not always XInput slot 0
    print(f"padstate: mirroring the operator's pad on XInput slot {slot}", flush=True)
    last_active = 0.0
    ax = lambda v: 0.0 if abs(v) < 7849 else round(max(-1.0, v / 32767), 2)      # XInput's recommended deadzone
    with httpx.Client(base_url=server, headers=headers, timeout=3) as c:
        while alive():
            time.sleep(1 / 30)
            if xinput.read(get_state, slot, st) is None:
                continue                                    # empty slot or a failed call: keep mirroring
            if st.packet == last_pkt:                       # unchanged: a button or stick still held is still input
                if (held or any(abs(v) > 0.3 for v in last_stick)) and not chording:
                    pad_lease(sid, held | stick_keys(last_stick))
                continue
            last_pkt, g = st.packet, st.gamepad
            now = {name for bit, name in _XI.items() if g.buttons & bit} | ({"l2"} if g.lt > 30 else set()) | ({"r2"} if g.rt > 30 else set())
            stick = (ax(g.lx), -ax(g.ly), ax(g.rx), -ax(g.ry))
            stick_changed = stick != last_stick
            ev = [{"key": k, "down": True} for k in now - held] + [{"key": k, "down": False} for k in held - now]
            if not ev and stick == last_stick:
                continue
            before, held, last_stick = held, now, stick
            moved = any(abs(v) > 0.3 for v in stick)
            fire, chording = chord_step(sid, before, now, moved, chording)
            if not chording:                                 # the autoplay chord itself is never a takeover
                pad_lease(sid, now | stick_keys(stick))
            if fire and CHORD.get(sid):
                threading.Thread(target=CHORD[sid], daemon=True).start()
            if now or moved:                                 # a press after a pause: keep the screen it answered
                t = time.time()
                if t - last_active >= 0.7 and not chording and ANCHOR.get(sid):
                    threading.Thread(target=ANCHOR[sid], args=(t,), daemon=True).start()
                last_active = t
            relayable = [e for e in ev if not e["key"].endswith(("left", "right", "up", "down"))] \
                or (any(abs(v) > RELAY_STICK for v in stick) and ev)
            if RELAY.get(sid) and relayable and stick_changed:
                # Dolphin is reading gBox's virtual pad, so the operator's own controller reaches the game only if we
                # put their presses on the session's input queue. Buttons are relayed always; STICKS only past a real
                # deflection, because a resting pad's drift (this one sits at lx -160, ly 1387) changes the packet
                # continuously and a flood of "operator" input starves the bot's own presses (pad_takeover yields the
                # pad to the operator while they are "playing").
                try:
                    events = [e for e in ev if abs(stick[0]) > RELAY_STICK or abs(stick[1]) > RELAY_STICK
                              or abs(stick[2]) > RELAY_STICK or abs(stick[3]) > RELAY_STICK
                              or not e["key"].endswith(("left", "right", "up", "down"))]
                    c.post(f"/api/sessions/{sid}/input", json={"events": events}, timeout=1)
                except Exception:                        # noqa: BLE001 - a relay hiccup must not stop the mirror
                    pass
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
