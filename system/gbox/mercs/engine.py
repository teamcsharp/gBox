"""The Mercenaries engine's round loop (docs/mercenaries_engine.md, section 7): what the deployment playbook
(gbox/mercs_bot.py) calls while a round is up.

    from gbox.mercs import engine as E
    why = E.play_round(prof, m, send, stopped, stats, lessons)     # "round" | "lost" | "stopped"

prof: the title's mercs block (+ map_id, platform); m: the session's RAM, read only (rd(addr, n)); send(rows): gBox pad
events [{"key", "down"}]; stopped(): the caller's stop flag; stats: the live dict the watch panel shows (timer and
ram_progress keep moving while the round runs); lessons: entry -> lessons.append(map_id, entry, run=...) or None;
tactical: the tactical map's hook (gbox.mercs.tactical.Publisher), handed (snap, bot, screen) every tick - it keeps at
most 10 a second and posts them on its own thread, and a failure there never costs the round a tick.

Per tick: the title's snapshot and screen (its driver); a prompt the game shows is pressed from RAM (reactions:
held while an attack lands first); else the title's brain decides (RE4: re4_merc_bot.Bot - threats first from the
Ganados' own routine and motion bytes, the time-bonus route, the learned map); keys are held / let go as a diff.
Returns "round" when the screen leaves the round (results, menus, a story room) for ROUND_GONE_S, "lost" when the
player is gone for LOST_S (a black screen, a hung game: the caller recovers), "stopped" when stopped() says so.

READY: the deployment hands rounds to play_round only when True (set once a live run on the title has played at least
as well through here as through the title's own playbook).
"""
from __future__ import annotations

import time
import uuid

from . import driver as D
from .reactions import PromptPresser
from .read_retry import NativeReadRetry

READY = False
ROUND_GONE_S, LOST_S = 1.0, 20.0
TAP_DOWN_S, TAP_REST_S = 0.25, 0.4
FRAME_WAIT_S, FRAME_POLL_S = 0.05, 0.002      # frame sync: wait for the game's next frame this long, polling this often
MASH_DOWN_S, MASH_UP_S = 0.045, 0.035         # a mash (a grab's SHAKE OFF): each press down / up this long - two game
                                              # frames down, one up, so every press is a new one to the game
RECOVERY_DOWN_S = RECOVERY_UP_S = 1. / 60.    # verified RE5 self-recovery: one game frame down, one released


class Latency:
    """Reaction times in the game's own clock (the title's VI / retrace count, 60 a second): from an attack's onset
    (its value first seen) to the bot's answer (a trigger press on it or an evade from it), and from a trigger press to
    the game firing (the player's routine entering its shot). Medians in stats: react_vi_med, respond_vi_med."""

    def __init__(self, stats: dict):
        self.stats = stats
        self.onset: dict = {}                    # slot -> vi when its attack was first seen
        self.react: list = []
        self.respond: list = []
        self.press_vi = None

    @staticmethod
    def _med(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if xs else None

    def observe(self, bot, snap, act, held_before, vi):
        if vi is None:
            return
        for t in getattr(bot, "_threats", []):
            if t.kind not in ("near", "down") and t.slot not in self.onset:
                self.onset[t.slot] = vi
        keys = set(act.get("hold", ())) if isinstance(act, dict) else set()
        target = getattr(bot, "target_slot", None)
        ev = getattr(bot, "evade", None)
        answered = None
        if "a" in keys and "a" not in held_before:
            self.press_vi = vi                       # a trigger press: when does the game fire?
            if target in self.onset:
                answered = target
        if answered is None and ev and ev.get("slot") in self.onset and ev.get("since") is not None:
            answered = ev["slot"]
        if answered is not None:
            self.react.append(vi - self.onset.pop(answered))
            self.stats["react_vi_med"] = self._med(self.react[-50:])
        r = (snap.get("player") or {}).get("r")
        if self.press_vi is not None and r and len(r) > 2 and r[1] == 6 and r[2] == 2:
            self.respond.append(vi - self.press_vi)
            self.press_vi = None
            self.stats["respond_vi_med"] = self._med(self.respond[-50:])
        live = {t.slot for t in getattr(bot, "_threats", [])}
        for k in [k for k in self.onset if k not in live]:
            self.onset.pop(k, None)


def play_round(prof, m, send, stopped, stats: dict, lessons=None, sleep=time.sleep, clock=time.time,
               tick_s: float = 0.05, driver=None, brain=None, learn_dir=None, tactical=None, damage=None,
               session_runtime=None, observe_only=False) -> str:
    drv = driver or D.load(prof)
    if damage is not None:
        damage.bind(drv, prof)
    from .training import HumanObserver, RoundAssistance, round_fields
    assistance = RoundAssistance()
    role_signature = session_runtime.signature() if session_runtime is not None else None
    bot = brain or (HumanObserver(stats) if observe_only else drv.brain(m, stats, clock, learn_dir=learn_dir))
    pp = PromptPresser(None if observe_only else drv.prompt_source(m, stats), keys=drv.prompt_keys, stats=stats,
                       unknown=getattr(drv, "prompt_unknown", (LookupError,)))
    held: set = set()
    gone_since = lost_since = None
    hits_seen = stats.get("hits_taken", 0)
    progress = 0
    frame_fn = getattr(drv, "frame", None)
    clock_frame = [None]                              # the game's frame (driver.frame) at the last decision
    lat = Latency(stats)
    read_retry = NativeReadRetry(stats, 'round')

    def hold(keys):
        nonlocal held
        rows = [{"key": k, "down": False} for k in sorted(held - keys)] + \
               [{"key": k, "down": True} for k in sorted(keys - held)]
        if rows:
            send(rows)
        held = set(keys)

    def next_frame():
        """Frame-synced: wait (polling the title's frame counter, a 4-byte read) until the game has stepped since the
        last decision, at most FRAME_WAIT_S; without a counter, tick_s."""
        if frame_fn is None:
            sleep(tick_s)
            return None
        t_end = clock() + FRAME_WAIT_S
        while True:
            try:
                f = frame_fn(m)
            except Exception:                        # noqa: BLE001
                f = None
            if f is None or f != clock_frame[0] or clock() >= t_end:
                clock_frame[0] = f
                return f
            sleep(FRAME_POLL_S)

    def log(kind, **fields):
        if lessons is not None:
            try:
                lessons({"kind": kind, **fields})
            except Exception:                        # noqa: BLE001 - a lesson lost never stops the round
                stats["local_log_errors"] = stats.get("local_log_errors", 0) + 1

    trace = None
    notebook = None
    remembered = None
    round_id = None
    outcome = "interrupted"
    last_stats = {}
    # Per-round deltas for counters retained by the deployment's live stats dict.
    delta_fields = ("bonuses_taken", "bonus_s", "stuck", "routes_blocked", "routes_given_up", "mines_placed",
                    "bonus_actor_removals", "clock_gain_s", "clock_jumps",
                    "damage_events", "player_damage_events", "hits_taken", "mine_attempts", "mine_detonations_observed", "mine_retreats_completed",
                    "mine_pickups_avoided", "qte_presses", "resuscitate_presses", "route_replans", "nav_recoveries")
    baseline = {k: stats.get(k, 0) for k in delta_fields}
    round_closed = False
    last_round_marker = None
    native_playing_seen = False
    terminal_witness = None
    solo_native_round = True
    source_sink=getattr(tactical,'sink',None)
    source_headers=getattr(getattr(source_sink,'client',None),'headers',{}) or {}
    provenance={key:value for key,value in {
        'source_session_id':getattr(source_sink,'sid',None),
        'source_autoplay_job_id':source_headers.get('x-gbox-parent-job')}.items()
        if isinstance(value,str) and 0<len(value)<=160}
    for key in ('source_session_id','source_autoplay_job_id'):
        stats.pop(key,None)
    stats.update(provenance)
    try:
        from . import lessons as lesson_store
        from .notebook import Notebook
        notebook = Notebook(lesson_store.ROOT.parent, prof["map_id"])
        round_id = uuid.uuid4().hex
        config = getattr(getattr(m,"adapter",None),"config",None)
        if config is not None and callable(getattr(config,"token",None)):
            notebook.configure_knowledge(config.public_url or "http://127.0.0.1:8765",config.token())
    except Exception as exc:
        stats["round_notebook_error"] = str(exc)[:200]
    if prof.get("map_id") == "BLUS30491":
        from .route_trace import Recorder
        from . import lessons as lesson_store
        trace = Recorder(log, atlas_root=lesson_store.ROOT.parent / "navigation", title=prof["map_id"], round_id=round_id,
                         provenance=provenance)

    def finish_evidence(at, reason, final_stats):
        nonlocal trace, round_closed
        if round_closed:
            return
        round_closed = True
        row = dict(final_stats)
        row['assistance'] = round_fields(stats, assistance)
        row['assistance_classification'] = row['assistance']['classification']
        row['assistance_verified'] = row['assistance']['verified']
        for key in delta_fields:
            row[key] = max(0, (row.get(key) or 0) - baseline[key])
        if row.get('round_accuracy') is not None:
            row['accuracy'] = row['round_accuracy']
        if trace is not None:
            try:
                # The writer owns this detached metric snapshot. Attaching its
                # returned review to row must never make review.metrics refer
                # back to row (a cycle breaks every later round's JSON output).
                metrics = {key:value for key,value in row.items()
                           if isinstance(value,(str,int,float,bool,type(None)))}
                metrics['assistance'] = row['assistance']
                navigation = trace.finish(at, reason, metrics)
                stats.update(navigation)
                row.update(navigation)
                log("navigation_round_review", **navigation)
            except Exception as exc:
                stats["navigation_atlas_error"] = str(exc)[:200]
            finally:
                trace = None
        if notebook is not None and remembered is not None:
            try:
                saved = notebook.finish(*remembered, reason, row, round_id=round_id)
                stats["round_memory_saved"] = saved["id"]
                stats["round_evidence_finalized"] = stats.get("round_evidence_finalized",0)+1
                log("round_learning", **saved)
                config = getattr(getattr(m, "adapter", None), "config", None)
                if config is not None and callable(getattr(config, "token", None)):
                    notebook.publish(config.public_url or "http://127.0.0.1:8765", config.token())
            except Exception as exc:
                stats["round_notebook_error"] = str(exc)[:200]
        stats["round_evidence_closed"] = True
        if not observe_only and solo_native_round and native_playing_seen and terminal_witness is not None \
                and isinstance(prof.get('map_id'),str) and bool(prof['map_id']) \
                and reason in ('completed','died') and (session_runtime is None or
                    session_runtime.config.get('role') == 'solo_p1'):
            from ..mercmode import publish_boundary
            publish_boundary(getattr(tactical,'sink',None), {
                'round_id':round_id, 'at':at, 'map_id':prof['map_id'], 'role':'solo_p1',
                'source':'native_terminal_reader', 'mode':str(stats.get('mercenaries_mode') or 'mercenaries'),
                'stage':str(remembered[0]) if remembered else None,
                'character':stats.get('character'), 'witness':terminal_witness},stats)

    def start_evidence(before):
        nonlocal trace, remembered, round_id, baseline, round_closed, outcome, last_stats, assistance
        nonlocal native_playing_seen, terminal_witness
        nonlocal solo_native_round
        round_id = uuid.uuid4().hex
        remembered = None
        baseline = {key:before.get(key,0) for key in delta_fields}
        round_closed, outcome, last_stats = False, "interrupted", {}
        native_playing_seen, terminal_witness = False, None
        solo_native_round = True
        assistance = RoundAssistance()
        for key in ("result_rank","result_rank_observed","rank_verified","completed_score_rank",
                    "completed_score_rank_source","finished_naturally"):
            stats.pop(key,None)
        stats.update(round_evidence_id=round_id,round_evidence_closed=False)
        if prof.get("map_id") == "BLUS30491":
            from .route_trace import Recorder
            from . import lessons as lesson_store
            trace = Recorder(log,atlas_root=lesson_store.ROOT.parent/"navigation",title=prof["map_id"],round_id=round_id,
                             provenance=provenance)

    stats.update(round_evidence_id=round_id,round_evidence_closed=False)

    try:
        while not stopped():
            if session_runtime is not None:
                status = session_runtime.poll(m, drv)
                if session_runtime.signature() != role_signature:
                    return 'role_changed'
                if not observe_only and status['control_player'] is None:
                    return 'control_unavailable'
            now = clock()
            before_observation = dict(stats)
            try:
                snap = drv.snapshot(m)
                where = drv.screen(m, snap)
            except OSError as error:
                # A missing sample is not a game decision. Release this bot's
                # keys, preserve its round, then re-read for a bounded interval.
                hold(set())
                delay = read_retry.failed(error, now)
                if delay is None:
                    raise
                sleep(delay)
                continue
            read_retry.recovered(now)
            if snap.get('scoring_players') == 2:
                solo_native_round = False
            if session_runtime is not None:
                session_runtime.poll(m, drv, snap)
            stats["screen"] = where
            if where == "playing":
                stats.pop("screen_note", None)
            if damage is not None:
                from .damage import Backpressure
                try:
                    damage.before(snap, where, m, bot, held, now)
                except Backpressure as exc:
                    stats.update(player_damage_status="backpressure", player_damage_error=str(exc)[:300])
                    log("player_damage_backpressure", error=str(exc)[:300])
                    return "evidence_backpressure"      # finally releases held input before returning
            observe_round = getattr(bot, "observe_round", None)
            if observe_round is not None:
                observe_round(snap, where, now)
            if where == "playing":
                # A fast retry can begin inside this invocation: DEAD is IN_ROUND,
                # and short menus/loading gaps do not satisfy ROUND_GONE_S.
                marker = getattr(bot,"_round_started",None)
                changed_round = last_round_marker is not None and marker is not None and marker != last_round_marker
                if round_closed or changed_round:
                    hold(set())
                    if not round_closed:
                        finish_evidence(now,outcome if outcome != "interrupted" else "ended",last_stats)
                    start_evidence(before_observation)
                if marker is not None:
                    last_round_marker = marker
                if snap.get('player'):
                    native_playing_seen = True
            assistance.observe(snap.get('assistance'))
            round_fields(stats, assistance)
            if damage is not None:
                damage.after(snap, where, now)
            if tactical is not None:                  # the tactical map: who is where, what the bot means to do
                try:
                    tactical(snap, bot, where)
                except Exception:                     # noqa: BLE001 - the map never costs the round a tick
                    pass
            if where not in D.IN_ROUND:
                if where == "results":
                    last_stats = dict(stats)
                    for key in ("timer","kills","score","combo"):
                        value = snap.get(key)
                        if value is not None and (key not in ("kills","score") or
                                isinstance(value,(int,float)) and value>=max(0,last_stats.get(key) or 0)):
                            last_stats[key] = value
                    if outcome != "died":
                        outcome = "completed" if last_stats.get("timer") == 0 or (last_stats.get("kills") or 0)>=150 else "ended"
                    hold(set())
                    result_ready = getattr(drv,"result_ready",None)
                    if not round_closed and callable(result_ready) and not result_ready(snap,now):
                        stats["result_tally_status"] = "observing terminal score count-up with inputs released"
                        sleep(.1)
                        continue
                    stats["result_tally_status"] = "terminal evidence closed"
                    terminal_witness = {'screen':'results','playing_observed':native_playing_seen,
                        'player_verified':native_playing_seen,'tally_ready':callable(result_ready),
                        'timer':last_stats.get('timer'),'kills':last_stats.get('kills')}
                    finish_evidence(now,outcome,last_stats)
                    if stats.get('mercmode_rotate_requested'):
                        return 'mercmode_boundary'
                hold(set())
                handoff = getattr(drv, "menu_handoff", None)
                known_menu = callable(handoff) and handoff(m, snap, where) is True
                if where == "loading" or (not snap.get("player") and not known_menu):
                    gone_since = None
                    lost_since = lost_since or now
                    if now - lost_since > LOST_S:
                        outcome = "lost"
                        return "lost"
                else:
                    lost_since = None
                    gone_since = gone_since or now
                    if now - gone_since > ROUND_GONE_S:
                        if outcome != "died":
                            outcome = "completed" if where == "results" and (last_stats.get("timer") == 0
                                or (last_stats.get("kills") or 0) >= 150) else "ended"
                        log("round", stats={k: v for k, v in stats.items() if isinstance(v, (int, float, str))})
                        return "round"
                sleep(0.1)
                continue
            gone_since = lost_since = None
            progress += 1
            stats.update(drv.progress(snap))
            if where == "dead":
                outcome = "died"
            last_stats = dict(stats)
            if where == "dead":
                hold(set())
                hp=(snap.get('player') or {}).get('hp') if isinstance(snap.get('player'),dict) else None
                hp=snap.get('hp') if hp is None else hp
                terminal_witness = {'screen':'dead','playing_observed':native_playing_seen,
                    'player_verified':bool(snap.get('player')),'hp':hp}
                finish_evidence(now,outcome,last_stats)
                if stats.get('mercmode_rotate_requested'):
                    return 'mercmode_boundary'
            if notebook is not None and remembered is None and where == "playing":
                mesh = snap.get("nav")
                stage = getattr(mesh, "learning_sig", None) or str(getattr(snap.get("stage"), "key", "unknown"))
                mode = stats.get("mercenaries_mode", "mercenaries")
                remembered = (stage, mode, stats.get("character", "unknown"))
                try:
                    recalled = notebook.recall(stage, mode, stats)
                    stats.update(round_memory_recalled=len(recalled), round_memory_db=str(notebook.path),
                                 round_guide=str(notebook.root / "guide.json"))
                    log("round_recall", stage=stage, mode=mode, lessons=recalled)
                    if callable(getattr(bot, "recall", None)):
                        bot.recall(recalled)
                except Exception as exc:
                    stats["round_notebook_error"] = str(exc)[:200]
            stats["ram_progress"] = progress
            if trace is not None:
                trace.observe(snap, bot, stats, now, held, "before_decision")
            if observe_only:
                next_frame()
                continue
            chords = pp.step(now, ok=lambda b: bot.prompt_ok(b, snap, now))
            if chords:                                # the game asks for a button: let go, press it
                hold(set())
                mash = getattr(pp, "mashing", False)  # a grab: as fast as the game takes new presses (30 a second)
                for chord in chords:
                    recovery = False
                    if mash and tuple(chord) == ("circle",) and snap.get("recovery_active") \
                            and callable(getattr(drv, "recovery_active", None)):
                        try:
                            recovery = bool(drv.recovery_active(m))
                        except (ValueError, OSError):
                            recovery = False
                        if not recovery:
                            continue  # the live signature ended; do not press into the next game state
                    # This fast path is authorized only by the live recovery signature,
                    # and reread on every pulse. Other Circle QTEs keep their normal cadence.
                    send([{"key": k, "down": True} for k in chord])
                    sleep(RECOVERY_DOWN_S if recovery else MASH_DOWN_S if mash else (0.12 if len(chords) == 1 else 0.06))
                    send([{"key": k, "down": False} for k in chord])
                    if mash or len(chords) > 1:
                        sleep(RECOVERY_UP_S if recovery else MASH_UP_S if mash else 0.04)
                    if recovery:
                        stats["resuscitate_fast_pulses"] = stats.get("resuscitate_fast_pulses", 0) + 1
                if not mash:
                    sleep(0.15)
                continue
            act = bot.tick(snap)
            if trace is not None:
                trace.observe(snap, bot, stats, now, act.get("hold", ()), "decision", act.get("tap"))
            vi = frame_fn.vi(m) if frame_fn is not None and hasattr(frame_fn, "vi") else None
            lat.observe(bot, snap, act, held, vi)
            if stats.get("hits_taken", 0) > hits_seen:   # what hit him, for the lessons
                hits_seen = stats["hits_taken"]
                log("hit_taken", player_r=list((snap.get("player") or {}).get("r") or ()),
                    attackers=[{"slot": t.slot, "kind": t.kind, "state": list(t.state) if t.state else None,
                                "act": (t.state[1] if t.state and len(t.state) > 1 else None),
                                "eta": round(t.eta, 2) if t.eta != float("inf") else None, "dist": round(t.dist),
                                "in_value_s": round(now - t.since, 2)} for t in getattr(bot, "_threats", [])[:3]])
            if "tap" in act:
                hold(set())
                sleep(0.15)
                send([{"key": act["tap"], "down": True}])
                sleep(TAP_DOWN_S)
                send([{"key": act["tap"], "down": False}])
                sleep(TAP_REST_S)
                continue
            hold(set(act.get("hold", ())))
            next_frame()
        return "stopped"
    finally:
        read_retry.stopped()
        try:
            hold(set())
        finally:
            finish_evidence(clock(),outcome,last_stats)
            try:
                bot.save()
            except Exception:                        # noqa: BLE001
                pass
