"""Disc-derived PSO catalog and shared defaults for all custom builds/PCs."""
import json
import threading
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from . import psoitems
from .pso_controls import DEFAULTS


class PreferencesIn(BaseModel):
    equip_any: bool


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
            temp.write_text(json.dumps(value.model_dump()))
            temp.replace(f)
            return value.model_dump()

    @app.get("/api/pso/items")
    def items(version: Literal["dcv2", "gc"] = "dcv2", actor=Depends(auth)):
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
