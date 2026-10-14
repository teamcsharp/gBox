"""gBox control plane: API gateway, job scheduler, independent validation, receipts, audit."""
import asyncio
import base64
import collections
import concurrent.futures
import hmac
import httpx
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field, StrictBool

from . import tools as _builtin  # noqa: F401  (registers tools)
from . import padstate
from . import fit_events
from . import operator_guard
from .config import HOST_OS, Config
from .models import Job, JobState, new_id, KnowledgeEdge, Receipt, RunRecord, WorkerInfo
from .registry import REGISTRY
from .store import Store, canon, sha256
from .worker_results import result_digest

WORKER_TTL = 30.0
WEB = Path(__file__).resolve().parent.parent / "clients" / "web" / "index.html"
BRAND = Path(__file__).resolve().parent.parent / "assets" / "brand"
# adapters whose second copy can't run beside the first on one PC (mGBA's GDB stub port is fixed): a relaunch closes
# the running copy first there (launch_game saves it before closing, and refuses if it can't)
RELAUNCH_BESIDE_UNSAFE = {"mgba"}


class ArtifactUpload(BaseModel):
    name: str
    media_type: str
    provenance: dict = {}
    b64: str


class JobResult(BaseModel):
    job_id: str
    ok: StrictBool
    output: dict | None = None
    error: str | None = None
    log: list[str] = []
    artifacts: list[ArtifactUpload] = []


class JobRequest(BaseModel):
    tool: str
    input: dict = {}
    require_os: str | None = None
    require_worker: str | None = None
    parent_request_id: str | None = None
    agent_use: bool = False
    low_priority: bool = False      # background work (the Sonic showcase): claimed after every other queued job


class Evaluation(BaseModel):
    evaluator: str
    passed: bool
    metrics: dict[str, float] = {}
    notes: str = ""


def _checkpoint_slot(result: dict, adapter: str) -> int:
    """Use native checkpoint evidence, never the slot requested before a dropped command."""
    if result.get("verified") is False:
        raise RuntimeError("the emulator did not verify the captured checkpoint")
    slot = result.get("slot")
    path = str(result.get("path") or result.get("file") or "")
    match = re.search(r"\.state(-?\d+)?$", path)
    native = (int(match[1] or 0) if match and adapter == "retroarch" else
              (1 if adapter == "dolphin" and path.endswith(".s01") else None))
    if adapter == "dolphin" and slot is not None and slot != 1:
        raise RuntimeError("Dolphin's captured checkpoint does not identify native slot 1")
    if slot is not None and (type(slot) is not int or (native is not None and native != slot)):
        raise RuntimeError("the captured checkpoint slot disagrees with its native filename")
    actual = slot if slot is not None else native
    if actual is None:
        raise RuntimeError("the captured checkpoint did not identify its actual native slot")
    return actual


def _is_stop_job(job: dict) -> bool:
    return job.get("tool") == "session_op" and (job.get("input") or {}).get("op") == "stop_game"


def create_app(config: Config) -> FastAPI:
    store = Store(config.data_dir)
    token = config.token()
    from . import cache_tiers                     # two-tier cache: recover + migrate before anything reads the cache
    cache_tiers.install(config)
    app = FastAPI(title="gBox", version="0.1.0")
    app.add_middleware(cache_tiers.TouchMiddleware)   # API traffic naming a game keeps it off the demotion list
    app.state.store = store
    from .character_collection import AutoCollection
    auto_collection = AutoCollection(store, config)
    stopping: dict[str, str] = {}                  # session id -> its pending stop job (GET /api/sessions "stopping")

    @app.on_event("startup")
    async def _more_threads():
        # every live stream viewer and worker input long-poll holds a worker thread
        import anyio.to_thread
        anyio.to_thread.current_default_thread_limiter().total_tokens = 256

    @app.on_event("startup")
    async def _audio_cpp_autostart():
        # audio.cpp runs beside the control plane when its binary is on this machine (docs/audio_cpp.md); absent = no-op
        from . import audio_cpp
        threading.Thread(target=audio_cpp.autostart, args=(config,), name="audio_cpp-autostart", daemon=True).start()

    def auth(request: Request) -> str:
        # ?token= is accepted so <img>/<video> tags can load frames and artwork
        got = request.headers.get("authorization", "").removeprefix("Bearer ") or request.query_params.get("token", "")
        if not hmac.compare_digest(got.encode(), token.encode()):
            raise HTTPException(401, "bad token")
        return request.headers.get("x-gbox-actor", "operator")

    def request_origin(request: Request) -> dict:
        """Where an HTTP request came from (stored on jobs): the web UI / desktop app / curl / a Python client."""
        h = request.headers
        out = {"client": h.get("x-gbox-client", ""), "user_agent": h.get("user-agent", "")[:160],
               "referer": h.get("referer", "")[:200], "via": "http",
               "remote": request.client.host if request.client else "",
               "parent_job": h.get("x-gbox-parent-job", "")[:32]}   # a worker tool calling back (worker._run_job)
        return {k: v for k, v in out.items() if v}

    from . import asset_library
    asset_library.routes(app, store, config, auth)
    from . import built_mods                      # built mod folders in the cache, joined with their mod cards
    built_mods.routes(app, store, config, auth)
    BM = built_mods
    cache_tiers.routes(app, config, auth)         # GET /api/cache/tiers, POST /api/cache/tiers/pin
    from . import build_notify                    # every finished build / collect / failed build -> the bell tray
    build_notes = build_notify.Notifier(store, config, index=lambda: getattr(app.state, "built_mods", None),
                                        workers=lambda: workers(), library=lambda: built_mods.library_of(config))
    app.state.build_notes = build_notes
    build_notes.watch(app.state.built_mods)
    build_notify.routes(app, store, auth, build_notes)

    # --- shell ---
    @app.get("/")
    def index():
        return FileResponse(WEB, headers={"cache-control": "no-cache"})

    # --- asset packages (UAP): list, 3D view (GLB with textures), exports for Blender & DCC tools ---
    UAP = config.data_dir / "uap"

    def _pkg(name: str) -> Path:
        p = (UAP / name).resolve()
        if p.parent != UAP.resolve() or not (p / "manifest.json").is_file():
            raise HTTPException(404, f"no asset package {name}")
        return p

    @app.get("/api/uap")
    def uap_list(q: str = "", actor=Depends(auth)):
        from . import uap
        out = []
        for p in sorted(UAP.glob("*/manifest.json")):
            if q and not all(w in p.parent.name.lower() for w in q.lower().split()):
                continue
            try:
                out.append({"package": p.parent.name, **uap.stats(uap.load(p.parent))})
            except Exception as e:
                out.append({"package": p.parent.name, "error": str(e)})
        return out

    @app.get("/api/uap/{name}/export")
    def uap_export(name: str, fmt: str = "glb", actor=Depends(auth)):
        """glb | obj | fbx | abc (fbx/abc converted by Blender in the background, then cached)."""
        from . import uap
        p = _pkg(name)
        out = p / "export" / f"{name}.{fmt}"
        src = p / "export" / f"{name}.glb"
        if fmt not in ("glb", "obj", "fbx", "abc"):
            raise HTTPException(422, "fmt must be glb, obj, fbx or abc")
        if not src.exists() or src.stat().st_mtime < (p / "manifest.json").stat().st_mtime:
            src.parent.mkdir(exist_ok=True)
            src.write_bytes(uap.to_glb(uap.load(p), p))
        if fmt == "obj" and not out.exists():
            out.write_text(uap.to_obj(uap.load(p)))
        if fmt in ("fbx", "abc") and not out.exists():         # Blender runs on whichever worker has it (the Spark is arm64)
            ref = store.put_artifact(src.read_bytes(), src.name, "model/gltf-binary", {"package": name})
            j = submit(JobRequest(tool="asset_convert", input={"glb": ref.sha256, "fmt": fmt, "name": name}), actor)
            t0 = time.time()
            while (jj := store.get("job", j.id))["state"] in ("queued", "running") and time.time() - t0 < 900:
                time.sleep(1)
            if jj["state"] != "succeeded":
                raise HTTPException(500, f"Blender export failed: {jj.get('error') or jj['state']}")
            out.write_bytes(store.artifact_path(jj["output"]["sha"]).read_bytes())
        media = {"glb": "model/gltf-binary", "obj": "text/plain", "fbx": "application/octet-stream", "abc": "application/octet-stream"}[fmt]
        return FileResponse(out, media_type=media, filename=out.name)

    @app.post("/api/uap/{name}/clipboard")
    def uap_clip(name: str, actor=Depends(auth)):
        """Put the asset on the gBox clipboard as a GLB (the Blender add-on pastes it)."""
        from . import uap
        p = _pkg(name)
        ref = store.put_artifact(uap.to_glb(uap.load(p), p), f"{name}.glb", "model/gltf-binary", {"clipboard": True, "by": actor, "package": name})
        prev = store.get("clipboard", "current") or {"seq": 0}
        item = {"seq": prev["seq"] + 1, "kind": "gltf", "name": name, "sha256": ref.sha256, "meta": {"package": name, "binary": True},
                "ts": time.time(), "by": actor}
        store.put("clipboard", "current", item)
        store.audit(actor, "clipboard.copy", ref.sha256, {"kind": "gltf", "name": name})
        app.state.assets.invalidate()
        return item

    from . import re6_api                         # Resident Evil 6: item catalogue + icons, saved Mercenaries loadout
    re6_api.routes(app, store, config, auth)

    # --- Phantasy Star Online item catalog (from the disc) + item thumbnails (PSO wiki) for the item sidebar ---
    from . import pso_api
    pso_api.routes(app, config, auth)

    @app.get("/api/pso/item_thumb")
    def pso_item_thumb(name: str, actor=Depends(auth)):
        """The item's picture from the Phantasy Star wiki (MediaWiki API search + page image), cached on disk."""
        import hashlib
        f = config.data_dir / "pso" / "thumbs" / (hashlib.sha1(name.lower().encode()).hexdigest() + ".img")
        if not f.exists():
            h = {"user-agent": "Mozilla/5.0 gBox (item sidebar)"}
            try:
                r = httpx.get("https://phantasystar.fandom.com/api.php", headers=h, timeout=15, params={
                    "action": "query", "format": "json", "generator": "search", "gsrsearch": f'"{name}"', "gsrlimit": 3,
                    "prop": "pageimages", "piprop": "thumbnail", "pithumbsize": 128}).json()
                pages = sorted((r.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
                src = next((p["thumbnail"]["source"] for p in pages if p.get("thumbnail")), None)
                data = httpx.get(src, headers=h, timeout=15).content if src else b""
            except httpx.HTTPError:
                data = b""
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)                                     # empty file = "no picture", don't ask the wiki again
        if not f.stat().st_size:
            raise HTTPException(404, "no picture")
        head = f.open("rb").read(8)
        return FileResponse(f, media_type="image/png" if head.startswith(b"\x89PNG") else "image/jpeg",
                            headers={"cache-control": "max-age=604800"})

    class RecipeIn(BaseModel):
        name: str
        description: str
        game: str = ""
        params: dict = {}
        steps: list[dict]

    @app.post("/api/recipes")
    def recipe_put(r: RecipeIn, actor=Depends(auth)):
        """A learned tool: verified steps the agent can replay (see agent save_recipe)."""
        store.put("recipe", r.name, r.model_dump() | {"by": actor, "ts": time.time()})
        store.audit(actor, "recipe.save", r.name, {"game": r.game, "steps": len(r.steps)})
        try:
            kb().add(f"Learned tool recipe_{r.name} ({r.game or 'any game'}): {r.description}. Steps: {json.dumps(r.steps)[:1500]}",
                     "recipe", r.name, r.game, "fact")
        except Exception:
            pass
        return {"saved": r.name}

    class ModIn(BaseModel):
        title: str                          # what the operator asked for ("Infinite red shells")
        calls: list[dict]                   # [{tool, input}] replayed in order on the live session (session_id filled in)
        game_id: str = ""                   # or derived from session_id
        game_title: str = ""
        session_id: str = ""
        desc: str = ""
        thumb: str = ""                     # artifact digest of a frame showing the mod working
        video: str = ""                     # artifact digest of a recording, if any
        state_slot: int | None = None       # save-state slot of the modded moment ("load this moment")
        verified: bool = False
        requests: list[int] = []            # operator request numbers (inbox) this mod answers

    @app.post("/api/mods")
    def mod_put(m: ModIn, actor=Depends(auth)):
        """A switchable mod for a game: a verified change gBox can re-apply with one click (Controls panel / Requests)."""
        import hashlib
        sess = store.get("session", m.session_id) or {} if m.session_id else {}
        gid = m.game_id or sess.get("game_id") or ""
        m.game_title = m.game_title or sess.get("title") or ""
        if not gid:
            raise HTTPException(400, "game_id or a known session_id is required")
        mid = hashlib.sha1(f"{gid}:{m.title.lower()}".encode()).hexdigest()[:12]
        old = store.get("mod", mid) or {}
        doc = old | {k: v for k, v in m.model_dump().items() if v not in ("", None, [])} | {"id": mid, "game_id": gid, "by": actor, "ts": time.time()}
        doc["calls"] = [{"tool": c["tool"], "input": {k: v for k, v in (c.get("input") or {}).items() if k != "session_id"}} for c in m.calls]
        if not doc.get("thumb") and m.session_id and sess.get("state") == "running":
            def _shoot(mid=mid, sid=m.session_id):
                try:
                    png = _session_png(sid)
                    ref = store.put_artifact(png, f"mod-{mid}.png", "image/png", {"mod": mid, "session": sid})
                    cur = store.get("mod", mid)
                    if cur and not cur.get("thumb"):
                        store.put("mod", mid, cur | {"thumb": ref.sha256})
                except Exception:
                    pass                                     # no picture is fine; the card offers 📷
            threading.Thread(target=_shoot, daemon=True).start()
        from . import built_mods
        doc = built_mods.supersede(store, doc)          # a writer's own card replaces the gallery's stand-in for its build
        store.put("mod", mid, doc)
        store.audit(actor, "mod.save", m.title, {"game": gid, "calls": len(doc["calls"])})
        app.state.built_mods_invalidate()
        return doc

    def _session_png(sid: str) -> bytes:
        """Current picture of a session: the live stream frame when fresh, else ask its worker for one (native windows)."""
        from .session_images import SessionImageError, as_png

        def normalize(frame: bytes) -> bytes:
            try:
                return as_png(frame)
            except SessionImageError as exc:
                raise HTTPException(409, str(exc)) from exc

        lv = live.get(sid) or {}
        if lv.get("frame") and time.time() - lv.get("ts", 0) < 5:
            return normalize(lv["frame"])
        j = submit(JobRequest(tool="get_frame", input={"session_id": sid}), "mods")
        t0 = time.time()
        while (jj := store.get("job", j.id))["state"] in ("queued", "running") and time.time() - t0 < 45:
            time.sleep(0.5)
        if jj["state"] != "succeeded":
            raise HTTPException(409, f"couldn't capture the game: {jj.get('error') or jj['state']}")
        o = jj["output"]
        if o.get('capture_source') == 'desktop-compositor' and (o.get('covered') or 0) > 0:
            raise HTTPException(409, 'Another window covers part of the game. Close the overlay and retry the capture.')
        if o.get("mean_luma") is not None and o["mean_luma"] < 6:   # None = the luma probe gave up, not a black screen
            raise HTTPException(409, "the game screen is black right now: try again once it's showing")
        return normalize(store.read_artifact(o["sha256"]) or b"")

    @app.post("/api/sessions/{sid}/report-frame")
    async def report_frame(sid: str, actor=Depends(auth)):
        """Capture a still for annotation without changing the mod thumbnail or game state."""
        import base64
        from .build_report_images import annotation_frame
        session = store.get("session", sid)
        if not session:
            raise HTTPException(404, "The game session was not found")
        if session.get("state") != "running":
            raise HTTPException(409, "The game session is no longer running")
        png = await asyncio.to_thread(lambda: annotation_frame(_session_png(sid)))
        return {"image_b64": base64.b64encode(png).decode("ascii"), "session_id": sid}

    def _mod_picture(m: dict) -> dict:
        """Discard missing or tiny artifacts left by the old JSON-body capture path."""
        if m.get("thumb"):
            artifact = store.get("artifact", m["thumb"]) or {}
            if (artifact.get("size") or 0) < 64:
                m = m | {"thumb": None}
        return m

    @app.post("/api/mods/{mid}/thumb")
    async def mod_thumb(mid: str, request: Request, session_id: str = "", force: bool = False, append: bool = False,
                        actor=Depends(auth)):
        """Set a mod's picture: an image in the body, or what the session shows right now. Without force, keeps an existing one.
        append=true adds the picture to the card's in-game shots (the Mods gallery); it becomes the thumb only if none."""
        m = _mod_picture(store.get("mod", mid) or _404())
        if m.get("thumb") and not force and not append:
            return m
        body = await request.body()
        if not (body.startswith(b"\x89PNG") or body.startswith(b"\xff\xd8\xff")):
            body = b""                                 # not an image (the app posts "{}"): use what the game shows now
        if not body:
            if not session_id:
                raise HTTPException(400, "send an image or a session_id")
            body = await asyncio.to_thread(_session_png, session_id)
        kind = "image/png" if body[:4] == b"\x89PNG" else "image/jpeg"
        ref = store.put_artifact(body, f"mod-{mid}.{kind[6:]}", kind, {"mod": mid, "session": session_id})
        if append:
            m["shots"] = [ref.sha256, *[x for x in m.get("shots") or [] if x != ref.sha256]][:24]
            m["thumb"] = m["thumb"] if m.get("thumb") and not force else ref.sha256
        else:
            m["thumb"] = ref.sha256
        store.put("mod", mid, m)
        store.audit(actor, "mod.thumb", mid, {"artifact": ref.sha256, "append": append})
        app.state.built_mods_invalidate()
        return m

    @app.get("/api/mods")
    def mod_list(game_id: str = "", actor=Depends(auth)):
        out = [m for m in store.all("mod") if not game_id or m["game_id"] == game_id]
        out = [_mod_picture(m) for m in out]
        # a card that boots a built mod shows under the operator's name for that build (Mods card ✎ / Builds view);
        # `title` stays the card's own, so a card saved back never bakes the display name in
        from . import built_mods
        names, favs = built_mods.display_names(store), built_mods.favorites(store)
        for i, m in enumerate(out):
            key = f"{m.get('game_id')}/{built_mods.card_mod(m)}"
            if key in names or key in favs:
                out[i] = m | {"display_name": names.get(key, ""), "favorite": key in favs}
        return sorted(out, key=lambda m: -m.get("ts", 0))

    @app.delete("/api/mods/{mid}")
    def mod_del(mid: str, actor=Depends(auth)):
        store.delete("mod", mid)
        store.audit(actor, "mod.delete", mid, {})
        app.state.built_mods_invalidate()
        return {"deleted": mid}

    # --- character library (gbox/characters.py): models extracted from the operator's games, reusable in any game ---
    def _chars():
        from . import characters
        return characters, characters.library_root(config)

    _CHAR_STATS: dict = {}
    try:                                                  # warm the HDD character library in the background at startup
        from . import characters as _ck
        _ck.warm_list(_ck.library_root(config))
    except Exception:
        pass

    @app.get("/api/characters")
    def chars_list(game_id: str = "", fresh: bool = False, actor=Depends(auth)):
        """Library characters (+ ready swap mods for game_id) with preview URLs. fresh=1 re-reads the library."""
        K, root = _chars()
        if fresh:
            K.refresh_list(root)
        def model_bytes(m):
            try:
                return (Path(root) / m["slug"] / m["model"]).stat().st_size
            except OSError:
                return 0
        tf = lambda slug: sorted("targets/" + f.name for f in (Path(root) / slug / "targets").glob("*") if f.is_file())             if (Path(root) / slug / "targets").is_dir() else []          # game-fitted models (Blender copy of a swap mod)
        entries = K.list_all(root, game_id)
        stats = _CHAR_STATS.setdefault(str(root), {})     # file stats cached per (slug, model) (thousands of HDD stats per call)
        for m in entries:
            k = (m["slug"], m.get("model"), len(m.get("targets") or {}))
            if k not in stats:
                stats[k] = (tf(m["slug"]), model_bytes(m))
        stats_for = {m["slug"]: stats[(m["slug"], m.get("model"), len(m.get("targets") or {}))] for m in entries}
        return [m | {"preview_url": f"/api/characters/{m['slug']}/preview", "model_url": f"/api/characters/{m['slug']}/file/{m['model']}",
                     "target_files": stats_for[m["slug"]][0], "model_bytes": stats_for[m["slug"]][1]}
                for m in entries]

    @app.get("/api/characters/{slug}")
    def chars_get(slug: str, actor=Depends(auth)):
        K, root = _chars()
        try:
            return K.get(root, slug)
        except KeyError:
            _404()

    def _char_file(slug: str, rel: str) -> Path:
        K, root = _chars()
        base = (root / slug).resolve()
        f = (base / rel).resolve()
        if base.parent != root.resolve() or not f.is_relative_to(base) or not f.is_file():
            _404()
        return f

    @app.get("/api/characters/{slug}/preview")
    def chars_preview(slug: str, actor=Depends(auth)):
        return FileResponse(_char_file(slug, "preview.png"), media_type="image/png", headers={"cache-control": "max-age=3600"})

    @app.get("/api/characters/{slug}/model")
    def chars_model(slug: str, actor=Depends(auth)):
        K, root = _chars()
        f = _char_file(slug, K.get(root, slug)["model"])
        return FileResponse(f, filename=f.name, media_type="model/gltf-binary" if f.suffix == ".glb" else "model/gltf+json")

    @app.get("/api/characters/{slug}/file/{rel:path}")
    def chars_file(slug: str, rel: str, actor=Depends(auth)):
        f = _char_file(slug, rel)
        return FileResponse(f, filename=f.name)

    class CharTargetIn(BaseModel):
        game_id: str
        slot: str = "player"
        mod: str = ""
        nodes: list[str] = []
        notes: str = ""
        needs_rebuild: bool = False         # a fresh build clears a variant's inherited / re-sent "needs rebuild"

    @app.post("/api/characters/{slug}/targets")
    def chars_target(slug: str, t: CharTargetIn, actor=Depends(auth)):
        """A worker built a swap mod for a game: record it so the library shows it as ready."""
        K, root = _chars()
        try:
            with store.lock:
                m = K.set_target(root, slug, t.game_id, t.model_dump())
        except KeyError:
            _404()
        store.audit(actor, "character.target", slug, t.model_dump())
        return m

    # --- retarget profiles (gbox/retarget_profile.py): the Retarget editor's per (donor, game[, slot]) adjustments ---
    def _profile_view(K, root, slug: str, game_id: str, slot: str) -> dict:
        from . import retarget_profile as RP
        try:
            m = K.get(root, slug)
        except KeyError:
            _404()
        key = RP.slot_key(slot)
        saved = RP.stored(m, game_id) if game_id else {}
        return {"slug": slug, "name": m.get("name"), "game_id": game_id, "slot": slot or "*", "key": key,
                "profile": saved.get(key), "game_wide": saved.get("*"), "saved_slots": sorted(saved),
                "resolved": RP.resolve(m, game_id, slot) if game_id else None,
                "defaults": RP.DEFAULT, "roles": RP.ROLES, "rig_roles": (m.get("rig") or {}).get("roles") or {},
                "model_url": f"/api/characters/{slug}/file/{m['model']}" if m.get("model") else None,
                "source": m.get("source") or {}}

    @app.get("/api/characters/{slug}/retarget_profile")
    def chars_profile_get(slug: str, game_id: str = "", slot: str = "", actor=Depends(auth)):
        """The donor's saved profile for game_id (+ slot), the merged one the writers will use, and its rig roles."""
        K, root = _chars()
        return _profile_view(K, root, slug, game_id, slot)

    class ProfileIn(BaseModel):
        game_id: str
        slot: str = ""
        profile: dict | None = None         # None / reset=true removes the saved profile of that slot
        reset: bool = False

    @app.put("/api/characters/{slug}/retarget_profile")
    @app.post("/api/characters/{slug}/retarget_profile")
    def chars_profile_put(slug: str, inp: ProfileIn, actor=Depends(auth)):
        """Save (or reset) a retarget profile; the donor's built mods for that game are marked for rebuild so the next
        build (single slot or whole cast) fits with it."""
        from . import retarget_profile as RP
        K, root = _chars()
        if not re.fullmatch(r"[0-9a-f]{16}", inp.game_id or ""):
            raise HTTPException(422, "game_id is a catalog game id")
        try:
            clean = None if inp.reset or inp.profile is None else RP.normalize(inp.profile)
        except ValueError as e:
            raise HTTPException(422, str(e))
        key = RP.slot_key(inp.slot)
        with store.lock:
            try:
                m = K.get(root, slug)
            except KeyError:
                _404()
            games = m.setdefault("retarget_profiles", {})
            entry = games.setdefault(inp.game_id, {})
            if clean is None:
                entry.pop(key, None)
            else:
                entry[key] = clean | {"updated": time.time(), "by": str(actor)[:80]}
            if not entry:
                games.pop(inp.game_id, None)
            if not games:
                m.pop("retarget_profiles", None)
            for t in (m.get("targets") or {}).get(inp.game_id, []):
                if key == "*" or RP.slot_key(t.get("slot")) in (key, "*"):
                    t["needs_rebuild"] = True
            K.put_meta(root, m)
        store.audit(actor, "character.retarget_profile", slug, {"game_id": inp.game_id, "slot": key,
                                                                 "reset": clean is None})
        return _profile_view(K, root, slug, inp.game_id, inp.slot)

    @app.get("/api/retarget/reference")
    def retarget_reference(game_id: str, slot: str = "", actor=Depends(auth)):
        """The target slot's stock model for the Retarget editor: the collection entry extracted from that game whose
        name best matches the slot (Kasumi for fighter:KAS), else the game's first collected character, else none
        (the editor then draws a standard humanoid skeleton at the game's proportions)."""
        K, root = _chars()
        if not re.fullmatch(r"[0-9a-f]{16}", game_id or ""):
            raise HTTPException(422, "game_id is a catalog game id")
        if re.fullmatch(r'ped:\d+',slot):
            from . import gta_lcs_cast, gta_stories_models
            game=store.catalog_get(game_id)
            exact=gta_lcs_cast.cached_reference(config,game,slot) if game else None
            if exact:
                return {'game_id':game_id,'slot':slot,'slot_name':slot,'exact':True,
                        'reference':{'name':f'Native {slot}','roles':gta_stories_models.LCS_ROLES,
                                     'model_url':f'/api/retarget/native-reference/{game_id}/{slot.split(":")[1]}'}}
        own = [m for m in K.list_all(root) if (m.get("source") or {}).get("game_id") == game_id
               and (m.get("kind") or "character") == "character" and not m.get("variant_of") and m.get("model")]
        words = set(re.findall(r"[a-z0-9]+", str(slot).lower())) - {"fighter", "wrestler", "player", "enemy", "driver",
                                                                    "character", "ped", "all", "slot"}
        name = slot
        try:
            from . import cast_swap
            g = store.catalog_get(game_id)
            row = next((r for r in cast_swap.slot_rows(g) if r.get("slot") == slot), None) if g else None
            if row and row.get("name"):
                name = row["name"]
                words |= set(re.findall(r"[a-z0-9]+", row["name"].lower()))
        except Exception:                                    # noqa: BLE001 - the slot name only sharpens the match
            pass

        def score(m):
            hay = set(re.findall(r"[a-z0-9]+", " ".join([m["slug"], m.get("name", ""), *m.get("aliases", [])]).lower()))
            return len(words & hay)
        best = max(own, key=score, default=None)
        if best is None:
            return {"game_id": game_id, "slot": slot, "slot_name": name, "reference": None}
        exact = score(best) > 0
        return {"game_id": game_id, "slot": slot, "slot_name": name, "exact": exact,
                "reference": {"slug": best["slug"], "name": best["name"],
                              "model_url": f"/api/characters/{best['slug']}/file/{best['model']}",
                              "roles": (best.get("rig") or {}).get("roles") or {}}}

    @app.get('/api/retarget/native-reference/{game_id}/{index}')
    def native_ped_reference(game_id:str,index:int,actor=Depends(auth)):
        from . import gta_lcs_cast
        if not re.fullmatch(r'[0-9a-f]{16}',game_id):raise HTTPException(422,'Invalid game id')
        game=store.catalog_get(game_id)
        try:path=gta_lcs_cast.cached_reference(config,game,f'ped:{index}') if game else None
        except (KeyError,ValueError):raise HTTPException(404,'Native pedestrian reference unavailable')
        if not path:raise HTTPException(404,'Native pedestrian reference unavailable; stage the base disc first')
        return FileResponse(path,media_type='model/gltf-binary')

    @app.get("/api/retarget/goals")
    def retarget_goals(game_id: str, slot: str = "", actor=Depends(auth)):
        """The target slot's own skeleton for the Retarget editor's Goals view, as the last fit of that slot loaded it
        (gbox.fit_events goals: role -> target joint, + the donor's joints that fit used); null before any fit."""
        from . import retarget_profile as RP
        if not re.fullmatch(r"[0-9a-f]{16}", game_id or ""):
            raise HTTPException(422, "game_id is a catalog game id")
        key = RP.slot_key(slot)
        doc = store.get("retarget_goals", f"{game_id}|{key}")
        if doc is None and key != "*" and ":" in key:        # 'fighter:kasumi' also matches goals kept as 'kasumi'
            doc = store.get("retarget_goals", f"{game_id}|{key.split(':', 1)[-1]}")
        return {"game_id": game_id, "slot": slot, "goals": doc}

    # replacement readiness (gbox/replacement_readiness.py): who can replace a slot, where a donor fits, gaps per game
    from . import replacement_readiness
    replacement_readiness.routes(app, auth, _chars, catalog=store.catalog_get)

    # overlay swap (gbox/overlay_swap.py): a collection model drawn over the player in the desktop app, any game
    from . import overlay_swap
    overlay_swap.register(app, auth, store, lambda slug: _chars()[0].get(_chars()[1], slug)["name"])

    # ghost runs (gbox/ghost_runs.py, #1098): recorded runs per game, the live player for the overlay, ghost picks
    from . import ghost_runs
    ghost_runs.register(app, auth, store)

    # Blender round trip (gbox/blender_roundtrip.py): a character out as one GLB with its rig role names / props,
    # copy to the clipboard (the picker's right-click), import back as a variant / new donor (a characters job)
    from . import blender_roundtrip
    blender_roundtrip.register(app, auth, store, _chars, lambda req, actor: submit(req, actor), JobRequest)
    from . import texture_review
    texture_review.register(app, auth, store, _chars, lambda req, actor: submit(req, actor), JobRequest)

    # environments: whole captured scenes (characters op=extract kind=environment), next to the characters
    def _env_file(slug: str, rel: str) -> Path:
        from . import characters
        root = characters.env_root(config).resolve()
        base = (root / slug).resolve()
        f = (base / rel).resolve()
        if base.parent != root or not f.is_relative_to(base) or not f.is_file():
            _404()
        return f

    @app.get("/api/environments")
    def envs_list(actor=Depends(auth)):
        """Collection environments with preview / model URLs."""
        from . import characters
        return [m | {"preview_url": f"/api/environments/{m['slug']}/preview", "model_url": f"/api/environments/{m['slug']}/file/{m['model']}"}
                for m in characters.list_all(characters.env_root(config))]

    @app.get("/api/environments/{slug}")
    def envs_get(slug: str, actor=Depends(auth)):
        from . import characters
        try:
            return characters.get(characters.env_root(config), slug)
        except KeyError:
            _404()

    @app.get("/api/environments/{slug}/preview")
    def envs_preview(slug: str, actor=Depends(auth)):
        return FileResponse(_env_file(slug, "preview.png"), media_type="image/png", headers={"cache-control": "max-age=3600"})

    @app.get("/api/environments/{slug}/file/{rel:path}")
    def envs_file(slug: str, rel: str, actor=Depends(auth)):
        f = _env_file(slug, rel)
        return FileResponse(f, filename=f.name)

    # --- bevy: the gBox Bevy viewer's scenes, renders and live sessions (the desktop app's Bevy tab) ---
    def _bevy_render(name: str) -> Path:
        import re as _re
        if not _re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name):
            _404()
        f = (config.data_dir / "bevy" / f"{name}.png").resolve()
        if not f.is_file():
            _404()
        return f

    @app.get("/api/bevy")
    def bevy_status(actor=Depends(auth)):
        """Bevy support & offerings: viewer build state, saved scenes and renders, live windows on this node."""
        from .tools import BEVY
        sdir = config.data_dir / "bevy"

        def _items(f: Path) -> int:
            try:
                return len(json.loads(f.read_text()).get("items", []))
            except Exception:
                return 0

        def _src(f: Path) -> list:
            try:
                return json.loads(f.read_text()).get("_src", [])
            except Exception:
                return []

        scenes = [{"name": f.stem, "mtime": f.stat().st_mtime, "items": _items(f), "src": _src(f)}
                  for f in sorted(sdir.glob("*.json"), key=lambda p: p.name)]
        renders = [{"name": f.stem, "mtime": f.stat().st_mtime} for f in sorted(sdir.glob("*.png"), key=lambda p: p.name)]
        live = [{"name": n, "pid": s["proc"].pid, "items": len(s["spec"]["items"])}
                for n, s in BEVY.items() if s["proc"].poll() is None]
        exe = config.runtime / "bevy-target" / "release" / ("gbox_viewer.exe" if HOST_OS == "windows" else "gbox_viewer")
        try:
            from . import characters
            n_char = len(characters.list_all(characters.library_root(config)))
            n_env = len(characters.list_all(characters.env_root(config)))
        except Exception:
            n_char, n_env = None, None
        return {"viewer_built": exe.exists(), "scenes": scenes, "renders": renders, "live": live,
                "characters": n_char, "environments": n_env}

    @app.get("/api/bevy/render/{name}.png")
    def bevy_render_png(name: str, actor=Depends(auth)):
        return FileResponse(_bevy_render(name), media_type="image/png")

    class NotifyIn(BaseModel):
        title: str
        text: str = ""
        session_id: str = ""                # click opens this session
        kind: str = "info"                  # info | ready | done | error | build | collect
        # a build (optional; the control plane posts its own build notifications, gbox/build_notify.py)
        game_id: str = ""
        mod: str = ""                       # the built mod (Play launches it through the mod launch path)
        thumbnail: str = ""                 # an authenticated /api/... picture URL
        launch: list[dict] = []             # launch options (gbox.special_builds.launch_options shape)
        job_id: str = ""
        summary: str = ""                   # "4/4 slots built · Sonic, Knuckles, Amy, Gamma"

    @app.post("/api/notify")
    def notify(n: NotifyIn, actor=Depends(auth)):
        """A notification for the operator's header tray (e.g. "Mario Mercenaries is ready")."""
        import uuid
        nid = uuid.uuid4().hex[:12]
        body = n.model_dump()
        if n.kind == "build" and n.mod and n.game_id and not n.launch:
            body["launch"] = build_notes.launch_for({"kind": "build", "game_id": n.game_id, "mod": n.mod})
        store.put("notify", nid, body | {"id": nid, "ts": time.time(), "read": False, "by": actor})
        return {"id": nid}

    @app.get("/api/notify")
    def notify_list(limit: int = 30, actor=Depends(auth)):
        """Newest first. Build entries (auto: "build") carry items with launch options for the PCs online now and a
        thumbnail URL (GET /api/notify/{id}/thumb)."""
        return build_notes.decorate(sorted(store.all("notify"), key=lambda x: -x.get("ts", 0))[:limit])

    @app.post("/api/notify/{nid}/read")
    def notify_read(nid: str, actor=Depends(auth)):
        n = store.get("notify", nid) or _404()
        store.put("notify", nid, n | {"read": True})
        return {"ok": True}

    class LabelIn(BaseModel):
        label: str = ""                     # shown on the session's tray icon
        owner: str = "you"                  # you | agent: agents' test sessions are shown dimmed

    @app.post("/api/sessions/{sid}/label")
    def session_label(sid: str, l: LabelIn, actor=Depends(auth)):
        store.put("slabel", sid, l.model_dump() | {"session_id": sid, "ts": time.time()})
        return {"ok": True}

    @app.get("/api/session_labels")
    def session_labels(actor=Depends(auth)):
        return {x["session_id"]: x for x in store.all("slabel")}

    # --- swap / move: a running game -> the same game with another mod (or none), on the same machine or another one ---
    # Mods that change game files (models, sprites, discs) need the emulator restarted with the new image; this keeps the
    # operator where they are: same PC, same moment (save state carried over), old copy closed, a frame check at the end.
    def _run_job(tool, inp, actor, worker=None, wait=240.0, progress=None, should_stop=None,
                 on_cancel_deferred=None, queue_wait=None, origin=None, agent_use: bool = False) -> dict:
        j = submit(JobRequest(tool=tool, input=inp, require_worker=worker, agent_use=agent_use), actor)
        if origin:                                     # e.g. the launch a swap made: traceable to its parent job
            with store.lock:
                rec = store.get("job", j.id)
                if rec is not None:
                    store.put("job", j.id, rec | {"origin": origin})
        t0 = time.time()
        deferred_launch = False
        while (jj := store.get("job", j.id))["state"] in ("queued", "running") and time.time() - t0 < wait:
            if queue_wait and jj["state"] == "queued" and time.time() - t0 >= queue_wait:
                # The worker never picked it up (busy or overloaded): nothing has been touched yet, so drop the child
                # and fail fast instead of leaving the parent "running" with no output for many minutes.
                with store.lock:
                    cj = store.get("job", j.id)
                    if cj["state"] == JobState.QUEUED:
                        cj.update(state=JobState.FAILED, finished=time.time(), cancel=True,
                                  error=f"not picked up by its worker within {queue_wait:.0f} s")
                        store.put("job", j.id, cj)
                        name = (store.get("worker", worker or "") or {}).get("name") or worker or "the worker"
                        raise HTTPException(409, f"{name} did not start {tool} within {queue_wait:.0f} s (it is busy). "
                                                 "Nothing was changed; your current game keeps running.")
                continue
            if should_stop and should_stop():
                # the parent was cancelled: drop a queued child, ask a running one to stop, and stop waiting (#1297)
                with store.lock:
                    cj = store.get("job", j.id)
                    queued = cj["state"] == JobState.QUEUED
                    if queued:
                        cj.update(state=JobState.FAILED, finished=time.time(), cancel=True,
                                  error="cancelled with its parent task")
                    elif cj["state"] == JobState.RUNNING and tool != 'launch_game':
                        cj["cancel"] = True
                    if queued or tool != 'launch_game':
                        store.put("job", j.id, cj)
                if tool != 'launch_game' or queued:
                    raise HTTPException(409, "cancelled by the operator before the replacement started; "
                                             "your current game was kept running")
                # Claim and cancellation share Store.lock. Once a launch is
                # claimed, its native outcome is unknown: do not race a recovery
                # launch or stop its emulator. Finish the existing handoff.
                if on_cancel_deferred:
                    on_cancel_deferred()
                deferred_launch = True
            if progress and jj.get('progress'):
                progress(jj['progress'].get('pct', 0), jj['progress'].get('msg', ''))
            time.sleep(0.5)
        if jj["state"] != "succeeded":
            if deferred_launch and jj['state'] == JobState.RUNNING:
                raise HTTPException(409, "Cancellation remains deferred: the replacement launch has no completed result yet. "
                                         "No recovery launch or game stop was requested.")
            raise HTTPException(409, f"{tool} failed: {jj.get('error') or jj['state']}")
        return jj.get("output") or {}

    def _swap_target(sess_wid: str, to: str) -> dict:
        """'' = the machine the game runs on now; a worker name/id; 'windows'/'linux' = that OS (the current one if it fits)."""
        ws = [w for w in workers() if w["online"]]
        cur = next((w for w in ws if w["id"] == _wid(sess_wid)), None)
        if not to or to == "same":
            if cur:
                return cur
            raise HTTPException(409, "the machine running this game is offline")
        hit = next((w for w in ws if to in (w["id"], w["name"])), None)
        if not hit and to in ("windows", "linux"):
            hit = cur if cur and cur["os"] == to else next(
                (w for w in sorted(ws, key=lambda w: -w["last_seen"]) if w["os"] == to), None)
        if not hit:
            raise HTTPException(409, f"no online gBox worker '{to}'")
        return hit

    SWAP_LAUNCH_QUEUE_S = 180.0      # the target worker must start the replacement launch within this (or nothing changes)

    def session_swap(sid: str, mod: str, to: str, actor: str, keep_state: bool = True, progress=None,
                     should_stop=None, keep_old: bool = False, parent_job: str = "") -> dict:
        """keep_old: on the same worker, the replacement starts beside the running copy (launch_game keep_session), which
        closes only once the replacement runs (a reset's relaunch: never stop a game before its replacement is up)."""
        say = progress or (lambda pct, msg: None)
        origin = {"via": "session_swap", "parent_job": parent_job} if parent_job else {"via": "session_swap"}
        stop = should_stop or (lambda: False)
        cancel_deferred = False

        def defer_cancel():
            nonlocal cancel_deferred
            if not cancel_deferred:
                cancel_deferred = True
                say(66, "The replacement launch has started. Cancellation is deferred while its safe handoff finishes.")
        sess = store.get("session", sid) or _404()
        seen = set()
        while sess.get('state') != 'running' and sess.get('replaced_by') and sid not in seen:
            seen.add(sid); sid = sess['replaced_by']; sess = store.get('session', sid) or _404()
        game = store.catalog_get(sess.get("game_id") or "") or _404()
        old_w, tw = sid.split("-")[0], _swap_target(sid.split("-")[0], to)
        running, art, notes, old_luma = sess.get("state") == "running", None, [], None
        launch_mod = mod
        if mod:
            say(2, "Preparing replacement files; your current game keeps running")
            staged = _run_job('prepare_mod', {'game': game, 'mod': mod}, actor, worker=tw['id'], wait=1800,
                              progress=lambda pct, msg: say(min(60, 2 + pct * .58), msg), should_stop=stop)
            if isinstance(staged, dict) and (staged.get('ready') is False or
                    (staged.get('source_mod') and staged['source_mod'] != mod)):
                raise HTTPException(409, 'Prepared replacement does not identify the requested mod')
            if isinstance(staged, dict) and staged.get('mod'):
                launch_mod = staged['mod']                 # <mod>~<build>: the running game holds the old copy open (#1270)
                from . import filemods
                try:
                    filemods.mod_dir(config, game['game_id'], launch_mod)
                except ValueError as error:
                    raise HTTPException(409, 'Prepared replacement returned an invalid cache folder') from error
                if launch_mod != mod and not launch_mod.startswith(mod + filemods.STAGED_SEP):
                    raise HTTPException(409, 'Prepared replacement returned another mod folder')
        if running and keep_state:
            say(62, "Saving your current moment before applying the replacement")
            try:
                old_luma = _run_job("get_frame", {"session_id": sid}, actor, worker=old_w, wait=30,
                                    should_stop=stop).get("mean_luma")
            except HTTPException:
                pass
            try:
                art = _run_job("state_transfer", {"session_id": sid, "op": "export"}, actor, worker=old_w, wait=90,
                               should_stop=stop)["result"]["artifact"]
            except HTTPException as e:
                if str(e.detail).startswith("cancelled by the operator"):
                    raise
                raise HTTPException(409, f"Replacement was not applied: the current state could not be saved ({e.detail}). Your game was kept running.")
            except KeyError as e:
                raise HTTPException(409, f"Replacement was not applied: the current state could not be saved ({getattr(e, 'detail', e)}). Your game was kept running.")
        if stop():
            raise HTTPException(409, "cancelled by the operator before the replacement started; your current game was kept running")
        say(66, f"Starting {game['title']} " + (f"with {mod}" if mod else "(original)") + f" on {tw['name']}")
        beside = keep_old and running and tw["id"] == _wid(old_w) and sess.get("adapter") not in RELAUNCH_BESIDE_UNSAFE
        try:
            new = _run_job("launch_game", {"game": game, "mod": launch_mod, **({"keep_session": sid} if beside else {})},
                           actor, worker=tw["id"], wait=900, should_stop=stop, on_cancel_deferred=defer_cancel,
                           queue_wait=SWAP_LAUNCH_QUEUE_S, origin=origin)
        except HTTPException as e:
            if str(e.detail).startswith('cancelled by the operator before the replacement started'):
                raise                            # the child never claimed a native launch; no recovery is needed
            if ' did not start launch_game within ' in str(e.detail):
                raise                            # never picked up: the old game was not touched
            if str(e.detail).startswith('Cancellation remains deferred:'):
                raise                            # no verified child outcome on which to base native recovery
            # a modded launch closes the same console's game on that PC first: if the new one didn't start, bring the old back
            alive = True
            if running:
                try:
                    _run_job("get_frame", {"session_id": sid}, actor, worker=old_w, wait=30)
                except HTTPException:
                    alive = False
            if running and not alive:
                say(60, "That didn't start: putting your game back")
                try:
                    back = _run_job("launch_game", {"game": game,
                        "mod": sess.get("launch_mod") or sess.get("staged_mod") or sess.get("mod") or ""}, actor, worker=old_w, wait=900)
                    if art:
                        time.sleep(6)
                        _run_job("state_transfer", {"session_id": back["session_id"], "op": "import", "artifact": art}, actor,
                                 worker=old_w, wait=90)
                    store.put("session", sid, (store.get("session", sid) or {}) | {"state": "ended", "replaced_by": back["session_id"]})
                except HTTPException:
                    pass
            if "no built mod" in str(e.detail):
                raise HTTPException(409, f"the mod '{mod}' isn't built for {tw['name']} yet (rebuild it), then try again")
            raise
        nsid = new["session_id"]
        if stop():
            defer_cancel()                       # includes cancellation racing a just-completed launch
        if launch_mod != mod and store.get("session", nsid):
            with store.lock:
                store.put("session", nsid, store.get("session", nsid) | {
                    "mod": mod, "collection_mod": mod, "staged_mod": launch_mod, "launch_mod": launch_mod})
            notes.append(f"The previous {mod} copy was preserved; the new build was staged as {launch_mod}.")
        loaded, load_requested, load_verified = False, False, None
        if art:
            say(70, "Loading your moment into it")
            time.sleep(6)                                      # let the core boot before loading the state
            try:
                restored = _run_job("state_transfer", {"session_id": nsid, "op": "import", "artifact": art}, actor, worker=tw["id"], wait=90)
                details = restored.get('result') if isinstance(restored, dict) else None
                details = details if isinstance(details, dict) else {}
                load_requested = details.get('load_requested') if type(details.get('load_requested')) is bool else None
                load_verified = details.get('load_verified') if type(details.get('load_verified')) is bool else None
                loaded = details.get('load_verified') is True and details.get('loaded') is True
                if not loaded:
                    notes.append(f"The state-import job completed, but the saved moment was not confirmed loaded. Your checkpoint is retained: {art}.")
            except HTTPException as e:
                try:
                    _run_job('session_op', {'session_id': nsid, 'op': 'stop_game', 'args': {}}, actor, worker=tw['id'], wait=60)
                except HTTPException:
                    pass
                if old_w == tw['id']:
                    say(75, 'State restore failed; recovering the original game and checkpoint')
                    try:
                        back = _run_job('launch_game', {'game': game,
                            'mod': sess.get('launch_mod') or sess.get('staged_mod') or sess.get('mod') or ''}, actor, worker=old_w, wait=900)
                        time.sleep(6)
                        _run_job('state_transfer', {'session_id': back['session_id'], 'op': 'import', 'artifact': art}, actor, worker=old_w, wait=90)
                        store.put('session', sid, (store.get('session', sid) or {}) | {'state': 'ended', 'replaced_by': back['session_id']})
                    except HTTPException:
                        pass
                raise HTTPException(409, f"Replacement state restore failed ({e.detail}). The original checkpoint is retained: {art}. Check Sessions for the recovered game.")
        if running and nsid != sid:
            say(85, "Closing the previous copy")
            try:
                _run_job("session_op", {"session_id": sid, "op": "stop_game", "args": {}}, actor, worker=old_w, wait=60)
            except HTTPException:
                pass                                           # already closed by the modded launch
            s_ = store.get("session", sid) or {}
            store.put("session", sid, s_ | {"state": "ended", "ended": s_.get("ended") or time.time(), "replaced_by": nsid,
                                            "exit": s_.get("exit") or {"by": actor, "via": "swap", "to": nsid},
                                            **({"checkpoint": art, "moment_ts": time.time()} if art else {})})   # last played
        if loaded and (old_luma is None or old_luma > 3):
            # A dark restored frame can be a loading screen. Never reset away the operator's saved moment.
            say(92, "Checking the picture")
            luma = []
            for wait_s in (2.0, 3.0):
                time.sleep(wait_s)
                try:
                    luma.append(_run_job("get_frame", {"session_id": nsid}, actor, worker=tw["id"], wait=30).get("mean_luma"))
                except HTTPException:
                    luma.append(None)
            if luma and all(v is not None and v <= 3 for v in luma):
                notes.append("The restored frame is dark. Your state was preserved; use Inspect or return to Play to check it.")
        store.audit(actor, "session.swap", sid, {"to": tw["name"], "mod": mod, "new": nsid,
                    "state_loaded": loaded, "load_requested": load_requested, "load_verified": load_verified})
        if cancel_deferred:
            notes.append("Cancellation arrived after the replacement launch started, so the launch and any requested state restoration were allowed to finish. No game was stopped solely to cancel this task.")
        return {"session_id": nsid, "from": sid, "worker": tw["name"], "mod": mod,
                "launch_mod": launch_mod, "state_loaded": loaded, "load_requested": load_requested,
                "load_verified": load_verified, "cancel_deferred": cancel_deferred, "notes": notes}

    # ids of in-server job threads alive in THIS process; a "running" session_swap missing here was left by a previous
    # server process (restart) and nothing will ever finish or cancel it unless we retire it (#1297)
    _server_job_threads: set[str] = set()

    def swap_job(sid: str, mod: str, to: str, actor: str, keep_state: bool = True, origin=None) -> Job:
        """session_swap in the background as a job record (polled like a launch; output.session_id = the new session)."""
        sess = store.get("session", sid) or _404()
        seen = set()
        while sess.get('state') != 'running' and sess.get('replaced_by') and sid not in seen:
            seen.add(sid); sid = sess['replaced_by']; sess = store.get('session', sid) or _404()
        if _automated(actor, origin) and sess.get('state') == 'running':
            from .background_testing import agent_owned
            if not agent_owned(store.get('slabel', sid), store.get('job', sid.split('-', 1)[-1])):
                # A swap restarts the emulator (a black screen mid-game): background agents never do that to the
                # operator's live game. The in-app chat agent acts on the operator's own words and is exempt.
                raise HTTPException(409, "That game is the operator's live session; automated tasks can't restart or "
                                         "swap it. Use an agent-owned test session (launch_game node=idle).")
        with store.lock:
            for existing in store.all('job'):
                inp = existing.get('input') or {}
                if (existing.get('tool') == 'session_swap' and existing.get('state') in ('queued', 'running')
                    and inp.get('game_id') == sess.get('game_id')
                    and _wid(inp.get('session_id', '').split('-')[0]) == _wid(sid.split('-')[0])):
                    if inp.get('mod', '') == mod and inp.get('to', '') == to and inp.get('keep_state', True) == keep_state:
                        return Job.model_validate(existing)
                    raise HTTPException(409, 'A replacement is already being prepared for this game. Wait for it to finish before selecting another model.')
            if keep_state and sess.get('state') != 'running':
                raise HTTPException(409, 'This session has ended. Open the running game before replacing its models.')
            from . import built_mods                      # the operator's name for the build: the launch bar shows it
            named = built_mods.label_of(store, sess.get("game_id") or "", mod, "") if mod else ""
            job = Job(tool="session_swap", input={"session_id": sid, "game_id": sess.get("game_id"), "mod": mod, "to": to, 'keep_state': keep_state,
                                                  **({"mod_title": named} if named and named != mod else {})},
                      state=JobState.RUNNING, started=time.time(), actor=actor,
                      agent_use=operator_guard.is_agent(actor),
                      origin={"via": "swap_job", **({"parent_job": origin["parent_job"]}
                                                    if isinstance(origin, dict) and origin.get("parent_job") else {})})
            store.put("job", job.id, job.model_dump())
            _server_job_threads.add(job.id)

        def prog(pct, msg):
            with store.lock:
                j = store.get("job", job.id)
                previous = j.get('progress') or {}
                if previous.get('pct') == pct and previous.get('msg') == msg:
                    return
                j["progress"] = {"pct": pct, "msg": msg, "ts": time.time()}
                j["progress_log"] = (j.get("progress_log") or [])[-49:] + [msg]
                store.put("job", job.id, j)

        def go():
            try:
                out, state, err = session_swap(sid, mod, to, actor, keep_state, prog,
                                               lambda: bool((store.get("job", job.id) or {}).get("cancel")),
                                               parent_job=job.id), JobState.SUCCEEDED, None
            except HTTPException as e:
                out, state, err = None, JobState.FAILED, str(e.detail)
            except Exception as e:                             # noqa: BLE001
                out, state, err = None, JobState.FAILED, f"{type(e).__name__}: {e}"
            with store.lock:
                current = store.get("job", job.id)
                if state == JobState.SUCCEEDED and current.get('cancel') and not out.get('cancel_deferred'):
                    out = out | {'cancel_deferred': True,
                                 'notes': out.get('notes', []) + ['Cancellation arrived after the replacement launch started, so its safe handoff was completed. No game was stopped solely to cancel this task.']}
                store.put("job", job.id, current | {"state": state, "finished": time.time(), "output": out,
                                                                     "error": err})
                _server_job_threads.discard(job.id)
            if state == JobState.FAILED and err and err.startswith('cancelled by the operator'):
                return                                         # the operator stopped it: not a failure to report
            if state == JobState.FAILED:
                # the mod could not be loaded into the game: a launch failure report (gbox/launch_failures.py)
                _lf_observe_later(job.id)
        try:
            threading.Thread(target=go, daemon=True).start()
        except Exception as exc:
            reason = f'Replacement background task could not start ({type(exc).__name__}); no replacement work was dispatched.'
            with store.lock:
                _server_job_threads.discard(job.id)
                store.put('job', job.id, store.get('job', job.id) | {
                    'state': JobState.FAILED, 'finished': time.time(), 'error': reason})
                store.audit(actor, 'job.failed', job.id, {'reason': reason, 'server_thread_start_failed': True})
            raise HTTPException(503, reason) from exc
        return job

    # ---- Reset / Restart (2026-10-13: Reset on a Dolphin game stopped it and nothing came back) ----------------------
    # One server operation per click: the emulator's own reset where it has one, else the same game and build relaunched
    # on the same PC beside the running copy, which closes only once the new one runs. A failed relaunch leaves the game
    # exactly as it was and says so; nothing here stops a game before its replacement is up.

    def _live_session(sid: str) -> tuple[str, dict]:
        sess = store.get("session", sid) or _404()
        seen = set()
        while sess.get('state') != 'running' and sess.get('replaced_by') and sid not in seen:
            seen.add(sid); sid = sess['replaced_by']; sess = store.get('session', sid) or _404()
        return sid, sess

    def session_relaunch(sid: str, actor: str, original: bool = False, progress=None, should_stop=None) -> dict:
        """The running game from boot again: the exact build folder it booted (a staged <mod>~<build> copy included: no
        rebuild, no staging), or the original game (original=True, the hard reset), same worker, launched beside it."""
        say = progress or (lambda pct, msg: None)
        sid, sess = _live_session(sid)
        if sess.get("state") != "running":
            raise HTTPException(409, "This game has already ended, so there is nothing to restart: use Play again.")
        game = store.catalog_get(sess.get("game_id") or "") or _404()
        old_w = sid.split("-")[0]
        tw = _swap_target(old_w, "")
        launch_mod = "" if original else (sess.get("launch_mod") or sess.get("staged_mod") or sess.get("mod") or "")
        build = "" if original else BM.session_build(sess)
        beside = sess.get("adapter") not in RELAUNCH_BESIDE_UNSAFE
        what = f"{game['title']}" + (f" ({build})" if build else " (original game)" if original else "")
        try:                                              # last played: the moment before the restart (best effort)
            say(10, "Saving your current moment first (Reload with your last moment can bring it back)")
            moment = _run_job("state_transfer", {"session_id": sid, "op": "export"}, actor, worker=old_w, wait=25,
                              should_stop=should_stop)["result"]["artifact"]
            store.put("session", sid, (store.get("session", sid) or {}) | {"checkpoint": moment, "moment_ts": time.time()})
        except HTTPException as e:
            if str(e.detail).startswith("cancelled by the operator"):
                raise
        except (KeyError, TypeError):
            pass
        say(20, f"Starting a fresh {what} on {tw['name']}" + ("; your game keeps running until it is up" if beside else ""))
        try:
            new = _run_job("launch_game", {"game": game, "mod": launch_mod, **({"keep_session": sid} if beside else {})},
                           actor, worker=tw["id"], wait=900, should_stop=should_stop,
                           progress=lambda pct, msg: say(20 + pct * .6, msg))
        except HTTPException as e:
            alive = (store.get("session", sid) or {}).get("state") == "running"
            if not alive:                                 # the game is gone and its relaunch failed: last played says so
                s_ = store.get("session", sid) or {}
                store.put("session", sid, s_ | {"exit": {"via": "relaunch_failed", "error": str(e.detail)[:300],
                                                         "before": s_.get("exit")}})
            raise HTTPException(409, f"{what} could not be relaunched ({e.detail}). "
                                     + ("Your game is still running as it was." if alive else
                                        "The previous copy is no longer running: use Play again."))
        nsid = new["session_id"]
        if not original and store.get("session", nsid):
            keep = {k: sess[k] for k in ("mod", "collection_mod", "staged_mod", "launch_mod") if sess.get(k)}
            with store.lock:
                store.put("session", nsid, store.get("session", nsid) | keep)
        notes = []
        if nsid != sid:
            say(85, "Closing the previous copy")
            try:
                _run_job("session_op", {"session_id": sid, "op": "stop_game", "args": {}}, actor, worker=old_w, wait=60)
            except HTTPException as e:
                notes.append(f"The previous copy did not confirm it closed ({e.detail}); close it from Sessions.")
            s_ = store.get("session", sid) or {}
            store.put("session", sid, s_ | {"state": "ended", "ended": s_.get("ended") or time.time(), "replaced_by": nsid,
                                            "exit": s_.get("exit") or {"by": actor, "via": "relaunch", "to": nsid}})
        store.audit(actor, "session.relaunch", sid, {"new": nsid, "mod": launch_mod, "original": original, "beside": beside})
        return {"session_id": nsid, "from": sid, "worker": tw["name"], "mod": build, "launch_mod": launch_mod,
                "notes": notes}

    RESET_MODES = {"reset": "reset", "restart": "restart", "hard": "hard_reset"}   # mode -> the intent it needs

    def session_reset(sid: str, actor: str, mode: str = "reset", progress=None, should_stop=None, parent_job: str = "") -> dict:
        """reset: the console's reset switch (the emulator's own reset), else a relaunch of the same game + build.
        restart: always relaunch (settings applied at launch). hard: the original game from boot (mods off)."""
        say = progress or (lambda pct, msg: None)
        stop = should_stop or (lambda: False)
        sid, sess = _live_session(sid)
        if sess.get("state") != "running":
            raise HTTPException(409, "This game has already ended, so there is nothing to reset: use Play again.")
        notes = []
        boot_build = (sess.get("collection_mod") or sess.get("mod") or "").split(BM.STAGED_SEP)[0]
        live = bool(sess.get("live_mod")) and sess["live_mod"] != boot_build    # a hot-swapped model in memory (#Blender)
        if mode == "reset" and not live:
            say(5, "Pressing the console's reset")
            try:
                r = _run_job("session_op", {"session_id": sid, "op": "reset"}, actor, worker=sid.split("-")[0], wait=40,
                             should_stop=stop)
                return {"session_id": sid, "from": sid, "mode": "native", "result": r.get("result"), "notes": notes}
            except HTTPException as e:
                if str(e.detail).startswith("cancelled by the operator"):
                    raise
                notes.append(f"No console reset reached the game ({e.detail}); it was relaunched instead.")
        if stop():
            raise HTTPException(409, "cancelled by the operator before the relaunch started; your current game was kept running")
        if live and mode != "hard":                    # the model in memory is the build to restart (a reset would boot
            say(10, f"Relaunching with {sess['live_mod']}")   # the disc's original model)
            out = session_swap(sid, sess["live_mod"], "", actor, keep_state=False, progress=say, should_stop=stop,
                               keep_old=True, parent_job=parent_job)
        else:
            out = session_relaunch(sid, actor, original=mode == "hard", progress=say, should_stop=stop)
        return out | {"mode": "hard" if mode == "hard" else "relaunch", "notes": notes + (out.get("notes") or [])}

    def reset_job(sid: str, mode: str, actor: str, origin=None) -> Job:
        """session_reset in the background as a job record (polled like a swap; output.session_id = the game now)."""
        sid, sess = _live_session(sid)
        if _automated(actor, origin) and sess.get('state') == 'running':
            from .background_testing import agent_owned
            if not agent_owned(store.get('slabel', sid), store.get('job', sid.split('-', 1)[-1])):
                # like a swap (docs/stream-stability.md): a reset / relaunch restarts the emulator, and background
                # agents never do that to the operator's live game; the in-app chat agent is exempt
                raise HTTPException(409, "That game is the operator's live session; automated tasks can't reset or "
                                         "restart it. Use an agent-owned test session (launch_game node=idle).")
        with store.lock:
            for existing in store.all('job'):
                inp = existing.get('input') or {}
                if (existing.get('tool') in ('session_swap', 'session_reset') and existing.get('state') in ('queued', 'running')
                        and inp.get('game_id') == sess.get('game_id')
                        and _wid(inp.get('session_id', '').split('-')[0]) == _wid(sid.split('-')[0])):
                    if existing.get('tool') == 'session_reset' and inp.get('mode') == mode:
                        return Job.model_validate(existing)
                    raise HTTPException(409, 'This game is already being reset or swapped. Wait for that to finish.')
            if sess.get('state') != 'running':
                raise HTTPException(409, 'This game has already ended, so there is nothing to reset: use Play again.')
            job = Job(tool="session_reset", input={"session_id": sid, "game_id": sess.get("game_id"), "mode": mode},
                      state=JobState.RUNNING, started=time.time(), actor=actor,
                      agent_use=operator_guard.is_agent(actor),
                      origin={"via": "reset_job", **({k: v for k, v in origin.items() if k != "via"}
                                                     if isinstance(origin, dict) else {})})
            store.put("job", job.id, job.model_dump())
            _server_job_threads.add(job.id)

        def prog(pct, msg):
            with store.lock:
                j = store.get("job", job.id)
                j["progress"] = {"pct": round(float(pct), 1), "msg": msg, "ts": time.time()}
                j["progress_log"] = (j.get("progress_log") or [])[-49:] + [msg]
                store.put("job", job.id, j)

        def go():
            try:
                out, state, err = session_reset(sid, actor, mode, prog,
                                                lambda: bool((store.get("job", job.id) or {}).get("cancel")),
                                                parent_job=job.id), JobState.SUCCEEDED, None
            except HTTPException as e:
                out, state, err = None, JobState.FAILED, str(e.detail)
            except Exception as e:                             # noqa: BLE001
                out, state, err = None, JobState.FAILED, f"{type(e).__name__}: {e}"
            with store.lock:
                store.put("job", job.id, store.get("job", job.id) | {"state": state, "finished": time.time(), "output": out,
                                                                     "error": err})
                _server_job_threads.discard(job.id)
            store.audit(actor, "session.reset", sid, {"mode": mode, "state": str(state), "error": err,
                                                      "new": (out or {}).get("session_id")})
        try:
            threading.Thread(target=go, daemon=True).start()
        except Exception as exc:
            reason = f'Reset background task could not start ({type(exc).__name__}); the game was not touched.'
            with store.lock:
                _server_job_threads.discard(job.id)
                store.put('job', job.id, store.get('job', job.id) | {'state': JobState.FAILED, 'finished': time.time(),
                                                                     'error': reason})
            raise HTTPException(503, reason) from exc
        return job

    def relay_job(inp: dict, actor: str) -> Job:
        """Examine 3D Capture again through a capture session (gbox/scene_relay.py), as an in-server job polled like
        scene_capture (output: glb, summary, paused=False). One relay per session at a time."""
        from . import scene_relay
        sid = inp["session_id"]
        with store.lock:
            for existing in store.all('job'):
                if (existing.get('tool') == scene_relay.TOOL and existing.get('state') in ('queued', 'running')
                        and (existing.get('input') or {}).get('session_id') == sid):
                    return Job.model_validate(existing)
            job = Job(tool=scene_relay.TOOL, input=inp | {"relay": True}, state=JobState.RUNNING, started=time.time(),
                      agent_use=actor in ("agent", "mcp", "gbox-agent", "hermes"))
            store.put("job", job.id, job.model_dump())
            _server_job_threads.add(job.id)

        def prog(pct, msg):
            with store.lock:
                j = store.get("job", job.id)
                j["progress"] = {"pct": round(float(pct), 1), "msg": msg, "ts": time.time()}
                j["progress_log"] = (j.get("progress_log") or [])[-49:] + [msg]
                store.put("job", job.id, j)

        def end_session(nsid):
            with store.lock:
                s_ = store.get("session", nsid)
                if s_ and s_.get("state") != "ended":
                    store.put("session", nsid, s_ | {"state": "ended", "ended": time.time(),
                                                     "exit": {"by": actor, "via": "examine_capture_session"}})

        def go():
            sess = store.get("session", sid) or {}
            try:
                game = store.catalog_get(sess.get("game_id") or "") or {}
                if not game:
                    raise scene_relay.RelayError("This game is no longer in the library, so no capture session can "
                                                 "start it. Your game keeps running.")
                out = scene_relay.relay(
                    sid, sess, game,
                    run_job=lambda tool, i, w, wait, progress=None: _run_job(tool, i, actor, worker=w, wait=wait,
                                                                             progress=progress),
                    workers=workers, live_sessions=lambda: store.all("session"),
                    label=lambda nsid, l: store.put("slabel", nsid, l | {"session_id": nsid, "ts": time.time()}),
                    end_session=end_session, preferred=config.examine_capture_worker,
                    frames=max(1, min(int(inp.get("frames") or 2), 4)), fovy=inp.get("fovy") or 0,
                    aspect=inp.get("aspect") or 0, say=prog,
                    should_stop=lambda: bool((store.get("job", job.id) or {}).get("cancel")),
                    worker_of=lambda s: _wid(s.split("-")[0]))
                state, err = JobState.SUCCEEDED, None
            except scene_relay.RelayError as e:
                out, state, err = None, JobState.FAILED, f"Unsupported: {e}"
            except Exception as e:                             # noqa: BLE001
                out, state, err = None, JobState.FAILED, f"{type(e).__name__}: {e}"
            with store.lock:
                store.put("job", job.id, store.get("job", job.id) | {"state": state, "finished": time.time(),
                                                                     "output": out, "error": err})
                _server_job_threads.discard(job.id)
            store.audit(actor, "examine.capture_session", sid, {"job": job.id, "state": state, "error": err,
                        "capture_session": (out or {}).get("capture_session")})
        try:
            threading.Thread(target=go, daemon=True, name=f"scene-relay-{job.id}").start()
        except Exception as exc:
            with store.lock:
                _server_job_threads.discard(job.id)
                store.put('job', job.id, store.get('job', job.id) | {
                    'state': JobState.FAILED, 'finished': time.time(), 'error': 'capture session task could not start'})
            raise HTTPException(503, 'capture session task could not start') from exc
        return job

    # --- PR evidence (gbox/evidence_capture.py, docs/pr-evidence.md): frames of a mod working, in agent test sessions ---
    EVIDENCE_MOMENTS = "evidence_moments"          # setting: {game_id: {variant: {artifact, label, after_moment, ...}}}

    def _evidence_recorded(gid: str, variant: str = "") -> dict | None:
        return ((store.get("setting", EVIDENCE_MOMENTS) or {}).get(gid) or {}).get(variant or "")

    def _evidence_mod_card(cid: str) -> dict | None:
        card = store.get("mod", cid)
        if card and card.get("session_id"):
            sess = store.get("session", card["session_id"]) or {}
            name = (sess.get("detail") or {}).get("worker_name")
            if name:
                card = card | {"worker": name}
        return card

    def _evidence_operator_active(w: dict) -> str | None:
        """Someone started using the capture's node: a game the capture did not start, or fresh input on that PC."""
        cur = next((x for x in workers() if x["id"] == w["id"]), None) or {}
        idle = cur.get("idle_seconds")
        if cur.get("os") == "windows" and idle is not None and idle < 30 and (w.get("idle_seconds") or 0) >= 30:
            return f"someone is using {cur.get('name')} (input {int(idle)} s ago)"
        labels = {x["session_id"]: x for x in store.all("slabel")}
        for sess in store.all("session"):
            sid = sess.get("session_id") or ""
            if (sess.get("state") == "running" and _wid(sid.split("-")[0]) == w["id"]
                    and not str((labels.get(sid) or {}).get("label", "")).startswith("Evidence capture")):
                return f"a game was started on {cur.get('name') or w['id']} ({sess.get('title') or sid})"
        return None

    def evidence_job(inp: dict, actor: str) -> Job:
        """evidence_capture as an in-server job (one at a time); output = EvidenceOut. Its test sessions are agent
        jobs (agent_use: 2% volume on Windows), labelled owner=agent, and always stopped by the capture itself."""
        from . import evidence_capture as EC
        game = store.catalog_get(inp.get("game_id") or "")
        if not game:
            raise HTTPException(404, f"game {inp.get('game_id')} is not in the library")
        with store.lock:
            for existing in store.all('job'):
                if (existing.get('tool') == EC.TOOL and existing.get('state') in ('queued', 'running')
                        and existing.get('id') in _server_job_threads):
                    raise HTTPException(409, f"an evidence capture is already running (job {existing['id']}); "
                                             "they run one at a time")
            job = Job(tool=EC.TOOL, input=inp, state=JobState.RUNNING, started=time.time(), agent_use=True)
            store.put("job", job.id, job.model_dump())
            _server_job_threads.add(job.id)

        def prog(pct, msg):
            with store.lock:
                j = store.get("job", job.id)
                j["progress"] = {"pct": round(float(pct), 1), "msg": msg, "ts": time.time()}
                j["progress_log"] = (j.get("progress_log") or [])[-49:] + [msg]
                store.put("job", job.id, j)

        def end_session(nsid):
            with store.lock:
                s_ = store.get("session", nsid)
                if s_ and s_.get("state") != "ended":
                    store.put("session", nsid, s_ | {"state": "ended", "ended": time.time(),
                                                     "exit": {"by": actor, "via": "evidence_capture"}})

        def put_artifact(data, name, media, prov):
            return store.put_artifact(data, name, media, prov | {"job": job.id}).sha256

        def go():
            try:
                ei = EC.EvidenceIn.model_validate(inp)
                out = EC.run(
                    ei, game,
                    run_job=lambda tool, i, w, wait, progress=None: _run_job(tool, i, actor, worker=w, wait=wait,
                                                                             progress=progress, agent_use=True),
                    workers=workers, live_sessions=lambda: store.all("session"),
                    recorded=_evidence_recorded(ei.game_id, ei.recipe),
                    label=lambda nsid, l: store.put("slabel", nsid, l | {"session_id": nsid, "ts": time.time()}),
                    end_session=end_session, put_artifact=put_artifact, read_artifact=store.read_artifact,
                    operator_active=_evidence_operator_active, mod_card=_evidence_mod_card,
                    running_jobs=store.running_job_counts, say=prog,
                    should_stop=lambda: bool((store.get("job", job.id) or {}).get("cancel")),
                    worker_of=lambda s: _wid(s.split("-")[0]))
                state, err = JobState.SUCCEEDED, None
                store.put("evidence", job.id, {"id": job.id, "game_id": ei.game_id, "mod": ei.mod, "ts": time.time(),
                                               "by": actor, "frames": out["frames"], "pairs": out["pairs"],
                                               "worker": out["worker"], "recipe": out["recipe"]})
            except EC.EvidenceError as e:
                out, state, err = None, JobState.FAILED, f"Unsupported: {e}"
            except Exception as e:                             # noqa: BLE001
                out, state, err = None, JobState.FAILED, f"{type(e).__name__}: {e}"
            with store.lock:
                store.put("job", job.id, store.get("job", job.id) | {"state": state, "finished": time.time(),
                                                                     "output": out, "error": err})
                _server_job_threads.discard(job.id)
            store.audit(actor, "evidence.capture", inp.get("game_id", ""), {"job": job.id, "state": state, "error": err,
                        "mod": inp.get("mod"), "frames": len((out or {}).get("frames") or [])})
        try:
            threading.Thread(target=go, daemon=True, name=f"evidence-{job.id}").start()
        except Exception as exc:
            with store.lock:
                _server_job_threads.discard(job.id)
                store.put('job', job.id, store.get('job', job.id) | {
                    'state': JobState.FAILED, 'finished': time.time(), 'error': 'evidence capture task could not start'})
            raise HTTPException(503, 'evidence capture task could not start') from exc
        return job

    @app.get("/api/evidence/recipes")
    def evidence_recipes(actor=Depends(auth)):
        """Per-game capture recipes (gbox/evidence_recipes.json) with the moments the operator recorded."""
        from . import evidence_capture as EC
        rec = store.get("setting", EVIDENCE_MOMENTS) or {}
        return {gid: r | {"recorded": rec.get(gid) or {}} for gid, r in EC.load_recipes().items()}

    class EvidenceMomentIn(BaseModel):
        game_id: str = ""                   # default: the session's game
        session_id: str                     # the running session to export the moment from (it keeps running)
        variant: str = ""                   # a recipe variant ("" = the game's default)
        label: str = ""
        after_moment: list[dict] | None = None   # None = keep the recipe's

    @app.post("/api/evidence/moments")
    def evidence_moment_put(m: EvidenceMomentIn, actor=Depends(auth)):
        """Record the game's gameplay moment for evidence captures: a state export of a running session (the game is
        not paused or stopped). Only on an explicit request that names the session."""
        from . import evidence_capture as EC
        sess = store.get("session", m.session_id) or _404()
        if sess.get("state") != "running":
            raise HTTPException(409, "That session has ended; open the game at the moment you want to record.")
        gid = m.game_id or sess.get("game_id") or ""
        if m.after_moment is not None:
            for k, st in enumerate(m.after_moment):
                try:
                    s_ = EC.InputStep.model_validate(st)
                except Exception as e:                         # noqa: BLE001
                    raise HTTPException(422, f"after_moment[{k}]: {e}")
                if s_.tool and (s_.tool not in EC.STEP_TOOLS or s_.input.get("op") not in EC.STEP_TOOLS[s_.tool]):
                    raise HTTPException(422, f"after_moment[{k}]: tool {s_.tool} is not allowed")
        out = _run_job("state_transfer", {"session_id": m.session_id, "op": "export"}, actor,
                       worker=m.session_id.split("-")[0], wait=120)
        art = (out.get("result") or {}).get("artifact")
        if not art:
            raise HTTPException(409, "the state export returned no artifact")
        with store.lock:
            allm = store.get("setting", EVIDENCE_MOMENTS) or {}
            rec = {"artifact": art, "label": m.label or "recorded gameplay moment", "session_id": m.session_id,
                   "adapter": sess.get("adapter"), "mod": sess.get("mod") or "", "by": actor, "ts": time.time()}
            if m.after_moment is not None:
                rec["after_moment"] = m.after_moment
            allm.setdefault(gid, {})[m.variant or ""] = rec
            store.put("setting", EVIDENCE_MOMENTS, allm)
        store.audit(actor, "evidence.moment", gid, {"variant": m.variant, "artifact": art})
        return rec | {"game_id": gid, "variant": m.variant}

    @app.get("/api/evidence")
    def evidence_list(game_id: str = "", mod: str = "", limit: int = 50, actor=Depends(auth)):
        """Finished evidence captures (frames + before/after pairs), newest first."""
        rows = [e for e in store.all("evidence") if (not game_id or e.get("game_id") == game_id)
                and (not mod or e.get("mod") == mod)]
        return sorted(rows, key=lambda e: -(e.get("ts") or 0))[:max(1, min(limit, 500))]

    # --- reverse-engineering library (gbox/re_lab.py): playbooks + per-title dossiers the agent reads and writes ---
    class LessonIn(BaseModel):
        lesson: str
        outcome: str = "worked"             # worked | failed | partial
        game: str = ""

    class FindingIn(BaseModel):
        kind: str = "note"
        address: str = ""
        name: str = ""
        role: str = ""
        status: str = "hypothesis"
        evidence: list[str] = []
        question: str = ""

    class StudyIn(BaseModel):
        executable: dict | None = None
        analysis: dict | None = None

    @app.get("/api/re/playbooks")
    def re_playbooks(q: str = "", platform: str = "", actor=Depends(auth)):
        from . import re_lab
        return re_lab.playbooks(store, q, platform)

    @app.get("/api/re/playbooks/{pid}")
    def re_playbook_get(pid: str, actor=Depends(auth)):
        from . import re_lab
        pb = re_lab.playbook(store, pid) or _404()
        return pb | {"text": re_lab.render_playbook(pb)}

    @app.post("/api/re/playbooks/{pid}/lessons")
    def re_playbook_learn(pid: str, l: LessonIn, actor=Depends(auth)):
        from . import re_lab
        try:
            r = re_lab.learn(store, pid, l.lesson, l.outcome, l.game, actor)
        except (KeyError, ValueError) as e:
            raise HTTPException(422, str(e))
        store.audit(actor, "re.lesson", pid, {"outcome": l.outcome, "game": l.game})
        return r

    @app.get("/api/re/dossier/{gid}")
    def re_dossier_get(gid: str, actor=Depends(auth)):
        from . import re_lab
        d = re_lab.dossier(store, store.catalog_get(gid) or _404())
        return d | {"text": re_lab.render_dossier(d)}

    @app.post("/api/re/dossier/{gid}/findings")
    def re_dossier_record(gid: str, f: FindingIn, actor=Depends(auth)):
        from . import re_lab
        r = re_lab.record(store, store.catalog_get(gid) or _404(), f.kind, f.address, f.name, f.role, f.status, f.evidence,
                          f.question, actor)
        store.audit(actor, "re.finding", gid, f.model_dump())
        return r

    @app.post("/api/re/dossier/{gid}/study")
    def re_dossier_study(gid: str, s: StudyIn, actor=Depends(auth)):
        from . import re_lab
        d = re_lab.set_study(store, store.catalog_get(gid) or _404(), s.executable, s.analysis)
        return {"ok": True, "text": re_lab.render_dossier(d)}

    class SignaturesIn(BaseModel):
        exe_artifact: str = ""               # sha256 of the executable (ELF or raw image) in the artifact store
        exe_rel: str = ""                    # or the re_study ELF: path relative to <data_dir>/analysis
        processor: str                       # Ghidra processor id, e.g. SuperH4:LE:32:default
        base: str | int = 0                  # load address of a raw image (ELF segments carry their own)
        functions: list[dict] = []           # [{address, size, name?}] e.g. Ghidra list_functions with sizes
        record: bool = True
        source: str = ""

    def _sig_exe(s: "SignaturesIn") -> tuple[bytes, int]:
        from . import re_transfer
        exe = store.read_artifact(s.exe_artifact) if re.fullmatch(r"[0-9a-f]{64}", s.exe_artifact or "") else None
        if exe is None and s.exe_rel:
            from .re_lab_tool import analysis_root
            root = analysis_root(config)
            p = (root / s.exe_rel).resolve()
            if p.is_relative_to(root) and p.is_file():
                exe = p.read_bytes()
        if exe is None:
            raise HTTPException(404, f"executable artifact {s.exe_artifact!r} not found")
        try:
            re_transfer.arch_of(s.processor)
            return exe, re_transfer._int(s.base or 0)
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.get("/api/re/signatures")
    def re_signatures(actor=Depends(auth)):
        """Cross-title function-body library: per arch, how many named bodies and which titles taught them."""
        from . import re_transfer
        out = {}
        for arch in ("sh4", "ppc-be", "ppc-le", "mips-le", "mips-be"):
            lib = store.get(re_transfer.LIB_KIND, arch)
            if lib:
                out[arch] = {"bodies": len(lib["sigs"]), "ambiguous": sum(1 for v in lib["sigs"].values()
                                                                         if v.get("ambiguous")),
                             "sources": lib.get("sources", {})}
        return out

    @app.post("/api/re/dossier/{gid}/signatures/learn")
    def re_signatures_learn(gid: str, s: SignaturesIn, actor=Depends(auth)):
        """Teach the library this title's named functions (dossier documented/validated names win over Ghidra's)."""
        from . import re_lab, re_transfer
        g = store.catalog_get(gid) or _404()
        exe, base = _sig_exe(s)
        d = re_lab.dossier(store, g)
        names = {f["address"]: f["name"] for f in d.get("findings", []) if f.get("kind") == "function"
                 and f.get("address") and f.get("status") in ("documented", "validated") and f.get("name")}
        fns = s.functions or re_transfer.elf_functions(exe)        # a debug/prototype ELF names itself
        r = re_transfer.learn(store, s.source or g.get("title") or gid, exe, base, s.processor, fns, names)
        store.audit(actor, "re.signatures.learn", gid, {k: r[k] for k in ("arch", "added", "library")})
        return r

    @app.post("/api/re/dossier/{gid}/signatures/transfer")
    def re_signatures_transfer(gid: str, s: SignaturesIn, actor=Depends(auth)):
        """Name this title's functions from bodies other titles already named; hits land in the dossier."""
        from . import re_transfer
        g = store.catalog_get(gid) or _404()
        exe, base = _sig_exe(s)
        r = re_transfer.transfer(store, g, exe, base, s.processor, s.functions or None, s.record,
                                 exclude_source=g.get("title") or "")
        store.audit(actor, "re.signatures.transfer", gid, {k: r[k] for k in ("arch", "named", "library")})
        return r

    @app.get("/api/games/{gid}/roster")
    def game_roster(gid: str, actor=Depends(auth)):
        """Who this game's own extractor can pull out (SmackDown! 2, No Mercy, SA2, FF7...), and which are collected."""
        from . import characters as C
        g = store.catalog_get(gid) or _404()
        t, plat = (g.get("title") or "").lower(), g.get("platform") or ""
        for name, test, roster, _run in C.DEDICATED:
            if test(t, plat):
                root = C.library_root(config)
                return {"extractor": name, "roster": [{"name": e["name"], "slug": e["slug"], "kind": e.get("kind", "character"),
                                                       "collected": (root / e["slug"] / "meta.json").is_file()}
                                                      for e in C.dedicated_entries(config, g, name, roster)],
                        "collection": auto_collection.status(gid)}
        return {"extractor": None, "roster": [], "collection": auto_collection.status(gid)}

    # whole-cast swap (gbox/cast_swap.py): the "Replace entire cast with..." menu's sources and plan; the build is a
    # characters op=cast_swap job on the Spark
    def _cast_chars():
        from . import characters as C
        root = C.library_root(config)
        return [m | {"preview_url": f"/api/characters/{m['slug']}/preview"} for m in C.list_all(root)], root

    @app.get("/api/cast_swap/sources")
    def cast_swap_sources(game_id: str = "", actor=Depends(auth)):
        """Source games / groups of the collection (usable donors after the costume dedupe) and, for game_id, the
        target's replaceable slots."""
        from . import cast_swap
        chars, _root = _cast_chars()
        out = {"sources": cast_swap.source_groups(chars)}
        if game_id:
            g = store.catalog_get(game_id) or _404()
            out["slots"] = cast_swap.slot_rows(g)
            out["slot_sets"] = cast_swap.slot_sets(out["slots"])
        return out

    class CastPlanIn(BaseModel):
        game_id: str
        source: str = ""
        mapping: str = "auto"
        assign: str = ""                                    # random | by_role | auto: wins over mapping
        prefer: str = ""                                    # a source whose donors are dealt first
        seed: str = ""
        slots: str = "all"
        assignments: list[dict] = []

    @app.post("/api/cast_swap/plan")
    def cast_swap_plan(inp: CastPlanIn, actor=Depends(auth)):
        """The planned assignments (target slot -> donor) without building; stale donors are flagged, not re-read."""
        from . import cast_swap
        g = store.catalog_get(inp.game_id) or _404()
        chars, root = _cast_chars()
        if not inp.source:
            return {"status": "needs_source", "sources": cast_swap.source_groups(chars), "slots": cast_swap.slot_rows(g)}
        try:
            return cast_swap.plan(g, chars, inp.source, cast_swap.mapping_of(inp), inp.seed, inp.slots,
                                  inp.assignments, root if root.is_dir() else None, prefer=inp.prefer)
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.get("/api/character-collection/policy")
    def collection_policy(actor=Depends(auth)):
        return auto_collection.policy()

    class CollectionPolicy(BaseModel):
        enabled: bool = True
        parent_request_id: str | None = None

    @app.post("/api/character-collection/policy")
    def set_collection_policy(inp: CollectionPolicy, actor=Depends(auth)):
        if inp.parent_request_id:
            parent = store.get('request', inp.parent_request_id)
            if not parent or parent.get('automated'):
                raise HTTPException(422, 'parent must identify an operator request')
        store.put('setting', 'auto_character_collection', inp.model_dump())
        return inp

    class SwapIn(BaseModel):
        mod: str = ""                       # "" = the original game
        to: str = ""                        # "" = the same machine | a worker name | windows | linux
        keep_state: bool = True
        intent: str = ""                    # required with keep_state=false: hard_reset | reset_model (an operator click)

    SWAP_DISCARD_INTENTS = ("hard_reset", "reset_model")

    @app.post("/api/sessions/{sid}/swap")
    def session_swap_api(sid: str, s: SwapIn, actor=Depends(auth), origin=Depends(request_origin)):
        """Turn a file/model mod on or off in a running game: same PC, same moment (job; output.session_id = new session).
        keep_state=false throws the current moment away (the game restarts from boot), so it needs an explicit intent
        from an operator action; a bare {mod:"", keep_state:false} is refused (docs/stream-stability.md)."""
        if not s.keep_state and s.intent not in SWAP_DISCARD_INTENTS:
            raise HTTPException(422, "keep_state=false restarts the game without its current moment; it needs intent "
                                     "'hard_reset' or 'reset_model' from an explicit operator action")
        job = swap_job(sid, s.mod, s.to, actor, s.keep_state, origin=origin)
        jid = getattr(job, "id", None)
        if jid:
            with store.lock:
                rec = store.get("job", jid)
                if rec is not None:
                    asks = (rec.get("requests") or [])[-9:] + [{"actor": actor, "intent": s.intent, "ts": time.time(), **origin}]
                    first = rec.get("origin") or {}
                    if "intent" not in first:            # the request that created the job; later ones are in requests
                        first = first | {"intent": s.intent, **origin}
                    store.put("job", jid, rec | {"origin": first, "requests": asks})
            store.audit(actor, "session.swap.request", jid, {"session_id": sid, "mod": s.mod, "to": s.to,
                        "keep_state": s.keep_state, "intent": s.intent, "origin": origin})
        return job

    class ResetIn(BaseModel):
        mode: Literal["reset", "restart", "hard"] = "reset"
        intent: str = ""                    # hard: "hard_reset" (an explicit operator action: the moment and mods go)

    @app.post("/api/sessions/{sid}/reset")
    def session_reset_api(sid: str, r: ResetIn, actor=Depends(auth), origin=Depends(request_origin)):
        """Reset / restart a running game as one server operation (job; output.session_id = the game afterwards).
        reset: the emulator's own reset where it has one, else the same game + build relaunched on the same PC;
        restart: always that relaunch; hard: the original game from boot. A relaunch starts beside the running copy,
        which closes only once the new one runs: a failed relaunch leaves the game as it was (the job says so)."""
        if r.mode == "hard" and r.intent != RESET_MODES["hard"]:
            raise HTTPException(422, "a hard reset restarts the ORIGINAL game from boot (mods off, moment lost): it needs "
                                     "intent 'hard_reset' from an explicit operator action")
        job = reset_job(sid, r.mode, actor, origin=origin)
        store.audit(actor, "session.reset.request", getattr(job, "id", None),
                    {"session_id": sid, "mode": r.mode, "intent": r.intent, "origin": origin})
        return job

    # ---- Last played (gbox/last_played.py, clients/web/viz/last-played.js): after the operator's game ends, offer
    # to reload it (same game, mod, PC) or reload it with the moment saved just before the end ---------------------------
    from . import last_played as LP

    @app.get("/api/last_played")
    def last_played_get(actor=Depends(auth)):
        return {"entry": LP.entry(store, workers(), _wid)}

    class LastPlayedDismissIn(BaseModel):
        session_id: str
        never_for_game: bool = False          # "Don't ask again for this game"

    @app.post("/api/last_played/dismiss")
    def last_played_dismiss(d: LastPlayedDismissIn, actor=Depends(auth)):
        s_ = store.get("session", d.session_id) or _404()
        store.put(LP.DISMISS_KIND, d.session_id, {"session_id": d.session_id, "ts": time.time(), "by": actor})
        if d.never_for_game and s_.get("game_id"):
            store.put(LP.MUTE_KIND, s_["game_id"], {"game_id": s_["game_id"], "ts": time.time(), "by": actor})
        return {"ok": True}

    class LastPlayedReloadIn(BaseModel):
        session_id: str                       # the session that ended
        moment: bool = False                  # load the moment saved before the end

    def session_reload(sid: str, actor: str, moment: bool, progress=None) -> dict:
        """Launch the ended game again (same game, mod and PC); with moment, load the state saved before it ended. Refuses
        a PC that is playing another game rather than closing it."""
        say = progress or (lambda pct, msg: None)
        sess = store.get("session", sid) or _404()
        game = store.catalog_get(sess.get("game_id") or "") or _404()
        wid = _wid(sid.split("-")[0])
        w = next((x for x in workers() if x["id"] == wid and x["online"]), None)
        if not w:
            raise HTTPException(409, "The PC that ran this game is offline: start gBox there, then Reload.")
        busy = [s_ for s_ in store.all("session") if s_.get("state") == "running" and _wid(s_["session_id"].split("-")[0]) == wid
                and not LP.is_agent_session(store, s_)]
        if busy:
            raise HTTPException(409, f"{busy[0].get('title') or 'Another game'} is running on {w['name']}; it was not "
                                     "stopped. Stop it first, then Reload.")
        art = (LP.moment_of(store, sess) or {}).get("artifact") if moment else None
        if moment and not art:
            raise HTTPException(409, "No saved moment was found for that game; Reload starts it from boot.")
        mod = str(sess.get("collection_mod") or sess.get("mod") or "").split(BM.STAGED_SEP)[0]
        say(5, f"Starting {game['title']}" + (f" ({mod})" if mod else "") + f" on {w['name']}")
        new = _run_job("launch_game", {"game": game, "mod": mod}, actor, worker=wid, wait=900,
                       progress=lambda pct, msg: say(5 + pct * .7, msg))
        nsid = new["session_id"]
        store.put(LP.DISMISS_KIND, sid, {"session_id": sid, "ts": time.time(), "by": actor, "reloaded": nsid})
        out = {"session_id": nsid, "from": sid, "worker": w["name"], "mod": mod, "moment_loaded": False}
        if art:
            say(80, "Loading your last moment")
            time.sleep(6)                                         # let the game boot before loading a state
            try:
                r = (_run_job("state_transfer", {"session_id": nsid, "op": "import", "artifact": art}, actor, worker=wid,
                              wait=120) or {}).get("result") or {}
                out |= {"moment_loaded": r.get("loaded") is True, "load_verified": r.get("load_verified")}
            except HTTPException as e:
                out["notes"] = [f"The game is running, but your moment could not be loaded ({e.detail}). It is kept: {art}."]
        store.audit(actor, "last_played.reload", sid, {"new": nsid, "moment": bool(art)})
        return out

    @app.post("/api/last_played/reload")
    def last_played_reload(r: LastPlayedReloadIn, actor=Depends(auth)):
        """Reload the ended game as an in-server job (output.session_id = the new session)."""
        store.get("session", r.session_id) or _404()
        with store.lock:
            for existing in store.all('job'):
                if (existing.get('tool') == 'session_reload' and existing.get('state') in ('queued', 'running')
                        and (existing.get('input') or {}).get('session_id') == r.session_id):
                    return Job.model_validate(existing)
            job = Job(tool="session_reload", input={"session_id": r.session_id, "moment": r.moment},
                      state=JobState.RUNNING, started=time.time())
            store.put("job", job.id, job.model_dump())
            _server_job_threads.add(job.id)

        def prog(pct, msg):
            with store.lock:
                j = store.get("job", job.id)
                j["progress"] = {"pct": round(float(pct), 1), "msg": msg, "ts": time.time()}
                store.put("job", job.id, j)

        def go():
            try:
                out, state, err = session_reload(r.session_id, actor, r.moment, prog), JobState.SUCCEEDED, None
            except HTTPException as e:
                out, state, err = None, JobState.FAILED, str(e.detail)
            except Exception as e:                             # noqa: BLE001
                out, state, err = None, JobState.FAILED, f"{type(e).__name__}: {e}"
            with store.lock:
                store.put("job", job.id, store.get("job", job.id) | {"state": state, "finished": time.time(), "output": out,
                                                                     "error": err})
                _server_job_threads.discard(job.id)
        threading.Thread(target=go, daemon=True).start()
        return job

    @app.post("/api/sessions/{sid}/moment")
    def session_moment(sid: str, wait: float = 6.0, actor=Depends(auth)):
        """Save the running game's moment now and keep it as the session's last-played checkpoint (the desktop app calls
        this for its games just before it quits; best effort within `wait` seconds)."""
        s_ = store.get("session", sid) or _404()
        if s_.get("state") != "running":
            return {"saved": False, "reason": "not running"}
        try:
            art = _run_job("state_transfer", {"session_id": sid, "op": "export"}, actor, worker=sid.split("-")[0],
                           wait=max(1.0, min(float(wait), 30.0)))["result"]["artifact"]
        except (HTTPException, KeyError, TypeError) as e:
            return {"saved": False, "reason": str(getattr(e, "detail", e))[:300]}
        store.put("session", sid, (store.get("session", sid) or {}) | {"checkpoint": art, "moment_ts": time.time()})
        return {"saved": True, "artifact": art}

    class MoveIn(BaseModel):
        to: str = "windows"                 # a worker name (this PC) | windows | linux (the Spark)

    @app.post("/api/sessions/{sid}/move")
    def session_move(sid: str, m: MoveIn, actor=Depends(auth)):
        """Move a running game to another machine: save state -> launch the same game (+ mod) there -> load it -> stop the
        old one. Pass this PC's worker name to pull a game here from the Spark or from another PC."""
        sess = store.get("session", sid) or _404()
        if _swap_target(sid.split("-")[0], m.to)["id"] == _wid(sid.split("-")[0]):
            return {"session_id": sid, "from": sid, "note": "already running there"}
        return session_swap(sid, sess.get("mod") or "", m.to, actor)

    @app.get("/api/gamedata/{name}")
    def gamedata(name: str, actor=Depends(auth)):
        """Per-game catalogs the game tools publish (profiles/gamedata/<name>.json, e.g. ac1-parts): the Ctrl+click
        editor's pick lists (weapons, parts, items)."""
        import re as _re
        if not _re.fullmatch(r"[a-z0-9_.-]{1,64}", name):
            raise HTTPException(400, "bad name")
        f = WEB.parent.parent.parent / "profiles" / "gamedata" / f"{name}.json"
        if not f.is_file():
            raise HTTPException(404, "no such catalog")
        return json.loads(f.read_text(encoding="utf-8"))

    @app.get("/api/recipes")
    def recipe_list(actor=Depends(auth)):
        return store.all("recipe")

    @app.get("/api/games/{gid}/workbench")
    def workbench(gid: str, actor=Depends(auth)):
        """Everything the conversations made for this game: live controls (sliders / toggles) and bookmarks (requests that
        changed the game, with save states before and after)."""
        controls, bookmarks = [], []
        for c in store.all("chat"):
            if gid not in [g["game_id"] for g in c.get("games") or []]:
                continue
            for e in c["events"]:
                if e.get("type") == "cards" and e.get("kind") == "controls":
                    for it in e.get("items", []):
                        controls.append({**it, "chat": c["id"], "ts": e.get("ts")})
                elif e.get("type") == "bookmark":
                    bookmarks.append({**e, "chat": c["id"]})
        seen, uniq = set(), []
        for it in sorted(controls, key=lambda x: x.get("ts") or 0, reverse=True):   # newest version of each control
            k = (it.get("label"), it.get("tool"))
            if k not in seen:
                seen.add(k)
                uniq.append(it)
        mods = sorted((m for m in store.all("mod") if m["game_id"] == gid), key=lambda m: -m.get("ts", 0))
        mods = [_mod_picture(m) for m in mods]
        return {"controls": uniq, "bookmarks": sorted(bookmarks, key=lambda b: b.get("ts") or 0, reverse=True), "mods": mods}

    previews = config.data_dir / "previews"

    @app.get("/api/preview")
    def preview(url: str, actor=Depends(auth)):
        """Thumbnail for a link card: the page's og:image (or the URL itself when it is an image), cached on disk."""
        import hashlib, html, ipaddress, re, socket
        from urllib.parse import urljoin, urlparse
        f = previews / (hashlib.sha256(url.encode()).hexdigest()[:32] + ".img")
        if not f.exists():
            def public(u):
                h = urlparse(u)
                if h.scheme not in ("http", "https") or not h.hostname:
                    return False
                try:
                    return all(ipaddress.ip_address(a[4][0]).is_global for a in socket.getaddrinfo(h.hostname, None))
                except (OSError, ValueError):
                    return False
            hdr = {"user-agent": "Mozilla/5.0 gBox"}
            try:
                if not public(url):
                    raise HTTPException(400, "not a public URL")
                r = httpx.get(url, timeout=10, headers=hdr)          # no redirects: each hop would need the same check
                img = r.content if r.headers.get("content-type", "").startswith("image/") else None
                if img is None:
                    m = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]*content=["\']([^"\']+)', r.text[:300000], re.I)
                    src = m and urljoin(url, html.unescape(m.group(1)))
                    if not src or not public(src):
                        raise HTTPException(404, "no preview image")
                    ri = httpx.get(src, timeout=10, headers=hdr)
                    if not ri.headers.get("content-type", "").startswith("image/"):
                        raise HTTPException(404, "no preview image")
                    img = ri.content
                previews.mkdir(parents=True, exist_ok=True)
                f.write_bytes(img[:8_000_000])
            except httpx.HTTPError:
                raise HTTPException(404, "preview unavailable")
        head = f.open("rb").read(16)
        mt = ("image/png" if head.startswith(b"\x89PNG") else "image/gif" if head.startswith(b"GIF") else
              "image/webp" if head[8:12] == b"WEBP" else "image/svg+xml" if head.lstrip().startswith(b"<") else "image/jpeg")
        return FileResponse(f, media_type=mt, headers={"cache-control": "max-age=604800"})

    @app.get("/viz/{path:path}")
    def viz(path: str):
        """Visualizer modules (clients/web/viz): static, no secrets, served like the shell."""
        root = (WEB.parent / "viz").resolve()
        f = (root / path).resolve()
        if root not in f.parents or not f.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(f, headers={"cache-control": "no-cache"})

    @app.get("/live-poll.js")
    def live_poll_js():
        """The shared cached polling helper (clients/desktop/live-poll.js, #712) for the web client: static, no secrets."""
        return FileResponse(WEB.parent.parent / "desktop" / "live-poll.js", media_type="text/javascript",
                            headers={"cache-control": "no-cache"})

    @app.get("/brand/{name}")
    def brand(name: str):
        """Public brand assets (logo/icons); no token so favicons and <img> work everywhere."""
        f = (BRAND / name).resolve()
        if not f.is_relative_to(BRAND.resolve()) or not f.is_file() or f.suffix not in (".svg", ".png", ".ico"):
            _404()
        return FileResponse(f, headers={"cache-control": "max-age=86400"})

    @app.get("/favicon.ico")
    def favicon():
        return FileResponse(BRAND / "gbox.ico")

    @app.get("/api/health")
    def health():
        return {"ok": True, "time": time.time()}

    # --- tools & workers ---
    def workers() -> list[dict]:
        now = time.time()
        from . import background_testing
        ex = background_testing.excluded(store)
        return [w | {"online": now - w["last_seen"] < WORKER_TTL, "background_testing": background_testing.allowed(w, ex),
                     "admission": {'allowed': (reason := background_testing.guarded_reason(store, w)) is None, 'reason': reason}}
                for w in store.all("worker")]

    @app.get("/api/tools")
    def list_tools(actor=Depends(auth)):
        ws = [w for w in workers() if w["online"]]
        return [t.info().model_dump() | {
            "granted": all(p in config.granted_permissions for p in t.permissions),
            "workers": [w["name"] for w in ws if t.name in w["tools"]],
            "unavailable": {w["name"]: w["unavailable"][t.name] for w in ws if t.name in w["unavailable"]},
        } for t in REGISTRY.values()]

    ghidra_cache: dict = {}

    def _ghidra_scripts() -> dict:
        """Every script shipped with the installed Ghidra (+ gBox's own), with @category and description."""
        from . import provision
        home = provision.ghidra_home(config)
        if not home or not home.exists():
            return {"home": None, "scripts": []}
        if ghidra_cache.get("home") == str(home):
            return ghidra_cache
        out = []
        dirs = [*home.glob("Ghidra/*/*/ghidra_scripts"), WEB.parent.parent.parent / "adapters" / "ghidra"]
        for d in dirs:
            for f in sorted(list(d.glob("*.java")) + list(d.glob("*.py"))):
                try:
                    head = f.read_text(errors="replace")[:3000]
                except OSError:
                    continue
                cat = next((ln.split("@category", 1)[1].strip() for ln in head.splitlines() if "@category" in ln), "")
                desc = []
                for ln in head.splitlines():
                    t = ln.strip().lstrip("/#*").strip()
                    if t.startswith("@") or ln.strip().startswith(("import", "package", "public", "class", "from ")):
                        if desc:
                            break
                        continue
                    lic = ("IP:", "Licensed", "You may", "you may", "http", "Unless", "distributed", "WITHOUT", "See the",
                           "limitations", "Copyright", "#", "NOTE:", "!")
                    if t and not t.startswith(lic) and "License" not in t:
                        desc.append(t)
                    if len(" ".join(desc)) > 300:
                        break
                out.append({"name": f.name, "language": "java" if f.suffix == ".java" else "python", "category": cat,
                            "module": d.parent.name if d.name == "ghidra_scripts" else "gBox",
                            "description": " ".join(desc)[:400], "path": str(f)})
        ghidra_cache.clear()
        ghidra_cache.update({"home": str(home), "version": home.name, "scripts": out})
        return ghidra_cache

    @app.get("/api/registry")
    def registry(actor=Depends(auth)):
        """Everything an LLM orchestrator can dispatch: typed tools, agent roles, and every Ghidra script."""
        from .tools import AGENTS
        ws = [w for w in workers() if w["online"]]
        tools_ = [t.info().model_dump(mode="json") | {
            "kind": "tool", "workers": [w["name"] for w in ws if t.name in w["tools"]],
            "unavailable": {w["name"]: w["unavailable"][t.name] for w in ws if t.name in w["unavailable"]},
            "granted": all(p in config.granted_permissions for p in t.permissions)} for t in REGISTRY.values()]
        return {"tools": tools_, "agents": AGENTS, "ghidra": _ghidra_scripts()}

    @app.get("/api/workers")
    def list_workers(actor=Depends(auth)):
        # running_jobs is the Spark's own count. A worker reporting busy slots with none running here
        # has leaked them and will never claim the queued launch (#1294); the loader says so.
        running = store.running_job_counts()
        # local_builds (a PC's own build list, for GET /api/builds) stays out of this often-polled answer
        return [{k: v for k, v in w.items() if k != "local_builds"} | {"running_jobs": running.get(w["id"], 0)}
                for w in workers()]

    def idle_worker(tool: str = "launch_game") -> dict:
        """Choose the other Windows PC, using recent user input and live-game ownership."""
        online = [w for w in workers() if w["online"] and w["os"] == "windows"]
        capable = [w for w in online if tool in (w.get("tools") or []) and w.get("background_testing", True)]
        if len(online) < 2 or not capable:
            if online and not any(w.get("background_testing", True) for w in online):
                raise HTTPException(409, "No PC is marked available for background testing (right-click the Tasks icon)")
            raise HTTPException(409, "Two online Windows workers and the requested tool are needed for other-PC testing")
        running = [s for s in store.all("session") if s.get("state") == "running"]
        newest = max(running, key=lambda s: s.get("started") or 0, default={})
        game_owner = (newest.get("session_id") or "").split("-")[0]
        # A recently interactive PC is the operator's; when input telemetry is not yet available,
        # the PC owning the most recent live game is the best known operator workstation.
        reported = [w for w in online if w.get("idle_seconds") is not None and not w.get("active_jobs")]
        active = min(reported, key=lambda w: w["idle_seconds"])["id"] if reported else game_owner
        if reported and all(w["idle_seconds"] >= 60 for w in reported) and game_owner:
            active = game_owner
        candidates = [w for w in capable if w["id"] != active]
        if not candidates:
            raise HTTPException(409, "The requested tool is available only on the computer in use")
        candidates.sort(key=lambda w: (w.get("idle_seconds") if w.get("idle_seconds") is not None else
                                       (0 if w["id"] == game_owner else 3600), -w.get("active_jobs", 0)), reverse=True)
        chosen = candidates[0]
        if chosen.get("idle_seconds") is not None and chosen["idle_seconds"] < 30 and not chosen.get("active_jobs"):
            raise HTTPException(409, "The other computer has recent user input; waiting for it to become idle")
        return chosen | {"operator_worker_id": active, "selection": "other Windows PC"}

    @app.get("/api/workers/idle")
    def get_idle_worker(tool: str = "launch_game", actor=Depends(auth)):
        return idle_worker(tool)

    # --- which PCs background testing may use (#1383): ticked in the Tasks icon menu, keyed by worker name ---
    class TestingIn(BaseModel):
        available: bool | None = None
        budget_percent: int | None = Field(default=None, ge=10, le=90)

    @app.get("/api/testing/workers")
    def testing_workers(actor=Depends(auth)):
        from . import background_testing
        ex = background_testing.excluded(store)
        rows = []
        for w in workers():
            policy = background_testing.policy(store, w['name'])
            reason = background_testing.guarded_reason(store, w)
            if not w.get('online'):
                reason = 'Worker is offline; queued work is preserved.'
            rows.append({k: w.get(k) for k in ('id','name','os','online','background_testing','resources',
                                               'idle_seconds','active_jobs')} | policy |
                        {'admission': {'allowed': reason is None, 'reason': reason},
                         'budget_kind': 'admission', 'hard_throttle': False})
        return {'excluded': sorted(ex), 'workers': rows}

    @app.post("/api/testing/workers/{wid}")
    def testing_worker_set(wid: str, body: TestingIn, actor=Depends(auth)):
        from . import background_testing
        w = store.get("worker", _wid(wid)) or next((x for x in workers() if x.get("name") == wid), None) or _404()
        if body.available is None and body.budget_percent is None:
            raise HTTPException(422, 'Choose availability or a resource budget.')
        with store.lock:
            if body.available is not None:
                background_testing.set_available(store, w["name"], body.available)
            if body.budget_percent is not None:
                setting = store.get('setting', background_testing.SETTING) or {}
                policies = dict(setting.get('policies') or {})
                policies[w['name']] = {'budget_percent': body.budget_percent}
                store.put('setting', background_testing.SETTING, setting | {'policies': policies})
        store.audit(actor, "worker.background_testing", w["id"], body.model_dump(exclude_none=True) | {'name': w['name']})
        return testing_workers(actor)

    background_coordinator_cache = {'at': 0, 'runs': []}
    background_coordinator_lock = threading.Lock()

    @app.get('/api/background/workers/{wid}/status')
    def background_worker_status(wid: str, actor=Depends(auth)):
        from .background_status import snapshot
        w = store.get('worker', _wid(wid)) or next((x for x in workers() if x.get('name') == wid), None) or _404()
        now = time.time()
        # Reading the coordinator must not enqueue inventory or create work.
        # Cache across workstation displays; do not scan transcripts every poll.
        with background_coordinator_lock:
            if now - background_coordinator_cache['at'] >= 10:
                from .hermes_tasks import list_runs
                runs = list_runs(limit=3)
                background_coordinator_cache.update(at=now, runs=[
                    {k: run.get(k) for k in ('id','name','state','progress','started','finished','request_id')}
                    for run in runs])
            coordinator = {'host': 'control plane', 'runs': background_coordinator_cache['runs'],
                           'sampled_at': background_coordinator_cache['at']}
        return snapshot(store, w, online=now-w.get('last_seen',0) < WORKER_TTL) | {'coordinator': coordinator}

    class WorkerActivity(BaseModel):
        idle_seconds: float | None = None
        active_jobs: int = 0

    desktop_frames: dict[str, dict] = {}
    desktop_watch: dict[str, float] = {}
    desktop_condition = threading.Condition()

    @app.get("/api/workers/{wid}/desktop/watch")
    def desktop_watch_state(wid: str, actor=Depends(auth)):
        return {"watch": time.time() < desktop_watch.get(_wid(wid), 0)}

    @app.get("/api/workers/{wid}/desktop/status")
    def desktop_status(wid: str, actor=Depends(auth)):
        wid = _wid(wid)
        frame = desktop_frames.get(wid) or {}
        return {"watching": time.time() < desktop_watch.get(wid, 0),
                "last_frame_age": round(time.time() - frame["ts"], 1) if frame else None,
                "frames": frame.get("seq", 0), "app_available": frame.get("app_rect") is not None}

    @app.post("/api/workers/{wid}/desktop/frame")
    async def desktop_frame_upload(wid: str, request: Request, actor=Depends(auth)):
        wid = _wid(wid)
        if not store.get("worker", wid):
            raise HTTPException(404, "worker not found")
        image = await request.body()
        if not image.startswith(b"\xff\xd8") or not image.endswith(b"\xff\xd9") or len(image) > 8_000_000:
            raise HTTPException(422, "expected a JPEG frame under 8 MB")
        try:
            app_rect = tuple(float(v) for v in request.headers.get("x-gbox-app-rect", "").split(","))
            if len(app_rect) != 4 or not all(0 <= v <= 1 for v in app_rect):
                app_rect = None
        except ValueError:
            app_rect = None
        with desktop_condition:
            prior = desktop_frames.get(wid) or {}
            desktop_frames[wid] = {"image": image, "app_rect": app_rect,
                                   "seq": prior.get("seq", 0) + 1, "ts": time.time()}
            desktop_condition.notify_all()
        return {"ok": True}

    @app.get("/api/workers/{wid}/desktop/stream")
    def desktop_stream(wid: str, view: str = "app", actor=Depends(auth)):
        wid = _wid(wid)
        if not store.get("worker", wid):
            raise HTTPException(404, "worker not found")
        if view not in ("app", "desktop"):
            raise HTTPException(422, "view must be app or desktop")
        def frames():
            from .remote_desktop import frame_for_view
            seen = 0
            while True:
                desktop_watch[wid] = time.time() + 8
                with desktop_condition:
                    desktop_condition.wait_for(lambda: (desktop_frames.get(wid) or {}).get("seq", 0) != seen, timeout=2)
                    frame = desktop_frames.get(wid) or {}
                if frame.get("seq") == seen or time.time() - frame.get("ts", 0) > 5:
                    continue
                seen = frame["seq"]
                image = frame_for_view(frame["image"], view, frame.get("app_rect"))
                if image:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + image + b"\r\n"
        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store"})

    def _wid(wid: str) -> str:
        """A worker id a client cached may belong to a worker that has since restarted (new id): follow it."""
        for _ in range(20):
            a = store.get("worker_alias", wid)
            if not a:
                break
            wid = a["to"]
        return wid

    @app.post("/api/workers/register")
    def register(w: WorkerInfo, actor=Depends(auth)):
        with store.lock:
            return _register(w, actor)

    def _register(w, actor):
        w.last_seen = time.time()
        prev = store.get("worker", w.id)
        if prev and (prev.get("tools"), prev.get("unavailable")) == (w.tools, w.unavailable):
            store.put("worker", w.id, w.model_dump())
            return {"id": w.id}
        old_ids = {o["id"] for o in store.all("worker") if o["name"] == w.name and o["id"] != w.id}
        for j in store.all("job"):                  # a restarted worker can never finish its old jobs
            if j["state"] == JobState.RUNNING and j["worker_id"] in old_ids:
                j.update(state=JobState.FAILED, finished=time.time(), error=f"worker {w.name} restarted while running")
                store.put("job", j["id"], j)
                build_notes.job_ended(j)
                store.audit(actor, "job.failed", j["id"], {"reason": "worker restarted"})
        for s_ in store.all("session"):             # ...and its emulator sessions died with it
            if s_.get("state") == "running" and s_["session_id"].split("-")[0] in old_ids:
                store.put("session", s_["session_id"], s_ | {"state": "ended", "ended": time.time(), "exit": "worker restarted"})
        for wid in old_ids:
            store.delete("worker", wid)
            store.put("worker_alias", wid, {"to": w.id, "name": w.name})
        for j in store.all("job"):                  # queued for the old id (a client that cached it): the new one takes them
            if j["state"] == JobState.QUEUED and j.get("require_worker") and _wid(j["require_worker"]) == w.id != j["require_worker"]:
                store.put("job", j["id"], j | {"require_worker": w.id})
        store.put("worker", w.id, w.model_dump())
        store.audit(actor, "worker.register", w.id, {"name": w.name, "os": w.os, "tools": w.tools, "unavailable": w.unavailable})
        return {"id": w.id}

    @app.post("/api/workers/{wid}/claim")
    def claim(wid: str, activity: WorkerActivity | None = None, actor=Depends(auth)):
        w = store.get("worker", wid)
        if not w:
            raise HTTPException(404, "unknown worker; register first")
        with store.lock:
            w["last_seen"] = time.time()
            if activity:
                w["idle_seconds"] = activity.idle_seconds
                w["active_jobs"] = activity.active_jobs
            store.put("worker", wid, w)
            # Stop goes first (#1504): a stop never waits behind queued polls or captures of the game it ends.
            # Low-priority background work (the Sonic showcase) goes last.
            for j in sorted(store.queued_jobs(), key=lambda j: (not _is_stop_job(j), bool(j.get("low_priority")))):
                if (j["state"] == JobState.QUEUED and j["tool"] in w["tools"]
                        and j["require_os"] in (None, w["os"]) and j["require_worker"] in (None, wid, w["name"])):   # by name: launched while that worker was restarting
                    try:
                        build_feedback.check(store, j)
                    except HTTPException as exc:
                        detail = exc.detail if isinstance(exc.detail,dict) else {"message":str(exc.detail)}
                        waiting = {"worker":w["name"], "reason":detail.get("message"), "code":detail.get("code")}
                        if j.get("admission_wait") != waiting:
                            store.put("job",j["id"],j | {"admission_wait":waiting})
                        continue
                    from . import background_testing
                    if background_testing.requires_admission(j):
                        reason = background_testing.guarded_reason(store, w)
                        if reason:
                            waiting = {'worker': w['name'], 'reason': reason}
                            if j.get('admission_wait') != waiting:
                                store.put('job', j['id'], j | {'admission_wait': waiting})
                            continue
                    j.pop('admission_wait', None)
                    j.update(state=JobState.RUNNING, worker_id=wid, started=time.time())
                    store.put("job", j["id"], j)
                    store.audit(actor, "job.claim", j["id"], {"worker": wid})
                    return j
        return Response(status_code=204)

    @app.post("/api/workers/{wid}/result")
    def result(wid: str, r: JobResult, actor=Depends(auth)):
        # Admission, cancellation, acceptance callbacks and duplicate delivery
        # share the Store lock. Never race two on_accept calls for one result.
        with store.lock:
            return _accept_result(wid, r, actor)

    def _result_ack(wid, job, receipt):
        return {'state': job['state'], 'receipt': receipt.id, 'accepted': True,
                'job_id': job['id'], 'worker_id': wid, 'result_sha256': job['result_sha256']}

    def _result_docs(job, receipt, *, admission=False, terminal_audit=None):
        # The result identity, pending job and provisional receipt become durable
        # together. Callback completion is a separate explicit durable phase.
        try:
            store.db.execute('BEGIN IMMEDIATE')
            if admission:
                changed = store.db.execute("UPDATE docs SET body=? WHERE kind='job' AND id=? "
                    "AND json_extract(body,'$.state')='running' AND json_extract(body,'$.worker_id')=? "
                    "AND coalesce(json_extract(body,'$.cancel'),0)=0",
                    (json.dumps(job), job['id'], job['worker_id'])).rowcount
                if changed != 1:
                    raise HTTPException(409, 'job result admission changed; result not accepted')
            else:
                changed = store.db.execute("UPDATE docs SET body=? WHERE kind='job' AND id=? "
                    "AND json_extract(body,'$.result_sha256')=? "
                    "AND json_extract(body,'$.result_acceptance')='pending' "
                    "AND json_extract(body,'$.worker_id')=? AND json_extract(body,'$.state')=?",
                    (json.dumps(job), job['id'], job['result_sha256'], job['worker_id'], JobState.RUNNING)).rowcount
                if changed != 1:
                    raise HTTPException(409, 'result completion changed; result not acknowledged')
            if terminal_audit is not None:
                actor, data = terminal_audit
                action, subject, ts = f"job.{job['state']}", job['id'], time.time()
                previous = store.db.execute('SELECT hash FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
                prev = previous[0] if previous else '0' * 64
                digest = sha256(prev.encode() + canon({'ts': ts, 'actor': actor, 'action': action,
                                                       'subject': subject, 'data': data}))
                receipt.audit_seq = store.db.execute('INSERT INTO audit(ts,actor,action,subject,data,prev,hash) '
                    'VALUES(?,?,?,?,?,?,?)', (ts, actor, action, subject, json.dumps(data), prev, digest)).lastrowid
            store.db.execute('INSERT OR REPLACE INTO docs(kind,id,body) VALUES(?,?,?)',
                             ('receipt', receipt.id, receipt.model_dump_json()))
            store.db.commit()
        except BaseException:
            store.db.rollback()
            raise

    def _accept_result(wid: str, r: JobResult, actor):
        j = store.get("job", r.job_id)
        if not j or j.get("worker_id") != wid:
            raise HTTPException(409, "job not running on this worker")
        identity = result_digest(r.model_dump())
        if j.get('cancel') and j['state'] == JobState.RUNNING and not j.get('result_sha256'):
            # Cancel asks a running tool to stop; the worker's answer (usually "cancelled by the
            # operator") is the job's outcome. Refusing it left the PC offline at its next start.
            j = {k: v for k, v in j.items() if k != 'cancel'} | {'cancel_requested': True}
            store.put("job", j["id"], j)
        t = REGISTRY[j["tool"]]
        recovering = bool(j.get('result_sha256')) or j['state'] != JobState.RUNNING
        if recovering:
            saved = store.get('receipt', j.get('receipt_id') or '')
            if not j.get('result_sha256'):
                try:
                    from .legacy_results import verify_legacy_success
                    # Bind verified historical bytes; never replay a callback.
                    try:
                        store.db.execute('BEGIN IMMEDIATE')
                        j = store.get('job', r.job_id)
                        saved = store.get('receipt', (j or {}).get('receipt_id') or '')
                        t = REGISTRY.get((j or {}).get('tool'))
                        if not t or (t.on_accept and t.on_accept is not _builtin._launch_accept):
                            raise HTTPException(409, 'legacy callback completion needs review')
                        try:
                            receipt = Receipt.model_validate(saved)
                            verify_legacy_success(store, j, saved, r.model_dump(), wid)
                        except (ValueError, TypeError, KeyError, AttributeError):
                            raise HTTPException(409, 'legacy completion evidence does not verify this result')
                        j.update(result_sha256=identity, result_acceptance='complete', result_state=j['state'])
                        changed = store.db.execute("UPDATE docs SET body=? WHERE kind='job' AND id=? "
                            "AND json_extract(body,'$.state')='succeeded' "
                            "AND json_extract(body,'$.worker_id')=? "
                            "AND json_extract(body,'$.result_sha256') IS NULL "
                            "AND coalesce(json_extract(body,'$.cancel'),0)=0",
                            (json.dumps(j), j['id'], wid)).rowcount
                        if changed != 1:
                            raise HTTPException(409, 'legacy result reconciliation changed')
                        previous = store.db.execute('SELECT hash FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
                        prev, ts = previous[0] if previous else '0' * 64, time.time()
                        data = {'receipt': saved['id'], 'result_sha256': identity,
                                'original_audit_seq': saved['audit_seq'], 'callbacks_replayed': False}
                        digest = sha256(prev.encode() + canon({'ts': ts, 'actor': actor,
                            'action': 'job.result_reconciled', 'subject': j['id'], 'data': data}))
                        store.db.execute('INSERT INTO audit(ts,actor,action,subject,data,prev,hash) VALUES(?,?,?,?,?,?,?)',
                            (ts, actor, 'job.result_reconciled', j['id'], json.dumps(data), prev, digest))
                        store.db.commit()
                    except BaseException:
                        store.db.rollback()
                        raise
                    return _result_ack(wid, j, receipt)
                except HTTPException:
                    # The job ended without this result (retired, cancelled, timed out, or finished
                    # before results were fingerprinted). Keep the bytes and settle the delivery.
                    return _settle_late_result(wid, r, j, identity, actor)
            if (j.get('result_sha256') != identity or not saved
                    or saved.get('worker_id') != wid or saved.get('job_id') != r.job_id):
                raise HTTPException(409, 'finished job does not verify this exact worker result')
            receipt = Receipt.model_validate(saved)
            if j.get('result_acceptance') == 'complete':
                return _result_ack(wid, j, receipt)
            # Known local callbacks can resume after an interrupted admission.
            # Unknown callbacks need review; a terminal job alone is not an ACK.
            state = j.get('result_state')
            callback = t.on_accept if state == JobState.SUCCEEDED else t.on_fail
            safe = {_builtin._launch_accept, _builtin._hash_accept, _builtin._session_accept, _builtin._launch_fail}
            if (j.get('result_acceptance') != 'pending' or j['state'] != JobState.RUNNING
                    or state not in {JobState.SUCCEEDED, JobState.FAILED, JobState.INVALID}
                    or receipt.tool_version != t.version
                    or (callback and callback not in safe)):
                raise HTTPException(409, 'result acceptance was interrupted; callback recovery needs review')
            out = t.Out.model_validate(r.output) if state == JobState.SUCCEEDED else None
            refs, problems = receipt.artifacts, receipt.validation_problems
        else:
            receipt, out, state, refs, problems = _admit_result(wid, r, j, t, identity)
        try:
            if state == JobState.SUCCEEDED and t.on_accept:
                t.on_accept(store, out, actor)
            elif state != JobState.SUCCEEDED and t.on_fail:
                t.on_fail(store, j, actor)
        except BaseException:
            # Admission is already durable. Discard any uncommitted callback
            # transaction so the same result can safely resume known callbacks.
            store.db.rollback()
            raise
        if state == JobState.SUCCEEDED and (t.name in asset_library.ASSET_TOOLS or t.name == 'blender_copy'):
            app.state.assets.invalidate()
        j['result_acceptance'] = 'complete'
        j.update(state=state, finished=receipt.finished)
        j.pop('result_state', None)
        _result_docs(j, receipt, terminal_audit=(actor, {
            "receipt": receipt.id, "artifacts": [a.sha256 for a in refs], "problems": problems, "error": r.error}))
        _result_followups(j, r, t, state, actor)
        return _result_ack(wid, j, receipt)

    def _settle_late_result(wid, r, j, identity, actor):
        """Settle a result for a job that already ended without it: no state change, no callback.

        The worker's exact bytes are stored as evidence and audited, and the worker gets a
        verifiable acknowledgement so it can release them. Answering 409 instead marked the
        result refused, and a refused result holds the worker offline at every start.
        """
        key = f"{j['id']}.{identity}"
        doc = store.get('late_result', key)
        if not doc:
            ref = store.put_artifact(canon(r.model_dump()), 'late-result.json', 'application/json',
                                     {'job': j['id'], 'worker': wid, 'result_sha256': identity})
            doc = {'job_id': j['id'], 'worker_id': wid, 'result_sha256': identity, 'evidence': ref.sha256,
                   'job_state': j['state'], 'job_error': j.get('error'), 'ok': r.ok, 'ts': time.time()}
            store.put('late_result', key, doc)
            store.audit(actor, 'job.late_result', j['id'], {k: doc[k] for k in ('evidence', 'result_sha256', 'job_state', 'ok')})
        state = j['state'] if j['state'] in (JobState.SUCCEEDED, JobState.FAILED, JobState.INVALID) else JobState.FAILED
        return {'state': state, 'receipt': 'late-' + doc['evidence'][:32], 'accepted': True, 'late': True,
                'job_id': j['id'], 'worker_id': wid, 'result_sha256': identity}

    def _admit_result(wid, r, j, t, identity):
        refs, blobs = [], {}
        for a in r.artifacts:
            data = base64.b64decode(a.b64)
            prov = a.provenance | {"tool": t.name, "tool_version": t.version, "job": j["id"], "worker": wid}
            refs.append(store.put_artifact(data, a.name, a.media_type, prov))
            blobs[a.name] = data
        problems, out = [], None
        if r.ok:
            try:                                     # independent validation on the control plane
                out = t.Out.model_validate(r.output)
                problems = t.validate(out, blobs) if t.validate else []
            except Exception as e:
                problems = [f"output failed schema validation: {e}"]
        state = JobState.FAILED if not r.ok else (JobState.INVALID if problems else JobState.SUCCEEDED)
        receipt = Receipt(job_id=j["id"], tool=t.name, tool_version=t.version, worker_id=wid,
                          input_sha256=sha256(canon(j["input"])),
                          output_sha256=sha256(canon(r.output)) if r.output is not None else None,
                          artifacts=refs, started=j["started"], finished=time.time(),
                          validation_ok=state == JobState.SUCCEEDED, validation_problems=problems)
        if r.log:
            j["log_sha"] = store.put_artifact("\n".join(r.log).encode(), "worker.log", "text/plain", {"job": j["id"]}).sha256
        j.update(state=JobState.RUNNING, result_state=state, output=r.output,
                 error=r.error or ("; ".join(problems) or None), receipt_id=receipt.id,
                 result_sha256=identity, result_acceptance='pending')
        _result_docs(j, receipt, admission=True)
        return receipt, out, state, refs, problems

    def _result_followups(j, r, t, state, actor):
        build_notes.job_ended(j)                      # a finished build / collect / failed build -> the bell tray
        attempt = j.get("input") or {}
        op = attempt.get("op") or ""
        if t.name == "launch_game" and state != JobState.SUCCEEDED:
            # a failed launch (modded or stock) files / updates its launch failure report (gbox/launch_failures.py);
            # it is no longer also an "Auto report: launch_game failed" mod report
            _lf_observe_later(j["id"])
        mod_attempt = ((t.name == "characters" and op in ("use", "live_use", "swap"))
                       or (t.name == "mod" and op == "apply")
                       or (t.name == "file_mod" and op == "build")
                       or (t.name.endswith("_mods") and op in ("apply", "build", "use", "enable", "swap")))
        if mod_attempt:
            outcome = (r.output or {}).get("result") or {}
            status = str(outcome.get("status") or "") if isinstance(outcome, dict) else ""
            failed_swap = (state != JobState.SUCCEEDED or status.startswith(("unsupported", "failed", "error"))
                           or status in ("not_in_collection", "overlay", "missing", "blocked", "reverted") or (isinstance(outcome, dict) and
                            (outcome.get("ok") is False or bool(outcome.get("error")))))
            gap_request = (outcome.get("request") or {}).get("id") if isinstance(outcome, dict) else None
            if failed_swap and not j.get("parent_request_id") and not gap_request:
                def _report_failed_swap():
                    try:
                        i = j.get("input") or {}
                        req_auto_mod_failure(AutoFailureIn(session_id=i.get("session_id") or "", game=i.get("game") or "",
                            model=i.get("character") or i.get("name") or "", action=f"{t.name} {i.get('op') or ''}".strip(),
                            target=i.get("slot") or "", character=i.get("character") or "",
                            x=i.get('x'), y=i.get('y'), moment=f"x={i.get('x')}, y={i.get('y')}",
                            detail=j.get("error") or (outcome.get("message") if isinstance(outcome, dict) else "") or status,
                            job_id=j["id"]), "gbox-auto")
                    except Exception as exc:
                        store.audit("gbox-auto", "request.auto_mod_failure.error", j["id"], {"error": str(exc)[:500]})
                threading.Thread(target=_report_failed_swap, daemon=True).start()
        if state == JobState.SUCCEEDED and t.name == 'launch_game':
            try:
                auto_collection.after_launch(j, r.output or {},
                    lambda request: submit(JobRequest(**request), actor).model_dump(mode='json'))
            except Exception as exc:
                # Extraction scheduling must never turn a successful gameplay launch into a worker retry.
                store.audit(actor, 'characters.auto_collect_failed', j['id'], {'error': str(exc)})

    # --- jobs ---
    def _automated(actor: str, origin) -> bool:
        """A request background automation made: an agent actor (not the in-app chat agent, which speaks for the
        operator), or a worker tool running inside such an agent's job (x-gbox-parent-job). Operator clicks are not."""
        if actor == "gbox-agent":
            return False
        if operator_guard.is_agent(actor):
            return True
        parent = store.get("job", (origin or {}).get("parent_job") or "") if isinstance(origin, dict) else None
        if parent:
            return bool(parent.get("agent_use")) and parent.get("actor") != "gbox-agent"
        return False

    def _operator_busy(wid: str, keep: str = "") -> list[dict]:
        """The operator's running sessions on one worker (not agent-owned test sessions)."""
        return operator_guard.operator_sessions(store.all("session"), lambda sid: store.get("slabel", sid),
                                                lambda jid: store.get("job", jid), [wid], keep=keep)

    def reject_broken_launch(gid, mod, actor, agent_use=False):
        if not mod or agent_use or operator_guard.is_agent(actor): return
        name = mod.split('~')[0]
        flag = store.get('build_broken', f'{gid}/{name}')
        if not flag or flag.get('state') == 'deleted': return
        index = getattr(app.state, 'built_mods', None)
        rec = next((r for r in index.records() if r['game_id'] == gid and r['name'] == name), None) if index else None
        built = ((rec or {}).get('meta') or {}).get('built')
        if built and flag.get('built') and built != flag['built']: return
        raise HTTPException(409, f'This build is marked broken; investigation #{flag.get("number") or "pending"}. Choose another build.')

    from . import build_feedback
    build_feedback.routes(app, store, auth)

    @app.post("/api/jobs")
    def submit(req: JobRequest, actor=Depends(auth), origin=Depends(request_origin)):
        build_feedback.check(store, req)
        origin = origin if isinstance(origin, dict) else {"via": "internal"}   # in-server callers pass no request
        if req.tool in ('@launch', 'launch_game'):
            i = req.input or {}
            game = i.get('game') if isinstance(i.get('game'), dict) else {}
            reject_broken_launch(i.get('game_id') or game.get('game_id'), i.get('mod'), actor, req.agent_use)
        if req.tool == "@launch":
            i = req.input or {}
            gid = i.get("game_id") or _404()
            mod, node, sid = i.get("mod") or "", i.get("node") or "", i.get("session_id") or ""
            online = {w["id"] for w in workers() if w["online"]}
            if not sid and i.get("swap", True) and node not in ("idle", "other"):
                # the game is already running: put the mod into THAT session (same PC, same moment) instead of starting
                # a second copy on whichever machine happened to build the mod
                ws = {w["id"]: w for w in workers() if w["online"]}
                run = [s for s in store.all("session") if s.get("state") == "running" and s.get("game_id") == gid
                       and _wid(s["session_id"].split("-")[0]) in online
                       # a named PC/OS: only a game running there is swapped, never one on another machine
                       and (node in ("", "auto") or node in (_wid(s["session_id"].split("-")[0]),
                            ws.get(_wid(s["session_id"].split("-")[0]), {}).get("name"),
                            ws.get(_wid(s["session_id"].split("-")[0]), {}).get("os")))]
                sid = max(run, key=lambda s: s.get("started") or 0)["session_id"] if run else ""
            if sid and (store.get("session", sid) or {}).get("state") == "running":
                return swap_job(sid, mod, "", actor, origin=origin)       # keeps the moment; automation refused there
            if node in ("", "auto", "linux", "windows"):
                # nothing running: the PC the operator plays on (newest session among online Windows workers) has the
                # real GPU and zero input lag; the node a mod was built on (often the Spark) is only a fallback
                win = {w["id"]: w for w in workers() if w["online"] and w["os"] == "windows"}
                recent = sorted((s for s in store.all("session") if _wid(s["session_id"].split("-")[0]) in win),
                                key=lambda s: -(s.get("started") or 0))
                if recent:
                    node = win[_wid(recent[0]["session_id"].split("-")[0])]["name"]
                elif win:
                    node = "windows"
            return launch(gid, node=node or "windows", mod=mod, actor=actor, origin=origin)
        t = REGISTRY.get(req.tool)
        if not t:
            raise HTTPException(404, f"unknown tool {req.tool}")
        try:
            inp = t.In.model_validate(req.input).model_dump(mode="json")
        except Exception as e:
            raise HTTPException(422, f"input invalid: {e}")
        if t.name == "evidence_capture":              # PR evidence: an in-server job driving agent test sessions
            return evidence_job(inp, actor)
        if t.name == "scene_capture":
            session = store.get("session", inp["session_id"])
            if inp.get("rebuild"):                          # replay the capture kept when the GPU ran out of memory:
                if not session:                             # the game may have ended (that frees it); runs on its worker
                    raise HTTPException(404, "Unknown game session.")
            elif not session or session.get("state") != "running":
                raise HTTPException(409, "This game session has ended. Open the running game in Sessions to examine it.")
            else:
                from . import scene_relay
                if scene_relay.wants_relay(session, inp):       # RenderDoc can't enter this session: capture its moment in a
                    return relay_job(inp, actor)                 # separate capture session; the game keeps running (#971)
        job = Job(tool=t.name, input=inp, require_os=req.require_os, require_worker=req.require_worker,
                  parent_request_id=req.parent_request_id,
                  agent_use=req.agent_use or actor in ("agent", "mcp", "gbox-agent", "hermes") or _automated(actor, origin),
                  low_priority=req.low_priority, actor=actor, origin=origin)
        if t.name == 'characters' and inp.get('op') == 'collect' and not job.parent_request_id:
            job.parent_request_id = auto_collection.policy().get('parent_request_id')
        if t.name == "characters" and inp.get("op") in ("extract", "collect", "add", "blender"):
            job.require_worker, job.require_os = None, "linux"   # they write the collection (Spark); captures go to the session's PC
        elif t.name in ("re_executable", "assimilate"):
            # Analysis output belongs on Spark; RAM is read remotely through the
            # session RPC. Pinning this to a Windows session makes Linux work unrunnable.
            # assimilate fingerprints the owned files where the library and the analysis cache live.
            job.require_worker, job.require_os = None, "linux"
        elif sid := inp.get("session_id"):          # sessions live on the worker that launched them
            job.require_worker = sid.split("-")[0]
        if job.require_worker in ("idle", "other"):
            job.require_worker = idle_worker(t.name)["id"]
        if job.require_worker:
            named = next((w["id"] for w in workers() if w["name"] == job.require_worker), None)
            if named:
                job.require_worker = named
            job.require_worker = _wid(job.require_worker)
        if t.name == "launch_game" and job.agent_use and actor != "gbox-agent" and job.state == JobState.QUEUED:
            # One emulator per PC: an automated launch where the operator is playing would save and close their game
            # (a black screen mid-match). The in-app chat agent (gbox-agent) acts on the operator's own words and is
            # exempt; MCP/Hermes/background launches go to another PC or are refused (docs/stream-stability.md).
            keep = inp.get("keep_session") or ""
            online = [w for w in workers() if w["online"] and t.name in (w.get("tools") or [])]
            if job.require_worker:
                cands = [w for w in online if w["id"] == job.require_worker] or [
                    {"id": job.require_worker, "name": (store.get("worker", job.require_worker) or {}).get("name")}]
            else:
                cands = [w for w in online if not job.require_os or w.get("os") == job.require_os]
            free, why = operator_guard.launch_block(cands, lambda wid: _operator_busy(wid, keep))
            if why:
                job.state, job.error = JobState.REJECTED, why
            elif not job.require_worker and free and len(free) < len(cands):
                job.require_worker = free[0]["id"]          # the operator's PC must not claim it
        missing = [p for p in t.permissions if p not in config.granted_permissions]
        w = store.get("worker", job.require_worker) if job.require_worker else None
        if w and job.agent_use and w.get("os") == "windows" and t.name in ("launch_game", "autoplay") \
                and "two_percent_audio" not in (w.get("features") or []):
            job.state, job.error = JobState.REJECTED, f"{w.get('name')} must update its worker before audible agent tests can enforce 2% volume"
        if w and t.name not in (w.get("tools") or []) and time.time() - w.get("last_seen", 0) < 60:
            why = (w.get("unavailable") or {}).get(t.name) or "; ".join(f"{k}: {v}" for k, v in (w.get("unavailable") or {}).items()
                                                                     if k.startswith("module ")) or "not installed there"
            job.state, job.error = JobState.REJECTED, f"{w.get('name')} can't run {t.name}: {why}"
        if missing:
            job.state, job.error = JobState.REJECTED, f"permission not granted: {missing}"
        store.put("job", job.id, job.model_dump())
        if job.state == JobState.REJECTED:
            build_notes.job_ended(job.model_dump(mode="json"))
        if t.name == "session_op" and inp.get("op") == "stop_game" and job.state == JobState.QUEUED:
            stopping[inp["session_id"]] = job.id
        if job.state == JobState.REJECTED and not job.parent_request_id and (
                (t.name == "characters" and inp.get("op") in ("use", "live_use", "swap"))
                or (t.name == "mod" and inp.get("op") == "apply")
                or (t.name == "file_mod" and inp.get("op") == "build")
                or (t.name.endswith("_mods") and inp.get("op") in ("apply", "build", "use", "enable", "swap"))):
            def _report_rejected_mod():
                try:
                    req_auto_mod_failure(AutoFailureIn(session_id=inp.get("session_id") or "", game=inp.get("game") or "",
                        model=inp.get("character") or inp.get("name") or "", action=f"{t.name} {inp.get('op')}",
                        target=inp.get("slot") or "", moment=f"x={inp.get('x')}, y={inp.get('y')}",
                        detail=job.error or "job rejected", job_id=job.id), "gbox-auto")
                except Exception as exc:
                    store.audit("gbox-auto", "request.auto_mod_failure.error", job.id, {"error": str(exc)[:500]})
            threading.Thread(target=_report_rejected_mod, daemon=True).start()
        if t.name == 'characters' and inp.get('op') == 'collect' and inp.get('game_id'):
            with auto_collection.lock:
                store.put('character_collection', inp['game_id'], {'state': job.state, 'job_id': job.id,
                           'updated': time.time(), 'session_id': inp.get('session_id')})
        store.audit(actor, "job.rejected" if missing else "job.submit", job.id, {"tool": t.name, "input": inp, "missing": missing})
        return job

    # --- the Sonic showcase (docs/sonic_showcase.md): background showcase_sonic_<title> builds, readiness for the rest ---
    from . import sonic_showcase
    sonic_showcase.routes(app, store, config, auth,
                          lambda request: submit(JobRequest(**request), "gbox-showcase").model_dump(mode="json"), workers)
    from . import special_builds                  # the game menu's "Special builds": grouped builds, launch + rebuild
    special_builds.routes(app, store, config, auth, workers=workers,
                          submit=lambda tool, inp, require_os, actor: submit(
                              JobRequest(tool=tool, input=inp, require_os=require_os), actor))
    from . import builds                          # top bar "Builds": every custom build, details, scheduled build jobs
    # ⚑ build reports go through the issue flow and then the investigation queue (both defined further down)
    builds.routes(app, store, config, auth, workers=workers, submit=lambda req, actor: submit(JobRequest(**req), actor),
                  file_report=lambda issue, details, actor: _build_report(issue, details, actor))
    from . import fit_reviews
    fit_reviews.routes(app, store, config, auth,
                       file_report=lambda issue, details, actor: _build_report(issue, details, actor))

    class Progress(BaseModel):
        pct: float
        msg: str

    @app.post("/api/jobs/{jid}/progress")
    def job_progress(jid: str, p: Progress, actor=Depends(auth)):
        with store.lock:                              # never race the result handler's final state write
            j = store.get("job", jid) or _404()
            if j["state"] != JobState.RUNNING:
                return {"ok": False, "cancel": bool(j.get("cancel"))}
            msg, event = fit_events.split(p.msg)              # a writer's fitting stage (gbox.fit_events)
            if event is not None:
                j["fitting"] = fit_events.fold(j.get("fitting"), event)
                _keep_goals(jid, j["fitting"], event)
            j["progress"] = {"pct": max(0.0, min(100.0, p.pct)), "msg": msg, "ts": time.time()}
            j["progress_log"] = (j.get("progress_log") or [])[-49:] + [msg]
            store.put("job", jid, j)
        return {"ok": True, "cancel": bool(j.get("cancel"))}

    def _keep_goals(jid: str, fitting: dict, event: dict):
        """A fit's goals (the target slot's own skeleton as the writer loaded it) for the Retarget editor's Goals
        view: the newest per (game, slot), whichever donor was fitted."""
        m = (fitting.get("models") or {}).get(str(event.get("model") or "")[:120]) or {}
        if not event.get("goals") or not m.get("goals") or not m.get("game") or not m.get("slot"):
            return
        from . import retarget_profile as RP
        store.put("retarget_goals", f"{m['game']}|{RP.slot_key(m['slot'])}",
                  m["goals"] | {"game_id": m["game"], "slot": m["slot"], "donor_slug": m.get("donor"), "job": jid,
                                "ts": time.time()})

    def _fitting_dir(jid: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", jid):
            raise HTTPException(400, "bad job id")
        return Path(config.cache) / "fitting-jobs" / jid

    @app.post("/api/jobs/{jid}/fitting/files/{name}")
    async def job_fitting_upload(jid: str, name: str, request: Request, actor=Depends(auth)):
        """A worker's fitting snapshot (GLB) or preview image for the live Fitting pop-up; served back below."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", name) or not name.lower().endswith((".glb", ".png", ".jpg", ".webp")):
            raise HTTPException(400, "bad file name")
        with store.lock:
            j = store.get("job", jid) or _404()
            if j["state"] != JobState.RUNNING:
                raise HTTPException(409, "job is not running")
        data = await request.body()
        if len(data) > 8 << 20:
            raise HTTPException(413, "fitting snapshot too large")
        d = _fitting_dir(jid)
        if not d.is_dir():                                   # a new job's snapshots: drop those older than 3 days
            import shutil
            for old in (d.parent.iterdir() if d.parent.is_dir() else []):
                try:
                    if old.is_dir() and time.time() - old.stat().st_mtime > 3 * 86400:
                        shutil.rmtree(old, ignore_errors=True)
                except OSError:
                    pass
        d.mkdir(parents=True, exist_ok=True)
        if sum(f.stat().st_size for f in d.iterdir() if f.is_file()) + len(data) > 256 << 20:
            raise HTTPException(413, "this job's fitting snapshots are over 256 MB")
        (d / name).write_bytes(data)
        return {"url": f"/api/jobs/{jid}/fitting/files/{name}"}

    @app.get("/api/jobs/{jid}/fitting/files/{name}")
    def job_fitting_file(jid: str, name: str, actor=Depends(auth)):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", name):
            _404()
        f = _fitting_dir(jid) / name
        if not f.is_file():
            _404()
        media = {".glb": "model/gltf-binary", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}
        return FileResponse(f, media_type=media.get(f.suffix.lower(), "application/octet-stream"),
                            headers={"cache-control": "max-age=86400"})

    @app.post("/api/jobs/{jid}/cancel")
    def job_cancel(jid: str, actor=Depends(auth)):
        """Queued jobs are dropped; running ones are told to stop at their next progress report (launches clean up)."""
        with store.lock:
            j = store.get("job", jid) or _404()
            if j["state"] == JobState.QUEUED:
                j.update(state=JobState.FAILED, finished=time.time(), error="cancelled by the operator")
            elif j["state"] == JobState.RUNNING:
                j["cancel"] = True
            store.put("job", jid, j)
        from .job_maintenance import is_orphaned_server_job, retire_orphaned_server_jobs
        if is_orphaned_server_job(j | {"id": jid}, _server_job_threads):
            # its thread died with an earlier server process: nothing would ever see the cancel flag (#1297)
            retire_orphaned_server_jobs(store, _server_job_threads)
            j = store.get("job", jid) or j
        store.audit(actor, "job.cancel", jid, {"state": j["state"]})
        return {"id": jid, "state": j["state"], "cancel_requested": j.get("cancel", False)}

    def retire_unrunnable_jobs(worker_snapshot=None):
        """Keep dead sessions and long-gone workers out of the visible active queue."""
        from .job_maintenance import retire_orphaned_server_jobs, retire_stalled_snapshots
        retire_stalled_snapshots(store)
        retire_orphaned_server_jobs(store, _server_job_threads)
        now = time.time()
        with store.lock:
            available = {key for w in (workers() if worker_snapshot is None else worker_snapshot)
                         if w["online"] for key in (w["id"], w["name"])}
            session_snapshot, worker_ids = {}, {}
            for job in store.queued_jobs():
                sid = (job.get("input") or {}).get("session_id")
                if sid and sid not in session_snapshot:
                    session_snapshot[sid] = store.get("session", sid)
                session = session_snapshot.get(sid)
                assigned = job.get("require_worker")
                if assigned and assigned not in worker_ids:
                    worker_ids[assigned] = _wid(assigned)
                worker_id = worker_ids.get(assigned)
                cleanup = job.get('tool') == 'session_op' and (job.get('input') or {}).get('op') == 'stop_game'
                reason = ("game session ended before the job could run" if sid and (not session or session.get("state") != "running") and not cleanup
                          else "assigned worker is no longer available" if worker_id and now - (job.get("created") or now) > 3600
                          and worker_id not in available else None)
                if not reason:
                    continue
                job.update(state=JobState.FAILED, finished=now, error=reason)
                store.put("job", job["id"], job)
                build_notes.job_ended(job)
                store.audit("scheduler", "job.failed", job["id"], {"reason": reason})

    @app.get("/api/jobs")
    def list_jobs(limit: int = 100, state: str = "", actor=Depends(auth)):
        retire_unrunnable_jobs()
        states = None
        if state:
            states = set(state.split(","))
            if not states <= {s.value for s in JobState}:
                raise HTTPException(422, "unknown job state")
        return store.jobs(states=tuple(sorted(states)) if states is not None else None, limit=limit, reverse=True)

    @app.get("/api/jobs/{jid}")
    def get_job(jid: str, actor=Depends(auth)):
        return store.get("job", jid) or _404()

    @app.get("/api/jobs/{jid}/log")
    def get_job_log(jid: str, actor=Depends(auth)):
        job = store.get("job", jid) or _404()
        data = store.read_artifact(job["log_sha"]) if job.get("log_sha") else None
        return {"log": data.decode("utf-8", "replace")[-50000:] if data else ""}

    @app.get("/api/receipts/{rid}")
    def get_receipt(rid: str, actor=Depends(auth)):
        return store.get("receipt", rid) or _404()

    @app.get("/api/artifacts/{digest}")
    def get_artifact(digest: str, actor=Depends(auth)):
        meta, data = store.get("artifact", digest), store.read_artifact(digest)
        if not meta or data is None:
            _404()
        # content-addressed (the URL is the SHA-256), so a client may keep it: the desktop inbox re-renders screenshots
        # and attachments every few seconds and re-downloaded each one without this (#712)
        return Response(data, media_type=meta["media_type"], headers={"x-gbox-provenance": json.dumps(meta["provenance"]),
                                                                      "cache-control": "private, max-age=31536000, immutable"})

    @app.post("/api/artifacts")
    async def upload_artifact(request: Request, name: str, media_type: str = "application/octet-stream",
                              provenance: str = "{}", actor=Depends(auth)):
        """Content-addressed upload (run traces, recordings, extracted assets). Provenance always records the uploader."""
        data = await request.body()
        ref = store.put_artifact(data, name, media_type, json.loads(provenance) | {"uploaded_by": actor})
        store.audit(actor, "artifact.upload", ref.sha256, {"name": name, "size": len(data)})
        return ref

    @app.get("/api/artifacts/{digest}/meta")
    def artifact_meta(digest: str, actor=Depends(auth)):
        return store.get("artifact", digest) or _404()

    # --- audit ---
    @app.get("/api/audit")
    def audit(after: int = 0, limit: int = 200, tail: int = 0, actor=Depends(auth)):
        if tail:                                           # newest N (status-bar console on first load)
            last = store.audit_log_last_seq()
            return store.audit_log(max(0, last - min(tail, 2000)), min(tail, 2000))
        return store.audit_log(after, limit)

    @app.get("/api/audit/verify")
    def audit_verify(actor=Depends(auth)):
        ok, n, bad = store.verify_audit()
        return {"ok": ok, "entries": n, "first_bad_seq": bad}

    # --- catalog, search, media ---
    @app.get("/api/catalog")
    def search_catalog(q: str = "", platform: str = "", system: str = "", library: str = "",
                       limit: int = 100, offset: int = 0, sort: str = "name", favorites: bool = False,
                       recent: bool = False, local: str = "", letter: str = "", exclude_platforms: str = "", actor=Depends(auth)):
        kw = dict(sort=sort, favorites=favorites, recent=recent, local=local, letter=letter, exclude_platforms=exclude_platforms)
        total, items = store.search(q, platform, system, library, min(limit, 500), offset, **kw)
        # build the thumbnail cache ahead of the user: this page, then the next one
        _warm([e["game_id"] for e in items])
        _, nxt = store.search(q, platform, system, library, min(limit, 500), offset + limit, **kw)
        _warm([e["game_id"] for e in nxt])
        return {"total": total, "offset": offset, "items": items}

    @app.get("/api/catalog/facets")
    def facets(actor=Depends(auth)):
        return store.facets()

    def rank_games(query: str, limit: int = 10) -> list[dict]:
        """Best matches for a spoken/typed title: exact/prefix title > all words in title > elsewhere;
        originals over hacks/prototypes/bootlegs; USA/World over other regions; playable cores first."""
        import re as _re
        q = _re.sub(r"[^a-z0-9 ]+", " ", query.lower()).strip()
        if not q:
            return []
        _, items = store.search(query, limit=400)
        words = q.split()

        def norm(t):
            return _re.sub(r"\s*[\(\[].*?[\)\]]", "", t.lower())
        def score(g):
            t, full, sysname = norm(g["title"]), g["title"].lower(), (g.get("system") or "").lower()
            tt = _re.sub(r"[^a-z0-9 ]+", " ", t).strip()
            s = 0
            if tt == q: s += 100
            elif tt.startswith(q): s += 60
            elif all(w in tt for w in words): s += 35
            if any(x in sysname or x in full for x in ("hack", "proto", "bootleg", "beta", "demo", "(unl)", "translated", "pirate")): s -= 40
            if "(usa" in full or "(world" in full: s += 12
            elif "(europe" in full: s += 6
            if g.get("core"): s += 5
            if g.get("clone_of"): s -= 8
            if (g.get("playable") or "").startswith(("verified", "launches")): s += 4
            return s - len(tt) * 0.05
        return sorted(items, key=score, reverse=True)[:limit]

    @app.get("/api/catalog/best")
    def catalog_best(q: str, limit: int = 10, actor=Depends(auth)):
        return rank_games(q, limit)

    import re as _re
    LOAD_RX = _re.compile(r"^(?:hey\s+)?(?:g[\s-]?box|gee\s?box|jibox)?[\s,.:!-]*(?:please\s+|can you\s+|could you\s+)?"
                          r"(?:load|launch|play|start|open|run|boot)(?:\s+up)?\s+(?:the\s+game\s+)?(?P<q>.+?)[\s.!?]*(?:\s+please)?[\s.!?]*$", _re.I)
    SEARCH_RX = _re.compile(r"^(?:hey\s+)?(?:g[\s-]?box|gee\s?box|jibox)?[\s,.:!-]*(?:please\s+|can you\s+)?"
                            r"(?:search|find|look\s+up|look\s+for|show(?:\s+me)?)(?:\s+for)?(?:\s+games?)?(?:\s+(?:called|named|like))?\s+(?P<q>.+?)[\s.!?]*$", _re.I)

    @app.get("/api/intent")
    def intent(text: str, actor=Depends(auth)):
        """Instant commands (typed or spoken), no LLM: 'gBox, load <game>' / 'search for <game>'. Else -> agent."""
        t = text.strip()
        if (m := LOAD_RX.match(t)) and len(m["q"]) > 1:
            best = rank_games(m["q"], 5)
            return {"action": "load", "query": m["q"], "game": best[0] if best else None,
                    "alternatives": [{k: g.get(k) for k in ("game_id", "title", "system")} for g in best[1:5]]}
        if (m := SEARCH_RX.match(t)) and len(m["q"]) > 1:
            total, _ = store.search(m["q"], limit=1)
            return {"action": "search", "query": m["q"], "total": total}
        return {"action": "agent"}

    @app.get("/api/catalog/letter_offset")
    def letter_offset(letter: str, q: str = "", platform: str = "", system: str = "", favorites: bool = False,
                      recent: bool = False, local: str = "", exclude_platforms: str = "", actor=Depends(auth)):
        n, _ = store.search(q, platform, system, "", 1, 0, favorites=favorites, recent=recent, local=local,
                            start_letter="" if letter == "#" else letter.upper()[:1], exclude_platforms=exclude_platforms)
        return {"letter": letter, "offset": n}

    @app.get("/api/catalog/platforms")
    def platforms(actor=Depends(auth)):
        return store.platform_summary()

    WHEELS = {}

    @app.get("/api/systemart/{name}")
    def system_art(name: str, actor=Depends(auth)):
        """Console/system wheel logo from the HyperSpin drive (menu-art/wheel), cached as a local PNG copy."""
        out = thumbs / "systems" / (name.replace("/", "_") + ".png")
        if not out.exists():
            src = None
            for lib in config.libraries:
                root = lib.root()
                if lib.kind == "attract" and root:
                    d = root / "menu-art" / "wheel"
                    if not WHEELS.get(str(d)):
                        try:
                            WHEELS[str(d)] = {f.lower(): f for f in os.listdir(d)}
                        except OSError:
                            WHEELS[str(d)] = {}
                    if real := WHEELS[str(d)].get(name.lower() + ".png"):
                        src = d / real
                        break
            if not src:
                _404()
            out.parent.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-vf", "scale='min(360,iw)':-2", str(out)],
                               capture_output=True, timeout=60)
            if r.returncode:
                _404()
        return FileResponse(out, media_type="image/png", headers={"cache-control": "max-age=604800"})

    @app.post("/api/catalog/{gid}/favorite")
    def favorite(gid: str, on: bool = True, actor=Depends(auth)):
        with store.lock:
            game = store.set_favorite(gid, on) or _404()  # includes unstar of a known, pruned title
            store.audit(actor, "catalog.favorite", gid, {"on": game["favorite"]})
        if on:
            try:
                auto_collection.after_favorite(game, lambda request: submit(JobRequest(**request), actor).model_dump(mode="json"))
            except Exception as exc:
                store.audit(actor, "characters.auto_collect_failed", gid, {"error": str(exc)})
        return {"game_id": gid, "favorite": on, "collection": auto_collection.status(gid)}

    @app.get("/api/favorites")
    def favorites_list(actor=Depends(auth)):
        items = store.favorites()
        return {"count": len(items), "items": items}

    @app.get("/api/catalog/{gid}")
    def catalog_entry(gid: str, actor=Depends(auth)):
        return store.catalog_get(gid) or _404()

    MEDIA_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")
    BEST = ("boxart", "snap", "wheel", "cartart")
    art_dirs: dict[str, tuple[float, dict[str, str]]] = {}     # dir -> (listed at, {lower name: real name})
    art_hits: dict[tuple[str, str], Path | None] = {}

    def _art_dir(d: Path) -> dict[str, str]:
        # one listing per art folder (SMB stat-per-candidate is too slow for a 60-card grid); refreshed every 10 min
        hit = art_dirs.get(str(d))
        if not hit or time.time() - hit[0] > 600:
            try:
                names = {n.lower(): n for n in os.listdir(d)}
            except OSError:
                names = {}
            hit = art_dirs[str(d)] = (time.time(), names)
        return hit[1]

    art_dir = config.data_dir / "art"                 # covers fetched online (#1067): art/<game_id>/<kind>.<ext> wins over the library

    def _local_art(gid: str, kind: str) -> Path | None:
        d = art_dir / gid
        if gid and d.is_dir():
            for f in sorted(d.glob(f"{kind}.*")):
                return f
        return None

    def _resolve_art(e: dict, kinds) -> Path | None:
        for kind in kinds:
            if local := _local_art(e.get("game_id") or "", kind):
                return local
        root = config.library(e["library"]).root() if e.get("library") else None
        if not root:
            return None
        for kind in kinds:
            for stem in (e.get("media") or {}).get(kind) or []:
                d, name = (root / stem).parent, Path(stem).name.lower()
                listing = _art_dir(d)
                for ext in MEDIA_EXT:
                    if real := listing.get(name + ext):
                        f = (d / real).resolve()
                        if f.is_relative_to(root.resolve()):
                            return f
        return None

    # --- persistent thumbnail cache: grows with every page viewed, survives restarts, served from local disk ---
    thumbs = config.data_dir / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    thumb_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="thumb")
    thumb_busy: set[str] = set()
    thumb_publish_lock = threading.Lock()
    MISS_TTL = 86400                                 # re-check art that was missing once a day

    def _thumb(gid: str, kind: str, w: int) -> Path | None:
        out = thumbs / gid[:2] / f"{gid}-{kind}-{w}.jpg"
        miss = out.with_suffix(".none")
        if out.exists():
            return out
        if miss.exists() and time.time() - miss.stat().st_mtime < MISS_TTL:
            return None
        e = store.catalog_get(gid)
        src = _resolve_art(e, BEST if kind == "best" else (kind,)) if e else None
        out.parent.mkdir(exist_ok=True)
        if not src:
            miss.touch()
            return None
        tmp = out.with_name(out.stem + f"-{threading.get_ident()}-{time.time_ns()}.tmp.jpg")
        r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-frames:v", "1",
                            "-vf", f"scale='min({w},iw)':-2", "-q:v", "4", str(tmp)], capture_output=True, timeout=60)
        if r.returncode or not tmp.exists():
            tmp.unlink(missing_ok=True)
            miss.touch()
            return None
        with thumb_publish_lock:
            if not out.exists():
                tmp.replace(out)
            else:
                tmp.unlink(missing_ok=True)
        return out

    def _warm(gids: list[str]):
        def warm(gid):
            try:
                _thumb(gid, "best", 360)
            finally:
                thumb_busy.discard(gid)
        for gid in gids:
            if gid not in thumb_busy and not (thumbs / gid[:2] / f"{gid}-best-360.jpg").exists():
                thumb_busy.add(gid)
                thumb_pool.submit(warm, gid)

    @app.get("/api/media/{gid}/{kind}")
    def media(gid: str, kind: str, w: int = 0, actor=Depends(auth)):
        """Library artwork. kind = boxart | snap | wheel | cartart | best (box art > snap > wheel > cart art).
        w>0 returns a cached JPEG thumbnail (generated once, then served from the local thumbnail cache)."""
        if w:
            f = _thumb(gid, kind, min(max(w, 64), 1024))
            return FileResponse(f, media_type="image/jpeg", headers={"cache-control": "max-age=604800, immutable"}) if f else _404()
        key = (gid, kind)
        if key not in art_hits:
            e = store.catalog_get(gid) or _404()
            art_hits[key] = _resolve_art(e, BEST if kind == "best" else (kind,))
        f = art_hits[key]
        return FileResponse(f, headers={"cache-control": "max-age=86400"}) if f else _404()

    class CoverIn(BaseModel):
        url: str = ""              # a picture the operator chose; empty = look it up online by platform + title
        kind: str = "boxart"       # boxart | snap | wheel

    @app.post("/api/catalog/{gid}/cover")
    def catalog_cover(gid: str, body: CoverIn, actor=Depends(auth)):
        """Attach cover art to a game (#1067): libretro-thumbnails by platform + title, or the given picture URL."""
        from . import cover_art
        e = store.catalog_get(gid) or _404()
        kind = body.kind if body.kind in cover_art.KINDS else "boxart"
        if body.url:
            try:
                data, src, tried = cover_art.fetch(body.url), body.url, []
            except Exception as exc:                  # noqa: BLE001
                raise HTTPException(400, f"could not fetch that picture: {exc}") from exc
        else:
            src, data, tried = cover_art.find(e.get("title") or "", e.get("platform") or "", kind)
            if not data:
                raise HTTPException(404, {"error": "no online cover found for this title", "title": e.get("title"),
                                          "platform": e.get("platform"), "tried": tried})
        d = art_dir / gid
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob(f"{kind}.*"):
            old.unlink()
        f = d / f"{kind}.{cover_art.image_type(data)}"
        f.write_bytes(data)
        for key in [k for k in art_hits if k[0] == gid]:
            art_hits.pop(key, None)
        for t in (thumbs / gid[:2]).glob(f"{gid}-*"):
            t.unlink(missing_ok=True)
        store.audit(actor, "catalog.cover", gid, {"kind": kind, "source": src, "bytes": len(data)})
        return {"ok": True, "kind": kind, "source": src, "bytes": len(data), "file": str(f)}

    @app.get("/api/thumbs/stats")
    def thumb_stats(actor=Depends(auth)):
        files = list(thumbs.rglob("*.jpg"))
        return {"cached": len(files), "misses": len(list(thumbs.rglob("*.none"))), "bytes": sum(f.stat().st_size for f in files),
                "queued": len(thumb_busy)}

    class StatusUpdate(BaseModel):
        playable: str
        evidence: list[str] = []          # artifact sha256s backing the status (e.g. a verified frame)

    @app.post("/api/catalog/{gid}/status")
    def set_status(gid: str, st: StatusUpdate, actor=Depends(auth)):
        store.catalog_get(gid) or _404()
        if any(store.get("artifact", d) is None for d in st.evidence):
            raise HTTPException(422, "evidence artifact missing")
        store.catalog_update(gid, playable=st.playable, playable_evidence=st.evidence)
        store.audit(actor, "catalog.status", gid, st.model_dump())
        return store.catalog_get(gid)

    @app.post("/api/games/{gid}/launch")
    def launch(gid: str, node: str = "auto", debug: bool = False, mod: str = "", swap: bool = False,
               actor=Depends(auth), origin=Depends(request_origin)):
        """Launch on the requested node; automatic PS2/PS3 play uses Windows, other cores prefer Linux.
        debug=true: on the Spark with a full-debugger emulator (Dolphin / mGBA / DuckStation / MAME) where one exists.
        With a mod and the game already running, the mod is swapped into that session (same PC, moment kept) only
        when the caller names that session's PC (worker id, name or OS) as the node or asks for it (swap=true);
        node=auto alone never turns a Play into a swap of a game running elsewhere (docs/stream-stability.md)."""
        reject_broken_launch(gid, mod, actor)
        origin = origin if isinstance(origin, dict) else {"via": "internal"}
        e = store.catalog_get(gid) or _404()
        if node in ("idle", "other"):
            if debug:
                raise HTTPException(409, "Full debugger mode currently requires the Spark; use debug=false on the other PC")
            node = idle_worker("launch_game")["name"]
        if mod and not debug:
            available = {w['id']: w for w in workers() if w['online']}
            for pending in store.all('job'):
                inp = pending.get('input') or {}
                wid = _wid((inp.get('session_id') or '').split('-')[0])
                worker = available.get(wid) or {}
            def here(wid):                                  # the caller asked for this session's PC (or swap=true)
                w = available.get(wid) or {}
                return node in (wid, w.get('name'), w.get('os')) or (swap and node == 'auto')
            for pending in store.all('job'):
                inp = pending.get('input') or {}
                wid = _wid((inp.get('session_id') or '').split('-')[0])
                if (pending.get('tool') == 'session_swap' and pending.get('state') in ('queued', 'running')
                        and inp.get('game_id') == gid and here(wid)):
                    return swap_job(inp['session_id'], mod, inp.get('to', ''), actor, origin=origin)
            running = [s for s in store.all('session') if s.get('game_id') == gid and s.get('state') == 'running'
                       and _wid(s['session_id'].split('-')[0]) in available and here(_wid(s['session_id'].split('-')[0]))]
            if running:
                current = max(running, key=lambda s: s.get('started') or 0)
                return swap_job(current['session_id'], mod, '', actor, origin=origin)   # keep_state=True
        from . import built_mods                          # the operator's name for the build: the launch bar shows it
        named = built_mods.label_of(store, gid, mod, "") if mod else ""
        req = JobRequest(tool="launch_game", input={"game": e, "debug": debug, **({"mod": mod} if mod else {}),
                                                    **({"mod_title": named} if named and named != mod else {})},
                         agent_use=actor in ("agent", "mcp", "gbox-agent", "hermes") or _automated(actor, origin))
        if debug:
            node = "linux"
        if node in ("linux", "windows"):
            req.require_os = node
        elif node != "auto":
            byname = [w for w in workers() if w["online"] and w["name"] == node]
            req.require_worker = byname[0]["id"] if byname else node
        elif e.get("platform") in ("ps2", "ps3"):
            # PS2 on the Spark uses an experimental ARM CPU backend. Keep ordinary
            # play on the Windows PC's mature recompiler and direct game display.
            req.require_os = "windows"
        elif e.get("launch", {}).get("kind") == "attract":
            from . import systems                          # the platform rule wins over a core stored at scan time
            has_core = e.get("core") and (e.get("platform") == "arcade" or systems.core_for(e.get("platform", ""))[0])
            req.require_os = "linux" if has_core else "windows"
        return submit(req, actor, origin)

    @app.get("/api/profiles/{gid}")
    def profile(gid: str, actor=Depends(auth)):
        p = store.get("profile", gid)
        if not p:
            e = store.catalog_get(gid) or _404()
            p = {"game_id": gid, "title": e["title"], "platform": e["platform"], "created": time.time(), "notes": []}
            store.put("profile", gid, p)
        return p | {"catalog": store.catalog_get(gid),
                    "knowledge": [e for e in store.all("edge") if e["game_id"] == gid],
                    "runs": [r for r in store.all("run") if r["game_id"] == gid]}

    @app.get("/api/profiles/{gid}/pick")
    def profile_pick(gid: str, actor=Depends(auth)):
        """What the pick whip learned about this game (gbox.pick_learn): struct offsets, model pointers, model
        signatures, live-replace outcomes, Ghidra findings. {} until the first pick."""
        return (store.get("profile", gid) or {}).get("pick") or {}

    @app.post("/api/profiles/{gid}/pick")
    def profile_pick_learn(gid: str, body: dict, actor=Depends(auth)):
        """Merge a pick's findings into the game's learned data (dicts merge, values replace, null deletes)."""
        from . import pick_learn
        with store.lock:
            p = store.get("profile", gid)
            if not p:
                e = store.catalog_get(gid) or _404()
                p = {"game_id": gid, "title": e["title"], "platform": e["platform"], "created": time.time(), "notes": []}
            p["pick"] = pick_learn.merge(p.get("pick") or {}, body) | {"updated": time.time()}
            store.put("profile", gid, p)
        store.audit(actor, "profile.pick", gid, {"keys": sorted(body)[:20]})
        return p["pick"]

    # --- live sessions (frames up from the worker, input down from the UI) ---
    live: dict[str, dict] = {}
    live_lock = threading.Lock()

    def _live(sid: str) -> dict:
        with live_lock:
            return live.setdefault(sid, {"frame": None, "seq": 0, "ts": 0, "input": collections.deque(maxlen=500),
                                         "cond": threading.Condition()})

    @app.get("/api/sessions")
    def sessions(actor=Depends(auth), include_ended: bool = True):
        out = []
        now = time.time()
        from . import built_mods
        names = built_mods.display_names(store)       # a session of a renamed build: mod_title (Mini window title)
        favs = built_mods.favorites(store)            # the session header's "★ Favorite this build" offer
        for s_ in store.all("session", reverse=True):
            if not include_ended and s_.get('state') != 'running':
                continue
            lv = live.get(s_["session_id"], {})
            row = s_ | {"last_frame_age": round(now - lv["ts"], 1) if lv.get("ts") else None}
            # the build folder it runs (a staged "<mod>~<build>" copy is still that build): the header renames it
            build = str(s_.get("collection_mod") or s_.get("mod") or "").split(built_mods.STAGED_SEP)[0]
            if build:
                row["mod_build"] = build
                named = names.get(f"{s_.get('game_id')}/{build}")
                if named:
                    row["mod_title"] = named
                if f"{s_.get('game_id')}/{build}" in favs:
                    row["mod_favorite"] = True
            if s_.get("state") == "running" and _stopping(s_["session_id"]):
                row["stopping"] = True              # Stop was pressed; the worker is killing the emulator (#1504)
            if s_.get("state") == "running":         # Hermes / observers keep heavy work off the operator's game
                from .background_testing import agent_owned
                row["agent_owned"] = agent_owned(store.get("slabel", s_["session_id"]),
                                                 store.get("job", s_["session_id"].split("-", 1)[-1]))
            out.append(row)
        return out

    def _stopping(sid: str) -> bool:
        """A stop job for this session is queued or running (the record turns 'ended' when the worker confirms)."""
        jid = stopping.get(sid)
        if not jid:
            return False
        if (store.get("job", jid) or {}).get("state") in (JobState.QUEUED, JobState.RUNNING):
            return True
        stopping.pop(sid, None)
        return False

    @app.get("/api/sessions/{sid}/observers")
    def session_observers(sid: str, actor=Depends(auth)):
        session = store.get('session', sid) or _404()
        runtime = store.get('setting', 'session_observers_runtime') or {}
        view = (store.get('session_observer', sid) or {'session_id': sid, 'state': 'not_attached'}) | {
            'service_online': time.time() - runtime.get('heartbeat', 0) < 30 and not runtime.get('error'),
            'service_error': runtime.get('error'), 'interval_seconds': 30}
        view.setdefault('title', session.get('title'))
        gid = view.get('game_id') or session.get('game_id') or ''
        if gid and isinstance(view.get('models'), dict):
            # The stored snapshot freezes when the session ends (#1623: an ended Twin Snakes session kept saying
            # "No native model reader registered" after the reader shipped and collected 17/17). Show the game's
            # collection as it is now; keep the snapshot's repair request id and state for the history.
            try:
                snap = view['models']
                live = auto_collection.status(gid)
                if (live.get('state'), live.get('job_id')) != (snap.get('state'), snap.get('job_id')):
                    view['models'] = live | {'request_id': snap.get('request_id'),
                                             'snapshot': {'state': snap.get('state'), 'updated': snap.get('updated'),
                                                          'message': snap.get('message')}}
            except Exception:                # a status read never hides the observations themselves
                pass
        view['goals'] = _session_agent_goals(view, gid)
        return view

    def _session_agent_goals(view: dict, gid: str) -> dict:
        """What each session agent is trying to do, from the observer state, the game's Hermes work-queue stage and
        the inbox requests / jobs targeting the game (session_observers.agent_goals). Never fails the panel."""
        from .session_observers import agent_goals
        queue = None
        try:
            from . import hermes_work_queue
            queue = next(iter(hermes_work_queue.snapshot(gid).get('games') or []), None) if gid else None
        except Exception:
            queue = None                     # no queue file on this host (or unreadable): no stage to explain
        requests = store.game_requests(gid) if gid else []
        jobs = [j for j in store.jobs(states=('queued', 'running')) if gid and gid in (
            (j.get('input') or {}).get('game_id'), ((j.get('input') or {}).get('game') or {}).get('game_id'))]
        try:
            return agent_goals(view, queue=queue, requests=requests, jobs=jobs)
        except Exception as exc:             # an odd stored row must not hide the observations themselves
            return {'agents': [], 'ask': None, 'error': f'{type(exc).__name__}: {exc}'[:300]}

    @app.post("/api/sessions/{sid}/observers/look")
    def session_observers_look(sid: str, actor=Depends(auth)):
        """"Done, look now": the operator set up what an agent is seeking. The observer samples this session on its
        next tick (within 5 s) with a fresh frame even if the screen looks unchanged, and re-checks model
        collection. It reads one frame; it never sends input, pauses or relaunches."""
        store.get('session', sid) or _404()
        with store.lock:
            row = store.get('session_observer', sid) or {'session_id': sid}
            store.put('session_observer', sid, row | {'look_requested': time.time(), 'next_sample': 0,
                                                      'frame_digest': None, 'models_checked': 0})
        store.audit(actor, 'session.observers.look', sid, {})
        return session_observers(sid, actor)

    class ObserverIn(BaseModel):
        enabled: StrictBool

    @app.post("/api/sessions/{sid}/observers")
    def session_observers_setting(sid: str, setting: ObserverIn, actor=Depends(auth)):
        store.get('session', sid) or _404()
        with store.lock:
            row = store.get('session_observer', sid) or {'session_id': sid}
            store.put('session_observer', sid, row | {'enabled': setting.enabled,
                      'state': 'waiting' if setting.enabled else 'paused'})
        store.audit(actor, 'session.observers', sid, {'enabled': setting.enabled})
        return session_observers(sid, actor)

    class LiveModelIn(BaseModel):
        mod: str = ""

    @app.post("/api/sessions/{sid}/live-model")
    def live_model(sid: str, model: LiveModelIn, actor=Depends(auth)):
        session = store.get("session", sid) or _404()
        if session.get("state") != "running":
            raise HTTPException(409, "session is not running")
        if model.mod and not all(c.isascii() and (c.isalnum() or c in "_-") for c in model.mod):
            raise HTTPException(422, "invalid mod name")
        session["live_mod"] = model.mod
        store.put("session", sid, session)
        store.audit(actor, "session.live_model", sid, {"mod": model.mod})
        return {"session_id": sid, "live_mod": model.mod}

    @app.post("/api/sessions/{sid}/live-pick")
    def live_pick(sid: str, pick: dict, actor=Depends(auth)):
        """The pick whip's last saved pick for this session (gbox.pick_tool.compact_pick): what pick_identify found /
        pick_replace put in. The Blender round trip (gbox.live_link) passes it back to pick_replace unchanged."""
        session = store.get("session", sid) or _404()
        if len(json.dumps(pick, default=str)) > 256 << 10:
            raise HTTPException(413, "pick too large (save the compact pick)")
        session["live_pick"] = pick | {"saved": time.time()}
        store.put("session", sid, session)
        store.audit(actor, "session.live_pick", sid, {"slot": pick.get("slot"), "status": pick.get("status")})
        return {"session_id": sid, "slot": pick.get("slot")}

    @app.post("/api/sessions/{sid}/frame")
    async def put_frame(sid: str, request: Request, actor=Depends(auth)):
        lv, body = _live(sid), await request.body()
        with lv["cond"]:
            lv["frame"], lv["seq"], lv["ts"] = body, lv["seq"] + 1, time.time()
            lv["cond"].notify_all()
        return {"seq": lv["seq"]}

    @app.post("/api/sessions/{sid}/stream")
    async def ingest_stream(sid: str, request: Request, actor=Depends(auth)):
        """Worker uploads a session's frames as one stream: [4-byte length][JPEG]...; parsed on the event loop."""
        from .live_stream import note_frame
        lv, buf, n = _live(sid), bytearray(), 0
        lv["sid"], lv["uploads"] = sid, lv.get("uploads", 0) + 1
        async for chunk in request.stream():
            buf += chunk
            while len(buf) >= 4:
                size = int.from_bytes(buf[:4], "big")
                if len(buf) < 4 + size:
                    break
                frame, buf = bytes(buf[4:4 + size]), buf[4 + size:]
                if size:
                    with lv["cond"]:
                        now = time.time()
                        note_frame(lv, now)               # a gap of 2 s+ is logged with timestamps (stream-stability)
                        lv["frame"], lv["seq"], lv["ts"] = frame, lv["seq"] + 1, now
                        lv["cond"].notify_all()
                    n += 1
        return {"frames": n}

    class StreamEvent(BaseModel):
        kind: str
        at: str = ""
        stream: str = ""
        silent_s: float | None = None
        gap_s: float | None = None
        restart: int | None = None
        returncode: int | None = None

    @app.post("/api/sessions/{sid}/stream/event")
    def stream_event(sid: str, ev: StreamEvent, actor=Depends(auth)):
        """The worker's encoder supervisor reports a stall, exit or restart (gbox/adapters.py MjpegStream)."""
        from .live_stream import note_event
        lv = _live(sid)
        lv["sid"] = sid
        with lv["cond"]:
            return note_event(lv, ev.model_dump(exclude_none=True))

    @app.get("/api/sessions/{sid}/stream/health")
    def stream_health(sid: str, actor=Depends(auth)):
        """Source frame age, recent stalls and encoder events: the client watchdog's stall signal and the log the
        operator's "it went black at ..." report is matched against."""
        from .live_stream import health
        s = store.get("session", sid)
        lv = live.get(sid) or {}
        w = store.get('worker', _wid(sid.split('-')[0])) or {}
        observer = store.get('session_observer', sid) or {}
        return health(lv, s.get("state") if s else None) | {'session_id': sid,
            'worker_online': bool(w and time.time()-w.get('last_seen',0) < WORKER_TTL),
            'local_window': bool((s or {}).get('detail',{}).get('local_window')),
            'gameplay_state': observer.get('gameplay_state'), 'presentation': observer.get('presentation'),
            'exit': (s or {}).get('exit')}

    @app.get("/api/sessions/{sid}/frame.jpg")
    def get_frame(sid: str, actor=Depends(auth)):
        f = _live(sid)["frame"]
        return Response(f, media_type="image/jpeg", headers={"cache-control": "no-store"}) if f else _404()

    @app.get("/api/sessions/{sid}/mjpeg")
    def mjpeg(sid: str, actor=Depends(auth)):
        from .live_stream import mjpeg_parts
        lv = _live(sid)

        def alive() -> bool:                         # stop streaming once the session has ended or was replaced
            s = store.get("session", sid)
            return s is None or s.get("state") != "ended"
        # Wakes on every new frame (stream fps = source fps) and repeats the newest frame while the source pauses,
        # so a state save or upload reconnect can no longer end the response and leave the operator's view black.
        return StreamingResponse(mjpeg_parts(lv, alive=alive), media_type="multipart/x-mixed-replace; boundary=f",
                                 headers={"cache-control": "no-store", "x-accel-buffering": "no"})

    class InputEvents(BaseModel):
        events: list[dict]

    padstate.register(app, auth)

    @app.post("/api/sessions/{sid}/input")
    def put_input(sid: str, ev: InputEvents, actor=Depends(auth)):
        lv = _live(sid)
        with lv["cond"]:
            lv["input"].extend(ev.events)
            padstate.record(sid, ev.events, actor)                 # controller glyph: who pressed what
            lv["cond"].notify_all()
        return {"queued": len(ev.events)}

    @app.get("/api/sessions/{sid}/input")
    def take_input(sid: str, wait: float = 0, actor=Depends(auth)):
        """Worker side. wait>0 long-polls so input is applied the moment it arrives."""
        lv = _live(sid)
        with lv["cond"]:
            if wait:
                lv["cond"].wait_for(lambda: len(lv["input"]) > 0, min(wait, 10))
            out = list(lv["input"])
            lv["input"].clear()
        return out

    # --- gBox clipboard: copy from the inspector / receipts, paste in Blender (gBox add-on) ---
    class ClipIn(BaseModel):
        kind: str                          # image | gltf | text | bytes
        name: str = "gbox"
        b64: str | None = None             # new content, stored as an artifact
        artifact: str | None = None        # or an existing artifact sha256
        meta: dict = {}                    # provenance: session, game, address, tile format...

    CLIP_TYPES = {"image": "image/png", "gltf": "model/gltf+json", "text": "text/plain", "bytes": "application/octet-stream"}

    @app.post("/api/clipboard")
    def clip_put(c: ClipIn, actor=Depends(auth)):
        if c.kind not in CLIP_TYPES:
            raise HTTPException(422, f"kind must be one of {list(CLIP_TYPES)}")
        if c.b64:
            ref = store.put_artifact(base64.b64decode(c.b64), c.name, CLIP_TYPES[c.kind], {"clipboard": True, "by": actor, **c.meta})
            sha = ref.sha256
        elif c.artifact and store.get("artifact", c.artifact):
            sha = c.artifact
        else:
            raise HTTPException(422, "need b64 data or an existing artifact")
        prev = store.get("clipboard", "current") or {"seq": 0}
        item = {"seq": prev["seq"] + 1, "kind": c.kind, "name": c.name, "sha256": sha, "meta": c.meta, "ts": time.time(), "by": actor}
        store.put("clipboard", "current", item)
        store.audit(actor, "clipboard.copy", sha, {"kind": c.kind, "name": c.name})
        app.state.assets.invalidate()
        return item

    @app.get("/api/clipboard")
    def clip_get(actor=Depends(auth)):
        return store.get("clipboard", "current") or {"seq": 0}

    # --- gBox chat agent (local LLM with tool calling over the gBox API + SearXNG web search) ---
    from .agent import Agent, ChatHub
    agent_cfg = config.agent

    # --- knowledge base: what the agent has learned, searched before the web ---
    kb_box: list = []

    def kb():
        if not kb_box:
            from .kb import KB
            kb_box.append(KB(config.data_dir / "knowledge.sqlite", agent_cfg["llm_url"]))
        return kb_box[0]

    class KbIn(BaseModel):
        text: str
        source: str = ""
        title: str = ""
        game: str = ""
        kind: str = "note"                 # page | wiki | answer | fact | note

    @app.post("/api/kb")
    def kb_add(k: KbIn, actor=Depends(auth)):
        n = kb().add(k.text, k.source, k.title, k.game, k.kind)
        if n:
            store.audit(actor, "kb.learn", k.source or k.title, {"kind": k.kind, "game": k.game, "chunks": n})
        return {"added": n}

    @app.get("/api/kb/search")
    def kb_search(q: str, game: str = "", k: int = 6, actor=Depends(auth)):
        return kb().search(q, game, k)

    @app.get("/api/kb/stats")
    def kb_stats(actor=Depends(auth)):
        return kb().stats()

    def _mod_root(gid: str, name: str) -> Path:
        from . import filemods
        try:
            return filemods.mod_dir(config, gid, name).resolve()
        except ValueError as error:
            raise HTTPException(400, "bad mod name") from error

    @app.get("/api/modfiles/{gid}/{name}")
    def modfiles(gid: str, name: str, actor=Depends(auth)):
        """The central mod collection (this Spark): any gBox machine fetches a built mod from here before launching it."""
        from . import filemods
        cache_tiers.touch(gid, queue=True)        # cold: answered from the HDD now (sidecar), moved up when idle
        d = _mod_root(gid, name)
        if not (d / ".gbox-mod.json").exists():
            raise HTTPException(404, "not in the collection")
        return {"game_id": gid, "name": name, "files": filemods._files(d, hashes=True)}

    @app.get("/api/modfiles/{gid}/{name}/file/{path:path}")
    def modfile_get(gid: str, name: str, path: str, actor=Depends(auth)):
        d = _mod_root(gid, name)
        from . import filemods
        try:
            f = filemods._file_path(d, path)
        except ValueError as error:
            raise HTTPException(404, "no such file") from error
        if not f.is_file():
            raise HTTPException(404, "no such file")
        return FileResponse(f)

    @app.put("/api/modfiles/{gid}/{name}/file/{path:path}")
    async def modfile_put(gid: str, name: str, path: str, request: Request, actor=Depends(auth)):
        """A machine that built a mod hands it to the collection (streamed to disk; .part until complete)."""
        from starlette.concurrency import run_in_threadpool
        await run_in_threadpool(cache_tiers.ensure_hot, gid)   # new writes land on the hot tier
        d = _mod_root(gid, name)
        import uuid
        from . import filemods
        try:
            f = filemods._file_path(d, path)
            # one .part per upload: a worker pushing the same build at startup (push_missing) can race an operator
            # upload; a shared .part made the second os.replace fail with FileNotFoundError (500) after a full transfer
            tmp = filemods._file_path(d, f"{path}.{uuid.uuid4().hex[:12]}.part")
        except ValueError as error:
            raise HTTPException(400, "bad path") from error
        f.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(tmp, "wb") as fh:
                async for chunk in request.stream():
                    fh.write(chunk)
            os.replace(tmp, f)
        finally:
            tmp.unlink(missing_ok=True)                  # an aborted upload leaves nothing behind
        return {"stored": path, "size": f.stat().st_size}

    # --- Export ROM hack (gbox/romexport.py): bootable modded image of the operator's own game + shareable patch ---
    class RomExportReq(BaseModel):
        mod_id: str = ""
        game_id: str = ""
        mods: list[str] = []
        changes: dict = {}
        name: str = ""
        formats: list[str] = ["bps", "ips", "xdelta"]
        wii_format: str = "iso"
        node: str = "linux"                 # where the mod collection lives (the Spark); "windows" or a worker name

    @app.post("/api/romexport")
    def romexport_start(r: RomExportReq, actor=Depends(auth)):
        """Start an export job (progress on /api/jobs/{id}); the result lists the files to download."""
        inp = r.model_dump(exclude={"node"}) | {"op": "export"}
        req = JobRequest(tool="rom_export", input=inp)
        if r.node in ("linux", "windows"):
            req.require_os = r.node
        else:
            byname = [w for w in workers() if w["online"] and w["name"] == r.node]
            req.require_worker = byname[0]["id"] if byname else r.node
        store.audit(actor, "romexport.start", r.mod_id or r.game_id, {"mods": r.mods, "name": r.name})
        return submit(req, actor)

    @app.get("/api/romexport")
    def romexport_list(game_id: str = "", actor=Depends(auth)):
        from . import romexport
        return romexport.list_exports(config, game_id)

    def _rx_dir(gid: str, name: str) -> Path:
        from . import romexport
        root = romexport.exports_root(config).resolve()
        d = (root / gid / name).resolve()
        if not d.is_relative_to(root) or "/" in gid + name or "\\" in gid + name or not (d / "export.json").exists():
            raise HTTPException(404, "no such export")
        return d

    @app.get("/api/romexport/{gid}/{name}")
    def romexport_get(gid: str, name: str, actor=Depends(auth)):
        return json.loads((_rx_dir(gid, name) / "export.json").read_text())

    @app.get("/api/romexport/{gid}/{name}/file/{path:path}")
    def romexport_file(gid: str, name: str, path: str, actor=Depends(auth)):
        """Download one exported file (operator only: every API call needs the token; nothing is published)."""
        d = _rx_dir(gid, name)
        f = (d / path).resolve()
        if not f.is_relative_to(d) or not f.is_file():
            raise HTTPException(404, "no such file")
        store.audit(actor, "romexport.download", f"{gid}/{name}/{path}", {"size": f.stat().st_size})
        return FileResponse(f, filename=f.name)

    @app.delete("/api/romexport/{gid}/{name}")
    def romexport_delete(gid: str, name: str, actor=Depends(auth)):
        from . import romexport
        _rx_dir(gid, name)
        store.audit(actor, "romexport.delete", f"{gid}/{name}", {})
        return {"removed": romexport.remove(config, gid, name)}

    def _run_on(wid: str, tool: str, inp: dict, wait: float = 25) -> dict | None:
        j = submit(JobRequest(tool=tool, input=inp, require_worker=wid), "tasks")
        t0 = time.time()
        while (jj := store.get("job", j.id))["state"] in ("queued", "running") and time.time() - t0 < wait:
            time.sleep(0.3)
        return jj

    @app.get("/api/hermes/task-mode")
    def hermes_task_mode_state(actor=Depends(auth)):
        from . import hermes_task_mode
        return hermes_task_mode.status()

    class QueuePriorityIn(BaseModel):
        ids: list[str] = []            # game ids and/or request ids (or numbers), most important first

    @app.get("/api/hermes/queue/priority")
    def hermes_queue_priority(actor=Depends(auth)):
        from . import hermes_work_queue
        return {"priority": hermes_work_queue.get_priority()}

    @app.post("/api/hermes/queue/priority")
    def hermes_queue_priority_set(body: QueuePriorityIn, actor=Depends(auth)):
        """Operator priority for the Hermes queue: these games/requests are worked first in their lane."""
        from . import hermes_work_queue
        ids = hermes_work_queue.set_priority(body.ids)
        store.audit(actor, "hermes.queue_priority", "", {"ids": ids})
        return {"priority": ids}

    class TaskModeIn(BaseModel):
        enabled: bool

    @app.post("/api/hermes/task-mode")
    def hermes_task_mode_set(value: TaskModeIn, actor=Depends(auth)):
        from . import hermes_task_mode
        try:
            result = hermes_task_mode.set_enabled(value.enabled)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            raise HTTPException(503, str(exc)[:1000]) from exc
        store.audit(actor, "hermes.task_mode", result.get("job_id") or "", {"enabled": value.enabled})
        return result

    task_cache: dict[str, dict] = {}
    task_cache_lock = threading.Lock()

    def hermes_runs(limit: int) -> list[dict]:
        """Recent Hermes runs, each naming the inbox tickets it confirmed work on."""
        from . import hermes_providers, hermes_tasks
        runs = hermes_tasks.list_runs(limit)
        # The provider that served the run's last successful model call, from Hermes's agent log; the
        # session's billing provider is only where the run started before falling through its routes.
        try:
            served = hermes_providers.session_providers()
        except Exception:  # the Providers view is optional; never break the run list
            served = {}
        titles: dict[str, dict | None] = {}
        for run in runs:
            if (who := served.get(run.get("session_id") or "")):
                run["billing_provider"] = run.get("provider")
                run.update(provider=who["provider"], model=who["model"] or run.get("model"),
                           provider_attribution=who["attribution"])
            tickets = []
            for rid in run.get("request_ids") or []:
                if rid not in titles:
                    r = store.get("request", rid)
                    titles[rid] = {"id": rid, "number": r.get("number"),
                                   "title": (r.get("title") or "")[:120],
                                   "status": r.get("status")} if r else None
                if titles[rid]:
                    tickets.append(titles[rid])
            run["tickets"] = tickets
        return runs

    @app.get("/api/tasks")
    def tasks_all(hermes_limit: int = 20, actor=Depends(auth)):
        """Return the latest machine readings without waiting for slow GPU/process counters.

        `hermes_limit` (1-100, default 20) is how many recent Hermes runs to list.
        """
        with store.lock:
            worker_snapshot = workers()
            retire_unrunnable_jobs(worker_snapshot)
        ws = [w for w in worker_snapshot if w["online"] and "tasks" in (w.get("tools") or [])]
        machines = []
        with task_cache_lock:  # concurrent UI polls must not create duplicate inventory jobs
            now = time.time()
            for w in ws:
                wid = w["id"]
                cached = task_cache.setdefault(wid, {})
                if jid := cached.get("job_id"):
                    jj = store.get("job", jid)
                    if not jj or jj["state"] not in ("queued", "running"):
                        cached["job_id"] = None
                        if jj and jj["state"] == "succeeded" and isinstance((jj.get("output") or {}).get("result"), dict):
                            cached["result"] = jj["output"]["result"]
                            cached["updated"] = jj.get("finished") or now
                            cached.pop("error", None)
                        else:
                            cached["error"] = (jj or {}).get("error") or "machine inventory failed"
                        cached["submitted"] = now
                if not cached.get("job_id") and now - cached.get("submitted", 0) >= 10:
                    jj = submit(JobRequest(tool="tasks", input={"op": "list"}, require_worker=wid), "tasks")
                    cached["submitted"] = now
                    if jj.state in (JobState.QUEUED, JobState.RUNNING):
                        cached["job_id"] = jj.id
                    else:
                        cached["error"] = jj.error or "machine inventory unavailable"
                machines.append({"worker_id": wid, "name": w["name"], "os": w.get("os"),
                                 **(cached.get("result") or {"tasks": []}),
                                 "updated": cached.get("updated"),
                                 "error": cached.get("error") if not cached.get("result") else None,
                                 "collecting": bool(cached.get("job_id"))})
        names = {w["id"]: w["name"] for w in worker_snapshot}
        def task_job(j):
            return {"id": j["id"], "tool": j["tool"], "state": j["state"],
                    "worker": names.get(j.get("worker_id") or j.get("require_worker") or "", ""),
                    "created": j.get("created"), "progress": (j.get("progress") or {}).get("msg", ""),
                    "pct": (j.get("progress") or {}).get("pct")}
        with store.lock:  # one consistent job snapshot across the two visible groups
            jobs = [task_job(j) for j in store.jobs(states=("queued", "running"), exclude_tool="tasks")]
            recent = [task_job(j) for j in store.jobs(exclude_states=("queued", "running"),
                                                   exclude_tool="tasks", limit=10, reverse=True)]
        auto_reports = store.resolution_requests()
        resolutions = []
        for report in auto_reports:
            cid = report["context"]["resolution_chat_id"]
            chat = store.get("chat", cid) or {}
            events = chat.get("events") or []
            latest = next((e for e in reversed(events) if e.get("type") in ("assistant", "tool_call", "tool_result", "error")), {})
            resolutions.append({"id": report["id"], "number": report["number"], "name": report["title"],
                                "state": "running" if chat.get("busy") else report["status"], "chat_id": cid,
                                "progress": (latest.get("text") or latest.get("name") or "Agent is starting")[:160],
                                "output": "\n".join(f"{e.get('type')}: {e.get('name') or e.get('text') or ''}" for e in events[-25:])[-12000:]})
        return {"machines": machines, "jobs": sorted(jobs, key=lambda j: -(j["created"] or 0)),
                "recent": recent, "hermes": hermes_runs(max(1, min(hermes_limit, 100))),
                "resolutions": resolutions}

    @app.get("/api/hermes/providers")
    def hermes_providers_view(window: Literal["today", "7d"] = "today", actor=Depends(auth)):
        """Which Hermes provider did the work and which can still do it, for the Tasks window.

        One row per route (feedback.json routes plus any other route that served calls in the
        window) and per provider: status now, last error, runs served to completion, model calls,
        tokens, wall time, OpenRouter credit (cached 5 min; the key never leaves the server) and a
        one-line recommendation.
        """
        from . import hermes_providers
        out = hermes_providers.summary(window)
        out["grunt"] = grunt.status()               # the Spark helper card ("Spark helper: doing X")
        return out

    # --- Hermes local route: the proxy in front of the Spark's Ollama, and the Spark helper (docs/hermes-local-fallback.md)
    from . import llm_proxy, spark_grunt

    def _spark_operator_playing() -> str | None:
        """The operator plays a game on the Spark (not an agent's test session): local model calls wait."""
        rows = workers()
        sess = spark_grunt.operator_session_on(store.all("session"), {x["session_id"]: x for x in store.all("slabel")},
                                               spark_grunt.spark_workers(rows), _wid)
        if sess:
            return f"the operator is playing {sess.get('title') or sess.get('game_id') or 'a game'} on the Spark"
        return None

    llm_proxy.routes(app, config, auth, gate=_spark_operator_playing)

    def _grunt_submit(tool: str, inp: dict) -> dict:
        return submit(JobRequest(tool=tool, input=inp, agent_use=True), "spark-helper").model_dump(mode="json")

    grunt = spark_grunt.install(app, store, config, submit=_grunt_submit, cancel=lambda jid: job_cancel(jid, "spark-helper"),
                                workers=workers, auto_collection=auto_collection, resolve=_wid)

    @app.on_event("startup")
    async def _grunt_start():
        # The Spark helper runs on the control plane's own node (the Spark) only, never in tests or on a Windows host.
        if (config.hermes.grunt.enabled and HOST_OS == "linux" and not os.environ.get("PYTEST_CURRENT_TEST")
                and os.environ.get("GBOX_GRUNT", "1") != "0"):
            grunt.start()

    @app.on_event("shutdown")
    async def _grunt_stop():
        grunt.stop()

    @app.get("/api/grunt")
    def grunt_status(actor=Depends(auth)):
        """The Spark helper: what it is doing now, why it waits, and each chore's last result and next run."""
        return grunt.status()

    class GruntIn(BaseModel):
        enabled: bool | None = None
        run: str = ""                  # a chore name: make it due now (it still waits for an idle Spark)

    @app.post("/api/grunt")
    def grunt_control(body: GruntIn, actor=Depends(auth)):
        if body.enabled is not None:
            grunt.set_enabled(body.enabled)
        if body.run:
            try:
                grunt.force(body.run)
            except KeyError:
                raise HTTPException(404, f"no chore named {body.run}") from None
        store.audit(actor, "grunt.control", body.run, body.model_dump())
        return grunt.status()

    @app.get("/api/hermes/local")
    def hermes_local_state(actor=Depends(auth)):
        """The local route: model, whether Hermes is on it now and why, and the operator's local-only switch."""
        from . import hermes_local
        return hermes_local.status() | {"proxy": app.state.local_llm.status()}

    class LocalModeIn(BaseModel):
        local_only: bool

    @app.post("/api/hermes/local")
    def hermes_local_set(body: LocalModeIn, actor=Depends(auth)):
        """local_only=true: Hermes uses only the Spark's GPU model (the supervisor applies it within 5 minutes)."""
        from . import hermes_local
        store.audit(actor, "hermes.local_only", "", {"local_only": body.local_only})
        return hermes_local.set_local_only(body.local_only)

    @app.get("/api/tasks/resolutions/{rid}")
    def tasks_resolution(rid: str, actor=Depends(auth)):
        report = _req(rid)
        cid = (report.get("context") or {}).get("resolution_chat_id") or _404()
        chat = store.get("chat", cid) or _404()
        steps, attempts = [], {}
        for e in chat.get("events") or []:
            if e.get("type") == "tool_call":
                name = e.get("name") or "tool"
                attempts[name] = attempts.get(name, 0) + 1
                steps.append({"action": name, "attempt": attempts[name], "input": e.get("args") or {},
                              "result": "Awaiting tool result", "status": "running"})
            elif e.get("type") in ("tool_result", "error"):
                for step in reversed(steps):
                    if step["status"] == "running" and (step["action"] == e.get("name") or e.get("type") == "error"):
                        result_text = (e.get("text") or "")[:5000]
                        failed = (e.get("type") == "error" or '"error"' in result_text[:300]
                                  or '"state": "failed"' in result_text[:300] or '"status": "unsupported' in result_text[:300])
                        step.update(result=result_text, status="failed" if failed else "finished")
                        break
        return {"request_id": rid, "name": report["title"], "state": "running" if chat.get("busy") else report["status"],
                "steps": steps, "output": "\n".join(f"{e.get('type')}: {e.get('name') or e.get('text') or ''}" for e in chat.get("events") or [])[-70000:]}

    @app.get("/api/tasks/hermes/{run_id}")
    def tasks_hermes_run(run_id: str, actor=Depends(auth)):
        """Live Hermes turn and tool output for an expandable Tasks entry."""
        from . import hermes_tasks
        run = hermes_tasks.get_run(run_id) or _404()
        if not run.get('session_id') and run.get('request_id'):
            report = store.get('request', run['request_id']) or {}
            messages = [m for m in report.get('messages', [])
                        if (m.get('task_step') or {}).get('action') == 'activate Hermes bridge safely']
            run['steps'] = [m['task_step'] for m in messages]
            if messages:
                run['output'] = '\n\n'.join(m.get('text', '') for m in messages)
        return run

    class TaskKill(BaseModel):
        worker_id: str
        pid: int

    @app.post("/api/tasks/kill")
    def tasks_kill(k: TaskKill, actor=Depends(auth)):
        """Hard stop of one task (and everything it started) on its machine; a game's session ends with it."""
        jj = _run_on(k.worker_id, "tasks", {"op": "kill", "pid": k.pid}, wait=20)
        if not jj or jj["state"] != "succeeded":
            raise HTTPException(409, (jj or {}).get("error") or "the machine didn't answer")
        r = jj["output"]["result"]
        if r.get("session_id"):
            s_ = store.get("session", r["session_id"])
            if s_:
                store.put("session", r["session_id"], s_ | {"state": "ended", "ended": time.time(), "exit": "killed from Tasks"})
        store.audit(actor, "task.kill", str(k.pid), r)
        return r

    class WhipIn(BaseModel):
        image: str                           # base64 PNG/JPEG of the frame with the whip drawn on it
        a: list[float]                       # start point, fractions of the image (0..1)
        b: list[float]                       # end point
        game: str = ""

    @app.post("/api/whip/identify")
    def whip_identify(w: WhipIn, actor=Depends(auth)):
        """Name the thing at each end of a pick whip, so the menu can say "Play as the Banshee" instead of "B"."""
        import io, json as _json, re as _re
        from PIL import Image
        img = Image.open(io.BytesIO(base64.b64decode(w.image))).convert("RGB")
        W, H = img.size
        side = int(min(W, H) * 0.34)

        def crop(p):
            cx, cy = int(p[0] * W), int(p[1] * H)
            box = (max(0, cx - side // 2), max(0, cy - side // 2), min(W, cx + side // 2), min(H, cy + side // 2))
            buf = io.BytesIO()
            img.crop(box).save(buf, "PNG")
            return base64.b64encode(buf.getvalue()).decode()

        def ask(p):
            # no game name in the prompt: told "RE4", the model answers "Ganado" for everything; asked what it SEES it's right
            q = ("Crop of a video game screenshot (ignore any red line/circle drawn over it). What is the main thing at the centre? "
                 "Describe what you SEE (appearance), not what the game usually has; use a character's name only if you are sure. "
                 'JSON only: {"name": "<short specific name or description, e.g. woman in a black jacket, yellow taxi, shotgun>", '
                 '"kind": "player|character|enemy|vehicle|weapon|item|object|scenery|ui"}')
            try:
                r = httpx.post(f"{agent_cfg['llm_url'].rstrip('/')}/chat/completions", timeout=120, json={
                    "model": agent_cfg.get("vision_model") or "qwen2.5vl:7b", "temperature": 0,
                    "messages": [{"role": "user", "content": [{"type": "text", "text": q},
                                 {"type": "image_url", "image_url": {"url": "data:image/png;base64," + crop(p)}}]}]}).json()
                t = r["choices"][0]["message"]["content"]
                m = _re.search(r"\{.*\}", t, _re.S)
                d = _json.loads(m.group(0)) if m else {"name": t.strip()[:60], "kind": "object"}
            except Exception as e:
                d = {"name": "the thing there", "kind": "object", "error": str(e)[:120]}
            try:                                     # already in the character collection? (reuse instead of re-extracting)
                from . import characters
                hit = characters.find(characters.list_all(characters.library_root(config)), d.get("name") or "")
                if hit:
                    d["library"] = {"slug": hit.get("slug"), "name": hit.get("name")}
            except Exception:
                pass
            if "metal gear solid 2" in (w.game or "").lower():   # MGS2: the cast slot the whipped thing belongs to
                try:
                    from . import mgs2_swap
                    slot = mgs2_swap.slot_for_name(d.get("name") or "", None, d.get("kind"))
                    if slot:
                        d["slot"] = slot
                except Exception:
                    pass
            return d

        with concurrent.futures.ThreadPoolExecutor(2) as ex:
            a, b = ex.map(ask, [w.a, w.b])
        return {"a": a, "b": b}

    def make_agent(model: str | None = None):
        model = model or agent_cfg["model"]
        sees = "vision" in (model_caps.get(model, (None, []))[1])   # a vision-capable chat model looks at the screen itself
        return Agent(f"http://127.0.0.1:{config.api_port}", token, agent_cfg["llm_url"], model,
                     agent_cfg["searx_url"], model if sees else agent_cfg.get("vision_model"))

    def api_requests(op: str, body: dict):
        try:
            if op == "get":
                return store.get("request", body["id"])
            if op == "create":
                return req_create(RequestIn(**body), "gbox-agent")["id"]
            if op == "reply":
                rid = body.pop("id")
                return req_message(rid, MessageIn(author="agent", **body), "gbox-agent")
            if op == "capture":
                rid = body.pop("id")
                return asyncio.run(req_capture(rid, RequestCaptureIn(**body), "gbox-agent"))
            if op == "metrics":
                rid = body.pop("id")
                return req_metrics(rid, MetricsIn(**body), "gbox-agent")
            if op == "status":
                rid = body.pop("id")
                return req_status(rid, StatusIn(**body), "gbox-agent")
        except Exception:
            return None

    hub = ChatHub(store, make_agent)
    for c in store.all("chat"):                   # a restart kills in-flight agent turns: release them, say so
        if c.get("busy"):
            c["busy"] = False
            c["events"].append({"type": "error", "text": "Interrupted: gBox restarted while this was running. Please send it again.",
                                "ts": time.time()})
            store.put("chat", c["id"], c)
    model_caps: dict[str, tuple] = {}             # name -> (digest, capabilities) from Ollama /api/show

    class ChatIn(BaseModel):
        text: str
        context: dict = {}
        model: str | None = None
        images: list[str] = []             # base64 PNG/JPEG pasted into the conversation (vision model describes them)

    @app.get("/api/chat/suggest")
    def chat_suggest(q: str = "", game: str = "", platform: str = "", limit: int = 10, actor=Depends(auth)):
        """Autocomplete: the operator's past chat requests (most used first) + things gBox can do for the current game."""
        import collections
        past = collections.Counter()
        last: dict[str, float] = {}
        for c in store.all("chat"):
            for e in c.get("events", []):
                if e.get("type") == "user" and e.get("text"):
                    t = e["text"].strip()
                    past[t] += 1
                    last[t] = max(last.get(t, 0), e.get("ts", 0))
        g = game or "this game"
        cart = platform in ("nes", "snes", "gb", "gbc", "gba", "genesis", "sms", "gamegear", "pce", "atari2600", "n64")
        templates = [
            f"Give me infinite lives in {g}", f"Give me infinite health in {g}", f"Max out money / items in {g}",
            f"Find a RAM map or GameShark codes for {g}", f"Find where the player's position is stored in {g}",
            f"Extract {g}'s sprites to Blender" if cart else f"Capture the current screen of {g} and send it to Blender",
            f"What is on screen right now in {g}?", f"Save state now in {g}", f"Pause {g}",
            f"Analyze {g}'s main executable in Ghidra and summarize its functions",
            "Find Ghidra scripts for finding strings / crypto / decompiling",
            "Launch the last game I played", "Search the library for ", "What can you do?",
        ]
        ql = q.lower().strip()
        def score(t):
            tl = t.lower()
            return (0 if tl.startswith(ql) else 1 if ql in tl else 2 if all(w in tl for w in ql.split()) else 9)
        hist = [{"text": t, "kind": "history", "uses": n} for t, n in sorted(past.items(), key=lambda kv: (-kv[1], -last[kv[0]]))]
        # mods that already worked (on this game first): one click away, and a menu of ideas when nothing is going on
        gl = (game or "").lower()
        here = lambda m: bool(gl) and gl in (m.get("game_title") or "").lower()
        proven = sorted(store.all("mod"), key=lambda m: (0 if here(m) else 1, -m.get("ts", 0)))
        hist = [{"text": m["title"] + ("" if here(m) else f" in {m.get('game_title') or 'its game'}"),
                 "kind": "mod", "mod": m["id"], "verified": m.get("verified", False)} for m in proven[:12]] + hist
        tmpl = [{"text": t, "kind": "suggestion"} for t in templates if t not in past]
        items = [x for x in hist + tmpl if not ql or score(x["text"]) < 9]
        items.sort(key=lambda x: (score(x["text"]) if ql else 0, {"mod": 0, "history": 1}.get(x["kind"], 2)))
        return items[:max(1, min(limit, 30))]

    def voice_default() -> str:
        """[voice] default_assistant, unless the operator picked another one at runtime (PUT /api/voice/default)."""
        return (store.get("setting", "voice") or {}).get("default_assistant") or config.voice.default_assistant

    @app.get("/api/voice/voices")
    def voice_list(actor=Depends(auth)):
        from . import audio_cpp, speech
        groups = [{"label": "XTTS v2 · cloned voices (Pine Box library)",
                   "voices": [{"id": f"xtts:{v['id']}", "name": v["name"]} for v in speech.voices(agent_cfg.get("voice_library", ""))]},
                  {"label": "Kokoro · fast", "voices": [{"id": f"kokoro:{vid}", "name": n} for vid, n in speech.KOKORO_VOICES]}]
        if audio_cpp.available(config) is None:     # audio.cpp on this machine: its voices, always served by audio.cpp
            ids = audio_cpp.voices(config) or ([v for v, _ in speech.KOKORO_VOICES] if config.audio_cpp.tts_family == "kokoro_tts" else [])
            names = dict(speech.KOKORO_VOICES)
            groups.append({"label": "audio.cpp · local", "voices": [{"id": f"audio_cpp:{v}", "name": names.get(v, v)} for v in ids]})
        return {"engine": agent_cfg.get("tts_engine", "xtts"), "default_assistant": voice_default(), "groups": groups}

    class TtsIn(BaseModel):
        text: str
        voice: str = ""
        engine: str | None = None

    @app.post("/api/tts")
    async def text_to_speech(t: TtsIn, actor=Depends(auth)):
        """Speak a reply: the default speech assistant (Voice Director or audio.cpp), the other one when it is busy, Piper last."""
        from . import speech
        wav, used = await asyncio.to_thread(speech.route_tts, config, t.text, t.engine, t.voice, voice_default())
        return Response(wav, media_type="audio/wav", headers={"x-gbox-tts-engine": used})

    @app.post("/api/stt")
    async def speech_to_text(request: Request, language: str = "en", actor=Depends(auth)):
        """Dictation: browser audio -> the default assistant (Spark faster-whisper over Wyoming, or audio.cpp) -> text."""
        from . import speech
        audio = await request.body()
        if not audio:
            raise HTTPException(422, "no audio")
        try:
            text, used = await asyncio.to_thread(speech.route_stt, config, audio, language or None, voice_default())
        except Exception as e:
            raise HTTPException(502, f"speech service: {e}")
        return {"text": text, "assistant": used}

    @app.get("/api/voice/assistants")
    def voice_assistants(actor=Depends(auth)):
        """Both speech assistants, which one is the default, and how requests were routed (docs/audio_cpp.md)."""
        from . import speech
        return speech.assistants(config, voice_default())

    class VoiceDefaultIn(BaseModel):
        assistant: Literal["director", "audio_cpp"] | None = None   # None = back to gbox.toml [voice] default_assistant

    @app.put("/api/voice/default")
    def voice_set_default(v: VoiceDefaultIn, actor=Depends(auth)):
        """Make audio.cpp (or the Voice Director) the default speech assistant without editing gbox.toml."""
        from . import audio_cpp
        if v.assistant == "audio_cpp" and (why := audio_cpp.available(config)):
            raise HTTPException(409, f"audio.cpp can't be the default here: {why}")
        store.put("setting", "voice", (store.get("setting", "voice") or {}) | {"default_assistant": v.assistant, "by": actor,
                                                                                "ts": time.time()})
        return {"default_assistant": voice_default()}

    @app.get("/api/audio_cpp/status")
    def audio_cpp_status(actor=Depends(auth)):
        from . import audio_cpp
        return audio_cpp.service(config).status()

    @app.post("/api/audio_cpp/{op}")
    async def audio_cpp_control(op: Literal["start", "stop"], actor=Depends(auth)):
        """Start (and keep alive) or stop the control plane's own audiocpp_server."""
        from . import audio_cpp
        svc = audio_cpp.service(config)
        if op == "stop":
            return await asyncio.to_thread(svc.stop)
        try:
            st = await asyncio.to_thread(svc.start, True)
        except audio_cpp.Down as e:
            raise HTTPException(409, str(e))
        svc.keep_alive()
        return st

    @app.get("/api/llm/models")
    def llm_models(actor=Depends(auth)):
        """Chat-capable models on the Spark's Ollama (embedding/OCR models filtered out)."""
        base = agent_cfg["llm_url"].rsplit("/v1", 1)[0]
        try:
            tags = httpx.get(f"{base}/api/tags", timeout=10).json().get("models", [])
        except Exception as e:
            raise HTTPException(502, f"LLM server unreachable: {e}")
        skip = ("embed", "ocr")
        names = [m for m in tags if not any(s in m["name"] for s in skip)]

        def caps(m):
            hit = model_caps.get(m["name"])
            if hit and hit[0] == m.get("digest"):
                return hit[1]
            try:
                c = httpx.post(f"{base}/api/show", json={"model": m["name"]}, timeout=20).json().get("capabilities") or []
            except Exception:
                return []                                       # don't cache a failed lookup (e.g. model still loading)
            model_caps[m["name"]] = (m.get("digest"), c)
            return c
        with concurrent.futures.ThreadPoolExecutor(8) as ex:
            cl = list(ex.map(caps, names))
        models = []
        for m, c in zip(names, cl):
            v, t = "vision" in c, "tools" in c
            models.append({"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 1), "capabilities": c,
                           "group": "Multimodal (vision + tools)" if v and t else "Vision" if v else "Tools" if t else "Text only"})
        order = {"Multimodal (vision + tools)": 0, "Vision": 1, "Tools": 2, "Text only": 3}
        return {"default": agent_cfg["model"], "models": sorted(models, key=lambda m: (order[m["group"]], m["name"]))}

    @app.get("/api/chat")
    def chat_list(actor=Depends(auth)):
        return hub.list()

    @app.post("/api/chat")
    def chat_new(actor=Depends(auth)):
        c = hub.get(new_id())
        store.put("chat", c["id"], c)
        return {"id": c["id"]}

    @app.get("/api/chat/{cid}")
    def chat_get(cid: str, after: int = 0, actor=Depends(auth)):
        c = store.get("chat", cid) or _404()
        return {k: c.get(k) for k in ("id", "title", "model", "games", "busy", "created", "updated")} | {"events": c["events"][after:], "count": len(c["events"])}

    @app.post("/api/chat/{cid}/messages")
    def chat_post(cid: str, m: ChatIn, actor=Depends(auth)):
        try:
            shas = [store.put_artifact(base64.b64decode(b), f"chat-{cid}-{i}.png", "image/png", {"chat": cid}).sha256
                    for i, b in enumerate(m.images[:6])]
            hub.post(cid, m.text, m.context, api_requests, m.model, shas)
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        store.audit(actor, "chat.message", cid, {"chars": len(m.text), "model": m.model, "context": m.context})
        return {"ok": True}

    @app.delete("/api/chat/{cid}")
    def chat_delete(cid: str, actor=Depends(auth)):
        store.delete("chat", cid)
        store.audit(actor, "chat.delete", cid, {})
        return {"ok": True}

    rpc_results: dict[str, dict] = {}

    class Rpc(BaseModel):
        op: str
        args: dict = {}

    @app.post("/api/sessions/{sid}/rpc")
    def session_rpc(sid: str, req: Rpc, actor=Depends(auth)):
        """Inspector peeks (read_memory / read_rom / info) and CPU debugger ops (debug_*), answered by the worker over the
        session channel. Debugger control (halt/step/breakpoints) changes execution, not memory, and is audited."""
        if req.op not in ("read_memory", "read_rom", "info", "state", "reset", "menu", "pause", "resume", "normal_speed") \
                and not req.op.startswith("debug_"):
            raise HTTPException(422, "read-only, reset, pause/resume and debug_* ops only; edits go through the write_memory job")
        if req.op in ("reset", "pause", "resume", "normal_speed", "debug_halt", "debug_resume", "debug_step", "debug_break", "debug_unbreak"):
            store.audit(actor, f"session.{req.op}", sid, req.args)
        rid, lv = new_id(), _live(sid)
        with lv["cond"]:
            lv["input"].append({"rpc": rid, "op": req.op, "args": req.args})
            lv["cond"].notify_all()
            if not lv["cond"].wait_for(lambda: rid in rpc_results, 10):
                raise HTTPException(504, "session did not answer (ended, or not a live gBox session)")
        res = rpc_results.pop(rid)
        if not res.get("ok"):
            raise HTTPException(422, res.get("error"))
        return res["data"]

    @app.post("/api/sessions/{sid}/rpc/{rid}")
    def session_rpc_result(sid: str, rid: str, res: dict, actor=Depends(auth)):
        lv = _live(sid)
        with lv["cond"]:
            rpc_results[rid] = res
            lv["cond"].notify_all()
        return {"ok": True}

    def _rpc_quick(sid: str, op: str, wait: float = 3.0):
        """session_rpc with a short wait, for the pick whip's pause hold: a session without the live channel answers
        through the job queue instead, and an unanswered request is withdrawn so a late worker never applies it."""
        rid, lv = new_id(), _live(sid)
        item = {"rpc": rid, "op": op, "args": {}}
        with lv["cond"]:
            lv["input"].append(item)
            lv["cond"].notify_all()
            if not lv["cond"].wait_for(lambda: rid in rpc_results, wait):
                try:
                    lv["input"].remove(item)
                except ValueError:
                    pass
                raise TimeoutError("session did not answer")
        res = rpc_results.pop(rid)
        if not res.get("ok"):
            raise RuntimeError(res.get("error") or f"{op} failed")
        return res["data"]

    from . import pickwhip                        # pick whip pause hold + watchdog (docs/live-picker.md)
    pickwhip.register(app, auth, store, rpc=_rpc_quick,
                      submit_op=lambda sid, op: submit(JobRequest(tool="session_op", input={"session_id": sid, "op": op, "args": {}},
                                                                  require_worker=sid.split("-")[0]), "pickwhip"))

    from . import re_inventory_api                # Resident Evil inventory helper (any RE): /api/re/inventory, /api/re/catalog
    re_inventory_api.routes(app, store, config, auth, submit=submit, JobRequest=JobRequest,
                            peek=lambda sid, a, n, actor: session_rpc(sid, Rpc(op="read_memory", args={"address": a, "length": n}), actor))

    @app.post("/api/sessions/{sid}/detail")
    def session_detail(sid: str, info: dict, actor=Depends(auth)):
        """A worker reports a changed process (e.g. RPCS3 relaunched into a save state) so the app re-docks the window."""
        s_ = store.get("session", sid) or _404()
        store.put("session", sid, s_ | {"detail": (s_.get("detail") or {}) | info})
        store.audit(actor, "session.detail", sid, info)
        return {"ok": True}

    @app.post("/api/sessions/{sid}/ended")
    def ended(sid: str, info: dict, actor=Depends(auth)):
        from .session_exit import merge, crash_code, intentional
        log_tail = info.pop("log_tail", None) if isinstance(info, dict) else None
        with store.lock:
            s_ = store.get("session", sid)
            stop = _stop_requested(sid)
            if s_:
                was_running = s_.get("state") != "ended"
                info = merge(s_.get("exit"), info)
                if stop and not info.get('via'):
                    info['via'] = 'stop'
                s_ = s_ | {"state": "ended", "ended": s_.get("ended") or time.time(), "exit": info}
                store.put("session", sid, s_)
        if s_:
            if was_running and crash_code(info) and not intentional(info):
                # Only recognizable crash evidence can file a crash report.
                ended_session = dict(s_)
                def _crash():
                    try:
                        launch_ledger.observe_session_end(ended_session, info | {"log_tail": log_tail or ""},
                                                          stop_requested=stop, label=store.get("slabel", sid))
                    except Exception as exc:                  # noqa: BLE001 - the report never blocks the session end
                        store.audit("gbox-auto", "launch_failure.error", sid, {"error": str(exc)[:500]})
                threading.Thread(target=_crash, daemon=True, name=f"launch-crash-{sid[-8:]}").start()
        store.audit(actor, "session.ended", sid, info)
        return {"ok": True}

    def _stop_requested(sid: str) -> bool:
        """An accepted stop intent, excluding failed/rejected/cancelled stop attempts."""
        with store.lock:
            return bool(store.db.execute(
                "SELECT 1 FROM docs WHERE kind='job' AND json_extract(body,'$.tool')='session_op' "
                "AND json_extract(body,'$.input.op')='stop_game' AND json_extract(body,'$.input.session_id')=? "
                "AND json_extract(body,'$.state') IN ('queued','running','succeeded') LIMIT 1",
                (sid,)).fetchone())

    # --- requests inbox: operator reports (screenshot / eyedropper / chat) <-> agent, with per-request metrics ---
    class RequestIn(BaseModel):
        title: str
        body: str = ""
        source: str = "app"                # app | chat | api
        kind: str = "text"                 # text | screenshot | element
        image_b64: str | None = None       # annotated PNG
        element: dict | None = None        # eyedropper: selector, text, rect, view...
        context: dict = {}                 # app state: tab, session, url, window size...
        author: str = "operator"
        parent_request_id: str | None = None
        automated: bool = False
        attachments: list[dict] = []       # [{name, b64}] pasted / dropped images

    class MessageIn(BaseModel):
        author: str                        # operator | agent
        text: str
        attachments: list[dict] = []
        task_step: dict | None = None       # action, attempt, result, status for report detail

    def _attach(rid: str, items: list[dict]) -> list[dict]:
        out = []
        for a in items[:20]:
            if a.get("sha256") and not a.get("b64"):        # an artifact gBox already holds (a replay clip, #1084)
                meta = store.get("artifact", str(a["sha256"]))
                if not meta:
                    raise HTTPException(422, f"unknown artifact {str(a['sha256'])[:12]}")
                out.append({"sha256": meta["sha256"], "name": a.get("name") or meta.get("name"),
                            "type": a.get("type") or meta.get("media_type"), "size": meta.get("size")})
                continue
            name = a.get("name") or "image.png"
            mt = a.get("type") or ("image/png" if name.lower().endswith(".png") else "application/octet-stream")
            ref = store.put_artifact(base64.b64decode(a["b64"]), name, mt, {"request": rid, "attachment": True})
            out.append({"sha256": ref.sha256, "name": name, "type": mt, "size": ref.size})
        return out

    class SolverIn(BaseModel):
        service: str = Field(min_length=1, max_length=80)
        model: str = Field(default="", max_length=160)
        system: str = Field(default="Hermes", max_length=80)
        verified_by: str = Field(default="", max_length=80)
        verification: str = Field(min_length=1, max_length=2000)
        run_id: str | None = Field(default=None, max_length=80)

    class StatusIn(BaseModel):
        status: str                        # open | in_progress | done | blocked
        note: str = ""
        solved_by: SolverIn | None = None  # implementation credit, separate from its reviewer

    class MetricsIn(BaseModel):
        model: str | None = None
        provider: str | None = None
        system: str | None = None
        tokens_in: int | None = None       # incl. cache reads/writes, from the agent transcript
        tokens_out: int | None = None
        tokens_detail: dict = {}
        tools: dict[str, int] = {}         # tool name -> calls
        files_changed: list[str] = []
        duration_s: float | None = None
        turns: int | None = None

    REQ_STATES = ("open", "in_progress", "done", "blocked")

    def _req(rid: str) -> dict:
        return store.get("request", rid) or _404()

    @app.post("/api/requests")
    def req_create(r: RequestIn, actor=Depends(auth)):
        from . import inbox
        parent = r.parent_request_id or r.context.get("parent_request_id") or r.context.get("request_id")
        if not parent and r.context.get("job_id"):
            parent = (store.get("job", r.context["job_id"]) or {}).get("parent_request_id")
        if parent and not store.get("request", parent):
            raise HTTPException(404, "parent request not found")
        rid = new_id()
        r.title, r.body = _redact(r.title), _redact(r.body)
        img = None
        if r.image_b64:
            img = store.put_artifact(base64.b64decode(r.image_b64), f"request-{rid}.png", "image/png",
                                     {"request": rid, "kind": r.kind}).sha256
        n = len(store.all("request")) + 1
        doc = {"id": rid, "number": n, "title": r.title, "body": r.body, "source": r.source, "kind": r.kind,
               "image": img, "element": r.element, "context": r.context, "status": "open", "created": time.time(),
               "started": None, "completed": None, "author": r.author,
               "parent_request_id": parent, "automated": r.automated,
               "messages": [{"author": r.author, "text": r.body, "ts": time.time(), "attachments": _attach(rid, r.attachments)}]
                           if (r.body or r.attachments) else [],
               "metrics": {"tokens_in": 0, "tokens_out": 0, "tools": {}, "files_changed": [], "duration_s": None, "turns": 0}}
        doc["automated"] = inbox.automated(doc)
        doc["parent_request_id"] = inbox.parent_for(doc, store.all("request"))
        store.put("request", rid, doc)
        store.audit(actor, "request.create", rid, {"title": r.title, "kind": r.kind, "source": r.source})
        return _clean(doc)

    class IssueIn(BaseModel):
        session_id: str = ""
        save_state: bool = True            # capture the exact game moment unless the operator opts out
        what: str                          # the option the operator right-clicked ("Use in this game", a mod, ...)
        detail: str = ""                   # what the card around it showed (its status / output line)
        note: str = ""                     # optional words from the operator
        element: dict | None = None
        title: str = ""                    # overrides "Doesn't work in <game>: <what>"
        image_b64: str | None = None       # the app's own OS-level screenshot (incl. the docked game); else a session frame
        attachments: list[dict] = []       # [{name, b64, type}] e.g. the desktop app's console output
        context: dict = {}                 # app state (tab, window, worker...)
        mods_on: list[str] = []            # mod cards showing as on / applied in the app ("title: status")
        kept_mods: list[str] = []          # mod ids the operator keeps on for this game

    def _issue_log(sid: str, s_: dict) -> tuple[str, str]:
        """The session's emulator log tail (worker session_op log_tail); a Spark session's log file is also readable here.

        An offline worker gets no log_tail job at all, and a job the worker did not pick up within 15 s is
        retired with an honest reason. Earlier, every capture-icon click while the worker was offline queued
        a job, waited 15 s, and recorded it as "failed: cancelled by the operator", so repeated reports stacked
        those failures (#1130)."""
        wid = _wid(sid.split("-")[0])
        w = store.get("worker", wid) or {}
        age = time.time() - float(w.get("last_seen") or 0)
        if not w or age >= WORKER_TTL:
            why = (f"log_tail skipped: worker {w.get('name') or wid} is offline"
                   + (f" (last seen {int(age)} s ago)" if w.get("last_seen") else "") + "; no log job queued")
        else:
            try:
                j = submit(JobRequest(tool="session_op", input={"session_id": sid, "op": "log_tail", "args": {"n": 60000}},
                                      require_worker=wid), "issue")
                with store.lock:
                    cur = store.get("job", j.id)
                    store.put("job", j.id, cur | {"issue_internal": True})
                t0 = time.time()
                while (jj := store.get("job", j.id))["state"] in ("queued", "running") and time.time() - t0 < 15:
                    time.sleep(0.4)
                if jj["state"] == "succeeded":
                    res = (jj.get("output") or {}).get("result") or {}
                    if res.get("log"):
                        return res["log"], res.get("path") or ""
                    why = f"the {res.get('emulator') or 'emulator'} keeps no log gBox can read"
                elif jj["state"] in ("queued", "running"):
                    why = f"log_tail: worker {w.get('name') or wid} did not answer within 15 s"
                    with store.lock:
                        cur = store.get("job", j.id) or jj
                        if cur["state"] == JobState.QUEUED:
                            cur.update(state=JobState.FAILED, finished=time.time(), issue_internal=True,
                                       error="issue report stopped waiting for the log (worker busy); not an operator cancel")
                        elif cur["state"] == JobState.RUNNING:
                            # A running read can finish normally. Cancelling it would
                            # recreate the misleading operator-cancel failure.
                            cur.update(issue_internal=True, issue_log_wait_expired=True)
                        store.put("job", j.id, cur)
                else:
                    why = f"log_tail: {jj.get('error') or jj['state']}"
            except Exception as e:                        # noqa: BLE001
                why = f"log_tail: {e}"
        f = Path(str((s_.get("detail") or {}).get("log") or ""))
        try:
            if f.name and f.is_file():
                return f.read_text(errors="replace")[-60000:], str(f)
        except OSError:
            pass
        return "", why

    def _issue_chat(sid: str) -> list[str]:
        """Conversation tool calls that touched this session (newest last), with their results."""
        out = []
        for c in store.all("chat"):
            ev = c.get("events") or []
            for i, e in enumerate(ev):
                if e.get("type") != "tool_call" or (e.get("args") or {}).get("session_id") != sid:
                    continue
                res = next((x for x in ev[i + 1:i + 40] if x.get("type") == "error"
                            or (x.get("type") == "tool_result" and x.get("name") == e.get("name"))), {})
                out.append((e.get("ts") or 0, f"- [{c['id'][:8]}] {e.get('name')} {json.dumps(e.get('args'))[:300]}"
                                              + (f"\n  -> {(res.get('text') or '')[:500]}" if res else "")))
        return [t for _, t in sorted(out, key=lambda x: x[0])[-15:]]

    @app.post("/api/requests/issue")
    def req_issue(r: IssueIn, actor=Depends(auth)):
        s_ = store.get("session", r.session_id) or {} if r.session_id else {}
        capture_key = json.dumps({k: getattr(r, k) for k in (
            "what", "detail", "note", "title", "element", "mods_on", "kept_mods")}, sort_keys=True)
        if r.save_state and r.session_id:
            # Repeated capture-icon clicks while a save-state capture is already in flight
            # stacked duplicate reports and jobs (the "failing endlessly" pileup). Reuse the
            # newest in-flight report for this session instead of creating another one.
            pending = None
            for old in store.all("request"):
                ctx = old.get("context") or {}
                if (ctx.get("session_id") != r.session_id or not ctx.get("state_job_id")
                        or ctx.get("issue_capture_key") != capture_key or old.get("status") == "done"):
                    continue
                job = store.get("job", ctx["state_job_id"])
                if job and job.get("state") in ("queued", "running"):
                    if pending is None or old.get("created", 0) > pending.get("created", 0):
                        pending = old
            if pending:
                rid, now = pending["id"], time.time()
                # Reuse the pending save job, while preserving every subsequent capture's
                # screenshot, diagnostics and context. A distinct issue gets a new report.
                attachments = _attach(rid, r.attachments)
                if r.image_b64:
                    attachments += _attach(rid, [{"name": "repeat-capture.png", "type": "image/png",
                                                   "b64": r.image_b64}])
                snapshot = r.model_dump(exclude={"image_b64", "attachments"}) | {"captured_at": now, "session": s_}
                ref = store.put_artifact(json.dumps(snapshot, ensure_ascii=False, indent=2).encode(),
                                         "repeat-capture-context.json", "application/json", {"request": rid})
                attachments.append({"sha256": ref.sha256, "name": ref.name, "type": "application/json", "size": ref.size})
                with store.lock:
                    latest = store.get("request", rid) or pending
                    latest.setdefault("messages", []).append({"author": "operator",
                        "text": f"Repeated capture: {r.what}" + (f"\n{r.detail}" if r.detail else "")
                                + (f"\n{r.note}" if r.note else ""), "ts": now, "attachments": attachments})
                    store.put("request", rid, latest)
                    store.audit(actor, "request.capture_reused", rid, {"state_job_id": latest["context"]["state_job_id"]})
                    return _clean(latest)
        game = s_.get("title") or s_.get("game_title") or r.context.get("game") or "no game running"
        since = (s_.get("started") or s_.get("created") or time.time() - 3600) - 5
        jobs = sorted((j for j in store.all("job") if (j.get("input") or {}).get("session_id") == r.session_id
                       or (s_.get("game_id") and (j.get("input") or {}).get("game_id") == s_.get("game_id") and j.get("created", 0) >= since)),
                      key=lambda j: j.get("created", 0)) if r.session_id else []
        jobs = [j for j in jobs if j.get("tool") != "get_frame" and not j.get("issue_internal")][-20:]
        lines = [f"## What the operator tried\n{r.what}" + (f"\n\n{r.note}" if r.note else ""),
                 f"## Game\n{game} (game_id {s_.get('game_id') or r.context.get('game_id') or '?'}, {s_.get('platform') or s_.get('system') or '?'}, "
                 f"emulator {s_.get('adapter') or s_.get('emulator') or '?'}, session {r.session_id or '-'}, worker {(r.session_id or '-').split('-')[0]})"]
        if r.detail:
            lines.append(f"## What gBox showed\n{r.detail}")
        if r.session_id and s_.get("mod"):
            lines.append(f"## Disc / model mod this session was launched with\n{s_['mod']}")
        kept = [(store.get("mod", m) or {"title": m}) for m in r.kept_mods[:30]]
        if r.mods_on or kept:
            lines.append("## Active mods\n" + "\n".join([f"- on in the app: {m[:300]}" for m in r.mods_on[:30]]
                + [f"- kept on: {m.get('title')} ({', '.join(c.get('tool', '?') for c in m.get('calls') or [])})" for m in kept]))
        if jobs:
            lines.append("## Recent gBox jobs for this game\n" + "\n".join(
                f"- {j['tool']} [{j['state']}] input={json.dumps(j.get('input'))[:300]}"
                + (f"\n  error: {j['error'][:600]}" if j.get("error") else "")
                + (f"\n  result: {json.dumps((j.get('output') or {}).get('result'))[:600]}" if (j.get("output") or {}).get("result") else "")
                for j in jobs))
        atts = list(r.attachments)
        if r.session_id:
            if chat := _issue_chat(r.session_id):
                lines.append("## Conversation tool calls on this session\n" + "\n".join(chat))
            log, where = _issue_log(r.session_id, s_)
            if log:
                atts.append({"name": "emulator-log.txt", "type": "text/plain", "b64": base64.b64encode(log.encode("utf-8", "replace")).decode()})
                lines.append(f"## Emulator log\nAttached: emulator-log.txt ({where}, last {len(log)} chars). Last lines:\n"
                             + "\n".join(log.rstrip().splitlines()[-15:]))
            else:
                lines.append(f"## Emulator log\nnone ({where})")
        if any(a.get("name") == "desktop-console.txt" for a in atts):
            lines.append("## Desktop app console\nAttached: desktop-console.txt")
        img = r.image_b64
        if r.session_id and not img:
            try:
                img = base64.b64encode(_session_png(r.session_id)).decode()
            except Exception:                         # noqa: BLE001  (no frame: the report still goes in)
                pass
        report = req_create(RequestIn(title=(r.title or f"Doesn't work in {game}: {r.what}")[:140], body="\n\n".join(lines), source="app",
                                      kind="screenshot" if img else "element", image_b64=img, element=r.element, attachments=atts,
                                      context=r.context | {"session_id": r.session_id, "game_id": s_.get("game_id") or r.context.get("game_id"),
                                                           "game": game,
                                                           "save_state_requested": r.save_state,
                                                           "issue_capture_key": capture_key}), actor)
        if not r.save_state or not r.session_id or s_.get("state") != "running":
            return report
        rid = report["id"]
        try:
            # A dedicated slot leaves the operator's ordinary quick save alone. The job is linked to the
            # report so Hermes can wait for its actual result before trying to reproduce the failure.
            slot = 60 + sum(1 for old in store.all("request") if old["id"] != rid and
                            (old.get("context") or {}).get("session_id") == r.session_id and
                            (old.get("context") or {}).get("state_job_id"))
            saved = submit(JobRequest(tool="session_op", input={"session_id": r.session_id, "op": "save_state", "args": {"slot": slot}},
                                      parent_request_id=rid), actor)
            report["context"].update(state_job_id=saved.id, state_slot=slot)
            report["messages"].append({"author": "agent", "text": f"Capturing the reported game moment in slot {slot} (job {saved.id}).",
                                       "ts": time.time(), "attachments": [], "task_step": {"action": "save reported game moment",
                                       "attempt": "1", "result": saved.state, "status": saved.state}})
            store.put("request", rid, report)

            # Supported cores can also export a portable artifact for Hermes or a client on another PC.
            # Upload the existing checkpoint; saving again would capture a later game moment.
            if (s_.get("adapter") or "").lower() in ("retroarch", "dolphin"):
                def export_issue_state():
                    deadline = time.time() + 120
                    while time.time() < deadline:
                        current = store.get("job", saved.id) or {}
                        if current.get("state") not in ("queued", "running"):
                            break
                        time.sleep(0.5)
                    if current.get("state") != "succeeded":
                        return
                    try:
                        # the checkpoint job reports the slot the emulator ACTUALLY wrote; export that one
                        saved_slot = _checkpoint_slot((current.get("output") or {}).get("result") or {},
                                                      (s_.get("adapter") or "").lower())
                        exported = submit(JobRequest(tool="state_transfer", input={"session_id": r.session_id,
                                                     "op": "export_saved", "slot": saved_slot,
                                                     "not_before": current.get("started") or current.get("created") or 0},
                                                     parent_request_id=rid), actor)
                        with store.lock:
                            latest = store.get("request", rid) or {}
                            if not latest:
                                return
                            latest.setdefault("context", {}).update(state_export_job_id=exported.id,
                                state_slot=saved_slot, state_requested_slot=slot)
                            latest.setdefault("messages", []).append({"author": "agent", "text": f"Portable save-state export queued (job {exported.id}).",
                                "ts": time.time(), "attachments": [], "task_step": {"action": "export reported game moment",
                                "attempt": "1", "result": exported.state, "status": exported.state}})
                            store.put("request", rid, latest)
                    except Exception as exc:
                        with store.lock:
                            latest = store.get("request", rid) or {}
                            if latest:
                                latest.setdefault("messages", []).append({"author": "agent", "text": f"Portable export unavailable: {exc}",
                                    "ts": time.time(), "attachments": []})
                                store.put("request", rid, latest)
                threading.Thread(target=export_issue_state, daemon=True, name=f"issue-state-{rid[:8]}").start()
        except Exception as exc:
            report["messages"].append({"author": "agent", "text": f"Save state unavailable: {exc}", "ts": time.time(), "attachments": []})
            store.put("request", rid, report)
        return report

    def _build_report(issue: dict, details: str, actor: str) -> dict:
        """A ⚑ build report (gbox.builds): filed like any issue report, then sent to the investigation queue the launch
        failure reports use (_lf_investigate: the top of the Hermes work queue, or dispatched now in task mode)."""
        existing_id = issue.pop('existing_report_id', None)
        filed = store.get('request', existing_id) if existing_id else None
        if filed:
            filed['status'] = 'open'
            filed.setdefault('messages', []).append({'author': actor, 'text': issue.get('detail') or details,
                                                     'ts': time.time(), 'attachments': []})
            store.put('request', existing_id, filed)
        else:
            filed = req_issue(IssueIn(**issue), actor)
        rid = filed["id"]
        report = store.get("request", rid) or filed
        try:
            out = _lf_investigate(rid, report.get("number") or 0, details, name=f"gBox build report #{report.get('number')}")
            report = store.get("request", rid) or report
            report.setdefault("context", {})["resolution_dispatch"] = "hermes_queue" if out.get("mode") == "queue" else "hermes_dispatch"
            if out.get("job_id"):
                report["context"]["resolution_job_id"] = out["job_id"]
            text = ("Build report queued for Hermes (work queue position %d): reproduce it on the agent test PC, find why the "
                    "build doesn't do what it should, rebuild it or fix its writer, and verify in game." % ((out.get("priority") or 0) + 1))
            report.setdefault("messages", []).append({"author": "agent", "text": text, "ts": time.time(), "attachments": [],
                "task_step": {"action": "dispatch investigation", "attempt": "1", "result": out.get("mode") or "",
                              "status": "queued" if out.get("mode") == "queue" else "running"}})
        except Exception as exc:                                 # noqa: BLE001 - the report is filed either way
            report = store.get("request", rid) or report
            report.setdefault("messages", []).append({"author": "agent", "text": f"Investigation dispatch failed: {exc}",
                                                      "ts": time.time(), "attachments": []})
        store.put("request", rid, report)
        return report

    class AutoFailureIn(BaseModel):
        session_id: str = ""
        game: str = ""
        model: str = ""
        action: str = "model replacement"
        target: str = ""
        moment: str = ""
        detail: str = ""
        image_b64: str | None = None
        job_id: str = ""
        character: str = ""
        target_kind: str = ""
        x: float | None = Field(default=None, ge=0, le=1)
        y: float | None = Field(default=None, ge=0, le=1)
        needs_rebuild: bool = False
        replacement_requested: bool = False

    @app.post("/api/requests/auto-mod-failure")
    def req_auto_mod_failure(f: AutoFailureIn, actor=Depends(auth)):
        """File visual evidence, preserve the current moment, and dispatch an agent to resolve a failed swap."""
        failed_launch = store.get("job", f.job_id) if f.job_id else None
        if failed_launch and failed_launch.get("tool") in ("launch_game", "session_swap") \
                and failed_launch.get("state") in ("failed", "invalid", "rejected"):
            # a client reporting a failed launch / swap: the launch failure report for it (one ticket per failure
            # signature, gbox/launch_failures.py) gets the client's words and screenshot instead of a second ticket
            rec = launch_ledger.observe_job(failed_launch)
            if rec:
                rid = rec["request_id"]
                atts = _attach(rid, [{"name": "client-screenshot.png", "type": "image/png", "b64": f.image_b64}]) \
                    if f.image_b64 else []
                with store.lock:
                    cur = store.get("request", rid) or {}
                    cur.setdefault("messages", []).append({"author": "agent", "text": "Reported by the app: "
                        + (f.detail or f.action)[:2000], "ts": time.time(), "attachments": atts})
                    store.put("request", rid, cur)
                store.audit(actor, "request.auto_mod_failure.launch", rid, {"job": f.job_id})
                return _clean(store.get("request", rid))
        s_ = store.get("session", f.session_id) or {} if f.session_id else {}
        game = f.game or s_.get("title") or s_.get("game_title") or "unknown game"
        details = (f"Action: {f.action}\nGame: {game} (game_id: {s_.get('game_id') or '?'})\n"
                   f"Model: {f.model or 'not identified'}\nTarget: {f.target or 'not identified'}\n"
                   f"Moment: {f.moment or 'current game frame'}\nSession: {f.session_id or 'none'}\n"
                   f"Failed job: {f.job_id or 'direct action'}\nFailure: {f.detail or 'action did not complete'}")
        with store.lock:
            existing = next((x for x in store.all("request") if x.get("source") == "automation"
                             and (x.get("context") or {}).get("job_id") == f.job_id), None) if f.job_id else None
            if existing:
                context = existing.setdefault("context", {})
                for key in ("character", "target", "target_kind", "x", "y"):
                    value = getattr(f, key)
                    if value is not None and value != "":
                        context[key] = value
                if f.needs_rebuild:
                    context["needs_rebuild"] = True
                if f.image_b64 and not existing.get("image"):
                    existing["messages"].append({"author": "agent", "text": f.detail or "Additional failure screenshot", "ts": time.time(),
                        "attachments": _attach(existing["id"], [{"name": "failed-moment.png", "type": "image/png", "b64": f.image_b64}])})
                store.put("request", existing["id"], existing)
                return _clean(existing)
            title = (f"Character replacement: {f.model} in {game}" if f.replacement_requested else
                     f"Auto report: {f.action} failed in {game}")
            report = req_create(RequestIn(title=title[:140], body=details,
                source="automation", kind="screenshot" if f.image_b64 else "text", image_b64=f.image_b64,
                author="system", automated=True, context={"session_id": f.session_id, "session": f.session_id, "game_id": s_.get("game_id"),
                                                            "game": game, "model": f.model, "moment": f.moment,
                                                            "character": f.character, "target": f.target,
                                                            "target_kind": f.target_kind, "x": f.x, "y": f.y,
                                                            "needs_rebuild": f.needs_rebuild, "native_replacement": True,
                                                            "replacement_requested": f.replacement_requested,
                                                            "job_id": f.job_id, "auto_report": True}), actor)
        rid = report["id"]
        if f.session_id and s_.get("state") == "running":
            try:
                slot = 40 + sum(1 for old in store.all("request") if old["id"] != rid and
                                (old.get("context") or {}).get("session_id") == f.session_id and
                                (old.get("context") or {}).get("auto_report"))
                saved = submit(JobRequest(tool="session_op", input={"session_id": f.session_id, "op": "save_state", "args": {"slot": slot}},
                                          parent_request_id=rid), actor)
                report["context"]["state_job_id"] = saved.id
                report["context"]["state_slot"] = slot
                report["messages"].append({"author": "agent", "text": f"Save state requested for this moment (job {saved.id}, slot {slot}). Its result is shown in the detailed report.",
                                           "ts": time.time(), "attachments": [], "task_step": {"action": "save game moment", "attempt": "1", "result": saved.state, "status": saved.state}})
            except Exception as exc:
                report["messages"].append({"author": "agent", "text": f"Save state unavailable: {exc}", "ts": time.time(), "attachments": []})
        store.put("request", rid, report)
        from . import hermes_task_mode
        controller = hermes_task_mode._job() or {}
        managed = bool(controller.get("no_agent"))
        try:
            prompt = (f"Resolve gBox auto report #{report['number']} ({rid}). {details}\n"
                      "Inspect the exact failure, fix the relevant model writer or mod path, verify the result in the game, "
                      "attach screenshots to this request, report each attempt and outcome, record actual token usage, "
                      "and mark the request done only after verification. Preserve the operator's running game and save state.")
            if managed:
                report["context"]["resolution_dispatch"] = "hermes_queue"
                report["messages"].append({"author": "agent", "text":
                    "Native replacement queued for Hermes. Identify the selected actor, repair or rebuild its native "
                    "assets, and verify this donor in gameplay. Preview and overlay do not complete this request.",
                    "ts": time.time(), "attachments": [], "task_step": {"action": "dispatch resolution",
                    "attempt": "1", "result": "durable Hermes queue", "status": "queued"}})
            else:
                chat = hub.get(new_id())
                store.put("chat", chat["id"], chat)
                hub.post(chat["id"], prompt, {"request_id": rid, "session_id": f.session_id,
                                          "resolve_auto_report": True}, api_requests, None, [])
                report = store.get("request", rid) or report
                report["context"]["resolution_chat_id"] = chat["id"]
                report["status"], report["started"] = "in_progress", time.time()
                report["messages"].append({"author": "agent", "text": f"Resolution agent dispatched (chat {chat['id']}).", "ts": time.time(), "attachments": [],
                                       "task_step": {"action": "dispatch resolution", "attempt": "1", "result": chat["id"], "status": "running"}})
        except Exception as exc:
            report = store.get("request", rid) or report
            report["messages"].append({"author": "agent", "text": f"Resolution dispatch failed: {exc}", "ts": time.time(), "attachments": []})
        store.put("request", rid, report)
        store.audit(actor, "request.auto_mod_failure", rid, {"session": f.session_id, "job": f.job_id, "model": f.model})
        if f.session_id and s_.get("state") == "running":
            def _preserve_failure():
                def add(text, action, result, status, attachment=None, **context):
                    with store.lock:
                        latest = store.get("request", rid)
                        if not latest:
                            return
                        latest.setdefault("context", {}).update(context)
                        latest.setdefault("messages", []).append({"author": "agent", "text": text, "ts": time.time(),
                            "attachments": [attachment] if attachment else [],
                            "task_step": {"action": action, "attempt": "1", "result": result, "status": status}})
                        store.put("request", rid, latest)

                def completed(jid, seconds=120):
                    deadline = time.time() + seconds
                    while time.time() < deadline:
                        job = store.get("job", jid) or {}
                        if job.get("state") not in ("queued", "running"):
                            return job
                        time.sleep(.5)
                    return {"state": "timeout", "error": "checkpoint job timed out"}

                try:
                    saved_id = (store.get("request", rid) or {}).get("context", {}).get("state_job_id")
                    saved_job = completed(saved_id) if saved_id else {"state": "unavailable"}
                    frame = next((a for a in store.all("artifact") if (a.get("provenance") or {}).get("job") == saved_id
                                  and a.get("media_type") == "image/png"), None) if saved_id else None
                    if frame:
                        att = {"sha256": frame["sha256"], "name": frame["name"], "type": "image/png", "size": frame["size"]}
                        add("Game frame captured with the save-state attempt.", "capture failed moment",
                            "game frame attached", "finished", att)
                    else:
                        try:
                            asyncio.run(req_capture(rid, RequestCaptureIn(session_id=f.session_id,
                                text="Automatic game screenshot after the failed action",
                                task_step={"action": "capture failed moment", "attempt": "1",
                                           "result": "game frame attached", "status": "finished"}), "gbox-auto"))
                        except Exception as exc:
                            add(f"Game screenshot unavailable: {exc}", "capture failed moment", str(exc)[:400], "failed")
                    if saved_job.get("state") != "succeeded":
                        add(f"Save state failed: {saved_job.get('error') or saved_job.get('state')}",
                            "save game moment", str(saved_job.get("error") or saved_job.get("state"))[:400], "failed")
                        return
                    if (s_.get("adapter") or "").lower() not in ("retroarch", "dolphin"):
                        add("This emulator cannot export a portable state; the local checkpoint remains available.",
                            "export game moment", "unsupported emulator", "unavailable")
                        return
                    # the checkpoint job reports the slot the emulator ACTUALLY wrote; export exactly that file
                    saved_slot = _checkpoint_slot((saved_job.get("output") or {}).get("result") or {},
                                                  (s_.get("adapter") or "").lower())
                    exported = submit(JobRequest(tool="state_transfer", input={"session_id": f.session_id,
                        "op": "export_saved", "slot": saved_slot, "not_before": saved_job.get("started") or 0},
                        parent_request_id=rid), "gbox-auto")
                    add(f"Exporting the exact saved checkpoint (job {exported.id}).", "export game moment",
                        exported.id, exported.state, state_export_job_id=exported.id,
                        state_slot=saved_slot, state_requested_slot=slot)
                    result = completed(exported.id)
                    if result.get("state") != "succeeded":
                        add(f"Portable checkpoint unavailable: {result.get('error') or result.get('state')}",
                            "export game moment", str(result.get("error") or result.get("state"))[:400], "failed")
                        return
                    info = (result.get("output") or {}).get("result") or {}
                    meta = store.get("artifact", info.get("artifact")) if info.get("artifact") else None
                    if not meta:
                        raise RuntimeError("checkpoint export did not upload its artifact")
                    att = {"sha256": meta["sha256"], "name": meta["name"], "type": meta["media_type"], "size": meta["size"]}
                    actual_slot = _checkpoint_slot(info, (s_.get("adapter") or "").lower())
                    if actual_slot != saved_slot:
                        raise RuntimeError("the portable export belongs to a different saved moment")
                    add(f"Portable save state attached: {info['file']} ({info['bytes']} bytes).",
                        "export game moment", "checkpoint attached", "finished", att,
                        state_artifact=meta["sha256"], state_file=info["file"], state_slot=actual_slot)
                except Exception as exc:
                    add(f"Automatic evidence preservation failed: {exc}", "preserve failed moment", str(exc)[:400], "failed")
            threading.Thread(target=_preserve_failure, daemon=True, name=f"auto-failure-{rid[:8]}").start()
        return _clean(report)

    from . import emulation_issue

    def _incident_job(tool, inp, worker, wait, parent, actor):
        job = submit(JobRequest(tool=tool, input=inp, require_worker=worker,
                                parent_request_id=parent, agent_use=True), actor)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            current = store.get('job', job.id) or {}
            if current.get('state') not in ('queued', 'running'):
                if current.get('state') != 'succeeded':
                    raise RuntimeError(f"{tool}: {current.get('error') or current.get('state')}")
                return current.get('output') or {}
            time.sleep(.25)
        job_cancel(job.id, actor)
        raise RuntimeError(f'{tool}: diagnostic/recovery job timed out ({job.id})')

    def _incident_dispatch(rid, number):
        from .hermes_task_mode import dispatch_request
        return dispatch_request(rid, number)

    emulation_issue.routes(app, store, auth, lambda body, actor: req_create(RequestIn(**body), actor),
                           _incident_job, _incident_dispatch)

    # --- launch failure reports (gbox/launch_failures.py, docs/launch-failure-reports.md) ---
    from . import launch_failures as LF

    def _lf_submit(tool, inp, worker_id):
        return submit(JobRequest(tool=tool, input=inp, require_worker=worker_id), "gbox-auto").model_dump(mode="json")

    def _lf_priority(change):
        """Edit the Hermes work queue's operator priority list under its lock (the cron pump holds it while it runs)."""
        from . import hermes_delivery, hermes_work_queue
        for _ in range(30):
            try:
                with hermes_delivery.locked("work-queue"):
                    return hermes_work_queue.set_priority(change(hermes_work_queue.get_priority()))
            except OSError:
                time.sleep(2)
        raise RuntimeError("the Hermes work queue stayed locked for a minute")

    def _lf_investigate(rid, number, task, attempt=1, name=""):
        """The investigation queue: the request goes to the top of the Hermes work queue and, in Hermes task mode, is
        dispatched now. Launch failure reports (#318) and ⚑ build reports (#1656) use it."""
        from . import hermes_task_mode
        ids = _lf_priority(lambda cur: [rid] + [x for x in cur if x != rid])
        controller = hermes_task_mode._job() or {}
        if controller.get("no_agent") or not controller.get("enabled"):
            # the managed work queue dispatches it on its next tick; with Hermes task mode off it waits there first
            return {"mode": "queue", "job_id": None, "priority": ids.index(rid)}
        # a reopened ticket is a new attempt: a finished job of the same name would otherwise be returned as is
        jid = hermes_task_mode.dispatch_request(rid, number, task=task, name=(name or f"gBox launch failure #{number}")
                                                + (f" attempt {attempt}" if attempt > 1 else ""))
        return {"mode": "dispatch", "job_id": jid, "priority": ids.index(rid)}

    def _lf_queue_job(rid):
        from . import hermes_work_queue
        try:
            item = (hermes_work_queue._read().get("items") or {}).get("inbox:" + rid) or {}
        except (OSError, ValueError):
            return None
        return item.get("job_id") if item.get("dispatch_state") in ("queued", "finished") else None

    from . import live_controls_api
    live_controls_api.routes(app, store, auth, submit, JobRequest,
        create_request=lambda body: req_create(RequestIn(**body), 'operator'), investigate=_lf_investigate)

    from . import custom_build_unlocks
    app.state.reconcile_build_unlocks = custom_build_unlocks.routes(
        app, store, config, auth,
        create_request=lambda body: req_create(RequestIn(**body), 'operator'),
        investigate=_lf_investigate, workers=workers)

    def _lf_verify(rec, node):
        from . import evidence_capture as EC
        inp = EC.EvidenceIn.model_validate({
            "game_id": rec["game_id"], "mod": rec.get("mod") or "", "node": node, "inputs": [], "load_moment": "none",
            "shots": [{"label": "verification", "at_s": 20}], "compare_stock": False, "boot_s": 10}).model_dump(mode="json")
        try:
            return evidence_job(inp, "gbox-launch-verify").model_dump(mode="json")
        except HTTPException as e:
            raise RuntimeError(str(e.detail)) from e

    def _lf_deployed(sha):
        """True when the Spark's deployed main (scripts/deploy_main.sh) contains the commit and no restart is pending;
        None when this machine keeps no deploy record."""
        head_file = Path(config.data_dir) / "deployed-main.txt"
        if not sha or not head_file.is_file():
            return None
        if (Path(config.data_dir) / "deploy-restart-pending").exists():
            return False                             # on the share, but the service still runs the old code
        head = head_file.read_text().strip()
        if head.startswith(sha):
            return True
        from . import hermes_delivery
        for repo in (Path.home() / "gBox-src", hermes_delivery.repository()):
            if (repo / ".git").exists():
                r = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", sha, head],
                                   capture_output=True, timeout=30)
                if r.returncode in (0, 1):
                    return r.returncode == 0
        return None

    def _lf_last_frame(sid):
        from .session_images import as_png
        lv = live.get(sid) or {}
        if lv.get("frame"):
            try:
                return as_png(lv["frame"])
            except Exception:                         # noqa: BLE001
                pass
        with store.lock:
            row = store.db.execute(
                "SELECT json_extract(body,'$.sha256') FROM docs WHERE kind='artifact' AND "
                "(json_extract(body,'$.provenance.session')=? OR json_extract(body,'$.provenance.session_id')=?) "
                "AND json_extract(body,'$.media_type') LIKE 'image/%' ORDER BY rowid DESC LIMIT 1", (sid, sid)).fetchone()
        return store.read_artifact(row[0]) if row and row[0] else None

    def _lf_swap_parent(job):
        gid = (((job.get("input") or {}).get("game")) or {}).get("game_id")
        t = job.get("created") or 0
        with store.lock:
            rows = store.db.execute(
                "SELECT json_extract(body,'$.id'), json_extract(body,'$.finished') FROM docs WHERE kind='job' "
                "AND json_extract(body,'$.tool')='session_swap' AND json_extract(body,'$.input.game_id')=? "
                "AND COALESCE(json_extract(body,'$.started'),json_extract(body,'$.created'),0) <= ?", (gid, t + 1)).fetchall()
        return next((jid for jid, fin in rows if fin is None or fin >= t - 1), None)

    launch_ledger = LF.Ledger(store, LF.Hooks(
        create_request=lambda body: req_create(RequestIn(**body), "gbox-auto"), workers=workers, submit_job=_lf_submit,
        investigate=_lf_investigate, queue_job_of=_lf_queue_job,
        unprioritize=lambda rid: _lf_priority(lambda cur: [x for x in cur if x != rid]),
        verify_launch=_lf_verify, deploy_contains=_lf_deployed, last_frame=_lf_last_frame, swap_parent=_lf_swap_parent))
    app.state.launch_ledger = launch_ledger

    def _lf_observe_later(jid):
        def go():
            try:
                job = store.get("job", jid)
                if job:
                    launch_ledger.observe_job(job)
            except Exception as exc:                  # noqa: BLE001 - a report never breaks result handling
                store.audit("gbox-auto", "launch_failure.error", jid, {"error": f"{type(exc).__name__}: {exc}"[:500]})
        threading.Thread(target=go, daemon=True, name=f"launch-failure-{jid[:8]}").start()

    @app.on_event("startup")
    async def _launch_failure_loop():
        if os.environ.get("GBOX_LAUNCH_FAILURES", "1") == "0":
            return

        def loop():
            time.sleep(90)                            # workers re-register first; a test server is long gone by then
            while True:
                try:
                    launch_ledger.scan(time.time() - 3600)    # failures no hook saw (worker restart, timeouts, retired)
                    launch_ledger.tick()
                except Exception as exc:              # noqa: BLE001
                    print(f"gBox: launch failure loop: {type(exc).__name__}: {exc}", flush=True)
                time.sleep(60)
        threading.Thread(target=loop, daemon=True, name="launch-failures").start()

    @app.get("/api/launch-failures")
    def launch_failures_list(game_id: str = "", job_id: str = "", actor=Depends(auth)):
        """Launch failure tickets (newest first) with the badge each client shows; ?job_id= the one for a launch job."""
        if job_id:
            mark = store.get(LF.JOB_KIND, job_id) or {}
            rec = store.get(LF.KIND, mark.get("signature") or "")
            return {"job_id": job_id, "report": launch_ledger.summary(rec) if rec else None,
                    "skipped": mark.get("skipped")}
        recs = [r for r in store.all(LF.KIND) if not game_id or r.get("game_id") == game_id]
        recs.sort(key=lambda r: -(r.get("last_seen") or 0))
        return {"settings": launch_ledger.settings(), "items": [launch_ledger.summary(r) | {
            k: r.get(k) for k in ("game_id", "title", "mod", "adapter", "worker", "first_seen", "remedies", "hermes",
                                  "pr", "verify", "verified")} for r in recs]}

    class LaunchBackfillIn(BaseModel):
        days: float = Field(default=7.0, gt=0, le=60)
        dry_run: bool = False

    @app.post("/api/launch-failures/backfill")
    def launch_failures_backfill(b: LaunchBackfillIn, actor=Depends(auth)):
        """File the failed launches of the last `days` days, grouped by signature, as live failures are filed (no
        automatic relaunches for old failures). dry_run lists the groups without filing."""
        if b.dry_run:
            return {"days": b.days, "dry_run": True, "groups": launch_ledger.preview(b.days)}
        out = launch_ledger.backfill(b.days)
        store.audit(actor, "launch_failure.backfill", "", out)
        return out

    @app.post("/api/launch-failures/tick")
    def launch_failures_tick(actor=Depends(auth)):
        """Run one pass of the verify-and-resolve loop now (it also runs every minute)."""
        return {"changes": launch_ledger.tick()}

    class LaunchSettingsIn(BaseModel):
        auto_remedy: bool | None = None
        investigate: bool | None = None
        verify: bool | None = None

    @app.post("/api/launch-failures/settings")
    def launch_failures_settings(s: LaunchSettingsIn, actor=Depends(auth)):
        out = launch_ledger.set_settings(**s.model_dump())
        store.audit(actor, "launch_failure.settings", "", out)
        return out

    class ImportItem(BaseModel):
        text: str
        created: float
        completed: float | None = None
        source: str = "chat"
        metrics: dict = {}

    SECRET = __import__("re").compile(r"(?i)\b(pw|pwd|pass(?:word)?|passcode|token|api[_ -]?key)(\s*[:=]?\s*)(\S+)")

    def _redact(t: str) -> str:
        """Operator prompts sometimes carry credentials ('ssh user@host / pw ...'): never keep them in the inbox."""
        return SECRET.sub(lambda m: m[1] + m[2] + "[redacted]", t or "")

    def _norm(t: str) -> str:
        return " ".join((t or "").split())[:100].lower()   # hook-made requests stored bodies cut at ~150 chars

    @app.post("/api/requests/import")
    def req_import(items: list[ImportItem], actor=Depends(auth)):
        """Backfill past operator prompts (e.g. from the Claude Code transcript), drop harness noise, renumber oldest-first."""
        noise = ("<task-notification", "<system-reminder", "<local-command")
        rs = store.all("request")
        for r in rs:
            if (r.get("body") or r.get("title") or "").lstrip().startswith(noise):
                store.delete("request", r["id"])
        have = {_norm(r.get("body") or r.get("title")): r for r in store.all("request")}
        added = 0
        for it in items:
            if it.text.lstrip().startswith(noise):
                continue
            it.text = _redact(it.text)
            old = have.get(_norm(it.text))
            if old:                                        # already logged: restore the full text if it was cut short
                if len(old.get("body") or "") < len(it.text):
                    msgs = old.get("messages") or []
                    if msgs and msgs[0].get("author") == "operator":
                        msgs[0] = msgs[0] | {"text": it.text}
                    store.put("request", old["id"], old | {"body": it.text, "messages": msgs})
                continue
            rid = new_id()
            store.put("request", rid, {
                "id": rid, "number": 0, "title": it.text.splitlines()[0][:100], "body": it.text, "source": it.source, "kind": "text",
                "image": None, "element": None, "context": {"imported": "claude-code transcript"}, "status": "done",
                "created": it.created, "started": it.created, "completed": it.completed or it.created, "author": "operator",
                "messages": [{"author": "operator", "text": it.text, "ts": it.created, "attachments": []}],
                "metrics": {"tokens_in": 0, "tokens_out": 0, "tools": {}, "files_changed": [], "duration_s": None, "turns": 0} | it.metrics})
            have[_norm(it.text)] = store.get("request", rid)
            added += 1
        for n, r in enumerate(sorted(store.all("request"), key=lambda r: r["created"]), 1):
            clean = r | {"number": n, "title": _redact(r.get("title")), "body": _redact(r.get("body")),
                         "messages": [m | {"text": _redact(m.get("text"))} for m in r.get("messages") or []]}
            if clean != r:
                store.put("request", r["id"], clean)
        store.audit(actor, "request.import", "requests", {"added": added})
        return {"added": added, "total": len(store.all("request"))}

    @app.get("/api/requests/export")
    def req_export(actor=Depends(auth)):
        """The whole request history, oldest first, as one Markdown transcript."""
        import datetime as _dt
        from zoneinfo import ZoneInfo
        ct = ZoneInfo("America/Chicago")                   # the operator's time, whatever the Spark's clock says
        out = ["# gBox request history", ""]
        for r in sorted(store.all("request"), key=lambda r: r["created"]):
            m = r.get("metrics") or {}
            when = _dt.datetime.fromtimestamp(r["created"], ct).strftime("%m-%d-%y %I:%M %p %Z")
            out += [f"## #{r.get('number')} · {when} · {r['source']} · {r['status']}", "",
                    f"Tokens in/out: {m.get('tokens_in', 0):,} / {m.get('tokens_out', 0):,} · model: {m.get('model') or 'n/a'} · "
                    f"time: {m.get('duration_s') or 0:.0f}s · files: {len(m.get('files_changed') or []) if isinstance(m.get('files_changed'), list) else m.get('files_changed', 0)}", ""]
            if solver := r.get("solved_by"):
                out += [f"Solver: {solver.get('service')} · {solver.get('model') or 'n/a'} · {solver.get('system') or 'n/a'}",
                        f"Verified by: {solver.get('verified_by') or 'n/a'} · {solver.get('verification') or 'n/a'}", ""]
            for msg in r.get("messages") or [{"author": r.get("author"), "text": r.get("body") or r.get("title")}]:
                out += [f"**{msg.get('author')}:**", "", (msg.get("text") or "").strip(), ""]
        return PlainTextResponse("\n".join(out), media_type="text/markdown",
                                 headers={"content-disposition": 'attachment; filename="gbox-request-history.md"'})

    @app.get("/api/requests")
    def req_list(request: Request, status: str = "", source: str = "", group: int = 0, actor=Depends(auth)):
        # The desktop inbox polls this every few seconds and it is the whole history (~8 MB, ~1 s to build). An unchanged
        # inbox answers 304 from a hash of the stored rows, without decoding, organizing or sending them (#712).
        # group=1 (#1788): each kind of automated ticket (launch failures, readiness, observer/gap, agent messages,
        # reviews, other automation) becomes one summary entry with its count, pending count, newest time and ids;
        # operator requests and build reports are returned unchanged. Without it the answer is the plain list.
        import hashlib
        from fastapi.responses import JSONResponse
        tag = f'"{store.digest("request")}:{hashlib.sha1((f"{status}|{source}" + (f"|group" if group else "")).encode()).hexdigest()[:8]}"'
        if request.headers.get("if-none-match") == tag:
            return Response(status_code=304, headers={"etag": tag})
        from . import inbox
        rs = [r for r in inbox.organize(store.all("request")) if (not status or r["status"] in status.split(",")) and (not source or r["source"] == source)]
        rs = sorted(rs, key=lambda r: r["created"], reverse=True)
        return JSONResponse(_clean(inbox.grouped(rs) if group else rs), headers={"etag": tag})

    def _clean(o):
        """Lone surrogates (bad clipboard/dictation text) can't be sent as UTF-8 JSON: replace them, don't fail the list."""
        if isinstance(o, str):
            return o.encode("utf-8", "replace").decode("utf-8")
        if isinstance(o, list):
            return [_clean(x) for x in o]
        if isinstance(o, dict):
            return {k: _clean(v) for k, v in o.items()}
        return o

    @app.get("/api/requests/{rid}")
    def req_get(rid: str, actor=Depends(auth)):
        return _clean(_req(rid))

    @app.get("/api/requests/{rid}/story")
    def req_story(rid: str, actor=Depends(auth)):
        """The request's resolution story in order, for the Detailed report: triage, identification (tool calls), each
        run with its recorded tokens and an estimated cost, jobs, the linked PRs with files and +/- lines (local git),
        replies and the resolution. Unrecorded values are null and listed in `missing` (gbox/request_story.py)."""
        from . import request_story
        return _clean(request_story.assemble(store, config, _req(rid)))

    class ParentIn(BaseModel):
        parent_request_id: str

    @app.post("/api/requests/{rid}/parent")
    def req_parent(rid: str, change: ParentIn, actor=Depends(auth)):
        r, parent = _req(rid), _req(change.parent_request_id)
        seen = {rid}
        while parent:
            if parent["id"] in seen:
                raise HTTPException(409, "request hierarchy cannot contain a cycle")
            seen.add(parent["id"])
            parent = store.get("request", parent.get("parent_request_id")) if parent.get("parent_request_id") else None
        r.update(parent_request_id=change.parent_request_id, automated=True)
        store.put("request", rid, r)
        store.audit(actor, "request.parent", rid, change.model_dump())
        return _clean(r)

    @app.post("/api/requests/{rid}/messages")
    def req_message(rid: str, m: MessageIn, actor=Depends(auth)):
        r = _req(rid)
        entry = {"author": m.author, "text": m.text, "ts": time.time(), "attachments": _attach(rid, m.attachments)}
        if m.task_step and m.author == "agent":
            entry["task_step"] = {k: str(m.task_step.get(k, ""))[:4000] for k in ("action", "attempt", "result", "status")}
        r["messages"].append(entry)
        if m.author == "operator" and r["status"] == "done":
            r["status"], r["completed"] = "open", None      # a follow-up reopens the request
        elif m.author == "operator" and r["status"] == "blocked":
            r["status"] = "open"                            # the operator answered what the agent asked
        store.put("request", rid, r)
        store.audit(actor, "request.message", rid, {"author": m.author, "chars": len(m.text)})
        return _clean(r)

    class IncompleteIn(BaseModel):
        explanation: str
        session_id: str = ""
        attachments: list[dict] = []

    @app.post("/api/requests/{rid}/report-incomplete")
    def req_report_incomplete(rid: str, complaint: IncompleteIn, actor=Depends(auth)):
        """Dispute a completion, retain its history and evidence, and queue another resolution attempt."""
        explanation = complaint.explanation.strip()
        if not explanation:
            raise HTTPException(422, "Explain what failed before reopening the task")
        report = _req(rid)
        if report["status"] != "done":
            raise HTTPException(409, "Only completed requests can be reported incomplete")
        now = time.time()
        report.setdefault("context", {}).setdefault("disputed_completions", []).append({
            "completed": report.get("completed"), "reported": now, "explanation": explanation})
        report["messages"].append({"author": "operator", "text": f"Completion disputed: {explanation}",
                                   "ts": now, "attachments": _attach(rid, complaint.attachments)})
        report["status"], report["completed"] = "in_progress", None
        report["messages"].append({"author": "agent", "text": "Previous completion withdrawn. The failure is being investigated again.",
                                   "ts": now, "attachments": [], "task_step": {"action": "reopen disputed completion",
                                   "attempt": str(len(report["context"]["disputed_completions"])),
                                   "result": explanation[:4000], "status": "running"}})
        session_id = complaint.session_id
        session = store.get("session", session_id) or {} if session_id else {}
        if session.get("state") == "running" and not session.get("ended"):
            try:
                slot = 40 + sum(1 for old in store.all("request") if (old.get("context") or {}).get("session_id") == session_id)
                saved = submit(JobRequest(tool="session_op", input={"session_id": session_id, "op": "save_state",
                                          "args": {"slot": slot}}, parent_request_id=rid), actor)
                report["context"].update(session_id=session_id, state_job_id=saved.id)
                report["messages"].append({"author": "agent", "text": f"Requested save state for the failed moment (job {saved.id}, slot {slot}).",
                                           "ts": time.time(), "attachments": [], "task_step": {"action": "save failed moment",
                                           "attempt": "1", "result": saved.state, "status": saved.state}})
            except Exception as exc:
                report["messages"].append({"author": "agent", "text": f"Save state unavailable: {exc}", "ts": time.time(), "attachments": []})
        store.put("request", rid, report)
        try:
            chat = hub.get(new_id())
            store.put("chat", chat["id"], chat)
            prompt = (f"Resolve disputed completion of gBox request #{report['number']} ({rid}): {report['title']}.\n"
                      f"Operator's observed failure: {explanation}\n"
                      "Inspect the prior result and attached evidence, fix the underlying problem, record each attempt and outcome, "
                      "capture verification screenshots, record actual token usage, and mark done only after the operator-visible result is verified. "
                      "Preserve the running game and any save state.")
            hub.post(chat["id"], prompt, {"request_id": rid, "session_id": session_id,
                                          "resolve_auto_report": True}, api_requests, None, [])
            report = store.get("request", rid) or report
            report.setdefault("context", {})["resolution_chat_id"] = chat["id"]
            report["messages"].append({"author": "agent", "text": f"Resolution dispatched (chat {chat['id']}).",
                                       "ts": time.time(), "attachments": [], "task_step": {"action": "dispatch resolution",
                                       "attempt": "1", "result": chat["id"], "status": "running"}})
        except Exception as exc:
            report = store.get("request", rid) or report
            report["messages"].append({"author": "agent", "text": f"Resolution dispatch failed: {exc}",
                                       "ts": time.time(), "attachments": []})
        store.put("request", rid, report)
        store.audit(actor, "request.report_incomplete", rid, {"chars": len(explanation), "session": session_id})
        if session.get("state") == "running" and not session.get("ended") and not complaint.attachments:
            def _capture_disputed():
                try:
                    asyncio.run(req_capture(rid, RequestCaptureIn(session_id=session_id,
                        text="Game frame when completion was disputed", task_step={"action": "capture failed moment",
                        "attempt": "1", "result": "game frame attached", "status": "finished"}), "gbox-auto"))
                except Exception as exc:
                    store.audit("gbox-auto", "request.capture.error", rid, {"error": str(exc)[:500]})
            threading.Thread(target=_capture_disputed, daemon=True).start()
        return _clean(report)

    class RequestCaptureIn(BaseModel):
        session_id: str
        text: str = ""
        task_step: dict = {}

    @app.post("/api/requests/{rid}/capture")
    async def req_capture(rid: str, c: RequestCaptureIn, actor=Depends(auth)):
        """Attach a real game frame to a report with the action/result that produced it."""
        r = _req(rid)
        session = store.get("session", c.session_id) or _404()
        if session.get("ended") or session.get("state") != "running":
            raise HTTPException(409, "session has ended; cannot capture a live frame")
        png = await asyncio.to_thread(_session_png, c.session_id)
        if not png.startswith(b"\x89PNG"):
            raise HTTPException(409, "session did not return a PNG frame")
        ref = store.put_artifact(png, f"task-{rid}-{int(time.time())}.png", "image/png",
                                 {"request": rid, "session": c.session_id, "task_evidence": True})
        entry = {"author": "agent", "text": c.text, "ts": time.time(),
                 "attachments": [{"sha256": ref.sha256, "name": ref.name, "type": "image/png", "size": ref.size}],
                 "task_step": {k: str(c.task_step.get(k, ""))[:4000] for k in ("action", "attempt", "result", "status")}}
        r["messages"].append(entry)
        store.put("request", rid, r)
        store.audit(actor, "request.capture", rid, {"session": c.session_id, "artifact": ref.sha256})
        return _clean(entry)

    @app.post("/api/requests/{rid}/status")
    def req_status(rid: str, s: StatusIn, actor=Depends(auth)):
        if s.status not in REQ_STATES:
            raise HTTPException(422, f"status must be one of {REQ_STATES}")
        if s.solved_by and s.status != "done":
            raise HTTPException(422, "Solver credit is recorded only for a completed, verified request")
        r, now = _req(rid), time.time()
        if s.status == 'done' and (gid := (r.get('context') or {}).get('custom_build_unlocks')):
            pending = app.state.custom_build_unlocks_pending(gid)
            if pending:
                raise HTTPException(409, {'message': 'Unlock-all requires verified receipts for every current custom build',
                                          'pending_builds': pending})
        if s.status == "in_progress" and not r["started"]:
            r["started"] = now
        if s.status == "done":
            r["completed"] = now
            r["metrics"]["duration_s"] = round(now - (r["started"] or r["created"]), 1)
            r["solved_by"] = s.solved_by.model_dump() if s.solved_by else None
        r["status"] = s.status
        if s.note:
            r["messages"].append({"author": "agent", "text": s.note, "ts": now})
        store.put("request", rid, r)
        store.audit(actor, f"request.{s.status}", rid, {"note": s.note[:200]})
        return _clean(r)

    @app.post("/api/requests/{rid}/metrics")
    def req_metrics(rid: str, m: MetricsIn, actor=Depends(auth)):
        """Accumulates agent usage onto a request (one call per agent turn)."""
        r = _req(rid)
        mt = r["metrics"]
        if m.model:
            mt["model"] = m.model
        if m.provider:
            mt["provider"] = m.provider[:80]
        if m.system:
            mt["system"] = m.system[:80]
        if m.provider and m.model:
            # A ticket can involve multiple providers and a separate reviewer.
            # Preserve each provider/model's measured usage for comparison.
            usage = mt.setdefault("usage_by_solver", [])
            entry = next((item for item in usage if item.get("provider") == m.provider[:80]
                          and item.get("model") == m.model and item.get("system") == (m.system or "")), None)
            if entry is None:
                entry = {"provider": m.provider[:80], "model": m.model, "system": m.system or "",
                         "tokens_in": 0, "tokens_out": 0, "agent_seconds": 0, "timed": False,
                         "token_count_unavailable": 0}
                usage.append(entry)
            entry["tokens_in"] += m.tokens_in or 0
            entry["tokens_out"] += m.tokens_out or 0
            entry["token_count_unavailable"] += int(bool(m.tokens_detail.get("token_count_unavailable")))
            if m.duration_s is not None:
                entry["agent_seconds"] = round(entry["agent_seconds"] + m.duration_s, 1)
                entry["timed"] = True
        mt["tokens_in"] = (mt.get("tokens_in") or 0) + (m.tokens_in or 0)
        mt["tokens_out"] = (mt.get("tokens_out") or 0) + (m.tokens_out or 0)
        for k, v in m.tokens_detail.items():
            detail = mt.setdefault("tokens_detail", {})
            previous = detail.get(k)
            if isinstance(v, (int, float)):
                detail[k] = (previous if isinstance(previous, (int, float)) else 0) + v
            elif v is not None or k not in detail:
                # SDK details also contain source/status text, nested metadata,
                # and unavailable (null) costs. Only numbers are counters.
                detail[k] = v
        for k, v in m.tools.items():
            mt["tools"][k] = mt["tools"].get(k, 0) + v
        mt["files_changed"] = sorted(set(mt["files_changed"]) | set(m.files_changed))
        mt["turns"] = (mt.get("turns") or 0) + (m.turns if m.turns is not None else 1)
        if m.duration_s is not None:
            mt["agent_seconds"] = round(mt.get("agent_seconds", 0) + m.duration_s, 1)
        store.put("request", rid, r)
        store.audit(actor, "request.metrics", rid, {"tokens_out": m.tokens_out, "tools": m.tools, "files": len(m.files_changed)})
        return _clean(r)

    @app.post("/api/knowledge")
    def add_edge(e: KnowledgeEdge, actor=Depends(auth)):
        if e.status == "validated":
            if not e.evidence or any(store.get("artifact", d) is None for d in e.evidence):
                raise HTTPException(422, "validated facts require existing evidence artifacts")
        store.put("edge", e.id, e.model_dump())
        store.audit(actor, "knowledge.add", e.id, e.model_dump())
        return e

    # --- experiments / runs (plan §21) ---
    @app.post("/api/runs")
    def add_run(r: RunRecord, actor=Depends(auth)):
        r.evaluation = None                        # proposers cannot self-evaluate
        store.put("run", r.id, r.model_dump())
        store.audit(actor, "run.record", r.id, {"game": r.game_id, "proposer": r.proposer})
        return r

    @app.post("/api/runs/{rid}/evaluation")
    def evaluate(rid: str, ev: Evaluation, actor=Depends(auth)):
        r = store.get("run", rid) or _404()
        if ev.evaluator == r["proposer"]:
            raise HTTPException(422, "evaluator must differ from proposer")
        r["evaluation"] = ev.model_dump() | {"at": time.time()}
        store.put("run", rid, r)
        store.audit(actor, "run.evaluate", rid, r["evaluation"])
        return r

    @app.get("/api/metrics")
    def metrics(actor=Depends(auth)):
        runs, jobs, edges = store.all("run"), store.all("job"), store.all("edge")
        arts = store.all("artifact")
        return {"runs_total": len(runs), "runs_evaluated": sum(1 for r in runs if r["evaluation"]),
                "validated_findings": sum(1 for e in edges if e["status"] == "validated"),
                "hypotheses": sum(1 for e in edges if e["status"] == "hypothesis"),
                "jobs_by_state": {s: sum(1 for j in jobs if j["state"] == s) for s in JobState},
                "artifact_bytes": sum(a["size"] for a in arts), "artifacts": len(arts)}

    return app


def _404():
    raise HTTPException(404, "not found")
