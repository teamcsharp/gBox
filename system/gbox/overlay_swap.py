"""Overlay swap: any game, right now. A collection model drawn over the operator's on-screen character in the gBox desktop
app (clients/desktop/overlay.js + overlay.html + overlay_track.py), following it frame by frame. It covers the original
(it is not an in-engine replacement: those are the per-game swap writers, characters op=use).

Control plane: the server keeps one small record per session, set by the chat tool (characters op=overlay, on any
worker), the session sidebar or the pick whip, and read by the desktop app every second:
  POST /api/overlay/{sid}  {"op": "start", "character": slug, "x": .., "y": ..}   start / switch character (x, y = the
                           target on the game picture, 0..1; none = the app asks the operator to Alt+click it)
                           {"op": "stop"} | {"op": "repick", "x", "y"} | {"op": "set", "scale", "dx", "dy", "backdrop", "facing"}
                           {"op": "status", "state", "fps", ...}   (the app reports back; doesn't change the request)
  GET  /api/overlay/{sid}  the record ({"on": false} when there is none) · GET /api/overlay: every active one
"""
import time

from pydantic import BaseModel

_STATE: dict[str, dict] = {}
SETTINGS = ("scale", "dx", "dy", "backdrop", "facing")


class OverlayIn(BaseModel):
    op: str = "start"                       # start | stop | repick | set | status
    character: str = ""                     # start: collection slug
    x: float | None = None                  # start / repick: the target's point on the game picture (0..1)
    y: float | None = None
    scale: float | None = None              # set: size multiplier (1 = the tracked box height, drawn slightly larger)
    dx: float | None = None                 # set: offset, fractions of the box (x right, y down)
    dy: float | None = None
    backdrop: bool | None = None            # set: soft backdrop behind the model (hides more of the original)
    facing: str | None = None               # set: auto | side | behind | front
    source: str = ""                        # who asked: chat | sidebar | whip
    state: str = ""                         # status (from the app): tracking | lost | waiting | picking | stopped | error
    detail: dict = {}


def apply(sid: str, inp: OverlayIn, name_of=None) -> dict:
    """Update the session's record; every change bumps rev (the app applies what changed), a new target bumps pick."""
    cur = _STATE.get(sid) or {"session_id": sid, "on": False, "rev": 0, "pick": 0, "scale": 1.0, "dx": 0.0, "dy": 0.0,
                               "backdrop": False, "facing": "auto", "status": {}}
    if inp.op == "status":
        if sid in _STATE:
            cur["status"] = {"state": inp.state, **inp.detail, "rev": inp.detail.get("rev", cur["rev"]), "t": time.time()}
        return cur
    if inp.op == "start":
        if not inp.character:
            raise ValueError("start needs a character (collection slug)")
        name = name_of(inp.character) if name_of else inp.character
        if inp.x is not None and inp.y is not None:          # a new target
            cur["point"], cur["pick"] = [inp.x, inp.y], cur["pick"] + 1
        elif not cur["on"]:                                  # no target yet: the app asks the operator to Alt+click it
            cur["point"], cur["pick"] = None, cur["pick"] + 1
        cur.update(on=True, character=inp.character, name=name, source=inp.source or cur.get("source", ""))
    elif inp.op == "repick":
        cur["point"] = [inp.x, inp.y] if inp.x is not None and inp.y is not None else None
        cur["pick"] += 1
    elif inp.op == "stop":
        cur["on"] = False
    elif inp.op != "set":
        raise ValueError(f"unknown op {inp.op} (start | stop | repick | set | status)")
    for k in SETTINGS:
        v = getattr(inp, k)
        if v is not None:
            cur[k] = v
    cur["rev"] += 1
    cur["updated"] = time.time()
    _STATE[sid] = cur
    return cur


def register(app, auth, store, char_names):
    """Routes on the control plane (server.create_app). char_names(slug) -> display name, KeyError if unknown."""
    from fastapi import Depends, HTTPException

    @app.post("/api/overlay/{sid}")
    def overlay_set(sid: str, inp: OverlayIn, actor=Depends(auth)):
        try:
            r = apply(sid, inp, char_names)
        except KeyError:
            raise HTTPException(404, f"no collection character {inp.character!r}")
        except ValueError as e:
            raise HTTPException(400, str(e))
        if inp.op != "status":
            store.audit(actor, "overlay." + inp.op, sid, inp.model_dump(exclude_none=True, exclude={"detail"}))
        return r

    @app.get("/api/overlay/{sid}")
    def overlay_get(sid: str, actor=Depends(auth)):
        return _STATE.get(sid) or {"session_id": sid, "on": False, "rev": 0, "pick": 0}

    @app.get("/api/overlay")
    def overlay_all(actor=Depends(auth)):
        return [v for v in _STATE.values() if v.get("on")]


def start(ctx, api, meta: dict, sid: str, x=None, y=None) -> dict:
    """characters op=overlay (any worker): ask the operator's desktop app to draw `meta` over their character in session
    `sid`, then wait briefly for the app to pick it up."""
    if not sid:
        raise ValueError("overlay needs the running session (session_id)")
    sess = next((s for s in api(ctx, "GET", "/api/sessions") if s.get("session_id") == sid), None)
    if not sess or sess.get("state") != "running":
        raise ValueError(f"session {sid} isn't running")
    body = {"op": "start", "character": meta["slug"], "source": "chat"}
    if x is not None and y is not None:
        body |= {"x": float(x), "y": float(y)}
    rec = api(ctx, "POST", f"/api/overlay/{sid}", json=body)
    seen = {}
    for _ in range(12):                                      # the app polls every second
        time.sleep(0.5)
        seen = api(ctx, "GET", f"/api/overlay/{sid}").get("status") or {}
        if seen.get("rev", 0) >= rec["rev"]:
            break
    local = (sess.get("detail") or {}).get("local_window")
    how = ("the operator Alt+clicks their character in the game to mark it" if body.get("x") is None
           else "tracking the character at the given point")
    msg = (f"{meta['name']} is drawn over the player as an overlay in gBox's desktop app ({how}). It covers the original "
           f"on screen; the game itself is unchanged (not an in-engine swap).")
    if not local:
        msg += " Note: this session isn't a docked PC game window; the overlay needs the game running in the desktop app."
    if seen.get("rev", 0) < rec["rev"]:
        msg += " The desktop app hasn't picked it up yet (is it open on the game's PC?)."
    return {"status": "overlay", "character": meta["name"], "slug": meta["slug"], "session_id": sid,
            "app": (seen.get("state") if seen.get("rev", 0) >= rec["rev"] else "") or "not seen yet", "message": msg}
