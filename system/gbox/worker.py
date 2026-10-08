"""Execution worker: same code on Linux and Windows. Registers capabilities, claims jobs, posts results+artifacts."""
import base64
import platform
import threading
import time

import httpx

from . import deps
from . import tools as _builtin  # noqa: F401  (registers tools)
from .config import Config
from .models import WorkerInfo
from .registry import HOST_OS, REGISTRY, Ctx, execute

MAX_PARALLEL = 4          # long jobs (library scans) must not block short ones (stop_game) on the same node
REDESCRIBE_S = 60         # re-check tool availability (e.g. after provisioning installed ghidra)


def describe(config: Config, name: str, wid: str | None = None) -> WorkerInfo:
    ok, bad = [], {}
    for t in REGISTRY.values():
        reason = t.unavailable_reason(config)
        (bad.__setitem__(t.name, reason) if reason else ok.append(t.name))
    bad.update({f"module {n}": why for n, why in _builtin.LOAD_ERRORS.items()})
    info = WorkerInfo(name=name, os=HOST_OS, tools=ok, unavailable=bad)
    if wid:
        info.id = wid
    return info


def _run_job(job: dict, config: Config, wid: str, server: str, h: dict, client: httpx.Client, active: set):
    ctx = Ctx(config, job_id=job["id"], worker=wid)
    ctx.server, ctx.headers = server, h
    res = {"job_id": job["id"], "ok": True}
    for attempt in (0, 1):
        try:
            res["output"] = execute(job["tool"], job["input"], ctx)
            res["ok"] = True
            res.pop("error", None)
            break
        except Exception as e:
            res.update(ok=False, error=f"{type(e).__name__}: {e}")
            # a package this node doesn't have yet (Pillow, OpenCV...): install it into this environment and run the job again
            mod = deps.missing_module(e)
            if attempt or not mod:
                break
            ctx.progress(1, f"Installing the Python package for '{mod}' on this machine (one time)")
            if not deps.install_for(mod):
                res["error"] += f" (gBox tried to install the package for '{mod}' here and couldn't)"
                break
            ctx.artifacts.clear()                          # the retry starts clean (its log keeps the install line)
            ctx._pct = 0.0
    # ponytail: artifacts inline as base64; switch to streamed upload when artifacts exceed ~100MB
    res["artifacts"] = [{"name": n, "media_type": mt, "provenance": p, "b64": base64.b64encode(d).decode()}
                        for n, d, mt, p in ctx.artifacts]
    res["log"] = ctx.log
    try:
        client.post(f"/api/workers/{wid}/result", json=res, timeout=600).raise_for_status()
    finally:
        active.discard(job["id"])


def run(server: str, token: str, config: Config, name: str | None = None,
        stop: threading.Event | None = None, poll_s: float = 1.0):
    stop = stop or threading.Event()
    h = {"authorization": f"Bearer {token}"}
    name = name or platform.node()
    info = describe(config, name)
    def _push():                                    # mods built on this machine join the central collection on the Spark
        try:
            from . import filemods
            sent = filemods.push_missing(config, server, h)
            if sent:
                print(f"uploaded {len(sent)} mod(s) to the central collection: {sent}", flush=True)
        except Exception as e:
            print(f"mod upload skipped: {e}", flush=True)
    threading.Thread(target=_push, daemon=True).start()
    try:                                            # close games a previous run of this worker left running in the background
        from .tools import reap_orphans
        gone = reap_orphans(config)
        if gone:
            print(f"closed {len(gone)} leftover emulator(s) from the previous worker run: {gone}", flush=True)
    except Exception as e:
        print(f"orphan cleanup skipped: {e}", flush=True)
    active: set[str] = set()
    with httpx.Client(base_url=server, headers=h | {"x-gbox-actor": f"worker:{name}"}, timeout=30) as c:
        while not stop.is_set():                    # the control plane may be restarting: keep trying
            try:
                c.post("/api/workers/register", json=info.model_dump()).raise_for_status()
                break
            except httpx.HTTPError:
                stop.wait(poll_s * 3)
        described = time.time()
        while not stop.is_set():
            if time.time() - described > REDESCRIBE_S:
                info, described = describe(config, name, info.id), time.time()
                c.post("/api/workers/register", json=info.model_dump())
            if len(active) >= MAX_PARALLEL:
                stop.wait(poll_s)
                continue
            try:
                r = c.post(f"/api/workers/{info.id}/claim")
            except httpx.TransportError:
                stop.wait(poll_s * 5)
                continue
            if r.status_code == 404:                               # server restarted with fresh state
                c.post("/api/workers/register", json=info.model_dump()).raise_for_status()
                continue
            if r.status_code == 204:
                stop.wait(poll_s)
                continue
            r.raise_for_status()
            job = r.json()
            active.add(job["id"])
            threading.Thread(target=_run_job, args=(job, config, info.id, server, h, c, active), daemon=True).start()
