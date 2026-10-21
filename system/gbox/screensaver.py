"""Autoplay screensaver: idle PCs play the operator's games by themselves, the way the operator plays them.

A PC opted in here that has been idle (no operator input for `idle_minutes`, CPU/memory headroom: the same admission as
background testing) launches one of the games the operator has played most (gameplay memory: enough recorded pad
input), agent-owned, and starts autoplay on it in screensaver mode: the operator's recorded run from boot (gbox.imitate
replay), then their learned style for as long as the session lasts. Every `session_minutes` the PC moves on to another
game. Moving the mouse or touching the pad on that PC hands the game to the operator (the worker posts /yield): it
stays up and plays on until they press Stop (operator 2026-10-20: "if I take control of the application while the screen
saver is in place and it's auto playing a game, let it continue playing until I click the stop button"). A mouse move
leaves the autoplay going; a pad touch means they play. The PC's run ends there and the session becomes theirs (label
owner "you"), so nothing automated closes, resets or rotates it.

The control plane runs the schedule (tick every 30 s); each PC's progress is a small state machine stored per worker:
  launching -> starting (session up, autoplay asked) -> playing -> (stop_game) -> idle again.
Results (what played, how long, why it ended, the autoplay result and score when the worker sends one) go to the log.

Every idle PC takes part by default (workers "*"): any PC not unticked in the Tasks menu (background testing) once it
has been idle long enough; a list of names limits it to those PCs. A game the operator is playing is never touched.

Roulette (gbox.roulette, setting "roulette"): a demo launches one of the game's built casts (Sonic / Mario casts, the
operator's starred builds and roulette builds first) rather than the stock game, the operator's favorites with such
builds join the games (when autoplay can play them well: recorded play or a playbook), and a background builder keeps
making new random casts from the whole character collection.

Jump states (gbox.jumpstate): every demo launch asks for a jump (launch_game jump=true). Where the emulator boots
straight into a saved gameplay moment of that game and build (standalone Dolphin) and the PC has one, no logo, title
or menu shows, the replay from boot is skipped and autoplay starts in the same tick, in the operator's style.
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
            "min_pads": 300, "games": [], "roulette": True}
FAVORITE_MIN_PADS = 50                       # a favorite joins with this much recorded play (or a playbook)
LAUNCH_TIMEOUT = 15 * 60
START_GRACE = 20                            # s after the session is up before autoplay starts (boot settles)
COOLDOWN = 60 * 60                          # a game played on any PC within this rests unless nothing else is left
ACTOR = "autoplay-screensaver"
LOG_KEEP = 300
BAD_ENDS = {"black": "the game showed only black: next game", "hung": "the game froze: next game"}


PENDING = "autoplay_on_launch"            # launch job id -> {game_id, at}: start autoplay when that game is up
PENDING_TTL = 15 * 60
BOT_DEMO = "bot_demo"                     # launch job id -> {game_id, by, at}: a bot demo (launched with autoplay on)
BOT_DEMO_KEEP = 300
DEMO_ACTOR = "autoplay"                   # who starts a bot demo's autoplay (the worker's own calls say the same)


def autoplay_on_launch(store, job_id: str, game_id: str, actor: str = "operator", agent: bool = False) -> None:
    """A launch asked to play itself: a bot demo ("Bot demo on <PC>" on any PC, the operator's own included; the Spark
    button). The next ticks start autoplay once it runs, and the session is marked a bot demo (GET /api/sessions
    bot_demo: the Sessions header says so; autoplay may relaunch it when it freezes, gbox.tools._bad_end)."""
    if job_id:
        now = time.time()
        store.put(PENDING, job_id, {"job": job_id, "game_id": game_id, "at": now, "actor": actor, "agent": bool(agent)})
        store.put(BOT_DEMO, job_id, {"job": job_id, "game_id": game_id, "by": actor, "agent": bool(agent), "at": now})
        old = store.all(BOT_DEMO)
        for row in sorted(old, key=lambda r: r.get("at") or 0)[:max(0, len(old) - BOT_DEMO_KEEP)]:
            store.delete(BOT_DEMO, row.get("job", ""))


def bot_demo(store, sid: str) -> dict | None:
    """The bot-demo record of a session (session ids are <worker>-<launch job>), or None."""
    jid = (sid or "").split("-", 1)[-1] if "-" in (sid or "") else ""
    return store.get(BOT_DEMO, jid) if jid else None


def carry_bot_demo(store, old_sid: str, new_sid: str) -> bool:
    """A bot demo relaunched (autoplay's _bad_end, a reset) stays a bot demo under its new session id."""
    rec = bot_demo(store, old_sid)
    if not rec or not new_sid or new_sid == old_sid or "-" not in new_sid:
        return False
    jid = new_sid.split("-", 1)[-1]
    store.put(BOT_DEMO, jid, rec | {"job": jid, "relaunched_from": old_sid, "at": time.time()})
    return True


def _jumped(sess: dict) -> bool:
    """The session booted straight into its jump state (gbox.jumpstate, launch detail.jump): it is in gameplay
    already, so autoplay starts at once instead of waiting START_GRACE for the boot to settle."""
    return bool(((sess.get("detail") or {}).get("jump") or {}).get("booted"))


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


NO_INPUT = ("does not support send_input",)   # a run that failed like this: the game can't be played by autoplay


def unplayable(store) -> set[str]:
    """Games whose screensaver run showed autoplay cannot press buttons in them (launcher-only adapters...)."""
    out = set()
    for row in store.all(LOG):
        err = str((row.get("result") or {}).get("error") or "")
        if any(m in err for m in NO_INPUT):
            out.add(row.get("game_id"))
    return out


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


def playbook_games() -> set[str]:
    """Catalog games a playbook plays without recorded play (gbox.doa2_bot)."""
    try:
        from . import doa2_bot
        return set(doa2_bot.GAME_IDS)
    except Exception:                                # noqa: BLE001
        return set()


class Screensaver:
    def __init__(self, store, archive, submit, workers, rng: random.Random | None = None, builds=None, favorites=None):
        # builds(game_id) -> [built mod]; favorites() -> [{game_id, title}] (roulette; both optional)
        self.store, self.archive, self.submit, self.workers = store, archive, submit, workers
        self.builds, self.favorites = builds, favorites
        self.builder = None
        self.rng = rng or random.Random()
        self.lock = threading.Lock()

    def games(self, cfg) -> list[dict]:
        """The games a demo may play: the operator's most played, plus (roulette) favorites with demo builds."""
        skip = unplayable(self.store)
        runs = self.archive.runs(limit=200)
        games = [x for x in played_games(runs, cfg["min_pads"]) if x["game_id"] not in skip]
        if cfg.get("roulette") and self.favorites and self.builds:
            from . import roulette
            have = {g["game_id"] for g in games}
            some = {g["game_id"]: g for g in played_games(runs, FAVORITE_MIN_PADS)}
            books = playbook_games()
            for f in self.favorites():
                gid = f.get("game_id")
                if not gid or gid in have or gid in skip or not (gid in some or gid in books):
                    continue
                if roulette.demo_builds(self.builds(gid)):
                    games.append({"game_id": gid, "title": f.get("title") or gid,
                                  "pads": max(cfg["min_pads"], (some.get(gid) or {}).get("pads", 0))})
                    have.add(gid)
        return games

    # --- schedule ---
    def tick(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        cfg = settings(self.store)
        out = {}
        with self.lock:
            running = self.store.running_sessions()
            out["launches"] = self._pending(running, now)
            for w in self.workers():
                run = self.store.get(STATE, w["name"])
                if run:
                    out[w["name"]] = self._advance(w, run, cfg, running, now)
                elif cfg["enabled"]:
                    reason = worker_reason(self.store, w, cfg, running, now)
                    out[w["name"]] = reason or self._start(w, cfg, now)
        return out

    def _pending(self, running, now) -> list[str]:
        """Launches marked autoplay (bot demos on any PC, the Spark button): autoplay starts START_GRACE s after the
        session is up, or at once when the launch booted straight into its jump state. It starts as a bot demo
        (demo: plays on, polite input on a PC someone uses), as autoplay's own job; agent_use only when an agent
        launched the demo (its callbacks then count as automation, which never touches the operator's games)."""
        from .server import JobRequest
        done = []
        for p in self.store.all(PENDING):
            jid = p.get("job", "")
            job = self.store.get("job", jid) or {}
            sess = next((s for s in running if s.get("session_id", "").endswith("-" + jid)), None)
            if job.get("state") in ("failed", "rejected", "invalid", "cancelled") or now - p.get("at", now) > PENDING_TTL:
                self.store.delete(PENDING, jid)
                continue
            if not sess:
                continue
            if "up" not in p:
                if not _jumped(sess):
                    self.store.put(PENDING, jid, p | {"up": now})
                    continue
                p = p | {"up": now - START_GRACE}            # in gameplay already: no boot to settle
            if now - p["up"] < START_GRACE:
                continue
            sid = sess["session_id"]
            self.submit(JobRequest(tool="autoplay", input={"session_id": sid, "op": "start", "mode": "auto", "demo": True},
                                   agent_use=bool(p.get("agent", False)), require_worker=sid.split("-")[0]),
                        actor=DEMO_ACTOR, origin={"via": "bot demo (autoplay on launch)", "session_id": sid,
                                                  "launched_by": p.get("actor") or "operator"})
            self.store.delete(PENDING, jid)
            done.append(sid)
        return done

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
        g = choose(self.games(cfg), self._recent(), now, self.rng, cfg["games"])
        game = g and self.store.catalog_get(g["game_id"])
        if not game:
            return "no recorded game to play (play a game for a while first)"
        build = None
        if cfg.get("roulette") and self.builds:
            from . import roulette
            build = roulette.demo_build(self.builds(g["game_id"]), self.rng)
        # jump: the demo starts in gameplay where this PC has a jump state for the game and build (gbox.jumpstate)
        inp = {"game": game, "jump": True} | ({"mod": build["name"]} if build else {})
        job = self.submit(JobRequest(tool="launch_game", input=inp, agent_use=True, low_priority=True,
                                     require_worker=w["id"]), actor=ACTOR,
                          origin={"via": "autoplay screensaver", "game_id": g["game_id"]})
        jid = _jid(job)
        label = build and (build.get("display_name") or build.get("label") or build["name"])
        self.store.put(STATE, w["name"], {"worker": w["name"], "worker_id": w["id"], "phase": "launching", "job": jid,
                                          "game_id": g["game_id"], "title": g["title"], "started": now,
                                          **({"mod": build["name"], "build": label} if build else {})})
        return f"launching {g['title']}" + (f" ({label})" if build else "")

    def _advance(self, w, run, cfg, running, now):
        from .server import JobRequest
        phase = run.get("phase")
        if phase == "launching":
            job = self.store.get("job", run.get("job")) or {}
            if job.get("state") in ("failed", "rejected", "invalid", "cancelled") or now - run["started"] > LAUNCH_TIMEOUT:
                return self._finish(w, run, now, f"launch {job.get('state') or 'timed out'}: {str(job.get('error') or '')[:200]}")
            sess = next((s for s in running if s.get("session_id", "").startswith(run["worker_id"] + "-")
                         and s.get("game_id") == run["game_id"]), None)
            if not sess:
                return f"launching {run['title']}"
            self.store.put("slabel", sess["session_id"], {"owner": "agent", "task": f"autoplay screensaver: {run['title']}"})
            jumped = _jumped(sess)                       # booted into gameplay: autoplay starts in this tick
            run |= {"phase": "starting", "session_id": sess["session_id"], "up": now - START_GRACE if jumped else now,
                    **({"jumped": True} if jumped else {})}
            self.store.put(STATE, w["name"], run)
            if not jumped:
                return f"launching {run['title']}"
            phase = "starting"
        sid = run.get("session_id")
        live = any(s.get("session_id") == sid for s in running)
        if not live:
            return self._finish(w, run, now, run.get("yield") or "the game ended")
        if run.get("handover"):                         # the operator came back: theirs now, it plays on until Stop
            self.store.put("slabel", sid, {"session_id": sid, "owner": "you", "ts": now,
                                           "label": f"{run['title']}: autoplay, handed over by the screensaver"})
            return self._finish(w, run, now, f"handed to the operator ({run['handover']}): plays on until Stop")
        if run.get("yield") or not cfg["enabled"] or not opted_in(self.store, w, cfg):
            return self._stop(w, run, now, run.get("yield") or "screensaver turned off")
        if phase == "starting" and now - run.get("up", now) >= START_GRACE:
            from . import imitate
            knobs = imitate.choose_knobs(self.history(run["game_id"]), self.rng)
            run["knobs"] = knobs
            job = self.submit(JobRequest(tool="autoplay", input={"session_id": sid, "op": "start", "mode": "auto",
                                                                 "screensaver": True, "style": knobs},
                                         agent_use=True, require_worker=run["worker_id"]), actor=ACTOR,
                              origin={"via": "autoplay screensaver", "session_id": sid})
            run |= {"phase": "playing", "autoplay_job": _jid(job), "playing_since": now}
            self.store.put(STATE, w["name"], run)
            return f"playing {run['title']}"
        if phase == "playing" and now - run.get("playing_since", now) >= cfg["session_minutes"] * 60:
            return self._stop(w, run, now, f"{cfg['session_minutes']} minutes: next game")
        return f"{phase} {run['title']}"

    def history(self, game_id: str) -> list[dict]:
        """This game's earlier screensaver runs as [{knobs, score}] (the novelty each set of style knobs reached)."""
        out = []
        for row in self.store.all(LOG):
            res = row.get("result") or {}
            if row.get("game_id") == game_id and isinstance(res.get("score"), (int, float)):
                out.append({"knobs": res.get("knobs") or row.get("knobs") or {}, "score": res["score"]})
        return out

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
        """The operator is back at this PC (mouse / pad): the game is handed to them and keeps playing - never closed."""
        with self.lock:
            run = self._by_session(sid)
            if not run:
                return False
            self.store.put(STATE, run["worker"], run | {"handover": reason})
        self.tick()
        return True

    def report(self, sid: str, result: dict) -> bool:
        """The worker's autoplay result. One that ended because the game froze or showed only black (bad_end) moves this
        PC on to its next game at the next tick (autoplay never leaves a frozen or black game on screen)."""
        with self.lock:
            run = self._by_session(sid)
            if not run:
                return False
            upd = {"result": (run.get("result") or {}) | result}
            bad = result.get("bad_end")
            if bad and not run.get("yield"):
                upd["yield"] = BAD_ENDS.get(bad, f"{bad}: next game")
            self.store.put(STATE, run["worker"], run | upd)
            return True

    def status(self) -> dict:
        cfg = settings(self.store)
        log = sorted(self.store.all(LOG), key=lambda r: -(r.get("started") or 0))[:30]
        games = self.games(cfg)
        out = {"settings": cfg, "running": self.store.all(STATE), "log": log,
               "games": [{k: g[k] for k in ("game_id", "title", "pads")} for g in games[:40]]}
        if self.builder is not None:
            out["roulette"] = self.builder.status()
        return out


# request bodies (module level: with postponed annotations FastAPI can't see classes defined inside install())
class Settings(BaseModel):
    enabled: bool | None = None
    workers: list[str] | None = None
    idle_minutes: float | None = None
    session_minutes: float | None = None
    min_pads: int | None = None
    games: list[str] | None = None
    roulette: bool | None = None


class Yield(BaseModel):
    session_id: str
    reason: str = "input"


class Report(BaseModel):
    session_id: str
    result: dict


class Telemetry(BaseModel):
    running: bool = True
    mode: str = ""
    mission: str = ""
    title: str = ""
    stats: dict = {}
    demo: bool = False                    # a bot demo plays (the Sessions header says so)


TELEMETRY: dict[str, dict] = {}           # session id -> what autoplay is doing right now (in memory: live view only)
TELEMETRY_TTL = 600


def telemetry_put(sid: str, body: dict, now: float | None = None) -> None:
    now = time.time() if now is None else now
    TELEMETRY[sid] = body | {"at": now}
    for k in [k for k, v in TELEMETRY.items() if now - v["at"] > TELEMETRY_TTL]:
        TELEMETRY.pop(k, None)


def telemetry_get(sid: str, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    t = TELEMETRY.get(sid)
    if not t or now - t["at"] > TELEMETRY_TTL:
        return {}
    return {k: v for k, v in t.items() if k != "at"} | {"age_s": round(now - t["at"], 1),
                                                         "running": t.get("running", True) and now - t["at"] < 30}


def install(app, store, config, auth, submit, workers, archive):
    from fastapi import Depends, HTTPException

    def builds_for(gid: str) -> list[dict]:
        cur = getattr(app.state, "built_mods_current", None)
        if cur is None:
            return []
        try:
            return [b for b in cur(False)["items"] if b.get("game_id") == gid]
        except Exception:                            # noqa: BLE001 - no index yet: stock games
            return []

    def favorites() -> list[dict]:
        try:
            return [f for f in store.favorites() if f.get("in_catalog", True)]
        except Exception:                            # noqa: BLE001
            return []

    saver = Screensaver(store, archive, lambda req, actor, origin: submit(req, actor=actor, origin=origin), workers,
                        builds=builds_for, favorites=favorites)
    app.state.autoplay_screensaver = saver
    from . import roulette
    from .server import JobRequest

    def roulette_candidates() -> list[dict]:
        cfg = settings(store)
        played = {g["game_id"]: g for g in played_games(archive.runs(limit=200), FAVORITE_MIN_PADS)}
        out = {gid: {"game_id": gid, "title": g["title"], "favorite": False} for gid, g in played.items()}
        for f in favorites():
            out[f["game_id"]] = {"game_id": f["game_id"], "title": f.get("title") or f["game_id"], "favorite": True}
        return [c for c in out.values() if not cfg["games"] or c["game_id"] in cfg["games"]]

    saver.builder = roulette.Builder(
        store, lambda call: submit(JobRequest(tool=call["tool"], input=call["input"], require_os="linux",
                                              agent_use=True, low_priority=True),
                                   actor=roulette.ACTOR, origin={"via": "autoplay roulette"}),
        builds_for, roulette_candidates)

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

    @app.post("/api/autoplay/telemetry/{sid}")
    def autoplay_telemetry_put(sid: str, body: Telemetry, actor=Depends(auth)):
        if len(str(body.stats)) > 4000:
            raise HTTPException(413, "stats too large")
        telemetry_put(sid, body.model_dump())
        return {"ok": True}

    @app.get("/api/autoplay/telemetry/{sid}")
    def autoplay_telemetry_get(sid: str, actor=Depends(auth)):
        return telemetry_get(sid)

    stopped = threading.Event()

    def loop():
        while not stopped.wait(30):
            try:
                saver.tick()
            except Exception as e:                       # one bad tick must not end the schedule
                print(f"autoplay screensaver tick failed: {type(e).__name__}: {e}", flush=True)
            try:
                saver.builder.tick(bool(settings(store).get("roulette")))
            except Exception as e:                       # the roulette builder never stops the screensaver
                print(f"autoplay roulette tick failed: {type(e).__name__}: {e}", flush=True)
    app.on_event("startup")(lambda: threading.Thread(target=loop, daemon=True, name="autoplay-screensaver").start())
    app.on_event("shutdown")(stopped.set)
