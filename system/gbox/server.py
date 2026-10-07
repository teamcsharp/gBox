"""gBox control plane: API gateway, job scheduler, independent validation, receipts, audit."""
import asyncio
import base64
import collections
import concurrent.futures
import hmac
import httpx
import json
import os
import subprocess
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from . import tools as _builtin  # noqa: F401  (registers tools)
from . import padstate
from .config import HOST_OS, Config
from .models import Job, JobState, new_id, KnowledgeEdge, Receipt, RunRecord, WorkerInfo
from .registry import REGISTRY
from .store import Store, canon, sha256

WORKER_TTL = 30.0
WEB = Path(__file__).resolve().parent.parent / "clients" / "web" / "index.html"
BRAND = Path(__file__).resolve().parent.parent / "assets" / "brand"


class ArtifactUpload(BaseModel):
    name: str
    media_type: str
    provenance: dict = {}
    b64: str


class JobResult(BaseModel):
    job_id: str
    ok: bool
    output: dict | None = None
    error: str | None = None
    log: list[str] = []
    artifacts: list[ArtifactUpload] = []


class JobRequest(BaseModel):
    tool: str
    input: dict = {}
    require_os: str | None = None
    require_worker: str | None = None


class Evaluation(BaseModel):
    evaluator: str
    passed: bool
    metrics: dict[str, float] = {}
    notes: str = ""


def create_app(config: Config) -> FastAPI:
    store = Store(config.data_dir)
    token = config.token()
    app = FastAPI(title="gBox", version="0.1.0")
    app.state.store = store

    @app.on_event("startup")
    async def _more_threads():
        # every live stream viewer and worker input long-poll holds a worker thread
        import anyio.to_thread
        anyio.to_thread.current_default_thread_limiter().total_tokens = 256

    def auth(request: Request) -> str:
        # ?token= is accepted so <img>/<video> tags can load frames and artwork
        got = request.headers.get("authorization", "").removeprefix("Bearer ") or request.query_params.get("token", "")
        if not hmac.compare_digest(got.encode(), token.encode()):
            raise HTTPException(401, "bad token")
        return request.headers.get("x-gbox-actor", "operator")

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
        return item

    from . import re6_api                         # Resident Evil 6: item catalogue + icons, saved Mercenaries loadout
    re6_api.routes(app, store, config, auth)

    # --- Phantasy Star Online item catalog (from the disc) + item thumbnails (PSO wiki) for the item sidebar ---
    # ponytail: one known disc image per version on the Spark; look them up in the catalog when more versions appear
    PSO_DISCS = {"dcv2": "/home/ehm_eckx/gbox-cache/dc/psov2.gdi", "gc": "/home/ehm_eckx/gbox-cache/gc/psogc.iso"}

    @app.get("/api/pso/items")
    def pso_items(version: str = "dcv2", actor=Depends(auth)):
        from . import psoitems
        f = config.data_dir / "pso" / f"items-{version}.json"
        if not f.exists():
            if version not in PSO_DISCS or not Path(PSO_DISCS[version]).exists():
                raise HTTPException(404, f"no PSO {version} disc on this node to read the item list from")
            from .gcdisc import GCDisc
            from .gdrom import GDRom
            f.parent.mkdir(parents=True, exist_ok=True)
            items = (psoitems.catalog_dc_v2(GDRom(PSO_DISCS[version]).read) if version == "dcv2"
                     else psoitems.catalog_gc(GCDisc(PSO_DISCS[version]).read))
            f.write_text(json.dumps(items))
        return json.loads(f.read_text())

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
        store.put("mod", mid, doc)
        store.audit(actor, "mod.save", m.title, {"game": gid, "calls": len(doc["calls"])})
        return doc

    def _session_png(sid: str) -> bytes:
        """Current picture of a session: the live stream frame when fresh, else ask its worker for one (native windows)."""
        lv = live.get(sid) or {}
        if lv.get("frame") and time.time() - lv.get("ts", 0) < 5:
            return lv["frame"]
        j = submit(JobRequest(tool="get_frame", input={"session_id": sid}), "mods")
        t0 = time.time()
        while (jj := store.get("job", j.id))["state"] in ("queued", "running") and time.time() - t0 < 45:
            time.sleep(0.5)
        if jj["state"] != "succeeded":
            raise HTTPException(409, f"couldn't capture the game: {jj.get('error') or jj['state']}")
        o = jj["output"]
        if (o.get("mean_luma") or 0) < 6:
            raise HTTPException(409, "the game screen is black right now: try again once it's showing")
        return store.read_artifact(o["sha256"]) or b""

    @app.post("/api/mods/{mid}/thumb")
    async def mod_thumb(mid: str, request: Request, session_id: str = "", force: bool = False, actor=Depends(auth)):
        """Set a mod's picture: an image in the body, or what the session shows right now. Without force, keeps an existing one."""
        m = store.get("mod", mid) or _404()
        if m.get("thumb") and not force:
            return m
        body = await request.body()
        if not body:
            if not session_id:
                raise HTTPException(400, "send an image or a session_id")
            body = await asyncio.to_thread(_session_png, session_id)
        kind = "image/png" if body[:4] == b"\x89PNG" else "image/jpeg"
        ref = store.put_artifact(body, f"mod-{mid}.{kind[6:]}", kind, {"mod": mid, "session": session_id})
        m["thumb"] = ref.sha256
        store.put("mod", mid, m)
        store.audit(actor, "mod.thumb", mid, {"artifact": ref.sha256})
        return m

    @app.get("/api/mods")
    def mod_list(game_id: str = "", actor=Depends(auth)):
        out = [m for m in store.all("mod") if not game_id or m["game_id"] == game_id]
        return sorted(out, key=lambda m: -m.get("ts", 0))

    @app.delete("/api/mods/{mid}")
    def mod_del(mid: str, actor=Depends(auth)):
        store.delete("mod", mid)
        store.audit(actor, "mod.delete", mid, {})
        return {"deleted": mid}

    # --- character library (gbox/characters.py): models extracted from the operator's games, reusable in any game ---
    def _chars():
        from . import characters
        return characters, characters.library_root(config)

    @app.get("/api/characters")
    def chars_list(game_id: str = "", actor=Depends(auth)):
        """Library characters (+ ready swap mods for game_id) with preview URLs."""
        K, root = _chars()
        tf = lambda slug: sorted("targets/" + f.name for f in (Path(root) / slug / "targets").glob("*") if f.is_file())             if (Path(root) / slug / "targets").is_dir() else []          # game-fitted models (Blender copy of a swap mod)
        return [m | {"preview_url": f"/api/characters/{m['slug']}/preview", "model_url": f"/api/characters/{m['slug']}/file/{m['model']}",
                     "target_files": tf(m["slug"])}
                for m in K.list_all(root, game_id)]

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
            m = K.set_target(root, slug, t.game_id, t.model_dump())
        except KeyError:
            _404()
        store.audit(actor, "character.target", slug, t.model_dump())
        return m

    # overlay swap (gbox/overlay_swap.py): a collection model drawn over the player in the desktop app, any game
    from . import overlay_swap
    overlay_swap.register(app, auth, store, lambda slug: _chars()[0].get(_chars()[1], slug)["name"])

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

    class NotifyIn(BaseModel):
        title: str
        text: str = ""
        session_id: str = ""                # click opens this session
        kind: str = "info"                  # info | ready | done | error

    @app.post("/api/notify")
    def notify(n: NotifyIn, actor=Depends(auth)):
        """A notification for the operator's header tray (e.g. "Mario Mercenaries is ready")."""
        import uuid
        nid = uuid.uuid4().hex[:12]
        store.put("notify", nid, n.model_dump() | {"id": nid, "ts": time.time(), "read": False, "by": actor})
        return {"id": nid}

    @app.get("/api/notify")
    def notify_list(limit: int = 30, actor=Depends(auth)):
        return sorted(store.all("notify"), key=lambda x: -x.get("ts", 0))[:limit]

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

    class MoveIn(BaseModel):
        to: str = "windows"                 # windows (this PC) | linux (the Spark)

    @app.post("/api/sessions/{sid}/move")
    def session_move(sid: str, m: MoveIn, actor=Depends(auth)):
        """Move a running game to another machine: save state there -> launch the same game (+ mod) here -> load it -> stop
        the old one. Spark streaming lags; playing natively on this PC doesn't."""
        sess = store.get("session", sid) or _404()

        def run(tool, inp, worker=None, os_=None, wait=240):
            body = {"tool": tool, "input": inp, **({"require_worker": worker} if worker else {}), **({"require_os": os_} if os_ else {})}
            j = submit(JobRequest(**body), actor)
            t0 = time.time()
            while (jj := store.get("job", j.id))["state"] in ("queued", "running") and time.time() - t0 < wait:
                time.sleep(0.5)
            if jj["state"] != "succeeded":
                raise HTTPException(409, f"{tool} failed: {jj.get('error') or jj['state']}")
            return jj["output"]
        out = run("state_transfer", {"session_id": sid, "op": "export"}, worker=sid.split("-")[0])
        game = store.catalog_get(sess["game_id"]) or _404()
        try:
            new = run("launch_game", {"game": game, "mod": sess.get("mod") or ""}, os_=m.to, wait=600)
        except HTTPException as e:
            if "no built mod" in str(e.detail):
                raise HTTPException(409, f"the mod '{sess.get('mod')}' isn't built on that machine yet: copy gbox-cache/mods/"
                                         f"{sess['game_id']}/{sess.get('mod')} there (or rebuild it), then move again")
            raise
        nsid = new["session_id"]
        time.sleep(8)                                          # let the core boot before loading the state
        run("state_transfer", {"session_id": nsid, "op": "import", "artifact": out["result"]["artifact"]}, worker=nsid.split("-")[0])
        try:
            run("session_op", {"session_id": sid, "op": "stop_game", "args": {}}, worker=sid.split("-")[0], wait=60)
        except HTTPException:
            pass
        store.audit(actor, "session.move", sid, {"to": m.to, "new": nsid})
        return {"session_id": nsid, "from": sid}

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
        return [w | {"online": now - w["last_seen"] < WORKER_TTL} for w in store.all("worker")]

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
        return workers()

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
        w.last_seen = time.time()
        old_ids = {o["id"] for o in store.all("worker") if o["name"] == w.name and o["id"] != w.id}
        for j in store.all("job"):                  # a restarted worker can never finish its old jobs
            if j["state"] == JobState.RUNNING and j["worker_id"] in old_ids:
                j.update(state=JobState.FAILED, finished=time.time(), error=f"worker {w.name} restarted while running")
                store.put("job", j["id"], j)
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
        prev = store.get("worker", w.id)
        store.put("worker", w.id, w.model_dump())
        if prev and (prev.get("tools"), prev.get("unavailable")) == (w.tools, w.unavailable):
            return {"id": w.id}                     # periodic refresh, nothing changed: not worth an audit row
        store.audit(actor, "worker.register", w.id, {"name": w.name, "os": w.os, "tools": w.tools, "unavailable": w.unavailable})
        return {"id": w.id}

    @app.post("/api/workers/{wid}/claim")
    def claim(wid: str, actor=Depends(auth)):
        w = store.get("worker", wid)
        if not w:
            raise HTTPException(404, "unknown worker; register first")
        with store.lock:
            w["last_seen"] = time.time()
            store.put("worker", wid, w)
            for j in store.all("job"):
                if (j["state"] == JobState.QUEUED and j["tool"] in w["tools"]
                        and j["require_os"] in (None, w["os"]) and j["require_worker"] in (None, wid, w["name"])):   # by name: launched while that worker was restarting
                    j.update(state=JobState.RUNNING, worker_id=wid, started=time.time())
                    store.put("job", j["id"], j)
                    store.audit(actor, "job.claim", j["id"], {"worker": wid})
                    return j
        return Response(status_code=204)

    @app.post("/api/workers/{wid}/result")
    def result(wid: str, r: JobResult, actor=Depends(auth)):
        j = store.get("job", r.job_id)
        if not j or j["worker_id"] != wid or j["state"] != JobState.RUNNING:
            raise HTTPException(409, "job not running on this worker")
        t = REGISTRY[j["tool"]]
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
        receipt.audit_seq = store.audit(actor, f"job.{state}", j["id"], {
            "receipt": receipt.id, "artifacts": [a.sha256 for a in refs], "problems": problems, "error": r.error})
        store.put("receipt", receipt.id, receipt.model_dump())
        if r.log:
            store.put_artifact("\n".join(r.log).encode(), "worker.log", "text/plain", {"job": j["id"]})
        j.update(state=state, finished=receipt.finished, output=r.output, error=r.error or ("; ".join(problems) or None),
                 receipt_id=receipt.id)
        store.put("job", j["id"], j)
        if state == JobState.SUCCEEDED and t.on_accept:
            t.on_accept(store, out, actor)
        elif state != JobState.SUCCEEDED and t.on_fail:
            t.on_fail(store, j, actor)
        return {"state": state, "receipt": receipt.id}

    # --- jobs ---
    @app.post("/api/jobs")
    def submit(req: JobRequest, actor=Depends(auth)):
        if req.tool == "@launch":
            i = req.input or {}
            gid = i.get("game_id") or _404()
            return launch(gid, node=i.get("node") or "windows", mod=i.get("mod") or "", actor=actor)
        t = REGISTRY.get(req.tool)
        if not t:
            raise HTTPException(404, f"unknown tool {req.tool}")
        try:
            inp = t.In.model_validate(req.input).model_dump(mode="json")
        except Exception as e:
            raise HTTPException(422, f"input invalid: {e}")
        job = Job(tool=t.name, input=inp, require_os=req.require_os, require_worker=req.require_worker)
        if sid := inp.get("session_id"):            # sessions live on the worker that launched them
            job.require_worker = sid.split("-")[0]
        if job.require_worker:
            job.require_worker = _wid(job.require_worker)
        missing = [p for p in t.permissions if p not in config.granted_permissions]
        if missing:
            job.state, job.error = JobState.REJECTED, f"permission not granted: {missing}"
        store.put("job", job.id, job.model_dump())
        store.audit(actor, "job.rejected" if missing else "job.submit", job.id, {"tool": t.name, "input": inp, "missing": missing})
        return job

    class Progress(BaseModel):
        pct: float
        msg: str

    @app.post("/api/jobs/{jid}/progress")
    def job_progress(jid: str, p: Progress, actor=Depends(auth)):
        with store.lock:                              # never race the result handler's final state write
            j = store.get("job", jid) or _404()
            if j["state"] != JobState.RUNNING:
                return {"ok": False, "cancel": bool(j.get("cancel"))}
            j["progress"] = {"pct": max(0.0, min(100.0, p.pct)), "msg": p.msg, "ts": time.time()}
            j["progress_log"] = (j.get("progress_log") or [])[-49:] + [p.msg]
            store.put("job", jid, j)
        return {"ok": True, "cancel": bool(j.get("cancel"))}

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
        store.audit(actor, "job.cancel", jid, {"state": j["state"]})
        return {"id": jid, "state": j["state"], "cancel_requested": j.get("cancel", False)}

    @app.get("/api/jobs")
    def list_jobs(limit: int = 100, actor=Depends(auth)):
        return store.all("job")[-limit:][::-1]

    @app.get("/api/jobs/{jid}")
    def get_job(jid: str, actor=Depends(auth)):
        return store.get("job", jid) or _404()

    @app.get("/api/receipts/{rid}")
    def get_receipt(rid: str, actor=Depends(auth)):
        return store.get("receipt", rid) or _404()

    @app.get("/api/artifacts/{digest}")
    def get_artifact(digest: str, actor=Depends(auth)):
        meta, data = store.get("artifact", digest), store.read_artifact(digest)
        if not meta or data is None:
            _404()
        return Response(data, media_type=meta["media_type"], headers={"x-gbox-provenance": json.dumps(meta["provenance"])})

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
                       recent: bool = False, local: str = "", letter: str = "", actor=Depends(auth)):
        kw = dict(sort=sort, favorites=favorites, recent=recent, local=local, letter=letter)
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
                      recent: bool = False, local: str = "", actor=Depends(auth)):
        n, _ = store.search(q, platform, system, "", 1, 0, favorites=favorites, recent=recent, local=local,
                            start_letter="" if letter == "#" else letter.upper()[:1])
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
        store.catalog_get(gid) or _404()
        store.catalog_update(gid, favorite=on)
        store.audit(actor, "catalog.favorite", gid, {"on": on})
        return {"game_id": gid, "favorite": on}

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

    def _resolve_art(e: dict, kinds) -> Path | None:
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
        tmp = out.with_suffix(".tmp.jpg")
        r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-frames:v", "1",
                            "-vf", f"scale='min({w},iw)':-2", "-q:v", "4", str(tmp)], capture_output=True, timeout=60)
        if r.returncode or not tmp.exists():
            miss.touch()
            return None
        tmp.replace(out)
        return out

    def _warm(gids: list[str]):
        for gid in gids:
            if gid not in thumb_busy and not (thumbs / gid[:2] / f"{gid}-best-360.jpg").exists():
                thumb_busy.add(gid)
                thumb_pool.submit(lambda g=gid: (_thumb(g, "best", 360), thumb_busy.discard(g)))

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
    def launch(gid: str, node: str = "auto", debug: bool = False, mod: str = "", actor=Depends(auth)):
        """Launch a cataloged game on the right node: linux core if one exists, else the Windows node.
        debug=true: on the Spark with a full-debugger emulator (Dolphin / mGBA / DuckStation / MAME) where one exists."""
        e = store.catalog_get(gid) or _404()
        req = JobRequest(tool="launch_game", input={"game": e, "debug": debug, **({"mod": mod} if mod else {})})
        if debug:
            node = "linux"
        if node in ("linux", "windows"):
            req.require_os = node
        elif node != "auto":
            byname = [w for w in workers() if w["online"] and w["name"] == node]
            req.require_worker = byname[0]["id"] if byname else node
        elif e.get("platform") == "ps3":
            req.require_os = "windows"                     # RPCS3
        elif e.get("launch", {}).get("kind") == "attract":
            from . import systems                          # the platform rule wins over a core stored at scan time
            has_core = e.get("core") and (e.get("platform") == "arcade" or systems.core_for(e.get("platform", ""))[0])
            req.require_os = "linux" if has_core else "windows"
        return submit(req, actor)

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

    # --- live sessions (frames up from the worker, input down from the UI) ---
    live: dict[str, dict] = {}
    live_lock = threading.Lock()

    def _live(sid: str) -> dict:
        with live_lock:
            return live.setdefault(sid, {"frame": None, "seq": 0, "ts": 0, "input": collections.deque(maxlen=500),
                                         "cond": threading.Condition()})

    @app.get("/api/sessions")
    def sessions(actor=Depends(auth)):
        out = []
        for s_ in store.all("session"):
            lv = live.get(s_["session_id"], {})
            out.append(s_ | {"last_frame_age": round(time.time() - lv["ts"], 1) if lv.get("ts") else None})
        return out[::-1]

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
        lv, buf, n = _live(sid), bytearray(), 0
        async for chunk in request.stream():
            buf += chunk
            while len(buf) >= 4:
                size = int.from_bytes(buf[:4], "big")
                if len(buf) < 4 + size:
                    break
                frame, buf = bytes(buf[4:4 + size]), buf[4 + size:]
                if size:
                    with lv["cond"]:
                        lv["frame"], lv["seq"], lv["ts"] = frame, lv["seq"] + 1, time.time()
                        lv["cond"].notify_all()
                    n += 1
        return {"frames": n}

    @app.get("/api/sessions/{sid}/frame.jpg")
    def get_frame(sid: str, actor=Depends(auth)):
        f = _live(sid)["frame"]
        return Response(f, media_type="image/jpeg", headers={"cache-control": "no-store"}) if f else _404()

    @app.get("/api/sessions/{sid}/mjpeg")
    def mjpeg(sid: str, actor=Depends(auth)):
        lv = _live(sid)

        def gen():                                   # wakes on every new frame: stream fps = source fps
            seq, idle = -1, time.time()
            while time.time() - idle < 30:
                with lv["cond"]:
                    lv["cond"].wait_for(lambda: lv["seq"] != seq and lv["frame"] is not None, 1.0)
                    if lv["seq"] == seq or lv["frame"] is None:
                        continue
                    seq, frame, idle = lv["seq"], lv["frame"], time.time()
                yield b"--f\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"
        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=f",
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
        d = filemods.mod_dir(config, gid, name).resolve()
        if not str(d).startswith(str((Path(config.cache) / "mods").resolve())) or "/" in gid + name or "\\" in gid + name:
            raise HTTPException(400, "bad mod name")
        return d

    @app.get("/api/modfiles/{gid}/{name}")
    def modfiles(gid: str, name: str, actor=Depends(auth)):
        """The central mod collection (this Spark): any gBox machine fetches a built mod from here before launching it."""
        from . import filemods
        d = _mod_root(gid, name)
        if not (d / ".gbox-mod.json").exists():
            raise HTTPException(404, "not in the collection")
        return {"game_id": gid, "name": name, "files": filemods._files(d)}

    @app.get("/api/modfiles/{gid}/{name}/file/{path:path}")
    def modfile_get(gid: str, name: str, path: str, actor=Depends(auth)):
        d = _mod_root(gid, name)
        f = (d / path).resolve()
        if not str(f).startswith(str(d)) or not f.is_file():
            raise HTTPException(404, "no such file")
        return FileResponse(f)

    @app.put("/api/modfiles/{gid}/{name}/file/{path:path}")
    async def modfile_put(gid: str, name: str, path: str, request: Request, actor=Depends(auth)):
        """A machine that built a mod hands it to the collection (streamed to disk; .part until complete)."""
        d = _mod_root(gid, name)
        f = (d / path).resolve()
        if not str(f).startswith(str(d)):
            raise HTTPException(400, "bad path")
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".part")
        with open(tmp, "wb") as fh:
            async for chunk in request.stream():
                fh.write(chunk)
        os.replace(tmp, f)
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

    @app.get("/api/tasks")
    def tasks_all(actor=Depends(auth)):
        """Task monitor: every machine's gBox processes (RAM/CPU/GPU/VRAM, machine totals) + the jobs in flight."""
        ws = [w for w in workers() if w["online"] and "tasks" in (w.get("tools") or [])]
        with concurrent.futures.ThreadPoolExecutor(max(1, len(ws))) as ex:
            res = list(ex.map(lambda w: (w, _run_on(w["id"], "tasks", {"op": "list"})), ws))
        machines = []
        for w, jj in res:
            ok = jj and jj["state"] == "succeeded"
            machines.append({"worker_id": w["id"], "name": w["name"], "os": w.get("os"),
                             **(jj["output"]["result"] if ok else {"error": (jj or {}).get("error") or "no answer", "tasks": []})})
        names = {w["id"]: w["name"] for w in workers()}
        jobs = [{"id": j["id"], "tool": j["tool"], "state": j["state"],
                 "worker": names.get(j.get("worker_id") or j.get("require_worker") or "", ""),
                 "created": j.get("created"), "progress": (j.get("progress") or {}).get("msg", "")}
                for j in store.all("job") if j["state"] in ("queued", "running") and j["tool"] != "tasks"]
        return {"machines": machines, "jobs": sorted(jobs, key=lambda j: -(j["created"] or 0))}

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
            if op == "create":
                return req_create(RequestIn(**body), "gbox-agent")["id"]
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

    @app.get("/api/voice/voices")
    def voice_list(actor=Depends(auth)):
        from . import speech
        return {"engine": agent_cfg.get("tts_engine", "xtts"),
                "groups": [{"label": "XTTS v2 · cloned voices (Pine Box library)",
                            "voices": [{"id": f"xtts:{v['id']}", "name": v["name"]} for v in speech.voices(agent_cfg.get("voice_library", ""))]},
                           {"label": "Kokoro · fast", "voices": [{"id": f"kokoro:{vid}", "name": n} for vid, n in speech.KOKORO_VOICES]}]}

    class TtsIn(BaseModel):
        text: str
        voice: str = ""
        engine: str | None = None

    @app.post("/api/tts")
    async def text_to_speech(t: TtsIn, actor=Depends(auth)):
        """Speak a reply: Pine Box Voice Director (XTTS v2 voice clones) with Piper as the fallback."""
        from . import speech
        wav, used = await asyncio.to_thread(speech.tts, t.text, agent_cfg.get("voice_director", "http://127.0.0.1:8090"),
                                            t.engine or agent_cfg.get("tts_engine", "xtts"), t.voice)
        return Response(wav, media_type="audio/wav", headers={"x-gbox-tts-engine": used})

    @app.post("/api/stt")
    async def speech_to_text(request: Request, language: str = "en", actor=Depends(auth)):
        """Dictation: browser audio -> Spark faster-whisper (Wyoming :10300) -> text."""
        from . import speech
        audio = await request.body()
        if not audio:
            raise HTTPException(422, "no audio")
        try:
            text = await asyncio.to_thread(speech.transcribe, audio, agent_cfg.get("stt_host", "127.0.0.1"),
                                           int(agent_cfg.get("stt_port", 10300)), language or None)
        except Exception as e:
            raise HTTPException(502, f"speech service: {e}")
        return {"text": text}

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
        if req.op not in ("read_memory", "read_rom", "info", "state") and not req.op.startswith("debug_"):
            raise HTTPException(422, "read-only and debug_* ops only; edits go through the write_memory job")
        if req.op in ("debug_halt", "debug_resume", "debug_step", "debug_break", "debug_unbreak"):
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

    @app.post("/api/sessions/{sid}/detail")
    def session_detail(sid: str, info: dict, actor=Depends(auth)):
        """A worker reports a changed process (e.g. RPCS3 relaunched into a save state) so the app re-docks the window."""
        s_ = store.get("session", sid) or _404()
        store.put("session", sid, s_ | {"detail": (s_.get("detail") or {}) | info})
        store.audit(actor, "session.detail", sid, info)
        return {"ok": True}

    @app.post("/api/sessions/{sid}/ended")
    def ended(sid: str, info: dict, actor=Depends(auth)):
        s_ = store.get("session", sid)
        if s_:
            store.put("session", sid, s_ | {"state": "ended", "ended": time.time(), "exit": info})
        store.audit(actor, "session.ended", sid, info)
        return {"ok": True}

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
        attachments: list[dict] = []       # [{name, b64}] pasted / dropped images

    class MessageIn(BaseModel):
        author: str                        # operator | agent
        text: str
        attachments: list[dict] = []

    def _attach(rid: str, items: list[dict]) -> list[dict]:
        out = []
        for a in items[:20]:
            name = a.get("name") or "image.png"
            mt = a.get("type") or ("image/png" if name.lower().endswith(".png") else "application/octet-stream")
            ref = store.put_artifact(base64.b64decode(a["b64"]), name, mt, {"request": rid, "attachment": True})
            out.append({"sha256": ref.sha256, "name": name, "type": mt, "size": ref.size})
        return out

    class StatusIn(BaseModel):
        status: str                        # open | in_progress | done | blocked
        note: str = ""

    class MetricsIn(BaseModel):
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
               "messages": [{"author": r.author, "text": r.body, "ts": time.time(), "attachments": _attach(rid, r.attachments)}]
                           if (r.body or r.attachments) else [],
               "metrics": {"tokens_in": 0, "tokens_out": 0, "tools": {}, "files_changed": [], "duration_s": None, "turns": 0}}
        store.put("request", rid, doc)
        store.audit(actor, "request.create", rid, {"title": r.title, "kind": r.kind, "source": r.source})
        return doc

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
            for msg in r.get("messages") or [{"author": r.get("author"), "text": r.get("body") or r.get("title")}]:
                out += [f"**{msg.get('author')}:**", "", (msg.get("text") or "").strip(), ""]
        return PlainTextResponse("\n".join(out), media_type="text/markdown",
                                 headers={"content-disposition": 'attachment; filename="gbox-request-history.md"'})

    @app.get("/api/requests")
    def req_list(status: str = "", source: str = "", actor=Depends(auth)):
        rs = [r for r in store.all("request") if (not status or r["status"] in status.split(",")) and (not source or r["source"] == source)]
        return _clean(sorted(rs, key=lambda r: r["created"], reverse=True))

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

    @app.post("/api/requests/{rid}/messages")
    def req_message(rid: str, m: MessageIn, actor=Depends(auth)):
        r = _req(rid)
        r["messages"].append({"author": m.author, "text": m.text, "ts": time.time(), "attachments": _attach(rid, m.attachments)})
        if m.author == "operator" and r["status"] == "done":
            r["status"], r["completed"] = "open", None      # a follow-up reopens the request
        store.put("request", rid, r)
        store.audit(actor, "request.message", rid, {"author": m.author, "chars": len(m.text)})
        return r

    @app.post("/api/requests/{rid}/status")
    def req_status(rid: str, s: StatusIn, actor=Depends(auth)):
        if s.status not in REQ_STATES:
            raise HTTPException(422, f"status must be one of {REQ_STATES}")
        r, now = _req(rid), time.time()
        if s.status == "in_progress" and not r["started"]:
            r["started"] = now
        if s.status == "done":
            r["completed"] = now
            r["metrics"]["duration_s"] = round(now - (r["started"] or r["created"]), 1)
        r["status"] = s.status
        if s.note:
            r["messages"].append({"author": "agent", "text": s.note, "ts": now})
        store.put("request", rid, r)
        store.audit(actor, f"request.{s.status}", rid, {"note": s.note[:200]})
        return r

    @app.post("/api/requests/{rid}/metrics")
    def req_metrics(rid: str, m: MetricsIn, actor=Depends(auth)):
        """Accumulates agent usage onto a request (one call per agent turn)."""
        r = _req(rid)
        mt = r["metrics"]
        mt["tokens_in"] = (mt.get("tokens_in") or 0) + (m.tokens_in or 0)
        mt["tokens_out"] = (mt.get("tokens_out") or 0) + (m.tokens_out or 0)
        for k, v in m.tokens_detail.items():
            mt.setdefault("tokens_detail", {})[k] = mt.get("tokens_detail", {}).get(k, 0) + v
        for k, v in m.tools.items():
            mt["tools"][k] = mt["tools"].get(k, 0) + v
        mt["files_changed"] = sorted(set(mt["files_changed"]) | set(m.files_changed))
        mt["turns"] = (mt.get("turns") or 0) + (m.turns or 1)
        if m.duration_s is not None:
            mt["agent_seconds"] = round(mt.get("agent_seconds", 0) + m.duration_s, 1)
        store.put("request", rid, r)
        store.audit(actor, "request.metrics", rid, {"tokens_out": m.tokens_out, "tools": m.tools, "files": len(m.files_changed)})
        return r

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
