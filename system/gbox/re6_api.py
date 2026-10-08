"""Resident Evil 6 endpoints on the control plane: item catalogue + icons (cut from the operator's own disc) and the
saved Mercenaries loadout. Registered from server.py with re6_api.routes(app, store, config, auth)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

GAME_ID = "0871eee3b68cdea3"


class SettingsIn(BaseModel):
    game_id: str = GAME_ID
    auto_qte: bool | None = None          # every QTE prompt succeeds (default on)
    infinite_health: bool | None = None
    infinite_ammo: bool | None = None
    everything_unlocked: bool | None = None   # boot profile "RE6: Everything unlocked": the save is unlocked before boot
    boot_to_title: bool | None = None         # skip the logo movie + press through to the title screen


DEFAULTS = {"auto_qte": True, "infinite_health": False, "infinite_ammo": False, "everything_unlocked": True,
            "boot_to_title": True}


class LoadoutIn(BaseModel):
    game_id: str = GAME_ID
    items: list[dict] = []          # [{id, amount?}] in order (first = equipped)
    auto: bool = True               # apply whenever a Mercenaries match starts
    replace: bool = True            # remove the character's default guns first


def _iso(store, config, game_id: str) -> Path:
    g = store.catalog_get(game_id) or {}
    if not g.get("library") or not g.get("rel_path"):
        raise HTTPException(404, "Resident Evil 6 (Xbox 360) is not in the catalogue")
    root = config.library(g["library"]).root()
    p = Path(root) / g["rel_path"] if root else None
    if not p or not p.is_file():
        raise HTTPException(404, f"the RE6 disc image isn't reachable from the control plane ({p})")
    return p


def routes(app, store, config, auth):
    d = Path(config.data_dir) / "re6"

    @app.get("/api/re6/items")
    def re6_items(game_id: str = GAME_ID, rebuild: bool = False, include_special: bool = True, actor=Depends(auth)):
        """Every RE6 item: id, name, kind, icon url (thumbnail cut from the disc's item atlas), story owner."""
        f = d / "items.json"
        if rebuild or not f.exists():
            from . import re6_items
            re6_items.build(_iso(store, config, game_id), d)
        items = json.loads(f.read_text())
        return [i for i in items if include_special or not i.get("special")]

    @app.get("/api/re6/icon/{item_id}")
    def re6_icon(item_id: int, actor=Depends(auth)):
        f = d / "icons" / f"{int(item_id)}.png"
        if not f.exists():
            raise HTTPException(404, "no icon for this item")
        return FileResponse(f, media_type="image/png", headers={"cache-control": "max-age=604800"})

    @app.get("/api/re6/loadout")
    def re6_loadout_get(game_id: str = GAME_ID, actor=Depends(auth)):
        return store.get("re6_loadout", game_id) or {"game_id": game_id, "items": [], "auto": False}

    @app.get("/api/re6/settings")
    def re6_settings_get(game_id: str = GAME_ID, actor=Depends(auth)):
        """RE6 switches the worker applies whenever RE6 boots through gBox (Auto QTE is on unless switched off)."""
        return DEFAULTS | (store.get("re6_settings", game_id) or {}) | {"game_id": game_id}

    @app.post("/api/re6/settings")
    def re6_settings_put(inp: SettingsIn, actor=Depends(auth)):
        cur = DEFAULTS | (store.get("re6_settings", inp.game_id) or {})
        cur |= {k: v for k, v in inp.model_dump().items() if k in DEFAULTS and v is not None}
        rec = cur | {"game_id": inp.game_id, "by": actor, "ts": time.time()}
        store.put("re6_settings", inp.game_id, rec)
        store.audit(actor, "re6.settings", inp.game_id, {k: rec[k] for k in DEFAULTS})
        return rec

    @app.post("/api/re6/loadout")
    def re6_loadout_put(inp: LoadoutIn, actor=Depends(auth)):
        if len(inp.items) > 12:
            raise HTTPException(422, "at most 12 items (the Mercenaries case has 12 slots: guns + grenades + recovery)")
        rec = inp.model_dump() | {"by": actor, "ts": time.time()}
        store.put("re6_loadout", inp.game_id, rec)
        store.audit(actor, "re6.loadout", inp.game_id, {"items": [i.get("id") for i in inp.items], "auto": inp.auto})
        return rec
