"""G-Box control plane: API gateway, job scheduler, independent validation, receipts, audit."""
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
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from . import tools as _builtin  # noqa: F401  (registers tools)
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
    app = FastAPI(title="G-Box", version="0.1.0")
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
        """Every script shipped with the installed Ghidra (+ G-Box's own), with @category and description."""
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
                            "module": d.parent.name if d.name == "ghidra_scripts" else "G-Box",
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
        store.put("worker", w.id, w.model_dump())
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
                        and j["require_os"] in (None, w["os"]) and j["require_worker"] in (None, wid)):
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

    @app.get("/api/artifacts/{digest}/meta")
    def artifact_meta(digest: str, actor=Depends(auth)):
        return store.get("artifact", digest) or _404()

    # --- audit ---
    @app.get("/api/audit")
    def audit(after: int = 0, limit: int = 200, actor=Depends(auth)):
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
        """Instant commands (typed or spoken), no LLM: 'G-Box, load <game>' / 'search for <game>'. Else -> agent."""
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
    def launch(gid: str, node: str = "auto", actor=Depends(auth)):
        """Launch a cataloged game on the right node: linux core if one exists, else the Windows node."""
        e = store.catalog_get(gid) or _404()
        req = JobRequest(tool="launch_game", input={"game": e})
        if node in ("linux", "windows"):
            req.require_os = node
        elif node != "auto":
            byname = [w for w in workers() if w["online"] and w["name"] == node]
            req.require_worker = byname[0]["id"] if byname else node
        elif e.get("launch", {}).get("kind") == "attract":
            req.require_os = "linux" if e.get("core") else "windows"
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

    @app.post("/api/sessions/{sid}/input")
    def put_input(sid: str, ev: InputEvents, actor=Depends(auth)):
        lv = _live(sid)
        with lv["cond"]:
            lv["input"].extend(ev.events)
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

    # --- G-Box clipboard: copy from the inspector / receipts, paste in Blender (G-Box add-on) ---
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

    # --- G-Box chat agent (local LLM with tool calling over the G-Box API + SearXNG web search) ---
    from .agent import Agent, ChatHub
    agent_cfg = config.agent

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
            c["events"].append({"type": "error", "text": "Interrupted: G-Box restarted while this was running. Please send it again.",
                                "ts": time.time()})
            store.put("chat", c["id"], c)
    model_caps: dict[str, tuple] = {}             # name -> (digest, capabilities) from Ollama /api/show

    class ChatIn(BaseModel):
        text: str
        context: dict = {}
        model: str | None = None

    @app.get("/api/chat/suggest")
    def chat_suggest(q: str = "", game: str = "", platform: str = "", limit: int = 10, actor=Depends(auth)):
        """Autocomplete: the operator's past chat requests (most used first) + things G-Box can do for the current game."""
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
        tmpl = [{"text": t, "kind": "suggestion"} for t in templates if t not in past]
        items = [x for x in hist + tmpl if not ql or score(x["text"]) < 9]
        items.sort(key=lambda x: (score(x["text"]) if ql else 0, 0 if x["kind"] == "history" else 1))
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
                c = []
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
            hub.post(cid, m.text, m.context, api_requests, m.model)
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
        """Inspector peeks (read_memory / read_rom / info), answered by the worker over the session channel."""
        if req.op not in ("read_memory", "read_rom", "info"):
            raise HTTPException(422, "read-only ops only; edits go through the write_memory job")
        rid, lv = new_id(), _live(sid)
        with lv["cond"]:
            lv["input"].append({"rpc": rid, "op": req.op, "args": req.args})
            lv["cond"].notify_all()
            if not lv["cond"].wait_for(lambda: rid in rpc_results, 10):
                raise HTTPException(504, "session did not answer (ended, or not a live G-Box session)")
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

    @app.get("/api/requests")
    def req_list(status: str = "", source: str = "", actor=Depends(auth)):
        rs = [r for r in store.all("request") if (not status or r["status"] in status.split(",")) and (not source or r["source"] == source)]
        return sorted(rs, key=lambda r: r["created"], reverse=True)

    @app.get("/api/requests/{rid}")
    def req_get(rid: str, actor=Depends(auth)):
        return _req(rid)

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
