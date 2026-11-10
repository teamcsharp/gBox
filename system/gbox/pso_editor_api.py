"""P6b's page: the placement editor over `pso_editor`, with the executable's own class labels (A3).

The backend already lists, edits, previews and builds (`gbox.pso_editor`, `gbox.pso_map_write`). This module is only
the web layer the page needs:

* `GET /pso/editor` - the page itself (`clients/web/pso-editor.html`);
* `GET /api/pso/editor/sets` - every editable set;
* `GET /api/pso/editor/set/{name}` - one set's placements, each labelled by `pso_class_registry` with a family and,
  where the room-local -> world offset has been measured, the world position too;
* `GET /api/pso/editor/set/{name}/svg` - a **server-rendered** top-down preview (no browser needed to test it);
* `POST /api/pso/editor/preview` - normalise + preview an edit set without building an image.

Building still runs on the command line (`python -m gbox.pso_editor build ...`): an image build needs the rom and a
config the page does not own.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from . import pso_editor, pso_gc
from . import pso_class_registry as REG

WEB = Path(__file__).resolve().parent.parent / "clients" / "web" / "pso-editor.html"

#: family -> colour (the editor groups markers by the class family A3 gives them)
FAMILY_COLOURS = {
    "door": "#e8b13a", "warp": "#3ac7e8", "switch": "#7ce83a", "trap": "#e85b3a", "sensor": "#c03ae8",
    "sign": "#b9b9b9", "prop": "#8a8a8a", "decor": "#e83a9c", "effects": "#3a6ce8", "collision": "#4a4a4a",
    "object": "#d8d8d8", "unknown": "#000000",
}


class PreviewIn(BaseModel):
    ops: list[dict]


class BuildIn(BaseModel):
    name: str
    ops: list[dict]


GAME_ID = "436e0bb84d5337d1"   # Phantasy Star Online Episode I & II Plus (USA)
MOD_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,40}")


def rom_for(config) -> Path:
    """The PSO GameCube image the editor works on: `PSO_GC_ISO`, the cache's own copy, or a built mod image."""
    cache = Path(config.cache)
    candidates = []
    env = os.environ.get("PSO_GC_ISO")
    if env:
        candidates.append(Path(env))
    candidates += [cache / "gc/436e0bb84d5337d1/disc.iso", cache / "gc/psogc.iso",
                   cache / "436e0bb84d5337d1/disc.iso"]
    mods = cache / "mods/436e0bb84d5337d1"
    if mods.is_dir():
        candidates += sorted(mods.glob("*/*.iso"))
    for path in candidates:
        if path.is_file():
            return path
    raise HTTPException(503, "no PSO GameCube disc image found (set PSO_GC_ISO or the cache's gc image)")


def svg_of(data: dict, *, width: int = 720, families: set[str] | None = None, world: bool = False) -> str:
    """A top-down SVG of a set's placements: one dot per record, coloured by class family, doors and warps named."""
    rows = data["records"]
    if families:
        rows = [r for r in rows if r.get("family") in families]
    points = []
    for row in rows:
        if world and row.get("world"):
            x, z = row["world"]
        else:
            x, z = row["x"], row["z"]
        points.append((x, z, row))
    if not points:
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="60"><text x="8" y="34" '
                'font-family="monospace" fill="#888">no placements</text></svg>' % width)
    xs, zs = [p[0] for p in points], [p[1] for p in points]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    span = max(x1 - x0, z1 - z0, 1.0)
    pad = 24
    scale = (width - 2 * pad) / span
    height = int(span * scale) + 2 * pad

    def at(x, z):
        return (pad + (x - x0) * scale, height - pad - (z - z0) * scale)     # z up

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'data-set="{data["set"]}" data-count="{len(points)}">',
             f'<rect width="{width}" height="{height}" fill="#101418"/>']
    for x, z, row in points:
        cx, cy = at(x, z)
        colour = FAMILY_COLOURS.get(row.get("family"), "#d8d8d8")
        title = f'{row["index"]}: {row["class"]} ({row["kind"]:#x}) at ({x:.1f}, {z:.1f})'
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" fill="{colour}"><title>{_esc(title)}</title></circle>')
        if row.get("family") in ("door", "warp"):
            parts.append(f'<text x="{cx + 6:.1f}" y="{cy - 6:.1f}" font-family="monospace" font-size="9" '
                         f'fill="{colour}">{_esc(row["class"])}</text>')
    legend = " ".join(f'{fam}:{sum(1 for r in rows if r.get("family") == fam)}' for fam in sorted({r.get("family") for r in rows}))
    parts.append(f'<text x="6" y="{height - 6}" font-family="monospace" font-size="9" fill="#777">'
                 f'{_esc(data["set"])} - {len(rows)} shown, {data["count"]} total - {_esc(legend)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def routes(app, config, auth):
    guard = threading.RLock()
    opened = {}

    def disc():
        with guard:
            if "disc" not in opened:
                opened["rom"] = rom_for(config)
                opened["disc"] = pso_gc.open_disc(opened["rom"])
            return opened["disc"]

    @app.get("/pso/editor")
    def page(actor=Depends(auth)):
        return FileResponse(WEB, media_type="text/html", headers={"cache-control": "no-cache"})

    @app.get("/api/pso/editor/sets")
    def sets(actor=Depends(auth)):
        rows = pso_editor.sets(disc())
        return {"count": len(rows), "sets": rows}

    @app.get("/api/pso/editor/set/{name}")
    def set_detail(name: str, world: bool = True, actor=Depends(auth)):
        try:
            data = pso_editor.placements(disc(), name)
        except (KeyError, ValueError) as exc:
            raise HTTPException(404, f"no such set: {exc}") from None
        families = {}
        for row in data["records"]:
            row["world"] = pso_editor.world_position(row, name) if world else None
            families[row["family"]] = families.get(row["family"], 0) + 1
        data["families"] = families
        return data

    @app.get("/api/pso/editor/set/{name}/svg")
    def set_svg(name: str, width: int = 720, families: str | None = None, world: bool = True, actor=Depends(auth)):
        try:
            data = pso_editor.placements(disc(), name)
        except (KeyError, ValueError) as exc:
            raise HTTPException(404, f"no such set: {exc}") from None
        for row in data["records"]:
            row["world"] = pso_editor.world_position(row, name)
        wanted = {part.strip() for part in families.split(",") if part.strip()} if families else None
        return HTMLResponse(svg_of(data, width=max(240, min(int(width), 2048)), families=wanted, world=world))

    @app.post("/api/pso/editor/build")
    def build(body: BuildIn, actor=Depends(auth)):
        """Apply the edits and build a mod image (a real disc build: minutes, run off the event loop)."""
        name = body.name.strip().lower()
        if not MOD_NAME.fullmatch(name):
            raise HTTPException(400, "mod name must be lowercase letters, digits, '.', '_' or '-', up to 41 chars")
        try:
            ops = pso_editor.edits(*body.ops)
        except pso_editor.EditError as exc:
            raise HTTPException(400, str(exc)) from None
        disc()                                          # resolve (and cache) the rom path first
        try:
            out = pso_editor.build(config, GAME_ID, opened["rom"], name, ops)
        except Exception as exc:                         # noqa: BLE001 - a failed build is a 400 with the reason
            raise HTTPException(400, f"build failed: {exc}") from None
        image = out.get("image")
        return {"ok": True, "name": name, "image": None if image is None else str(image),
                "verification": out.get("verification"), "edits": out.get("edits")}

    @app.get("/api/pso/editor/swapfit")
    def swapfit(host: str = "A", donor: str = "C", actor=Depends(auth)):
        """Will a raw body copy from `donor` over `host` work? The P7b gate, from the disc's own bodies.

        Textures and vertex counts come from each class's PL<x>BDY00.NJ on the running disc, and the verdict is
        `pso_swapfit.compare`'s: buckets must match (the crash case), matching buckets with a different vertex count
        is the deformed case, everything equal is safe.
        """
        from . import ninja, pso_gc, pso_player, pso_swapfit
        host, donor = host.strip().upper(), donor.strip().upper()
        for letter in (host, donor):
            if letter not in pso_player.CLASS_ROLES:
                raise HTTPException(400, f"unknown class letter {letter!r} (A..I)")
        signatures = {}
        for letter in (host, donor):
            body = pso_player.pso_gc_paths.read_part(disc(), pso_player.pso_gc_paths.gc_path(
                f"PSO/PL{letter}BDY00.NJ") if True else f"PSO/PL{letter}BDY00.NJ")
            signatures[letter] = pso_swapfit.signature_nj(ninja.NJ(body, be=True))
        verdict = pso_swapfit.compare(signatures[host], signatures[donor])
        return {"host": {"class": host, **signatures[host]}, "donor": {"class": donor, **signatures[donor]},
                "safe": verdict["safe"], "deforms": verdict.get("deforms", False), "why": verdict["why"]}

    @app.post("/api/pso/editor/preview")
    def preview(body: PreviewIn, actor=Depends(auth)):
        try:
            ops = pso_editor.edits(*body.ops)
        except pso_editor.EditError as exc:
            raise HTTPException(400, str(exc)) from None
        try:
            return pso_editor.preview(disc(), ops)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from None
