"""Storage overview + purge panel (operator 2026-11-03): "see what's eating disk across gBox, and give me a right-click
panel to view the breakdown and purge the auto-generated builds — without touching my curated library."

Two cheap routes behind the PiP menu's "Storage" panel (clients/desktop: storageOverviewPanel):

  GET  /api/storage/usage            per-mount (df) + per-category breakdown of the control-plane node (lilspark).
                                     A real `du` pass is slow on a 600 GB cache, so it runs in a background thread and
                                     the result is cached (USAGE_TTL). The request path never scans: it returns the
                                     newest snapshot and, when it is stale/missing, kicks a refresh and says computing.
                                     ?refresh=1 forces a new pass. Each category is tagged library | runtime (keep) vs
                                     cache | autobuild | stale (purgeable) so the panel can never confuse the two.

  POST /api/storage/purge            {worker=lilspark, unplayed_days, include, paths, confirm=false}. A thin wrapper over
                                     the vetted per-PC storage purge (gbox/storage_purge.py, job_storage_purge): confirm
                                     maps to dry_run = not confirm. Dry run (the default) lists what WOULD go; confirm
                                     true + the reviewed `paths` deletes only those. Nothing here reinvents deletion, and
                                     the library mounts (HyperSpin Arcade, Emulation game files) are never in a purge: the
                                     purge tool only ever touches this PC's cache, never a mount or a game file.
  GET  /api/storage/purge            the newest purge result for ?worker= (defaults lilspark): reuses the worker route.

Auto-build note (surfaced in the usage payload, never changed here): builds are opt-in ([builds] auto_send = false, so
nothing is copied to a PC automatically), but the roulette cast builder (gbox/roulette.py, the "roulette" screensaver
setting) still queues one random cast build every 10 min into the central mods/ collection. `autobuild_generation`
reports whether that generator is on and how to turn it off (POST /api/autoplay-screensaver {"roulette": false}).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from pydantic import BaseModel, Field

# ------------------------------------------------------------------------------------------------ mounts & categories

USAGE_TTL = 30 * 60          # a du snapshot is good for this long before the next poll kicks a refresh
DU_TIMEOUT = 600             # a single `du` pass (one disk walk per root) may take minutes on the big cache
DATED_RX = re.compile(r"-\d{6,}")   # gbox-pr-audit-20261017, share-git-parked-20261020-224717: a dated one-off folder

# group -> whether it is safe to free. library/runtime are the operator's; the rest is cache/auto-generated/stale.
PURGEABLE_GROUPS = {"cache", "autobuild", "stale"}

_LOCK = threading.Lock()
_STATE: dict = {"snapshot": None, "at": 0.0, "computing": False, "error": ""}


def _mounts() -> list[dict]:
    """df for the mounts that matter, cross-platform (shutil.disk_usage on each that exists). role: library (the
    operator's curated collection, never purged) | working (cache/data/system) | other."""
    want = [
        ("/", "Spark NVMe — system, cache & data", "working"),
        ("/mnt/gbox/hyperspin", "HyperSpin Arcade library", "library"),
        ("/mnt/gbox/quickswap2", "Emulation game files (Switch / PS3)", "library"),
        ("/home/ehm_eckx/samples", "Samples disk — cold cache tier", "working"),
        ("/home/ehm_eckx/pinebox-recordings", "Pine Box recordings", "other"),
    ]
    out = []
    for path, label, role in want:
        try:
            u = shutil.disk_usage(path)
        except (OSError, ValueError):
            continue
        out.append({"path": path, "label": label, "role": role, "size": u.total, "used": u.used,
                    "free": u.free, "pct": round(u.used / u.total * 100, 1) if u.total else None})
    return out


def _du_children(root: Path) -> dict[str, int]:
    """{child-name: bytes} for the top level of `root` in one disk walk (du -xb --max-depth=1). -x stays on one
    filesystem so a symlink into another folder/mount is not followed and double-counted. {} on any failure."""
    try:
        r = subprocess.run(["du", "-xb", "--max-depth=1", str(root)], capture_output=True, text=True,
                           timeout=DU_TIMEOUT, check=False)
    except (subprocess.SubprocessError, OSError):
        return {}
    out: dict[str, int] = {}
    rootn = str(root).rstrip("/")
    for line in r.stdout.splitlines():
        try:
            size_s, path = line.split("\t", 1)
            size = int(size_s)
        except ValueError:
            continue
        path = path.rstrip("/")
        name = "." if path == rootn else (path[len(rootn) + 1:] if path.startswith(rootn + "/") else path)
        out[name] = size
    return out


# per-root classification of a top-level child -> (label, group). Anything unmatched falls to the root's default.
def _classify_hot(name: str) -> tuple[str, str]:
    if name == "mods":
        return "Central build collection (auto-built casts)", "autobuild"
    if name == "modbase":
        return "Build base copies", "cache"
    if name == ".broken-builds":
        return "Broken / failed builds", "stale"
    if name in (".gbox-tiers", ".gbox-purging", ".gbox-redirected"):
        return "Cache tier / housekeeping", "cache"
    return "Staged games & disc extracts", "cache"     # game-id dirs, dc/gc/ps2/romexport_base: tool-purgeable


def _classify_data(name: str) -> tuple[str, str]:
    if name.startswith("runtime"):
        return "Emulators, saves & states (runtime)", "runtime"
    if name == "artifacts":
        return "Job output artifacts", "autobuild"
    if name == "exports":
        return "Asset / model exports", "autobuild"
    if name == "hermes-dispatch":
        return "Hermes dispatch logs & references", "stale"
    if name == "deploy-backups":
        return "Deploy backups", "stale"
    if name.startswith("mercs"):
        return "MercMode data", "cache"
    if name in ("memory-cards", "pso", "cheatdb", "thumbs", "analysis"):
        return "Game data (memory cards, PSO, cheats…)", "runtime"
    if DATED_RX.search(name):
        return "Dated one-off data (stale)", "stale"
    return "Other gBox data", "other"


def _classify_alt(name: str, hot_name: str) -> tuple[str, str] | None:
    if name == hot_name:
        return None                                    # the hot cache itself: reported under its own root, not here
    if name == "gbox-hermes-tasks":
        return "Hermes task worktrees", "stale"
    if name == "gbox-result-review-worktrees":
        return "Hermes review worktrees", "stale"
    if name in ("scratch", "gbox-scratch"):
        return "Scratch workspaces", "stale"
    if name == "switch":
        return "Switch build work", "cache"
    if DATED_RX.search(name):
        return "Dated audit / research (stale)", "stale"
    return "Other Spark side folders", "other"


def _category(key, label, group, path, bytes_, note="") -> dict:
    return {"key": key, "label": label, "group": group, "path": str(path), "bytes": int(bytes_),
            "purgeable": group in PURGEABLE_GROUPS, "note": note}


def compute(config) -> dict:
    """The real breakdown (slow: du of every working root). Called only from the background thread."""
    hot = Path(getattr(config, "cache", "") or "")
    cold = getattr(config, "cold_cache", None)
    cold = Path(cold) if cold else None
    data = Path(getattr(config, "data_dir", "") or "")
    alt = hot.parent if str(hot) else None
    cats: list[dict] = []

    # Hot cache (NVMe): its children carry the auto-built collection and the staged games.
    if hot and hot.is_dir():
        agg: dict[tuple, int] = {}                      # sum children that share a label (staged games etc.)
        for name, size in _du_children(hot).items():
            if name == ".":
                continue
            agg[_classify_hot(name)] = agg.get(_classify_hot(name), 0) + size
        for (label, group), size in agg.items():
            cats.append(_category(f"hot:{label}", label, group, hot, size,
                                  "central collection on the Linux node — the tool never deletes it; clean manually"
                                  if group == "autobuild" else
                                  "staged library copies — freed by the purge tool (games)" if group == "cache"
                                  and "Staged" in label else ""))

    # Cold cache (big samples disk): low pressure, but shown for completeness.
    if cold and cold.is_dir():
        total = sum(v for k, v in _du_children(cold).items() if k != ".") or 0
        cats.append(_category("cold:all", "Cold cache tier (samples disk)", "cache", cold, total,
                              "on the 5.5 TB samples disk (26% used): not under pressure"))

    # gBox data (NVMe): runtime (keep) vs artifacts/exports/dispatch/backups (auto-generated / stale).
    if data and data.is_dir():
        agg = {}
        for name, size in _du_children(data).items():
            if name == ".":
                continue
            agg[_classify_data(name)] = agg.get(_classify_data(name), 0) + size
        for (label, group), size in agg.items():
            cats.append(_category(f"data:{label}", label, group, data, size))

    # Spark side folders (~/gBox_alt): Hermes/agent worktrees and dated one-offs — the biggest stale accumulation.
    if alt and alt.is_dir():
        agg = {}
        for name, size in _du_children(alt).items():
            if name == ".":
                continue
            cls = _classify_alt(name, hot.name)
            if cls is None:
                continue
            agg[cls] = agg.get(cls, 0) + size
        for (label, group), size in agg.items():
            cats.append(_category(f"alt:{label}", label, group, alt, size))

    cats.sort(key=lambda c: -c["bytes"])
    return {"mounts": _mounts(), "categories": cats, "computed_at": time.time()}


def _refresh_async(config) -> None:
    def work():
        try:
            snap = compute(config)
            with _LOCK:
                _STATE.update(snapshot=snap, at=snap["computed_at"], computing=False, error="")
        except Exception as e:                           # noqa: BLE001 - a background thread must never die loud
            with _LOCK:
                _STATE.update(computing=False, error=f"{type(e).__name__}: {e}"[:300])
    with _LOCK:
        if _STATE["computing"]:
            return
        _STATE["computing"] = True
    threading.Thread(target=work, name="storage-usage-du", daemon=True).start()


# ------------------------------------------------------------------------------------------------ auto-build status

def autobuild_generation(store) -> dict:
    """Is gBox still auto-MAKING builds? Builds are opt-in to SEND ([builds] auto_send), but the roulette cast builder
    keeps generating new casts while the "roulette" screensaver setting is on. Report both, and how to stop."""
    cfg = store.get("setting", "autoplay_screensaver") or {}
    roulette = cfg.get("roulette", True)               # DEFAULTS["roulette"] is True (gbox/screensaver.py)
    try:
        auto_send = bool(getattr(getattr(store.config, "builds", None), "auto_send", False))
    except Exception:                                    # noqa: BLE001
        auto_send = False
    return {"auto_send": auto_send, "roulette_builder": bool(roulette),
            "generating": bool(roulette),
            "note": ("builds are NOT sent to PCs automatically (auto_send=false), but the roulette cast builder is ON: "
                     "it queues one random build every ~10 min into the central collection. Turn it off with "
                     "POST /api/autoplay-screensaver {\"roulette\": false}.") if roulette else
                    "auto-build generation is off (roulette builder disabled) and builds are opt-in (auto_send=false)."}


# ------------------------------------------------------------------------------------------------ routes

class PurgeBody(BaseModel):
    """The purge request body. Module level on purpose: this module uses postponed annotations, so a model
    defined inside routes() is only a local name and FastAPI cannot resolve it when building the schema."""
    worker: str = "lilspark"
    unplayed_days: int = Field(14, ge=1, le=3650)
    include: list[str] = ["games", "builds"]
    paths: list[str] = []
    confirm: bool = False                            # false => dry run (list only); true + paths => delete those


def routes(app, store, config, auth, *, submit, workers, wid, origin_dep, job_request, rejected_state):
    from fastapi import Depends, HTTPException
    from pydantic import BaseModel, Field

    @app.get("/api/storage/usage")
    def storage_usage(refresh: int = 0, actor=Depends(auth)):
        """Per-mount + per-category breakdown of the control-plane node. Cheap: returns the cached du snapshot and
        kicks a background refresh when it is stale (or ?refresh=1). library/runtime categories are the operator's
        and never purged; cache/autobuild/stale are the purgeable ones."""
        now = time.time()
        with _LOCK:
            snap, at, computing, error = _STATE["snapshot"], _STATE["at"], _STATE["computing"], _STATE["error"]
        stale = snap is None or (now - at) > USAGE_TTL
        if (stale or refresh) and not computing:
            _refresh_async(config)
            with _LOCK:
                computing = _STATE["computing"]
        # Never stat the SMB mounts on the request path: the snapshot (from the background thread) carries them.
        return {"computing": computing, "stale": stale, "age_s": round(now - at, 1) if at else None,
                "ttl_s": USAGE_TTL, "error": error, "autobuild_generation": autobuild_generation(store),
                **(snap or {"mounts": [], "categories": [], "computed_at": None})}

    def _worker(name: str) -> dict:
        w = next((x for x in workers() if x["name"] == name or x["id"] == wid(name)), None)
        if not w:
            raise HTTPException(404, f"no gBox worker '{name}'")
        return w

    @app.post("/api/storage/purge")
    def storage_purge(body: PurgeBody | None = None, actor=Depends(auth), origin=Depends(origin_dep)):
        """Run the vetted per-PC storage purge (gbox/storage_purge.py) for the panel. confirm=false lists what would be
        freed (dry run); confirm=true deletes only the reviewed `paths`. The purge only ever touches the PC's cache —
        never a library mount or a game file."""
        body = body or PurgeBody()
        dry_run = not body.confirm
        if not dry_run and not body.paths:
            raise HTTPException(422, "Deleting needs the reviewed list: run the dry run, then pass its item paths "
                                     "with confirm=true")
        w = _worker(body.worker)
        if not w.get("online"):
            raise HTTPException(409, f"{w['name']} is offline: its storage can be checked once its worker is back")
        inp = {"dry_run": dry_run, "unplayed_days": body.unplayed_days,
               "include": [i for i in body.include if i in ("games", "builds")] or ["games", "builds"],
               "paths": body.paths}
        origin = {**(origin if isinstance(origin, dict) else {}), "via": "storage_panel"}
        job = submit(job_request(tool="storage_purge", require_worker=w["id"], input=inp), actor, origin)
        if getattr(job, "state", None) == rejected_state:
            raise HTTPException(409, getattr(job, "error", None) or "the storage purge job was rejected")
        store.audit(actor, "storage.panel_purge", w["id"],
                    {"name": w["name"], "job": job.id, "dry_run": dry_run, "paths": len(body.paths)})
        return {"job_id": job.id, "worker": {"id": w["id"], "name": w["name"], "os": w.get("os")}, "dry_run": dry_run}

    @app.get("/api/storage/purge")
    def storage_purge_result(worker: str = "lilspark", job_id: str = "", actor=Depends(auth)):
        """The newest storage purge result for a PC (defaults lilspark). Reuses gbox/storage_purge result shaping."""
        from . import storage_purge as sp
        w = next((x for x in workers() if x["name"] == worker or x["id"] == wid(worker)), None)
        j = sp.latest(store, (w or {}).get("name") or worker, job_id)
        if not j:
            raise HTTPException(404, f"no storage check has run on {worker} yet (run a dry run first)")
        out = dict(j.get("output") or {})
        for group in ("items", "kept"):
            rows = []
            for r in out.get(group) or []:
                if not r.get("title") and r.get("game"):
                    try:
                        r = r | {"title": (store.catalog_get(r["game"]) or {}).get("title") or ""}
                    except Exception:                    # noqa: BLE001
                        pass
                rows.append(r)
            out[group] = rows
        facts = (j.get("input") or {}).get("facts") or {}
        return {"job_id": j.get("id"), "state": j.get("state"), "finished": j.get("finished"),
                "deletable": "central" in (facts.get("sources") or []), **out}
