"""Resident Evil inventory helper on the control plane (any RE gBox can reach live; see gbox/re_inventory.py).

  GET  /api/re/inventory?session_id=   the selected character's slots + HP, read through the session's read-only rpc
                                       channel (no job, cheap enough for the on-screen helper's 1 s refresh)
  POST /api/re/inventory               {session_id, op: give|remove|set|loadout|health, item, amount, slot, character,
                                       items}: runs the `re_inventory` tool on the session's worker; returns the message
                                       and the inventory after the change
  GET  /api/re/catalog?session_id=|game_id=   the game's items + the cross-game list ("any RE") + which ops/loadouts exist
Registered from server.py with re_inventory_api.routes(app, store, config, auth, peek, submit, JobRequest).
"""
from __future__ import annotations

import time

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from . import re_inventory as R
from .registry import Unsupported


class InvOp(BaseModel):
    session_id: str
    op: str = "give"          # give | remove | set | loadout | health
    item: str = ""
    amount: int = 0
    slot: int = -1
    character: str = ""
    items: list = []


def routes(app, store, config, auth, peek, submit, JobRequest):
    class Peek:
        def __init__(self, sid, actor):
            self.sid, self.actor = sid, actor

        def read_memory(self, a: int, n: int) -> bytes:
            return bytes.fromhex(peek(self.sid, int(a), int(n), self.actor))

    def session(sid: str) -> dict:
        s = store.get("session", sid)
        if not s:
            raise HTTPException(404, "no such session")
        return s

    @app.get("/api/re/catalog")
    def re_catalog(session_id: str = "", game_id: str = "", actor=Depends(auth)):
        gid = game_id or session(session_id)["game_id"]
        sup = R.support(gid)
        if not sup["backend"] and not sup["has_catalog"]:
            raise HTTPException(404, "not a Resident Evil game gBox has an inventory catalog for")
        return sup | {"items": R.catalog(gid).get("items", []), "cross": R.cross(gid)}

    @app.get("/api/re/inventory")
    def re_inventory_get(session_id: str, actor=Depends(auth)):
        s = session(session_id)
        gid = s["game_id"]
        sup = R.support(gid)
        if not sup["backend"]:
            raise HTTPException(404, "not a Resident Evil game with a live inventory in gBox")
        base = {"session_id": session_id, "title": s.get("title"), "ts": time.time()}
        if s.get("state") != "running":
            return base | sup | {"slots": [], "error": "the game isn't running"}
        if not sup["live"]:
            return base | sup | {"slots": [], "error": sup["note"]}
        try:
            return base | R.read(R.Retry(Peek(session_id, actor), 3), gid)
        except Unsupported as e:
            return base | sup | {"slots": [], "error": str(e)}
        except HTTPException as e:
            return base | sup | {"slots": [], "error": f"the session didn't answer ({e.detail})"}
        except Exception as e:                                       # noqa: BLE001 - a menu / loading screen mid-read
            return base | sup | {"slots": [], "error": f"{type(e).__name__}: {e}"}

    @app.post("/api/re/inventory")
    def re_inventory_post(req: InvOp, actor=Depends(auth)):
        s = session(req.session_id)
        sup = R.support(s["game_id"])
        if not sup["live"]:
            raise HTTPException(422, sup["note"] or "no live inventory for this game")
        j = submit(JobRequest(tool="re_inventory", input=req.model_dump()), actor)
        t0 = time.time()
        while (jj := store.get("job", j.id))["state"] in ("queued", "running") and time.time() - t0 < 90:
            time.sleep(0.15)
        if jj["state"] != "succeeded":
            raise HTTPException(422, jj.get("error") or f"the change didn't finish ({jj['state']})")
        return (jj.get("output") or {}).get("result") or {}
