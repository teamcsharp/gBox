"""Disc-derived PSO catalog and shared defaults for all custom builds/PCs."""
import json
import threading
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from . import psoitems, pso_loadouts
from .pso_controls import DEFAULTS


class PreferencesIn(BaseModel):
    equip_any: bool | None = None
    always_hit: bool | None = None
    permanent_scape: bool | None = None
    legendary: bool | None = None
    enemy_drops: bool | None = None
    enemy_codes: list[str] | None = Field(default=None,max_length=20)
    enemy_max_grind: bool | None = None
    walk_through: bool | None = None


def routes(app, config, auth):
    guard = threading.RLock()
    folder = config.data_dir / "pso"
    candidates = {
        "dcv2": [config.cache / "dc/daba7a3b195dcf6b/disc.gdi", config.cache / "dc/psov2.gdi"],
        "gc": [config.cache / "gc/436e0bb84d5337d1/disc.iso", config.cache / "gc/psogc.iso"],
    }

    @app.get("/api/pso/preferences")
    def preferences(actor=Depends(auth)):
        with guard:
            f = folder / "preferences.json"
            return DEFAULTS | (json.loads(f.read_text()) if f.exists() else {})

    @app.post("/api/pso/preferences")
    def save_preferences(value: PreferencesIn, actor=Depends(auth)):
        with guard:
            folder.mkdir(parents=True, exist_ok=True)
            f = folder / "preferences.json"
            temp = f.with_suffix(".json.tmp")
            saved=DEFAULTS | (json.loads(f.read_text()) if f.exists() else {}) | value.model_dump(exclude_none=True)
            codes=saved['enemy_codes']
            if len(set(codes))!=len(codes) or any(len(c)!=6 or any(ch not in '0123456789abcdef' for ch in c) for c in codes):
                raise HTTPException(422,'Choose unique six-digit lowercase catalog item codes')
            if saved['enemy_drops'] and not codes:
                raise HTTPException(422,'Select items before enabling enemy drops')
            temp.write_text(json.dumps(saved))
            temp.replace(f)
            return saved

    def read_items(version):
        with guard:
            f = folder / f"items-{version}-v{psoitems.CATALOG_SCHEMA}.json"
            if f.exists():
                return json.loads(f.read_text())
            disc = next((p for p in candidates[version] if p.is_file()), None)
            if not disc:
                raise HTTPException(404, f"Prepare the owned PSO {version} disc to read its item database.")
            from .gcdisc import GCDisc
            from .gdrom import GDRom
            if version == "dcv2":
                catalog = psoitems.catalog_dc_v2(GDRom(disc).read)
            else:
                reader = GCDisc(disc)
                try:
                    catalog = psoitems.catalog_gc(reader.read)
                finally:
                    reader.f.close()
            folder.mkdir(parents=True, exist_ok=True)
            temp = f.with_suffix(".json.tmp")
            temp.write_text(json.dumps(catalog))
            temp.replace(f)
            return catalog

    @app.get("/api/pso/items")
    def items(version: Literal["dcv2", "gc"] = "dcv2", actor=Depends(auth)):
        return read_items(version)

    @app.get('/api/pso/loadouts')
    def loadouts(actor=Depends(auth)):
        return {'presets': pso_loadouts.presets(), 'researched_on': '2026-10-15'}

    @app.post('/api/pso/loadouts/plan')
    def loadout_plan(value: pso_loadouts.LoadoutIn, actor=Depends(auth)):
        if value.op != 'plan':
            raise HTTPException(422, 'Preview this list, then use the session-pinned drop button')
        try:
            return pso_loadouts.plan(read_items(value.version), value.version, value.preset,
                value.character_class, value.count, value.names, value.source_urls)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
