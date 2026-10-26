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

import json
import random
from .mercs import warm_boot
import threading
import time

from pydantic import BaseModel

SETTING = "autoplay_screensaver"
STATE = "autoplay_screensaver_run"          # worker name -> current run
LOG = "autoplay_screensaver_log"            # run id -> finished run
DEFAULTS = {"enabled": True, "workers": ["*"], "idle_minutes": 10, "session_minutes": 20,
            "min_pads": 300, "games": [], "roulette": True,
            "bot_pcs": []}                  # PCs dedicated to bots: a bot demo there owns the keyboard (no polite input)
FAVORITE_MIN_PADS = 50                       # a favorite joins with this much recorded play (or a playbook)
LAUNCH_TIMEOUT = 15 * 60
START_GRACE = 20                            # s after the session is up before autoplay starts (boot settles)
COOLDOWN = 60 * 60                          # a game played on any PC within this rests unless nothing else is left
ACTOR = "autoplay-screensaver"
LOG_KEEP = 300
BAD_ENDS = {"black": "the game showed only black: next game", "hung": "the game froze: next game"}


ROTATION = "verified native round boundary: next MercMode title"   # why a MercMode run ends at its native round boundary

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
    own = store.get(BOT_DEMO, jid) if jid else None
    if own:
        return own
    sess = store.get('session', sid) or {}
    central = sess.get('central_launch_job_id')
    record = store.get(BOT_DEMO, central) if central else None
    # Federation preserves the native local SID. A central marker belongs to it
    # only after the accepted launch and both job mappings agree exactly.
    if record and _launch_session(store, central, [sess], game_id=record.get('game_id')):
        return record | {'job': jid, 'central_launch_job_id': central}
    return None


def _launch_session(store, jid, sessions, *, worker_id=None, game_id=None):
    """Resolve this launch only, including an accepted central-to-local relay."""
    if not isinstance(jid, str) or not jid:
        return None
    job = store.get('job', jid) or {}
    owner = worker_id or job.get('worker_id') or job.get('require_worker')
    expected_game = game_id or (job.get('input', {}).get('game') or {}).get('game_id')
    for sess in sessions:
        sid = sess.get('session_id', '')
        wid, _, local = sid.partition('-')
        if not local or (owner and wid != owner) or (expected_game and sess.get('game_id') != expected_game):
            continue
        if any(job.get(key) and job[key] != wid for key in ('worker_id', 'require_worker')):
            continue
        if local == jid and not sess.get('federation'):
            return sess                          # original native launch identity
        out = job.get('output') or {}
        detail = out.get('detail') or {}
        command = store.get('federation_command', jid) or {}
        inverse = store.get('federation_local_job', sid) or {}
        authority = (sess.get('federation') or {}).get('authority')
        gid = (job.get('input', {}).get('game') or {}).get('game_id')
        if (job.get('state') == 'succeeded' and job.get('tool') == 'launch_game'
                and job.get('worker_id') == wid
                and out.get('session_id') == sid and gid and gid == sess.get('game_id')
                and (detail.get('_game') or {}).get('game_id') == gid
                and out.get('adapter') == sess.get('adapter')
                and detail.get('pid') == (sess.get('detail') or {}).get('pid')
                and sess.get('central_launch_job_id') == jid and sess.get('local_launch_job_id') == local
                and authority and command.get('authority') == authority and command.get('worker_id') == wid
                and command.get('local_job_id') == local and command.get('local_state') == 'succeeded'
                and (command.get('ack') or {}).get('accepted') is True
                and inverse == {'authority': authority, 'central_job_id': jid, 'local_job_id': local}):
            return sess
    return None


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


def _current_workers(workers) -> list:
    """One registration per PC name: the online one, else the last registered (a restart leaves the old ids behind)."""
    best: dict = {}
    for w in workers:
        name = w.get('name')
        if name not in best or (w.get('online') and not best[name].get('online')) or \
                (bool(w.get('online')) == bool(best[name].get('online')) and (w.get('last_seen') or 0) >= (best[name].get('last_seen') or 0)):
            best[name] = w
    return list(best.values())


def _local_scheduler(worker):
    return (worker.get('federation') or {}).get('scheduler_owner')=='local'


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
    from . import mercmode
    warm = mercmode.warm_sessions(store, worker['name'])
    if worker.get("active_jobs"):
        # a MercMode warm switch may go ahead while only this scheduler's own pause / preload jobs are in flight there
        own = sum(1 for j in store.all('job') if j.get('actor') == ACTOR and j.get('require_worker') == worker['id']
                  and j.get('state') in ('queued', 'assigned', 'running')) \
            if warm or store.get(mercmode.NEXT, worker['name']) else 0
        if worker['active_jobs'] > own:
            return "busy with jobs"
    if any(s.get("session_id", "").startswith(worker["id"] + "-") and s.get("session_id") not in warm for s in running):
        return "a game is already running there"
    merc_cfg=mercmode.settings(store,worker['name'])
    if merc_cfg['enabled'] and merc_cfg['presentation_priority']:
        return background.admission_reason(worker,background.excluded(store),101,now=now,
                                           allow_active=True,require_gpu=False)
    if worker.get("os") == "windows" and (worker.get("idle_seconds") or 0) < cfg["idle_minutes"] * 60:
        return f"waiting for {cfg['idle_minutes']} minutes without operator input"
    return background.guarded_reason(store, worker, now=now, require_gpu=False)


def playbook_games() -> set[str]:
    """Catalog games a playbook plays without recorded play (gbox.doa2_bot, gbox.doa3_bot)."""
    out: set[str] = set()
    for name in ("doa2_bot", "doa3_bot"):
        try:
            import importlib
            out |= set(importlib.import_module(f".{name}", __package__).GAME_IDS)
        except Exception:                            # noqa: BLE001
            pass
    return out


class Screensaver:
    def __init__(self, store, archive, submit, workers, rng: random.Random | None = None, builds=None, favorites=None):
        # builds(game_id) -> [built mod]; favorites() -> [{game_id, title}] (roulette; both optional)
        self.store, self.archive, self.submit, self.workers = store, archive, submit, workers
        self.builds, self.favorites = builds, favorites
        self.config = None                           # install(): [builds] auto_send for the roulette's build choice
        self.builder = None
        self.rng = rng or random.Random()
        self.lock = threading.Lock()
        self.wake = None                                 # install(): the schedule loop's event; nudge() sets it

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
                host_cfg = self._worker_settings(w, cfg)
                if not _local_scheduler(w):
                    self._tend_warm(w, running, now)
                run = self.store.get(STATE, w["name"])
                if run:
                    out[w["name"]] = self._advance(w, run, host_cfg, running, now)
                    if run.get('mercmode') and host_cfg["enabled"] and not _local_scheduler(w) \
                            and self.store.get(STATE, w["name"]) is None and str(out[w["name"]]).startswith(f'ended: {ROTATION}'):
                        # a MercMode rotation: the next title starts in this same tick (the ready one is resumed at
                        # once: no 30 s gap between the park and the swap)
                        running = self.store.running_sessions()
                        reason = worker_reason(self.store, w, host_cfg, running, now)
                        out[w["name"]] = reason or self._start(w, host_cfg, now)
                elif host_cfg["enabled"]:
                    reason = ('scheduled by this PC\'s local control plane' if _local_scheduler(w)
                              else worker_reason(self.store, w, host_cfg, running, now))
                    out[w["name"]] = reason or self._start(w, host_cfg, now)
        return out

    def nudge(self, why: str = '') -> None:
        """Tick now (on the schedule's own thread, install): a scheduler job landed on the worker (the pause, resume,
        launch or autoplay start of a MercMode warm switch) or a native round boundary asked for the next title. The
        30 s loop alone left the swap waiting up to a tick at every step (operator 2026-10-26: "the transitions between
        loads is just too long ... I hate waiting"). Without the installed loop (tests) this is a no-op."""
        wake = getattr(self, 'wake', None)
        if wake is not None:
            self.nudged = why
            wake.set()

    def _worker_settings(self, worker, cfg):
        from . import mercmode
        return cfg | {"enabled": True, "workers": [worker['name']]} \
            if mercmode.settings(self.store, worker['name'])['enabled'] else cfg

    def _pending(self, running, now) -> list[str]:
        """Launches marked autoplay (bot demos on any PC, the Spark button): autoplay starts START_GRACE s after the
        session is up, or at once when the launch booted straight into its jump state. It starts as a bot demo
        (demo: plays on, polite input on a PC someone uses), as autoplay's own job; agent_use only when an agent
        launched the demo (its callbacks then count as automation, which never touches the operator's games)."""
        from .server import JobRequest
        done = []
        local_workers={w['id'] for w in self.workers() if _local_scheduler(w)}
        for p in self.store.all(PENDING):
            jid = p.get("job", "")
            job = self.store.get("job", jid) or {}
            sess = _launch_session(self.store, jid, running, game_id=p.get('game_id'))
            if job.get("state") in ("failed", "rejected", "invalid", "cancelled") or now - p.get("at", now) > PENDING_TTL:
                self.store.delete(PENDING, jid)
                continue
            if not sess:
                continue
            if sess['session_id'].split('-',1)[0] in local_workers:
                continue                           # the explicit launch marker is relayed to its sole local scheduler
            if "up" not in p:
                if not _jumped(sess):
                    self.store.put(PENDING, jid, p | {"up": now})
                    continue
                p = p | {"up": now - START_GRACE}            # in gameplay already: no boot to settle
            if now - p["up"] < START_GRACE:
                continue
            sid = sess["session_id"]
            names = {w.get("id"): w.get("name") for w in self.workers()}
            owns = names.get(sid.split("-")[0]) in settings(self.store)["bot_pcs"]
            self.submit(JobRequest(tool="autoplay", input={"session_id": sid, "op": "start", "mode": "auto", "demo": True,
                                                           **({"owns_keyboard": True} if owns else {})},
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
        from . import mercmode
        if _local_scheduler(w):
            return 'scheduled by this PC\'s local control plane'
        merc_cfg = mercmode.settings(self.store, w['name'])
        merc_pick = mercmode.choose(self.store, w, self.rng, merc_cfg) if merc_cfg['enabled'] else None
        warm_ok = bool(merc_pick) and self._warm_capable(w, merc_cfg)
        if warm_ok:
            resumed = self._resume_warm(w, merc_pick, merc_cfg, now)
            if resumed:
                return resumed
        g = ({'game_id': merc_pick['game_id'], 'title': merc_pick['name']} if merc_pick else None) \
            if merc_cfg['enabled'] else choose(self.games(cfg), self._recent(), now, self.rng, cfg["games"])
        game = g and self.store.catalog_get(g["game_id"])
        if not game:
            if merc_cfg['enabled']:
                prepared=self.store.get(mercmode.PREPARATION,w['name']) or {}
                if ('mercmode' in w.get('tools',[]) and now-prepared.get('requested_at',-1e9)>=300
                        and any(r.get('backend_playable') for r in mercmode.inventory(self.store,w,merc_cfg))):
                    job=self.submit(JobRequest(tool='mercmode',input={'op':'prepare'},agent_use=True,
                        low_priority=True,require_worker=w['id']),actor=ACTOR,
                        origin={'via':'MercMode host readiness','worker':w['name']})
                    self.store.put(mercmode.PREPARATION,w['name'],prepared|{'requested_at':now,
                        'job':_jid(job),'state':'checking'})
                    return 'MercMode: checking ROM access and cached assets on this PC'
                return 'MercMode: no ready title ('+'; '.join(r['reason'] for r in mercmode.inventory(self.store,w,merc_cfg))+')'
            return "no recorded game to play (play a game for a while first)"
        build = None
        if not merc_cfg['enabled'] and cfg.get("roulette") and self.builds:
            from . import roulette, storage_policy
            # builds are opt-in per PC ([builds] auto_send = false): a demo plays a build this PC already has or the
            # operator downloaded here, else the stock game; it never copies one over (gbox/storage_policy.py)
            build = roulette.demo_build([b for b in self.builds(g["game_id"]) if storage_policy.sendable(
                self.store, self.config, w, g["game_id"], str(b.get("name") or ""))], self.rng)
        # jump: the demo starts in gameplay where this PC has a jump state for the game and build (gbox.jumpstate)
        # memory_cards: the operator's own cards go in, so their saved characters load (#2817: "get my memory card ...
        # you need to use it with screensaver for playing the game"); their own launch elsewhere takes a card back
        if merc_pick:
            game = game | {'launch':dict(game.get('launch') or {}) | {
                'mercmode': mercmode.launch_block(merc_cfg, merc_pick.get('selection'))}}
            if merc_pick.get('selection'):
                mercmode.pop_queue(self.store, w['name'])        # the DJ's queued round is on its way
        inp = {"game": game, "jump": True, "memory_cards": "operator"} | (
            {"mod": build["name"], "local_build_ok": True} if build else {})    # a stale copy here still demos
        if warm_ok and not mercmode.memory_reason(w, now):
            # a cold launch of a title with nothing warm keeps the pool's paused games (with too little memory the
            # worker's one-game rule closes them, without a save: nothing was played in them)
            keep = [r['session_id'] for r in self._warm(w, self.store.running_sessions(), now).values()
                    if r.get('session_id') and r.get('state') != 'releasing']
            if keep:
                inp["keep_sessions"] = keep
        job = self.submit(JobRequest(tool="launch_game", input=inp, agent_use=True, low_priority=True,
                                     require_worker=w["id"]), actor=ACTOR,
                          origin={"via": "autoplay screensaver", "game_id": g["game_id"]})
        jid = _jid(job)
        label = build and (build.get("display_name") or build.get("label") or build["name"])
        self.store.put(STATE, w["name"], {"worker": w["name"], "worker_id": w["id"], "phase": "launching", "job": jid,
                                          "game_id": g["game_id"], "title": g["title"], "started": now,
                                          **({'mercmode_predecessor':mercmode.rotation_predecessor(self.store,w,now),
                                              'mercmode': {'title': merc_pick['title'], 'map_id': merc_pick['map_id'],
                                               'rounds_per_title': merc_cfg['rounds_per_title'],
                                               **({'selection': merc_pick['selection']} if merc_pick.get('selection') else {})}}
                                              if merc_pick else {}),
                                          **({"mod": build["name"], "build": label} if build else {})})
        return f"launching {g['title']}" + (f" ({label})" if build else "")

    def _advance(self, w, run, cfg, running, now):
        from .server import JobRequest
        phase = run.get("phase")
        if phase == "launching":
            job = self.store.get("job", run.get("job")) or {}
            if job.get("state") in ("failed", "rejected", "invalid", "cancelled") or now - run["started"] > LAUNCH_TIMEOUT:
                why = f"launch {job.get('state') or 'timed out'}: {str(job.get('error') or '')[:200]}"
                if run.get('prelaunched'):                   # the warm preload failed: that title launches cold next
                    return self._warm_fallback(w, run, now, 'warm ' + why)
                return self._finish(w, run, now, why)
            # An accepted relay keeps its local launch ID; never adopt another
            # same-game session merely because it is running on the chosen PC.
            sess = _launch_session(self.store, run.get('job'), running,
                                   worker_id=run['worker_id'], game_id=run['game_id'])
            if not sess:
                return f"launching {run['title']}"
            if run.get('prelaunched'):
                # a warm preload taken over mid-load: the worker pauses it when its launch finishes, so the resume
                # waits for that exact launch to succeed (a resume sent earlier would be undone by that pause)
                if job.get('state') != 'succeeded':
                    return f"launching {run['title']}"
                warm = warm_boot.receipt(sess, job)
                if warm.get('state') == 'loading':
                    return f"preparing {run['title']} (native title/menu not ready)"
                if warm.get('state') == 'preparing':
                    return f"preparing {run['title']} (its round is being set up in the background)"
                if warm.get('state') == 'cancelled':
                    return self._finish(w, run, now, 'native preparation cancelled; session left untouched')
                if not warm_boot.prepared(sess, job, (run.get('mercmode') or {}).get('map_id')):
                    return self._warm_fallback(w, run, now, str(warm.get('reason') or 'native preparation failed'))
                resume = self.submit(JobRequest(tool='session_op', input={'session_id': sess['session_id'], 'op': 'resume',
                                                                          'args': {'warm': False}},
                                                agent_use=True, require_worker=run['worker_id']), actor=ACTOR,
                                     origin={'via': 'MercMode warm switch', 'session_id': sess['session_id']})
                self.store.put("slabel", sess["session_id"], {"session_id": sess["session_id"], "owner": "agent", "ts": now,
                                                              "task": f"autoplay screensaver: {run['title']}"})
                run = {k: v for k, v in run.items() if k != 'prelaunched'} | {
                    'phase': 'starting', 'session_id': sess['session_id'], 'up': now - START_GRACE,
                    'warm_resume_job': _jid(resume)}
                self.store.put(STATE, w['name'], run)
                return f"switching to {run['title']} (preloaded: resuming it)"
            if run.get('mercmode'):
                from . import mercmode
                mercmode.link_rotation(self.store,run,sess,now)
            self.store.put("slabel", sess["session_id"], {"owner": "agent", "task": f"autoplay screensaver: {run['title']}"})
            jumped = _jumped(sess)                       # booted into gameplay: autoplay starts in this tick
            run |= {"phase": "starting", "session_id": sess["session_id"], "up": now - START_GRACE if jumped else now,
                    **({"jumped": True} if jumped else {})}
            self.store.put(STATE, w["name"], run)
            if run.get('mercmode') and not run.get('mercmode_rotate_requested'):
                # the next title boots beside this one from the moment this one is up (a cold start after a service
                # restart has the pool warm again before the first round ends; operator 2026-10-26)
                self._prelaunch(w, run, mercmode.settings(self.store, w['name']), now)
                run = self.store.get(STATE, w["name"]) or run
            if not jumped:
                return f"launching {run['title']}"
            phase = "starting"
        sid = run.get("session_id")
        live = any(s.get("session_id") == sid for s in running)
        if not live:
            return self._finish(w, run, now, run.get("yield") or "the game ended")
        if run.get('warm_adoption'):
            from . import mercmode
            sess=next(s for s in running if s.get('session_id')==sid)
            if not mercmode.warm_adoption_owned(self.store,w,run,sess):
                return self._finish(w,run,now,'adopted session ownership changed; game left untouched')
        if run.get('mercmode_predecessor'):
            # A native session can register just before its launch job completes.
            # Retry the receipt link after that exact job is accepted as succeeded.
            from . import mercmode
            sess=next(s for s in running if s.get('session_id')==sid)
            mercmode.link_rotation(self.store,run,sess,now)
        if run.get("handover"):                         # the operator came back: theirs now, it plays on until Stop
            self.store.put("slabel", sid, {"session_id": sid, "owner": "you", "ts": now,
                                           "label": f"{run['title']}: autoplay, handed over by the screensaver"})
            self._warm_release(w, running, now, 'the operator took over this PC')   # no paused agent games left behind
            return self._finish(w, run, now, f"handed to the operator ({run['handover']}): plays on until Stop")
        if run.get('mercmode'):
            from . import mercmode
            pinned = not mercmode.settings(self.store,w['name'])['enabled']
            if pinned != bool(run.get('mercmode_pinned')):
                run = run | {'mercmode_pinned':pinned,'mercmode_rotate_requested':False,'mercmode_resume_job':False}
                self.store.put(STATE,w['name'],run)
            if pinned:
                # A boundary can already have told the native bot to exit. Wait
                # for its stopped receipt before restarting it in this same game.
                live_bot = telemetry_get(sid,now)
                if (live_bot.get('running') is False and live_bot.get('age_s',999)<=10
                        and (live_bot.get('stats') or {}).get('mercmode_rotate_requested')
                        and not run.get('mercmode_resume_job')):
                    phase = 'starting'
                    run = run | {'phase':phase,'up':now-START_GRACE,'mercmode_resume_job':True}
                    self.store.put(STATE,w['name'],run)
        if run.get("yield") or (not run.get('mercmode_pinned') and (not cfg["enabled"] or not opted_in(self.store, w, cfg))):
            return self._stop(w, run, now, run.get("yield") or "screensaver turned off")
        if run.get('mercmode'):
            if run.get('mercmode_rotate_requested'):
                # kept warm (paused) where the pool may hold it, else closed as before (_park falls back to _stop)
                return self._park(w, run, now, ROTATION)
            if phase in ('starting', 'playing') and sid:
                # the next title boots (and prepares its round) as soon as this one is up: after a service restart the
                # pool is warm again before the first round ends, not only at the switch (operator 2026-10-26)
                ahead = self._prelaunch(w, run, mercmode.settings(self.store, w['name']), now)
                run = self.store.get(STATE, w['name']) or run            # _prelaunch marked the run (once per run)
                if ahead and phase == 'playing':
                    return ahead
        if phase == "starting" and run.get('warm_resume_job'):
            resumed = self.store.get('job', run['warm_resume_job']) or {}
            if resumed.get('state') in ('failed', 'rejected', 'invalid', 'cancelled'):
                return self._warm_fallback(w, run, now, 'the warm game did not resume: '
                                           + str(resumed.get('error') or resumed.get('state'))[:200])
            if resumed.get('state') != 'succeeded':
                return f"resuming {run['title']}"
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
        if phase == "playing" and not run.get('mercmode') and now - run.get("playing_since", now) >= cfg["session_minutes"] * 60:
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

    # --- MercMode warm pool (gbox.mercmode WARM / NEXT) ---
    # The next title boots beside the playing one as soon as that one is up (launch_game warm=true, keep_sessions): the
    # worker pauses it as soon as it runs, so it makes no sound and nothing shows it (the clients follow current_run).
    # Then, on a worker with PREPARE_FEATURE, its own menus are driven to the first frame of a round
    # in the background (autoplay op=prepare) and it is paused again right there: the pool entry is "ready". At the
    # native round boundary the finished title is paused in turn ("parked") and the ready one resumed straight into
    # gameplay, instead of a stop, a cold boot and a menu walk in the PiP (operator 2026-10-26: "never sitting on a game
    # over screen or a menu screen ... match after match after match"). A parked title is prepared the same way once it
    # is picked to play next. Only this scheduler's own agent launches on this exact PC ever enter the pool or get
    # paused, resumed, prepared or stopped from it; anything else is dropped from the pool untouched. Any failure (no
    # pause, a failed preload, prepare or resume, low memory, an older worker) falls back to the earlier behaviour: a
    # failed prepare leaves the game paused where it was (its bot walks the menus after the switch), everything else
    # the normal cold launch.

    def _warm_capable(self, w, merc_cfg):
        from . import mercmode
        return bool(merc_cfg.get('enabled') and merc_cfg.get('keep_warm') and not w.get('federation')
                    and mercmode.WARM_FEATURE in (w.get('features') or []))

    def _prepare_capable(self, w):
        """This worker's autoplay has op=prepare (an older one would fail the job: the switch then resumes the game at
        its menus as before, so nothing is submitted to it)."""
        from . import mercmode
        return mercmode.PREPARE_FEATURE in (w.get('features') or [])

    def _warm_owned(self, w, row, running):
        """The running session of a pool entry (or of the current run), only when it is exactly this scheduler's own
        agent launch on this PC (same worker id and name, launch actor, agent_use, launch identity) and the operator has
        not taken it over. None otherwise: the caller then never pauses, resumes or stops it."""
        sid = row.get('session_id') or ''
        sess = next((s for s in running if s.get('session_id') == sid), None) if sid else None
        if not sess or row.get('worker_id') != w['id'] or not sid.startswith(w['id'] + '-'):
            return None
        if (self.store.get('slabel', sid) or {}).get('owner') == 'you':
            return None
        job = self.store.get('job', row.get('job')) or {}
        if job.get('tool') != 'launch_game' or job.get('require_worker') != w['id']:
            return None
        if _launch_session(self.store, row.get('job'), [sess], worker_id=w['id'], game_id=row.get('game_id')) is None:
            return None
        if row.get('warm_adoption'):
            from . import mercmode
            return sess if mercmode.warm_adoption_owned(self.store,w,row,sess) else None
        if job.get('actor') != ACTOR or not job.get('agent_use'):
            return None
        return sess

    def _warm_label(self, sid, title, now, loading=False, state=None):
        """state: loading (booting) | preparing (its menus are being driven to a round start) | ready (paused at its
        boot menu / where its last round left it) | round_ready (paused on the first frame of its next round)."""
        state = state or ('loading' if loading else 'ready')
        text = {'loading': 'is preparing its native title/menu', 'preparing': 'is preparing its next round in the background',
                'round_ready': 'waits paused at the start of its next round'}.get(state, 'waits paused for its turn')
        self.store.put('slabel', sid, {'session_id': sid, 'owner': 'agent', 'warm': True, 'ts': now,
                                       'warm_state': state, 'task': f'MercMode: {title} {text}'})

    def _warm_stop(self, w, row, why):
        """Close one verified pool game (callers check _warm_owned first)."""
        from .server import JobRequest
        self.submit(JobRequest(tool='session_op', input={'session_id': row['session_id'], 'op': 'stop_game', 'args': {}},
                               agent_use=True, require_worker=w['id']), actor=ACTOR,
                    origin={'via': 'MercMode warm pool', 'session_id': row['session_id'], 'why': why})

    def _warm(self, w, running, now):
        """This PC's verified pool: entries whose session ended, whose preload failed or timed out, or that are not
        exactly ours are dropped (never touched); a preload that came up gets its session id and the warm label; a
        preload the emulator could not pause is closed (its title then cold-launches at its turn). A preload paused at
        its boot menu, and a parked title picked to play next, get their round prepared (autoplay op=prepare) and
        become "ready" on the worker's receipt (session detail warm, or the prepare job's result)."""
        from .server import JobRequest
        from . import mercmode
        pool = mercmode.warm_pool(self.store, w['name'])
        out, changed = {}, False
        for title, row in pool.items():
            job = self.store.get('job', row.get('job')) or {}
            map_id = (mercmode.TITLES.get(title) or {}).get('map_id')
            if not row.get('session_id'):
                if job.get('state') in ('failed', 'rejected', 'invalid', 'cancelled') or now - row.get('at', now) > LAUNCH_TIMEOUT:
                    changed = True
                    continue
                sess = _launch_session(self.store, row.get('job'), running, worker_id=w['id'], game_id=row.get('game_id'))
                if not sess:
                    out[title] = row
                    continue
                row, changed = row | {'session_id': sess['session_id']}, True
            sess = self._warm_owned(w, row, running)
            if not sess:
                changed = True
                continue
            if row.get('state') == 'releasing':
                self._warm_stop(w, row, 'MercMode warm pool released')
                changed = True
                continue
            warm = warm_boot.receipt(sess, job)
            # the round receipt of this entry's own prepare job (one of an earlier preparation of the same game never
            # counts: the game played since and waits parked again); a receipt without a job stamp is taken as is
            round_receipt = warm_boot.round_receipt(sess, job, row.get('prepare_job') or '') if row.get('prepare_job') else {}
            if row.get('state') == 'prelaunch' and warm.get('state') == 'cancelled' \
                    or row.get('prepare_job') and round_receipt.get('state') == 'cancelled':
                # Explicit control/process changes (Stop, the player's pad, a manual pause) revoke this observer's
                # ownership; cancellation is not a failed bot game to close.
                label = self.store.get('slabel', row['session_id']) or {}
                self.store.put('slabel', row['session_id'], label | {'warm': False, 'warm_state': 'cancelled'})
                changed = True
                continue
            prepare = self.store.get('job', row['prepare_job']) or {} if row.get('prepare_job') else {}
            result = (prepare.get('output') or {}).get('result') or {} if prepare.get('state') == 'succeeded' else {}
            if round_receipt.get('state') == 'failed' or result.get('state') == 'failed':
                # the walk ended and the game did not pause: an unseen game running on with no bot is closed
                why = round_receipt.get('reason') or result.get('reason') or 'no pause after the round preparation'
                self._warm_stop(w, row, 'its round could not be prepared and the game did not pause: ' + str(why)[:200])
                changed = True
                continue
            receipt = round_receipt if round_receipt.get('prepared') is not None else result
            if row.get('state') != 'ready' and receipt.get('prepared') is True and receipt.get('paused') is True \
                    and receipt.get('title') == map_id:
                row = row | {'state': 'ready', 'prepared': {k: receipt.get(k) for k in
                             ('character', 'stage', 'stage_index', 'mercenaries_mode', 'room', 'wait_s') if receipt.get(k) is not None}}
                changed = True
            elif not row.get('prepare_failed') and row.get('state') != 'ready':
                failed = receipt.get('prepare_failed') if receipt.get('prepared') is False else None
                if not failed and prepare.get('state') in ('failed', 'rejected', 'invalid', 'cancelled'):
                    failed = f"prepare {prepare['state']}: {str(prepare.get('error') or '')[:160]}"
                if not failed and row.get('prepare_job') and now - row.get('prepare_at', now) > LAUNCH_TIMEOUT:
                    failed = 'the round preparation timed out'
                if failed:
                    row, changed = row | {'prepare_failed': str(failed)[:240]}, True
            loading = warm.get('state') == 'loading' and now - row.get('at', now) <= LAUNCH_TIMEOUT
            preparing = row.get('state') != 'ready' and bool(row.get('prepare_job')) and not row.get('prepare_failed') \
                and now - row.get('prepare_at', now) <= LAUNCH_TIMEOUT
            if row.get('state') == 'prelaunch' and job.get('state') == 'succeeded' and not loading and not preparing \
                    and not warm_boot.prepared(sess, job, map_id):
                self._warm_stop(w, row, 'native preparation was not confirmed: ' + str(warm.get('reason') or 'no native menu receipt'))
                changed = True
                continue
            pause = self.store.get('job', row['pause_job']) or {} if row.get('pause_job') else {}
            if pause.get('state') in ('failed', 'rejected', 'invalid', 'cancelled'):
                self._warm_stop(w, row, 'the finished game could not pause: ' + str(pause.get('error') or pause.get('state'))[:200])
                changed = True
                continue
            if self._prepare_capable(w) and row.get('state') in ('prelaunch', 'parked') and not row.get('prepare_job') \
                    and not row.get('prepare_failed') and not loading:
                settled = (job.get('state') == 'succeeded' and warm_boot.prepared(sess, job, map_id)
                           if row['state'] == 'prelaunch' else
                           # a parked title: once it is picked to play next, after its pause and its bot's stop landed
                           row.get('prepare_wanted') and pause.get('state') == 'succeeded'
                           and (not row.get('autoplay_job') or (self.store.get('job', row['autoplay_job']) or {}).get('state') == 'succeeded'))
                if settled:
                    selection = row.get('selection')
                    submitted = self.submit(JobRequest(tool='autoplay', input={'session_id': row['session_id'], 'op': 'prepare',
                                                                               **({'selection': selection} if selection else {})},
                                                       agent_use=True, require_worker=w['id']), actor=ACTOR,
                                            origin={'via': 'MercMode prepare', 'session_id': row['session_id'], 'title': title})
                    row, changed, preparing = row | {'prepare_job': _jid(submitted), 'prepare_at': now}, True, True
            state = 'loading' if loading else 'preparing' if preparing else 'round_ready' if row.get('state') == 'ready' else 'ready'
            label = self.store.get('slabel', row['session_id']) or {}
            if not label.get('warm') or label.get('warm_state') != state:
                self._warm_label(row['session_id'], (mercmode.TITLES.get(title) or {}).get('name', title), now, state=state)
            out[title] = row
        if changed:
            self.store.put(mercmode.WARM, w['name'], out)
        return out

    def _warm_waiting(self, w, row, now):
        """Why the next title is not ready to be swapped in yet (None: it is, or it never will be on its own): still
        loading, or its round is still being prepared (a prepare running, or about to be submitted). The playing title
        then plays another round meanwhile (round_boundary, EXTRA_ROUNDS_MAX)."""
        if not row or row.get('state') in ('ready', 'releasing') or row.get('prepare_failed'):
            return None
        job = self.store.get('job', row.get('job')) or {}
        session = self.store.get('session', row.get('session_id')) or {}
        if row.get('state') == 'prelaunch' and (not row.get('session_id') or job.get('state') != 'succeeded'
                                                or warm_boot.loading(session, job)):
            return 'loading'
        if not self._prepare_capable(w):
            return None
        if row.get('prepare_job'):
            return 'preparing' if now - row.get('prepare_at', now) <= LAUNCH_TIMEOUT else None
        if row.get('state') == 'prelaunch' or row.get('prepare_wanted'):
            return 'preparing'                       # its prepare is submitted at the next tick (the pause / stop land first)
        return None

    def _warm_release(self, w, running, now, why):
        """Close every verified pool game of this PC (MercMode off, keep_warm 0, the operator took over). A preload
        still loading is marked releasing and closed once it comes up."""
        from . import mercmode
        pool = self._warm(w, running, now)
        left = {}
        for title, row in pool.items():
            if row.get('session_id'):
                self._warm_stop(w, row, why)
            else:
                left[title] = row | {'state': 'releasing'}
        self.store.put(mercmode.WARM, w['name'], left)
        self.store.delete(mercmode.NEXT, w['name'])

    def _tend_warm(self, w, running, now):
        from . import mercmode
        if not self.store.get(mercmode.WARM, w['name']):
            return
        cfg = mercmode.settings(self.store, w['name'])
        if not self._warm_capable(w, cfg):
            self._warm_release(w, running, now, 'MercMode warm pool off on this PC')
        else:
            self._warm(w, running, now)

    def _resume_warm(self, w, pick, merc_cfg, now):
        """Switch to a title kept warm (parked after its last turn) or preloaded while the previous title played - at
        best "ready": paused on the first frame of its prepared round, resumed straight into gameplay. No boot, no
        shader/PPU build, no menu walk. None when that title has nothing warm (cold launch)."""
        from .server import JobRequest
        from . import mercmode
        running = self.store.running_sessions()
        row = self._warm(w, running, now).get(pick['title'])
        if not row or row.get('state') == 'releasing':
            return None
        if row.get('pause_job') and (self.store.get('job', row['pause_job']) or {}).get('state') != 'succeeded':
            # its pause has not landed yet (a resume now could be undone by it): wait a little, then give up on it
            if now - row.get('at', now) < 120:
                return f"waiting for {pick['name']} to finish pausing"
            self._warm_stop(w, row, 'its pause never completed')
            mercmode.take_warm(self.store, w['name'], pick['title'])
            return None
        mercmode.take_warm(self.store, w['name'], pick['title'])
        selection = {'selection': pick['selection']} if pick.get('selection') else {}
        base = {'worker': w['name'], 'worker_id': w['id'], 'game_id': row.get('game_id') or pick['game_id'],
                'title': pick['name'], 'started': now, 'job': row.get('job'), 'warm_from': row.get('state'),
                **({'session_id': row['session_id']} if row.get('session_id') else {}),
                **({'warm_adoption':row['warm_adoption'],'autoplay_job':row.get('autoplay_job')}
                   if row.get('warm_adoption') else {}),
                'mercmode_predecessor': mercmode.rotation_predecessor(self.store, w, now),
                'mercmode': {'title': pick['title'], 'map_id': pick['map_id'],
                             'rounds_per_title': merc_cfg['rounds_per_title'], **selection}}
        job = self.store.get('job', row.get('job')) or {}
        session = next((s for s in running if s.get('session_id') == row.get('session_id')), None)
        if not row.get('session_id') or row.get('state') == 'prelaunch' and (
                job.get('state') != 'succeeded' or warm_boot.loading(session, job)):
            # still loading: its preload becomes this run's launch, resumed once the worker has finished (and paused) it
            self.store.put(STATE, w['name'], base | {'phase': 'launching', 'prelaunched': True})
            return f"switching to {pick['name']} (finishing its background load)"
        sid = row['session_id']
        if row.get('prepared'):
            base['mercmode'] = base['mercmode'] | {'prepared': row['prepared']}
        self.store.put('slabel', sid, {'session_id': sid, 'owner': 'agent', 'ts': now,
                                       'task': f"autoplay screensaver: {pick['name']}"})
        if pick.get('selection') and row.get('selection') != pick['selection']:
            # a DJ pick queued after this game was prepared: its menus are past, so it is taken at the next menu visit
            spec = mercmode.selection_job(pick['title'], sid, pick['selection'])
            if spec:
                self.submit(JobRequest(tool=spec[0], input=spec[1], agent_use=True, require_worker=w['id']),
                            actor=ACTOR, origin={'via': 'MercMode queue', 'session_id': sid})
        prepare = self.store.get('job', row['prepare_job']) or {} if row.get('prepare_job') else {}
        if row.get('state') != 'ready' and row.get('prepare_job') and not row.get('prepare_failed'):
            # its round preparation is still walking the menus (the extra rounds ran out): no wait for it - the bot takes
            # the game over from the walk at once (autoplay start ends it where the menus are; the game is unpaused)
            if prepare.get('state') == 'queued':
                self.store.put('job', prepare['id'], prepare | {'state': 'cancelled', 'finished': now,
                               'error': 'The MercMode switch took this game before its round preparation started'})
                resume = self.submit(JobRequest(tool='session_op', input={'session_id': sid, 'op': 'resume', 'args': {'warm': False}},
                                                agent_use=True, require_worker=w['id']), actor=ACTOR,
                                     origin={'via': 'MercMode warm switch', 'session_id': sid})
                self.store.put(STATE, w['name'], base | {'phase': 'starting', 'session_id': sid, 'up': now - START_GRACE,
                                                         'warm_resume_job': _jid(resume)})
                return f"switching to {pick['name']} (kept warm: no reload)"
            self.store.put(STATE, w['name'], base | {'phase': 'starting', 'session_id': sid, 'up': now - START_GRACE,
                                                     'warm_from': 'preparing'})
            return f"switching to {pick['name']} (its round preparation still runs: the bot takes over from it)"
        resume = self.submit(JobRequest(tool='session_op', input={'session_id': sid, 'op': 'resume', 'args': {'warm': False}},
                                        agent_use=True, require_worker=w['id']), actor=ACTOR,
                             origin={'via': 'MercMode warm switch', 'session_id': sid})
        self.store.put(STATE, w['name'], base | {'phase': 'starting', 'session_id': sid, 'up': now - START_GRACE,
                                                 'warm_resume_job': _jid(resume)})
        if row.get('state') == 'ready':
            return f"switching to {pick['name']} (its round is ready: resuming it in gameplay)"
        return f"switching to {pick['name']} (kept warm: no reload)"

    def _warm_fallback(self, w, run, now, why):
        """A warm switch that failed: this run ends, and the same title (and queued round) launches cold next."""
        from . import mercmode
        # A preload can acquire its session only after the pool entry was
        # claimed. Resolve the exact launch again so a failed preparation is
        # closed instead of becoming an orphan that blocks the cold fallback.
        running = self.store.running_sessions()
        sess = _launch_session(self.store, run.get('job'), running,
                               worker_id=run['worker_id'], game_id=run['game_id'])
        run = {k: v for k, v in run.items() if k != 'session_id'}
        if sess:
            run = run | {'session_id': sess['session_id']}
            job = self.store.get('job', run.get('job')) or {}
            if not self._warm_owned(w, run, running) or warm_boot.receipt(sess, job).get('state') == 'cancelled':
                return self._finish(w, run, now, 'native preparation control changed; session left untouched')
        m = run.get('mercmode') or {}
        if m.get('title'):
            self.store.put(mercmode.NEXT, w['name'], {'title': m['title'], 'selection': m.get('selection'), 'at': now,
                                                      'cold': True})
        if run.get('session_id'):
            return self._stop(w, run, now, why)
        return self._finish(w, run, now, why)

    def _park(self, w, run, now, why):
        """End this title's turn without closing it: its emulator is paused (args.warm: no save when it closes later)
        and kept for its next turn. The pool stays at keep_warm titles besides the one about to play (NEXT)."""
        from .server import JobRequest
        from . import mercmode
        cfg = mercmode.settings(self.store, w['name'])
        running = self.store.running_sessions()
        owned=self._warm_owned(w,run,running)
        if run.get('warm_adoption') and not owned:
            return self._finish(w,run,now,'adopted session ownership changed; game left untouched')
        if not self._warm_capable(w, cfg) or mercmode.memory_reason(w, now) or not owned:
            return self._stop(w, run, now, why)
        sid = run['session_id']
        # its bot stops first: left running on the paused game it saw "nothing moved in RAM", reported a freeze, and the
        # worker's freeze recovery relaunched the parked game cold (2026-10-24: "why is it loading the same game again?")
        stopped=self.submit(JobRequest(tool='autoplay', input={'session_id': sid, 'op': 'stop'}, agent_use=True,
                               require_worker=w['id']), actor=ACTOR, origin={'via': 'MercMode park', 'session_id': sid})
        pause = self.submit(JobRequest(tool='session_op', input={'session_id': sid, 'op': 'pause', 'args': {'warm': True}},
                                       agent_use=True, require_worker=w['id']), actor=ACTOR,
                            origin={'via': 'MercMode keep warm', 'session_id': sid})
        mercmode.keep_warm(self.store, w['name'], run['mercmode']['title'],
                           {'session_id': sid, 'game_id': run['game_id'], 'job': run['job'], 'worker_id': w['id'],
                            'autoplay_job':_jid(stopped),
                            'display_park':{'round_id':(run.get('mercmode_last_round') or {}).get('round_id'),
                                            'started':owned.get('started'),'pid':(owned.get('detail') or {}).get('pid')},
                            **({'warm_adoption':run['warm_adoption']}
                               if run.get('warm_adoption') else {}),
                            'state': 'parked', 'at': now, 'pause_job': _jid(pause)})
        self._warm_label(sid, run['title'], now)
        nxt = (self.store.get(mercmode.NEXT, w['name']) or {}).get('title')
        others = sorted(((t, r) for t, r in self._warm(w, running, now).items() if t != nxt),
                        key=lambda tr: -tr[1].get('at', 0))
        if others[cfg['keep_warm']:]:
            pool = mercmode.warm_pool(self.store, w['name'])
            for title, row in others[cfg['keep_warm']:]:
                if row.get('session_id'):
                    self._warm_stop(w, row, f"MercMode keeps {cfg['keep_warm']} title(s) warm")
                    pool.pop(title, None)
                else:
                    pool[title] = row | {'state': 'releasing'}
            self.store.put(mercmode.WARM, w['name'], pool)
        return self._finish(w, run | {'mercmode_kept_warm': True}, now, why)

    def _prelaunch(self, w, run, cfg_merc, now):
        """Once per run (and again after a failed attempt, round_boundary), as soon as this title is up: pick the title
        that plays next and boot it beside this one, paused (or note that it already waits warm), so that it is ready -
        booted, its round prepared - long before the switch. The pick is kept (NEXT) for the switch even when the preload
        is skipped (low memory); the switch then waits for a later, successful attempt (round_boundary)."""
        from .server import JobRequest
        from . import mercmode
        if run.get('mercmode_prelaunch') or run.get('mercmode_pinned') or run.get('mercmode_stay') \
                or not self._warm_capable(w, cfg_merc):
            return None
        history = self.store.get(mercmode.HISTORY, w['name']) or {}
        self.store.put(mercmode.HISTORY, w['name'], history | {'last_game_id': run['game_id']})   # never "next" = this one
        pick = mercmode.choose(self.store, w, self.rng, cfg_merc)
        self.store.put(mercmode.HISTORY, w['name'], history)
        mark = lambda **kw: self.store.put(STATE, w['name'], run | {'mercmode_prelaunch': {'at': now, **kw}})
        if not pick or pick['title'] == run['mercmode']['title']:
            mark(title=None)
            return None
        if pick.get('selection'):
            mercmode.pop_queue(self.store, w['name'])
        self.store.put(mercmode.NEXT, w['name'], {'title': pick['title'], 'selection': pick.get('selection'), 'at': now,
                                                  **({'queued': True} if pick.get('selection') else {})})
        running = self.store.running_sessions()
        pool = self._warm(w, running, now)
        ready = pool.get(pick['title'])
        if ready and ready.get('state') != 'releasing':
            if ready.get('state') == 'parked' and self._prepare_capable(w) \
                    and (not ready.get('prepare_job') or ready.get('prepare_failed')):
                # a parked title picked to play next: its menus are driven from where its last round left it to its
                # next round start meanwhile (_warm submits the prepare once its pause and stop have landed), with the
                # DJ's pick when there is one; an earlier failed attempt is tried once more for this pick
                row = {k: v for k, v in ready.items() if k not in ('prepare_job', 'prepare_at', 'prepare_failed')}
                mercmode.keep_warm(self.store, w['name'], pick['title'],
                                   row | {'prepare_wanted': True, **({'selection': pick['selection']} if pick.get('selection') else {})})
                mark(title=pick['title'], warm=ready.get('state'), prepare=True)
                return f"{pick['name']} waits warm for the next round (preparing its round)"
            mark(title=pick['title'], warm=ready.get('state'))
            return f"{pick['name']} waits warm for the next round"
        why = mercmode.memory_reason(w, now)
        game = None if why else self.store.catalog_get(pick['game_id'])
        if not game:
            mark(title=pick['title'], skipped=why or 'the game is not in the catalog')
            return None
        others = sorted(((t, r) for t, r in pool.items() if t != pick['title']), key=lambda tr: tr[1].get('at', 0))
        while others and len(others) >= cfg_merc['keep_warm']:          # room for the next title: oldest out first
            title, row = others.pop(0)
            if row.get('session_id'):
                self._warm_stop(w, row, f"MercMode keeps {cfg_merc['keep_warm']} title(s) warm")
                mercmode.take_warm(self.store, w['name'], title)
            else:
                mercmode.keep_warm(self.store, w['name'], title, row | {'state': 'releasing'})
        keep = [run['session_id']] + [r['session_id'] for _, r in others if r.get('session_id')]
        selection = {'selection': pick['selection']} if pick.get('selection') else {}
        game = game | {'launch': dict(game.get('launch') or {}) | {
            'mercmode': mercmode.launch_block(cfg_merc, pick.get('selection'))}}
        job = self.submit(JobRequest(tool='launch_game', input={'game': game, 'jump': True, 'memory_cards': 'operator',
                                                                'warm': True, 'keep_sessions': keep},
                                     agent_use=True, low_priority=True, require_worker=w['id']), actor=ACTOR,
                          origin={'via': 'MercMode preload', 'game_id': pick['game_id']})
        mercmode.keep_warm(self.store, w['name'], pick['title'],
                           {'session_id': None, 'game_id': pick['game_id'], 'job': _jid(job), 'worker_id': w['id'],
                            'state': 'prelaunch', 'at': now, **selection})
        mark(title=pick['title'], job=_jid(job))
        return f"preloading {pick['name']} for the next round (paused until the switch)"

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
            session=self.store.get('session',sid) or {}
            if not run and session.get('state')!='running':
                return False
            cancelled=False
            for job in self.store.all('job'):
                inp=job.get('input') or {}
                if (job.get('state')=='queued' and job.get('tool')=='session_op' and job.get('actor')==ACTOR
                        and job.get('require_worker')==sid.split('-',1)[0]
                        and inp.get('session_id')==sid and inp.get('op')=='stop_game'):
                    self.store.put('job',job['id'],job|{'state':'cancelled','finished':time.time(),
                        'error':'The operator took control before this automatic stop was dispatched'})
                    cancelled=True
            if run:
                self.store.put(STATE, run["worker"], run | {"handover": reason})
            elif cancelled:
                # The minute/round rotation can remove STATE before the native
                # handover arrives. Its queued stop still must not close a human game.
                self.store.put('slabel',sid,{'session_id':sid,'owner':'you','ts':time.time(),
                    'label':f"{session.get('title') or session.get('game_id') or 'Game'}: handed over by the screensaver"})
            elif (self.store.get('slabel',sid) or {}).get('owner')!='you':
                return False
        self.tick()
        return True

    def current_run(self, sid: str) -> dict | None:
        """This scheduler's live run on exactly this session, while its autobot is meant to drive it: playing, not handed
        over to the operator, not ending and not switching titles. None otherwise (a parked or preloading game too)."""
        run = self._by_session(sid)
        if not run or run.get('phase') != 'playing' or run.get('handover') or run.get('yield') \
                or run.get('mercmode_rotate_requested'):
            return None
        return run

    def restart_bot(self, sid: str, *, requested_by: str = 'operator', why: str = 'F5 recovery',
                    now: float | None = None) -> str | None:
        """Start this scheduler's own autobot again on its current run (F5 found it stopped or quiet): the same autoplay
        start the schedule makes (screensaver mode, the run's style knobs, this scheduler's actor), so MercMode keeps owning
        the run. Returns the autoplay job id, or None when the session is no longer such a run."""
        from .server import JobRequest
        now = time.time() if now is None else now
        with self.lock:
            run = self.current_run(sid)
            if not run:
                return None
            knobs = run.get('knobs')
            if not isinstance(knobs, dict):
                from . import imitate
                knobs = imitate.choose_knobs(self.history(run['game_id']), self.rng)
            job = self.submit(JobRequest(tool='autoplay', input={'session_id': sid, 'op': 'start', 'mode': 'auto',
                                                                 'screensaver': True, 'style': knobs},
                                         agent_use=True, require_worker=run['worker_id']), actor=ACTOR,
                              origin={'via': 'autoplay screensaver', 'session_id': sid, 'recovery': why,
                                      'requested_by': requested_by})
            self.store.put(STATE, run['worker'], run | {'autoplay_job': _jid(job), 'knobs': knobs,
                                                        'bot_restarted': {'at': now, 'why': why, 'by': requested_by}})
            return _jid(job)

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

    def round_boundary(self, body, parent_job, now=None):
        from . import mercmode
        now = time.time() if now is None else now
        with self.lock:
            run = self._by_session(body.get('session_id'))
            if not run or not run.get('mercmode') or run.get('handover'):
                return {'saved': False, 'rotate_requested': False}
            live=telemetry_get(run['session_id'],now)
            if not live.get('running') or live.get('age_s',999)>10 \
                    or not any(s.get('session_id')==run['session_id'] for s in self.store.running_sessions()):
                raise ValueError('The owned autoplay runtime and game must still be live')
            receipt = mercmode.accept_boundary(self.store,run,body,parent_job=parent_job,now=now)
            if receipt is None:
                return {'saved': True, 'duplicate': True, 'rotate_requested': bool(run.get('mercmode_rotate_requested'))}
            ids = (run.get('mercmode_round_ids',[])+[receipt['round_id']])[-256:]
            # a death early in an attempt is a retry, not a round played (operator 2026-10-26: "are sure it is playing 5
            # rounds of mercenaries in each game before moving onto the next one?" - RE4 went back to RE5 after one stage
            # each turn: every death + retry sent a boundary, five quick deaths were five "rounds"). A death within
            # ROUND_MIN_S of the attempt's start counts a round only every QUICK_DEATHS_PER_ROUND (never stuck in a title)
            began = max(run.get('playing_since') or run.get('started') or 0,
                        (run.get('mercmode_last_round') or {}).get('at') or 0)
            quick = (receipt.get('witness') or {}).get('screen') == 'dead'                 and (receipt.get('at') or now) - began < mercmode.ROUND_MIN_S
            quick_deaths = run.get('mercmode_quick_deaths', 0) + (1 if quick else 0)
            count = run.get('mercmode_rounds',0) + (0 if quick else 1)
            played = count + quick_deaths // mercmode.QUICK_DEATHS_PER_ROUND
            worker = next((w for w in self.workers() if w.get('id')==run['worker_id']),None)
            cfg = mercmode.settings(self.store,run['worker'])
            alternatives = [r for r in mercmode.inventory(self.store,worker,cfg) if r['playable']
                            and r['title'] in cfg['titles'] and r['game_id']!=run['game_id']] if worker else []
            rotate = bool(cfg['enabled'] and not run.get('mercmode_pinned') and alternatives and played>=cfg['rounds_per_title'])
            head = (cfg.get('queue') or [None])[0] if cfg['enabled'] and not run.get('mercmode_pinned') else None
            ahead = self.store.get(mercmode.NEXT, run['worker']) if cfg['enabled'] and not run.get('mercmode_pinned') else None
            playable = lambda title: worker is not None and any(
                r['playable'] and r['title'] == title for r in mercmode.inventory(self.store, worker, cfg))
            if head and head['title'] == run['mercmode']['title']:
                # the DJ queued this same game next: no relaunch, the running bot takes the selection at its menus
                rotate = False
                selection = mercmode.resolve_selection(head, self.rng)
                spec = mercmode.selection_job(head['title'], run['session_id'], selection)
                if spec:
                    from .server import JobRequest
                    self.submit(JobRequest(tool=spec[0], input=spec[1], agent_use=True, require_worker=run['worker_id']),
                                actor=ACTOR, origin={'via': 'MercMode queue', 'session_id': run['session_id']})
                mercmode.pop_queue(self.store, run['worker'])
                run = run | {'mercmode': run['mercmode'] | {'selection': selection}}
            elif head and playable(head['title']):
                rotate = True                    # the DJ's next round is another game: switch after this round
                run = {k: v for k, v in run.items() if k not in ('mercmode_stay', 'mercmode_warm_attempts')}   # asked for: try again
                if ahead and ahead.get('title') != head['title']:
                    self.store.delete(mercmode.NEXT, run['worker'])      # the DJ's pick replaces the one made ahead
                    ahead = None
                    run = {k: v for k, v in run.items() if k != 'mercmode_prelaunch'}
            elif ahead and ahead.get('title') != run['mercmode']['title'] and playable(ahead.get('title')) \
                    and (ahead.get('queued') or ahead.get('cold')):
                rotate = True                    # the DJ's round, picked (and preloaded) ahead: that title is next
            if rotate and worker and self._warm_capable(worker, cfg):
                # the switch waits until the next title is ready - booted, paused on the first frame of its round (a
                # worker without op=prepare: paused at its menu) - and this title plays another round meanwhile, never a
                # loading screen or a menu walk (operator 2026-10-24: "they could play a 2nd round of mercenaries and
                # continue gaming while the game loads. i want the autobot playing the entire time"; 2026-10-26: "the
                # transitions between loads is just too long and I need it to be a seamless swap"). A failed or skipped
                # preload is tried again next round; after EXTRA_ROUNDS_MAX failed attempts MercMode stays in this title.
                nxt = (ahead or {}).get('title') or (run.get('mercmode_prelaunch') or {}).get('title') \
                    or (head or {}).get('title')
                row = self._warm(worker, self.store.running_sessions(), now).get(nxt) if nxt else None
                waiting = self._warm_waiting(worker, row, now)
                ready = bool(row) and not waiting and (row.get('state') == 'ready' or not self._prepare_capable(worker)
                                                       or row.get('prepare_failed'))
                if ready:
                    run = {k: v for k, v in run.items() if k != 'mercmode_waiting_for'}
                else:
                    rotate = False
                    if not run.get('mercmode_stay'):
                        run = run | {'mercmode_extra_rounds': run.get('mercmode_extra_rounds', 0) + 1,
                                     'mercmode_waiting_for': waiting or 'the next title is not ready'}
                        if not waiting:
                            # nothing is on its way (the preload failed, was skipped or never happened): try again next
                            # round; after EXTRA_ROUNDS_MAX such attempts this title keeps playing instead
                            attempts = run.get('mercmode_warm_attempts', 0) + 1
                            run = {k: v for k, v in run.items() if k != 'mercmode_prelaunch'} | {'mercmode_warm_attempts': attempts}
                            if attempts >= mercmode.EXTRA_ROUNDS_MAX:
                                name = (mercmode.TITLES.get(nxt) or {}).get('name', nxt or 'the next title')
                                run = run | {'mercmode_stay': f"{name} could not be made ready {attempts} times: staying in this title"}
            self.store.put(mercmode.HISTORY,run['worker'],{'last_game_id':run['game_id'],
                'last_round':receipt,'at':now})
            # a restarted autobot in this same session (the operator's F3, the hang relaunch) owns the run from here
            self.store.put(STATE,run['worker'],run | {'mercmode_round_ids':ids,'autoplay_job':parent_job['id'],
                'mercmode_rounds':count,'mercmode_quick_deaths':quick_deaths,'mercmode_rounds_played':played,
                'mercmode_last_round':receipt,'mercmode_rotate_requested':rotate})
        if rotate:
            self.nudge('native round boundary: the next title is ready')      # park and swap now, not at the next tick
        return {'saved': True, 'rotate_requested': rotate}

    def pcs(self, cfg: dict, now: float | None = None) -> list[dict]:
        """Each PC, and why the screensaver would not start a game there now (reason None: it may at its next tick).
        starts_in_s: a Windows PC's idle time still to go before it may (the Sessions view's "nothing is playing")."""
        now = time.time() if now is None else now
        running = self.store.running_sessions()
        out = []
        for w in self.workers():
            host_cfg = self._worker_settings(w,cfg)
            run = self.store.get(STATE, w.get("name"))
            if run:
                reason = f"playing {run.get('title') or run.get('game_id') or 'a demo'}"
            elif not host_cfg["enabled"]:
                reason = "the autoplay screensaver is off"
            elif _local_scheduler(w):
                reason = 'scheduled by this PC\'s local control plane'
            else:
                try:
                    reason = worker_reason(self.store, w, host_cfg, running, now)
                except Exception as e:                       # noqa: BLE001 - one PC's check never hides the others
                    reason = f"unknown ({type(e).__name__})"
            idle = w.get("idle_seconds")
            left = (max(0.0, cfg["idle_minutes"] * 60 - idle) if w.get("os") == "windows" and idle is not None
                    and w.get("online") else None)
            out.append({"name": w.get("name"), "id": w.get("id"), "os": w.get("os"), "online": bool(w.get("online")),
                        "demo": bool(run), "reason": reason, "starts_in_s": round(left) if left is not None else None})
        return out

    def status(self) -> dict:
        from . import mercmode
        cfg = settings(self.store)
        log = sorted(self.store.all(LOG), key=lambda r: -(r.get("started") or 0))[:30]
        games = self.games(cfg)
        out = {"settings": cfg, "running": self.store.all(STATE), "log": log,
               "games": [{k: g[k] for k in ("game_id", "title", "pads")} for g in games[:40]],
               "pcs": self.pcs(cfg)}
        out['mercmode']=self.mercmode_status()
        if self.builder is not None:
            out["roulette"] = self.builder.status()
        return out

    def mercmode_status(self) -> dict:
        """GET /api/mercmode: one row per PC (its current registration, not every stale id a restart left behind) and one
        read of the session table for all of them (the desktop's 8 s request limit was exceeded: 4-11 s on lilspark)."""
        from . import mercmode
        sessions = self.store.all('session')
        running = self.store.running_sessions()
        hosts=[]
        for w in _current_workers(self.workers()):
            observed=mercmode.observation(self.store,w)
            command=self.store.get(mercmode.COMMAND,w['name']) or {}
            if command.get('worker_id')!=w['id']:command={}
            job=self.store.get('job',command.get('job')) if command.get('job') else None
            actual=observed.get('settings') or (dict(mercmode.DEFAULT) if _local_scheduler(w)
                else mercmode.settings(self.store,w['name']))
            candidate=next((s['session_id'] for s in running
                if s.get('session_id','').startswith(w['id']+'-')
                and (t:=telemetry_get(s['session_id'])).get('running') is True
                and (t.get('stats') or {}).get('team_role')=='solo_p1'
                and (t.get('stats') or {}).get('screen')=='playing'),None) if not w.get('federation') else None
            hosts.append({'name':w['name'],'id':w['id'],'online':bool(w.get('online')),
                'current_run':self.store.get(STATE,w['name']),'adoptable_solo_session':candidate,
                'settings':actual,
                'settings_source':'local_scheduler_observation' if observed else
                    'unobserved_local_scheduler' if _local_scheduler(w) else 'this_control_plane',
                'observed_at':observed.get('at'),'desired_settings':mercmode.settings(self.store,w['name']),
                'command':command | ({'state':job.get('state'),'error':str(job.get('error') or '')[:240]} if job else {}),
                'scheduler_owner':'local' if _local_scheduler(w) else 'this_control_plane',
                'titles':mercmode.inventory(self.store,w,sessions=sessions),'preparation':mercmode.host_preparation(self.store,w),
                'history':observed.get('history',self.store.get(mercmode.HISTORY,w['name']) or {}),
                # the warm pool: titles waiting paused for their turn, and the title picked to play next
                'warm':[{'title':t,'state':r.get('state'),'session_id':r.get('session_id'),'at':r.get('at'),
                         'prepare_job':r.get('prepare_job'),'prepared':r.get('prepared'),'prepare_failed':r.get('prepare_failed')}
                        for t,r in sorted(mercmode.warm_pool(self.store,w['name']).items())],
                'next':self.store.get(mercmode.NEXT,w['name'])})
        from .mercs.research_profiles import coverage, VERSION
        for h in hosts:
            sid = (h['current_run'] or {}).get('session_id')
            stats = (telemetry_get(sid).get('stats') or {}) if sid else {}
            h['now_playing'] = {k: stats.get(k) for k in ('character', 'stage', 'mercenaries_mode', 'screen', 'timer', 'score')
                                if stats.get(k) is not None} or None
        try:
            queue_catalog = mercmode.catalog()
        except Exception:                                   # noqa: BLE001 - a title module missing: no picks for it
            queue_catalog = {}
        return {'hosts':hosts,'experience_coverage':coverage(),'research_version':VERSION,'catalog':queue_catalog}


# request bodies (module level: with postponed annotations FastAPI can't see classes defined inside install())
class Settings(BaseModel):
    enabled: bool | None = None
    workers: list[str] | None = None
    idle_minutes: float | None = None
    session_minutes: float | None = None
    min_pads: int | None = None
    games: list[str] | None = None
    roulette: bool | None = None
    bot_pcs: list[str] | None = None       # PC names dedicated to bots (a bot demo there owns the keyboard)


class Yield(BaseModel):
    session_id: str
    reason: str = "input"


class Report(BaseModel):
    session_id: str
    result: dict


class MercModeSettings(BaseModel):
    host: str
    enabled: bool | None = None
    titles: list[str] | None = None
    rounds_per_title: int | None = None
    presentation_priority: bool | None = None
    queue: list[dict] | None = None             # the DJ queue: [{title, mode, character, stage}], None fields = random
    keep_warm: int | None = None                # titles waiting paused beside the playing one (0 = cold switches)
    stalemate_cut: bool | None = None           # the bots cut the clock when no enemy shows for 15 s (gbox.mercs.stalemate)
    stalemate_cut_s: int | None = None          # ... to this many seconds (1..60; default 5)


class MercModeAdopt(BaseModel):
    host: str
    session_id: str


class MercModeBoundary(BaseModel):
    session_id: str
    round_id: str
    at: float
    map_id: str
    role: str
    source: str
    mode: str | None = None
    stage: str | int | None = None
    character: str | None = None
    witness: dict


class DirectiveIn(BaseModel):
    command: str
    hold_s: float | None = None     # how long a standing mode lasts (0 .. directives.MAX_HOLD_S); default: the command's own


class MercModePreparation(BaseModel):
    worker_id: str
    result: dict


class MercModePrepare(BaseModel):
    worker_id: str


class Telemetry(BaseModel):
    running: bool = True
    mode: str = ""
    mission: str = ""
    title: str = ""
    stats: dict = {}
    demo: bool = False                    # a bot demo plays (the Sessions header says so)
    autoplay_taken_over: bool = False
    source_autoplay_job_id: str = ""


TELEMETRY: dict[str, dict] = {}           # session id -> what autoplay is doing right now (in memory: live view only)
TELEMETRY_TTL = 600
TELEMETRY_STATS_MAX_BYTES = 64 * 1024     # rich Mercenaries diagnostics, bounded as actual UTF-8 JSON


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


def telemetry_last(sid: str, now: float | None = None) -> dict:
    """The newest report exactly as autoplay sent it (running is what it said, however old) plus its age; {} when there
    is none. F5 recovery tells "the bot stopped" (running false) from "the bot went quiet while driving" (stale)."""
    now = time.time() if now is None else now
    t = TELEMETRY.get(sid)
    if not t or now - t["at"] > TELEMETRY_TTL:
        return {}
    return {k: v for k, v in t.items() if k != "at"} | {"age_s": round(now - t["at"], 1)}


def install(app, store, config, auth, submit, workers, archive):
    from fastapi import Depends, HTTPException, Header

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
    saver.config = config
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
    def screensaver_yield(body: Yield, parent_job: str=Header(default='',alias='x-gbox-parent-job'),actor=Depends(auth)):
        return {"yielded": saver.yield_to_operator(body.session_id, body.reason[:80])}

    @app.post("/api/autoplay-screensaver/result")
    def screensaver_result(body: Report, parent_job: str=Header(default='',alias='x-gbox-parent-job'),actor=Depends(auth)):
        if len(str(body.result)) > 8000:
            raise HTTPException(413, "result too large")
        return {"saved": saver.report(body.session_id, body.result)}

    @app.get('/api/mercmode')
    def mercmode_status(actor=Depends(auth)):
        return saver.mercmode_status()

    @app.post('/api/mercmode/adopt')
    def mercmode_adopt(body: MercModeAdopt, actor=Depends(auth)):
        from . import mercmode
        with saver.lock:
            worker=next((w for w in _current_workers(saver.workers()) if w.get('name')==body.host),None)
            session=store.get('session',body.session_id)
            if not worker or not session:raise HTTPException(404,'Exact host/session unavailable')
            try:run=mercmode.adopt_current(store,worker,session,telemetry_get(body.session_id))
            except ValueError as exc:raise HTTPException(409,str(exc)) from None
        store.audit(actor,'mercmode.adopt',body.session_id,{'host':body.host,'autoplay_job':run['autoplay_job']})
        return {'adopted':True,'session_id':body.session_id,'host':body.host,'run':run}

    @app.post('/api/mercmode')
    def mercmode_settings(body: MercModeSettings, actor=Depends(auth)):
        from . import mercmode
        worker=next((w for w in workers() if w.get('name')==body.host),None)
        if worker is None:
            raise HTTPException(422,'Choose an exact registered worker name')
        try:
            patch=body.model_dump(exclude_none=True,exclude={'host'})
            desired=mercmode.configure(store,body.host,patch)
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from None
        store.audit(actor,'mercmode.settings',body.host,patch)
        if _local_scheduler(worker):
            previous=store.get(mercmode.COMMAND,body.host) or {}
            old_job=store.get('job',previous.get('job')) if previous.get('job') else None
            if not (previous.get('settings')==desired and previous.get('worker_id')==worker['id'] and old_job
                    and old_job.get('require_worker')==worker['id'] and old_job.get('tool')=='mercmode'
                    and old_job.get('state') not in ('failed','invalid','cancelled','rejected')):
                # an older worker's mercmode tool forbids unknown fields and cannot warm-launch anyway
                relay={k:v for k,v in desired.items()
                       if (k!='keep_warm' or mercmode.WARM_FEATURE in (worker.get('features') or []))
                       and (k not in mercmode.STALEMATE_KEYS or mercmode.STALEMATE_FEATURE in (worker.get('features') or []))
                       and not (k=='preferred_editions' and not v)}      # unset: never sent to a worker that lacks it
                job=submit(JobRequest(tool='mercmode',input={'op':'configure','host':body.host,**relay},
                    require_worker=worker['id']),actor=actor,
                    origin={'via':'MercMode local scheduler settings','worker':body.host})
                store.put(mercmode.COMMAND,body.host,{'job':_jid(job),'settings':desired,'at':time.time(),
                    'worker_id':worker['id'],'state':'queued'})
        return saver.mercmode_status()

    @app.post('/api/mercmode/prepare')
    def mercmode_prepare(body: MercModePrepare,actor=Depends(auth)):
        from . import mercmode
        worker=next((w for w in workers() if w.get('id')==body.worker_id),None)
        if worker is None:
            raise HTTPException(422,'Choose an exact registered worker')
        job=submit(JobRequest(tool='mercmode',input={'op':'prepare'},require_worker=worker['id']),
            actor=actor,origin={'via':'MercMode host readiness','worker':worker['name']})
        old=store.get(mercmode.PREPARATION,worker['name']) or {}
        store.put(mercmode.PREPARATION,worker['name'],old|{'requested_at':time.time(),'job':_jid(job),'state':'checking'})
        return {'queued':True,'job_id':_jid(job),'worker_id':worker['id']}

    @app.post('/api/autoplay-screensaver/round-boundary')
    def mercmode_round(body: MercModeBoundary, parent_job: str=Header(default='',alias='x-gbox-parent-job'),
                      actor=Depends(auth)):
        try:encoded=json.dumps(body.model_dump(),allow_nan=False)
        except ValueError:raise HTTPException(422,'finite native round values required') from None
        if len(encoded)>8000:
            raise HTTPException(413,'round boundary too large')
        try:
            return saver.round_boundary(body.model_dump(),store.get('job',parent_job) or {})
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from None

    @app.post('/api/mercmode/preparation')
    def mercmode_preparation(body: MercModePreparation,actor=Depends(auth)):
        from . import mercmode
        worker=next((w for w in workers() if w.get('id')==body.worker_id),None)
        if worker is None or not mercmode.valid_preparation(body.result):
            raise HTTPException(422,'An exact host and bounded read-only preparation receipt are required')
        store.put(mercmode.PREPARATION,worker['name'],body.result)
        return {'saved':True,'host':worker['name'],'preparation':body.result}

    @app.post("/api/autoplay/telemetry/{sid}")
    def autoplay_telemetry_put(sid: str, body: Telemetry, actor=Depends(auth)):
        try:
            encoded = json.dumps(body.stats, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, OverflowError, RecursionError):
            raise HTTPException(422, "stats must contain finite JSON values") from None
        if len(encoded) > TELEMETRY_STATS_MAX_BYTES:
            raise HTTPException(413, "stats too large")
        if body.autoplay_taken_over:
            from .autoplay_resume import note_handoff
            note_handoff(store, sid, body.source_autoplay_job_id)
        telemetry_put(sid, body.model_dump())
        return {"ok": True}

    @app.get("/api/autoplay/telemetry/{sid}")
    def autoplay_telemetry_get(sid: str, actor=Depends(auth)):
        return telemetry_get(sid)

    @app.get("/api/sessions/{sid}/directive")
    def directive_get(sid: str, actor=Depends(auth)):
        from .mercs import directives
        return {"directive": directives.latest(sid), "commands": {k: v["label"] for k, v in directives.COMMANDS.items()}}

    @app.post("/api/sessions/{sid}/directive")
    def directive_post(sid: str, body: DirectiveIn, actor=Depends(auth)):
        """An instant command for the session's autobot (the chat's dropdown): the bot reads it within a second."""
        from .mercs import directives
        try:
            row = directives.post(sid, body.command, source=str(actor), hold_s=body.hold_s)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        store.audit(actor, "autoplay.directive", sid, {"command": body.command} | ({"hold_s": body.hold_s} if body.hold_s is not None else {}))
        return {"directive": row}

    stopped = threading.Event()
    saver.wake = threading.Event()                       # saver.nudge(): a tick now, between the 30 s ones

    def loop():
        while not stopped.is_set():
            nudged = saver.wake.wait(30)
            saver.wake.clear()
            if stopped.is_set():
                break
            try:
                saver.tick()
            except Exception as e:                       # one bad tick must not end the schedule
                print(f"autoplay screensaver tick failed: {type(e).__name__}: {e}", flush=True)
            if nudged:
                continue                                 # the builder keeps its 30 s cadence
            try:
                saver.builder.tick(bool(settings(store).get("roulette")))
            except Exception as e:                       # the roulette builder never stops the screensaver
                print(f"autoplay roulette tick failed: {type(e).__name__}: {e}", flush=True)
    app.on_event("startup")(lambda: threading.Thread(target=loop, daemon=True, name="autoplay-screensaver").start())
    app.on_event("shutdown")(lambda: (stopped.set(), saver.wake.set()))
