"""Autoplay screensaver: idle PCs play the operator's games by themselves, the way the operator plays them.

A PC opted in here that has been idle (no operator input for `idle_minutes`, CPU/memory headroom: the same admission as
background testing) launches one of the games the operator has played most (gameplay memory: enough recorded pad
input), agent-owned, and starts autoplay on it in screensaver mode: the operator's recorded run from boot (gbox.imitate
replay), then their learned style for as long as the session lasts. Every `session_minutes` the PC moves on to another
game. Moving the mouse or touching the pad on that PC ends it at once (the worker posts /yield), like a screensaver.

The control plane runs the schedule (tick every 30 s); each PC's progress is a small state machine stored per worker:
  launching -> starting (session up, autoplay asked) -> playing -> (stop_game) -> idle again.
Results (what played, how long, why it ended, the autoplay result and score when the worker sends one) go to the log.

Every idle PC takes part by default (workers "*"): any PC not unticked in the Tasks menu (background testing) once it
has been idle long enough; a list of names limits it to those PCs. A game the operator is playing is never touched.
"""
from __future__ import annotations

import random
import threading
import time

from pydantic import BaseModel

SETTING = "autoplay_screensaver"
STATE = "autoplay_screensaver_run"          # worker name -> current run
LOG = "autoplay_screensaver_log"            # run id -> finished run
DEFAULTS = {"enabled": True, "workers": ["*"], "idle_minutes": 10, "session_minutes": 20,
            "min_pads": 300, "games": []}
LAUNCH_TIMEOUT = 15 * 60
START_GRACE = 20                            # s after the session is up before autoplay starts (boot settles)
COOLDOWN = 60 * 60                          # a game played on any PC within this rests unless nothing else is left
ACTOR = "autoplay-screensaver"
LOG_KEEP = 300


def _jid(job) -> str:
    """The id of a submitted job (the server's submit returns a Job model; tests pass dicts)."""
    return getattr(job, "id", None) or (job.get("id") or job.get("job_id") if isinstance(job, dict) else "") or ""


def settings(store) -> dict:
    return DEFAULTS | {k: v for k, v in (store.get("setting", SETTING) or {}).items() if k in DEFAULTS}


def played_games(runs: list[dict], min_pads: int) -> list[dict]:
    """Games the operator really played (gameplay memory), most played first: [{game_id, title, pads, last}]."""
    games: dict[str, dict] = {}
    for r in runs:
        gid, pads = r.get("game_id"), (r.get("events") or {}).get("pad", 0)
        if not gid or not pads:
            continue
        g = games.setdefault(gid, {"game_id": gid, "title": r.get("title") or gid, "pads": 0, "last": 0})
        g["pads"] += pads
        g["last"] = max(g["last"], r.get("updated") or 0)
    return sorted((g for g in games.values() if g["pads"] >= min_pads), key=lambda g: -g["pads"])


def choose(games: list[dict], recent: dict[str, float], now: float, rng: random.Random | None = None,
           pinned: list[str] | None = None) -> dict | None:
    """The next game: pinned games if the operator chose some, else weighted by how much the operator played it
    (square root, so one long game doesn't crowd out the rest); games played in the last hour rest when others can go."""
    rng = rng or random.Random()
    pool = [g for g in games if not pinned or g["game_id"] in pinned]
    fresh = [g for g in pool if now - recent.get(g["game_id"], 0) >= COOLDOWN]
    pool = fresh or pool
    if not pool:
        return None
    return rng.choices(pool, [max(1.0, g["pads"]) ** 0.5 for g in pool])[0]


def opted_in(store, worker: dict, cfg: dict) -> bool:
    """'*' = every PC background testing may use (not unticked in the Tasks menu); else the named PCs."""
    from . import background_testing as background
    if "*" in cfg["workers"]:
        return background.allowed(worker, background.excluded(store)) and worker.get("background_testing") is not False
    return worker.get("name") in cfg["workers"]


def worker_reason(store, worker: dict, cfg: dict, running: list[dict], now: float | None = None) -> str | None:
    """Why this PC may not start a screensaver game now (None = it may)."""
    from . import background_testing as background
    if not opted_in(store, worker, cfg):
        return "not opted in to the autoplay screensaver (Tasks menu or the screensaver's PC list)"
    if not worker.get("online"):
        return "offline"
    if worker.get("active_jobs"):
        return "busy with jobs"
    if any(s.get("session_id", "").startswith(worker["id"] + "-") for s in running):
        return "a game is already running there"
    if worker.get("os") == "windows" and (worker.get("idle_seconds") or 0) < cfg["idle_minutes"] * 60:
        return f"waiting for {cfg['idle_minutes']} minutes without operator input"
    return background.guarded_reason(store, worker, now=now, require_gpu=False)


class Screensaver:
    def __init__(self, store, archive, submit, workers, rng: random.Random | None = None):
        self.store, self.archive, self.submit, self.workers = store, archive, submit, workers
        self.rng = rng or random.Random()
        self.lock = threading.Lock()

    # --- schedule ---
    def tick(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        cfg = settings(self.store)
        out = {}
        with self.lock:
            running = self.store.running_sessions()
            for w in self.workers():
                run = self.store.get(STATE, w["name"])
                if run:
                    out[w["name"]] = self._advance(w, run, cfg, running, now)
                elif cfg["enabled"]:
                    reason = worker_reason(self.store, w, cfg, running, now)
                    out[w["name"]] = reason or self._start(w, cfg, now)
        return out

    def _recent(self) -> dict[str, float]:
        recent: dict[str, float] = {}
        for row in self.store.all(LOG):
            gid = row.get("game_id")
            recent[gid] = max(recent.get(gid, 0), row.get("started") or 0)
        for row in self.store.all(STATE):
            recent[row.get("game_id")] = time.time()
        return recent

    def _start(self, w, cfg, now):
        from .server import JobRequest
        g = choose(played_games(self.archive.runs(limit=200), cfg["min_pads"]), self._recent(), now, self.rng, cfg["games"])
        game = g and self.store.catalog_get(g["game_id"])
        if not game:
            return "no recorded game to play (play a game for a while first)"
        job = self.submit(JobRequest(tool="launch_game", input={"game": game}, agent_use=True, low_priority=True,
                                     require_worker=w["id"]), actor=ACTOR,
                          origin={"via": "autoplay screensaver", "game_id": g["game_id"]})
        jid = _jid(job)
        self.store.put(STATE, w["name"], {"worker": w["name"], "worker_id": w["id"], "phase": "launching", "job": jid,
                                          "game_id": g["game_id"], "title": g["title"], "started": now})
        return f"launching {g['title']}"

    def _advance(self, w, run, cfg, running, now):
        from .server import JobRequest
        phase = run.get("phase")
        if phase == "launching":
            job = self.store.get("job", run.get("job")) or {}
            if job.get("state") in ("failed", "rejected", "invalid", "cancelled") or now - run["started"] > LAUNCH_TIMEOUT:
                return self._finish(w, run, now, f"launch {job.get('state') or 'timed out'}: {str(job.get('error') or '')[:200]}")
            sess = next((s for s in running if s.get("session_id", "").startswith(run["worker_id"] + "-")
                         and s.get("game_id") == run["game_id"]), None)
            if sess:
                self.store.put("slabel", sess["session_id"], {"owner": "agent", "task": f"autoplay screensaver: {run['title']}"})
                run |= {"phase": "starting", "session_id": sess["session_id"], "up": now}
                self.store.put(STATE, w["name"], run)
            return f"launching {run['title']}"
        sid = run.get("session_id")
        live = any(s.get("session_id") == sid for s in running)
        if not live:
            return self._finish(w, run, now, run.get("yield") or "the game ended")
        if run.get("yield") or not cfg["enabled"] or not opted_in(self.store, w, cfg):
            return self._stop(w, run, now, run.get("yield") or "screensaver turned off")
        if phase == "starting" and now - run.get("up", now) >= START_GRACE:
            job = self.submit(JobRequest(tool="autoplay", input={"session_id": sid, "op": "start", "mode": "auto",
                                                                 "screensaver": True},
                                         agent_use=True, require_worker=run["worker_id"]), actor=ACTOR,
                              origin={"via": "autoplay screensaver", "session_id": sid})
            run |= {"phase": "playing", "autoplay_job": _jid(job), "playing_since": now}
            self.store.put(STATE, w["name"], run)
            return f"playing {run['title']}"
        if phase == "playing" and now - run.get("playing_since", now) >= cfg["session_minutes"] * 60:
            return self._stop(w, run, now, f"{cfg['session_minutes']} minutes: next game")
        return f"{phase} {run['title']}"

    def _stop(self, w, run, now, why):
        from .server import JobRequest
        self.submit(JobRequest(tool="session_op", input={"session_id": run["session_id"], "op": "stop_game", "args": {}},
                               agent_use=True, require_worker=run["worker_id"]), actor=ACTOR,
                    origin={"via": "autoplay screensaver", "session_id": run["session_id"]})
        return self._finish(w, run, now, why)

    def _finish(self, w, run, now, why):
        key = f"{run['worker']}-{int(run['started'])}"
        self.store.put(LOG, key, run | {"key": key, "ended": now, "why": why, "minutes": round((now - run["started"]) / 60, 1)})
        self.store.delete(STATE, w["name"])
        old = self.store.all(LOG)
        for row in old[:max(0, len(old) - LOG_KEEP)]:            # keep the newest LOG_KEEP runs
            self.store.delete(LOG, row.get("key", ""))
        return f"ended: {why}"

    # --- worker reports ---
    def _by_session(self, sid):
        return next((r for r in self.store.all(STATE) if r.get("session_id") == sid), None)

    def yield_to_operator(self, sid: str, reason: str) -> bool:
        with self.lock:
            run = self._by_session(sid)
            if not run:
                return False
            self.store.put(STATE, run["worker"], run | {"yield": f"operator came back ({reason})"})
        self.tick()
        return True

    def report(self, sid: str, result: dict) -> bool:
        with self.lock:
            run = self._by_session(sid)
            if not run:
                return False
            self.store.put(STATE, run["worker"], run | {"result": result})
            return True

    def status(self) -> dict:
        cfg = settings(self.store)
        log = sorted(self.store.all(LOG), key=lambda r: -(r.get("started") or 0))[:30]
        games = played_games(self.archive.runs(limit=200), cfg["min_pads"])
        return {"settings": cfg, "running": self.store.all(STATE), "log": log,
                "games": [{k: g[k] for k in ("game_id", "title", "pads")} for g in games[:40]]}


# request bodies (module level: with postponed annotations FastAPI can't see classes defined inside install())
class Settings(BaseModel):
    enabled: bool | None = None
    workers: list[str] | None = None
    idle_minutes: float | None = None
    session_minutes: float | None = None
    min_pads: int | None = None
    games: list[str] | None = None


class Yield(BaseModel):
    session_id: str
    reason: str = "input"


class Report(BaseModel):
    session_id: str
    result: dict


def install(app, store, config, auth, submit, workers, archive):
    from fastapi import Depends, HTTPException

    saver = Screensaver(store, archive, lambda req, actor, origin: submit(req, actor=actor, origin=origin), workers)
    app.state.autoplay_screensaver = saver

    @app.get("/api/autoplay-screensaver")
    def screensaver_status(actor=Depends(auth)):
        return saver.status()

    @app.post("/api/autoplay-screensaver")
    def screensaver_settings(body: Settings, actor=Depends(auth)):
        update = {k: v for k, v in body.model_dump().items() if v is not None}
        if "idle_minutes" in update and not 1 <= update["idle_minutes"] <= 240:
            raise HTTPException(422, "idle_minutes: 1..240")
        if "session_minutes" in update and not 2 <= update["session_minutes"] <= 600:
            raise HTTPException(422, "session_minutes: 2..600")
        store.put("setting", SETTING, settings(store) | update)
        store.audit(actor, "autoplay_screensaver.settings", SETTING, update)
        return saver.status()

    @app.post("/api/autoplay-screensaver/yield")
    def screensaver_yield(body: Yield, actor=Depends(auth)):
        return {"yielded": saver.yield_to_operator(body.session_id, body.reason[:80])}

    @app.post("/api/autoplay-screensaver/result")
    def screensaver_result(body: Report, actor=Depends(auth)):
        if len(str(body.result)) > 8000:
            raise HTTPException(413, "result too large")
        return {"saved": saver.report(body.session_id, body.result)}

    stopped = threading.Event()

    def loop():
        while not stopped.wait(30):
            try:
                saver.tick()
            except Exception as e:                       # one bad tick must not end the schedule
                print(f"autoplay screensaver tick failed: {type(e).__name__}: {e}", flush=True)
    app.on_event("startup")(lambda: threading.Thread(target=loop, daemon=True, name="autoplay-screensaver").start())
    app.on_event("shutdown")(stopped.set)
