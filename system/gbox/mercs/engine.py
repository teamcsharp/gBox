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

import json
import time
import traceback
import uuid

from . import driver as D
from .core import doctrine          # at import: the bot hot reload only tracks modules loaded with the worker
from .core import combat as _combat  # noqa: F401 - the universal fight (the titles' UNIVERSAL_CORE), the same reason
from .reactions import PromptPresser
from .read_retry import NativeReadRetry

READY = False
ROUND_GONE_S, LOST_S = 1.0, 20.0
TAP_DOWN_S, TAP_REST_S = 0.25, 0.4
FRAME_WAIT_S, FRAME_POLL_S = 0.05, 0.002      # frame sync: wait for the game's next frame this long, polling this often
MASH_DOWN_S, MASH_UP_S = 0.045, 0.035         # a mash (a grab's SHAKE OFF): each press down / up this long - two game
                                              # frames down, one up, so every press is a new one to the game
RECOVERY_DOWN_S = RECOVERY_UP_S = 1. / 60.    # verified RE5 self-recovery: one game frame down, one released
# A bot's tick that raises costs that tick, never the round (operator 2026-10-28: a TypeError in the RE6 bot ended its
# run 30 s into a round and Sherry stood still among the zombies until the clock ran out, 0 kills). Keys are let go, the
# error and where it was are kept in stats (tick_errors, tick_error) and the lessons; this many in a row ends the run.
TICK_ERRORS_MAX = 200


class DecisionWork:
    """Attribute combat-loop latency without including the frame-budget sleep.

    Stage times are wall time and may include nested native calls; they are not
    CPU utilization. Slow samples retain round identity for later death review.
    """
    def __init__(self, stats):
        self.stats = stats
        self.begin()

    def begin(self):
        self.started = time.perf_counter()
        self.stages = {}

    def call(self, stage, fn, *args, **kwargs):
        start = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            self.stages[stage] = self.stages.get(stage, 0.0) + time.perf_counter() - start

    def finish(self):
        total = max(0.0, time.perf_counter() - self.started)
        stages = {key:round(value * 1000, 2) for key,value in self.stages.items()}
        self.stats['decision_stages_ms'] = stages
        # The live telemetry transport keeps scalar stats; the rich copy is
        # still retained by the flight recorder and completed-round evidence.
        self.stats['decision_stages_json'] = json.dumps(stages, separators=(',', ':'))
        if total >= .25 and self.stats.get('screen') == 'playing':
            row = {'at':time.time(), 'round_id':self.stats.get('round_evidence_id'),
                   'work_ms':round(total * 1000, 2), 'stages_ms':stages}
            rows = list(self.stats.get('decision_slow_recent') or ())[-19:]
            self.stats.update(decision_slow_recent=rows + [row],
                              decision_slow_last_json=json.dumps(row, separators=(',', ':')),
                              decision_slow_cycles=int(self.stats.get('decision_slow_cycles', 0)) + 1)
        return total


def tick_error_where(exc) -> str:
    """The innermost frame of a tick's exception in our own code (not the standard library, not site-packages):
    file:line function."""
    import sysconfig
    lib = sysconfig.get_paths()["stdlib"].replace("\\", "/").lower()
    frames = traceback.extract_tb(exc.__traceback__)
    own = [f for f in frames if "site-packages" not in f.filename
           and not f.filename.replace("\\", "/").lower().startswith(lib)] or frames
    if not own:
        return "?"
    f = own[-1]
    return f"{f.filename.replace(chr(92), '/').rsplit('/', 1)[-1]}:{f.lineno} {f.name}"


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


def _enemy_round(title, stats=None) -> dict:
    """The enemy knowledge database's round (gbox.mercs.enemy_db): stats None opens one, else closes it - its numbers
    into stats and returned for the round's row (Notebook, round report). Never costs the round."""
    if not title:
        return {}
    try:
        from . import enemy_db
        if stats is None:
            enemy_db.round_begin(title)
            return {}
        return enemy_db.round_end(title, stats)
    except Exception as exc:                          # noqa: BLE001 - the database never stops a round
        if stats is not None:
            stats["enemy_db_error"] = str(exc)[:200]
        return {}


def _attackers(bot, snap) -> list:
    """The attackers to report with a hit: the bot's own threat tracks when it has them, else the snapshot's near
    enemies (class, distance, state, eta) - a hit taken during a bomb/grenade action still names who was on him."""
    rows = []
    for t in getattr(bot, "_threats", []) or ():
        try:
            state = getattr(t, "state", None)
            eta = getattr(t, "eta", None)
            rows.append({"kind": getattr(t, "kind", None), "dist": round(getattr(t, "dist", 0) or 0),
                         "state": list(state) if state else None,
                         "act": (state[1] if state and len(state) > 1 else None),
                         "eta": round(eta, 2) if isinstance(eta, (int, float)) and eta != float("inf") else None})
        except Exception:                                # noqa: BLE001 - a bad track never costs the report
            continue
    if rows:
        return rows[:3]
    player = (snap or {}).get("player") or {}
    pos = player.get("pos")
    if not pos:
        return rows
    for e in (snap or {}).get("enemies") or ():
        if not isinstance(e, dict) or not e.get("pos"):
            continue
        try:
            d = ((e["pos"][0] - pos[0]) ** 2 + (e["pos"][2] - pos[2]) ** 2) ** 0.5
        except (TypeError, IndexError, KeyError):
            continue
        if d > 500.0:
            continue
        state = e.get("state")
        rows.append({"kind": e.get("class") or e.get("kind"), "dist": round(d),
                     "state": list(state) if isinstance(state, (list, tuple)) else None,
                     "act": (state[1] if isinstance(state, (list, tuple)) and len(state) > 1 else None),
                     "eta": e.get("eta")})
    rows.sort(key=lambda row: row.get("dist") or 1e9)
    return rows[:3]


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
                       unknown=getattr(drv, "prompt_unknown", (LookupError,)),
                       # QTE vision fallback (gbox.mercs.qte): RAM first, vision only when RAM can't tell, so a title
                       # with no RAM map - or a frame where a RAM read tore - still answers its prompts (grab escapes).
                       vision=None if observe_only else (getattr(drv, "prompt_vision", lambda *_: None)(m, stats)))
    # The universal doctrine (gbox.mercs.core.doctrine): the operator's standing goals for every title, measured on
    # each playing tick and handed to the bot as the commands it already takes. Never costs the round a tick.
    director = None
    if not observe_only:
        try:
            title_mod = doctrine.title_module(drv)
            director = doctrine.Director(stats, weights_of=lambda: doctrine.weights(title_mod))
            director.reset(clock())
        except Exception as exc:                     # noqa: BLE001
            stats["doctrine_error"] = f"{type(exc).__name__}: {exc}"[:160]
    # The grenade ring's own rule (gbox.mercs.grenade_ring): fires it when surrounded, facing a boss/heavy or held by
    # a crowd that is not thinning - never inside the learned blast reach, at most every RING_EVERY_S. One call per
    # playing tick; a title with no native ring refuses in the controller and the round goes on.
    ring_step = None
    if not observe_only:
        try:
            # The ring's target is the session's adapter when it has one (the Switch titles). RE4's MercMode rounds
            # are driven by its own loop and expose no adapter, so `ring_ad` was None, the whole block was skipped and
            # the 360 launcher ring never armed on RE4 (live 2026-11-11: rounds 3-9 playing with no ring_armed, no
            # ring_decision and no grenade_ring_error - the code path never ran). The driver itself is the fallback
            # target: grenade_ring.controller() builds the title's native controller from whatever it is given.
            ring_ad = getattr(m, "adapter", None) or m
            # Diagnostic for the "ring never fires" investigation: the profile id and whether an adapter exists are
            # what grenade_ring.control decides on. Recorded before the call so a refusal is visible in telemetry.
            stats["ring_prof_map"] = str((prof or {}).get("map_id") or "")
            stats["ring_adapter"] = bool(getattr(m, "adapter", None) is not None)
            if ring_ad is not None:
                from . import grenade_ring
                ring_step = grenade_ring.control(ring_ad, prof)
            stats["ring_armed"] = bool(ring_step is not None)
        except Exception as exc:                     # noqa: BLE001
            stats["grenade_ring_error"] = f"{type(exc).__name__}: {exc}"[:160]
    remote_step = None
    if not observe_only:
        try:
            remote_ad = getattr(m, "adapter", None)
            if remote_ad is not None:
                from . import remote_mines
                remote_step = remote_mines.control(remote_ad, prof, bot_getter=lambda: bot)
        except Exception as exc:                     # noqa: BLE001
            stats["remote_mines_error"] = f"{type(exc).__name__}: {exc}"[:160]
    held: set = set()
    gone_since = lost_since = None
    damage_run = stats.get("player_damage_run")
    hits_seen = (int(stats.get("player_damage_events") or 0) if damage_run is not None
                 else int(stats.get("hits_taken") or 0))
    tick_errors = 0                                  # TICK_ERRORS_MAX: ticks in a row that raised
    progress = 0
    frame_fn = getattr(drv, "frame", None)
    clock_frame = [None]                              # the game's frame (driver.frame) at the last decision
    lat = Latency(stats)
    read_retry = NativeReadRetry(stats, 'round')
    decision_interval = getattr(drv, 'decision_interval_s', None)
    cycle_started = time.perf_counter()
    timing_since, timing_count, work_samples = cycle_started, 0, []
    decision_work = DecisionWork(stats)

    def hold(keys):
        nonlocal held
        if stats.get("operator_control") is True:     # the operator has the pad (gbox/pad_takeover.py): the bot holds
            held = set()                              # nothing, so its first decision after they put it down presses
            return                                    # what it wants then - nothing held from before comes back
        rows = [{"key": k, "down": False} for k in sorted(held - keys)] + \
               [{"key": k, "down": True} for k in sorted(keys - held)]
        if rows:
            receipt = send(rows)
            if receipt is False or (isinstance(receipt, dict) and
                    (receipt.get('stopped') or receipt.get('held') or receipt.get('skipped') or
                     receipt.get('sent') != len(rows))):
                # Keep the held set until the transport accepts the release;
                # a native equipment handover must not acknowledge dropped input.
                return False
        held = set(keys)
        return True

    def next_frame():
        """Frame-synced: wait (polling the title's frame counter, a 4-byte read) until the game has stepped since the
        last decision, at most FRAME_WAIT_S; without a counter, tick_s."""
        nonlocal timing_since, timing_count
        decision_work.finish()
        if frame_fn is None:
            if decision_interval is None:
                sleep(tick_s)
                return None
            # Subtract decision work instead of adding a full sleep after it.
            # An overrun starts a fresh budget; never run a catch-up burst.
            current = time.perf_counter()
            work = max(0.0, current - cycle_started)
            work_samples.append(work * 1000)
            del work_samples[:-120]
            timing_count += 1
            if current - timing_since >= 1.0:
                ordered = sorted(work_samples)
                stats.update(decision_hz=round(timing_count / (current - timing_since), 1),
                             decision_work_ms=round(work * 1000, 2),
                             decision_work_p95_ms=round(ordered[int((len(ordered)-1)*.95)], 2),
                             decision_budget_ms=round(decision_interval * 1000, 2))
                timing_since, timing_count = current, 0
            sleep(max(0.001, decision_interval - work))
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

    def tick_failed(exc, in_a_row):
        """A tick that raised (TICK_ERRORS_MAX): its keys let go, the error and where kept, the next tick after a frame.
        -> the count in a row; past TICK_ERRORS_MAX the exception ends the run as before."""
        in_a_row += 1
        if in_a_row > TICK_ERRORS_MAX:
            raise exc
        error = f"{type(exc).__name__}: {str(exc)[:160]} at {tick_error_where(exc)}"
        stats["tick_errors"] = stats.get("tick_errors", 0) + 1
        if stats.get("tick_error") != error:
            log("tick_error", error=error, trace="".join(traceback.format_exception(exc))[-2000:])
        stats["tick_error"] = error
        hold(set())
        next_frame()
        return in_a_row

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
    round_counters = tuple(getattr(drv, "round_counters", ()) or ())   # the driver's turn-long counters (Driver)
    counter_base = {k: stats.get(k) for k in round_counters}
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
    if session_runtime is None and getattr(drv, "solo_p1", False) is True:
        # A driver with no teamplay: the bot alone on P1, the score P1's own (Driver.solo_p1). round_reports and
        # MercMode adoption require this exact role; SessionRuntime records it for the titles that have teamplay.
        stats.update(team_role="solo_p1", scoring_scope="solo")
    combo_step = None
    hit_step = None
    try:
        from . import lessons as lesson_store
        from .notebook import Notebook
        notebook = Notebook(lesson_store.ROOT.parent, prof["map_id"])
        round_id = uuid.uuid4().hex
        config = getattr(getattr(m,"adapter",None),"config",None)
        if config is not None and callable(getattr(config,"token",None)):
            notebook.configure_knowledge(config.public_url or "http://127.0.0.1:8765",config.token())
            # Every combo lost and every hit taken files one follow report (gbox.mercs.combo_reports/hit_reports).
            from . import combo_reports, hit_reports
            combo_reports.configure(config.public_url or "http://127.0.0.1:8765", config.token(),
                                    title=str(prof.get("map_id") or ""),
                                    session_id=str(stats.get("source_session_id") or ""))
            combo_step = combo_reports.observe
            hit_reports.configure(config.public_url or "http://127.0.0.1:8765", config.token(),
                                  title=str(prof.get("map_id") or ""),
                                  session_id=str(stats.get("source_session_id") or ""))
            hit_step = hit_reports.observe
    except Exception as exc:
        stats["round_notebook_error"] = str(exc)[:200]
    if prof.get("map_id") == "BLUS30491":
        from .route_trace import Recorder
        from . import lessons as lesson_store
        trace = Recorder(log, atlas_root=lesson_store.ROOT.parent / "navigation", title=prof["map_id"], round_id=round_id,
                         provenance=provenance)
    capture = None

    def start_capture():
        """Every round's run map (gbox.mercs.run_capture), keyed by its curriculum row id; a brain that keeps its own
        round map (trace_finish: RE5 PS3, RE4) keeps it alone."""
        nonlocal capture
        capture = None
        if callable(getattr(bot, "trace_finish", None)) or not isinstance(prof.get("map_id"), str):
            return
        try:
            from . import run_capture
            from . import lessons as lesson_store
            capture = run_capture.RunCapture(lesson_store.ROOT.parent / "round_maps", prof["map_id"], round_id,
                                             provenance=provenance)
        except Exception as exc:                      # noqa: BLE001 - no map never costs the round
            stats["run_map_error"] = str(exc)[:200]
    start_capture()

    transport_send = send
    def recorded_send(events):
        receipt = transport_send(events)
        if capture is not None:
            try:
                capture.input(clock(), events, receipt)
            except Exception as exc:
                stats['input_record_error'] = f'{type(exc).__name__}: {exc}'[:160]
                stats['input_record_failures'] = stats.get('input_record_failures', 0) + 1
        return receipt
    send = recorded_send

    def finish_evidence(at, reason, final_stats):
        nonlocal trace, round_closed, capture
        if round_closed:
            return
        round_closed = True
        row = dict(final_stats)
        if capture is not None:                       # the run map: its exploration numbers into the row, files after
            mapped = capture.finish(at, reason, stage=remembered[0] if remembered else None)
            row.update(mapped)
            if mapped.get("round_map_file"):
                stats["last_run_map"] = mapped["round_map_file"]
            capture = None
        row['assistance'] = round_fields(stats, assistance)
        row['assistance_classification'] = row['assistance']['classification']
        row['assistance_verified'] = row['assistance']['verified']
        for key in delta_fields:
            row[key] = max(0, (row.get(key) or 0) - baseline[key])
        for key in round_counters:
            end, start = row.get(key), counter_base.get(key)
            if type(end) in (int, float):
                row['round_'+key] = round(max(0, end - (start if type(start) in (int, float) else 0)), 3)
        if row.get('round_accuracy') is not None:
            row['accuracy'] = row['round_accuracy']
        row.update(_enemy_round(prof.get('map_id') if isinstance(prof, dict) else None, stats))
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
        # a bot+bot split-screen round (RE5 / RE6 Switch, switch_team) is a team round, published as one: MercMode
        # counts it only for a turn that asked for split screen (mercmode.accept_boundary)
        team_round = session_runtime is not None and session_runtime.config.get('role') == 'bots_p1_p2'
        from .round_controls import hold_boundary
        if not hold_boundary(m, stats) and not observe_only and (solo_native_round or team_round) and native_playing_seen and terminal_witness is not None \
                and isinstance(prof.get('map_id'),str) and bool(prof['map_id']) \
                and reason in ('completed','died') and (session_runtime is None or team_round or
                    session_runtime.config.get('role') == 'solo_p1'):
            from ..mercmode import publish_boundary
            publish_boundary(getattr(tactical,'sink',None), {
                'round_id':round_id, 'at':at, 'map_id':prof['map_id'], 'role':'bots_p1_p2' if team_round else 'solo_p1',
                'source':'native_terminal_reader', 'mode':str(stats.get('mercenaries_mode') or 'mercenaries'),
                'stage':str(remembered[0]) if remembered else None,
                'character':stats.get('character'), 'witness':terminal_witness},stats)

    def start_evidence(before):
        nonlocal trace, remembered, round_id, baseline, round_closed, outcome, last_stats, assistance
        nonlocal native_playing_seen, terminal_witness
        nonlocal solo_native_round, counter_base
        round_id = uuid.uuid4().hex
        remembered = None
        baseline = {key:before.get(key,0) for key in delta_fields}
        counter_base = {key:before.get(key) for key in round_counters}
        round_closed, outcome, last_stats = False, "interrupted", {}
        native_playing_seen, terminal_witness = False, None
        solo_native_round = True
        assistance = RoundAssistance()
        for key in ("result_rank","result_rank_observed","rank_verified","completed_score_rank",
                    "completed_score_rank_source","finished_naturally"):
            stats.pop(key,None)
        stats.update(round_evidence_id=round_id,round_evidence_closed=False)
        _enemy_round(prof.get("map_id") if isinstance(prof, dict) else None)
        start_capture()
        if director is not None:                      # a new round: its own doctrine measures
            director.reset(clock())
        if prof.get("map_id") == "BLUS30491":
            from .route_trace import Recorder
            from . import lessons as lesson_store
            trace = Recorder(log,atlas_root=lesson_store.ROOT.parent/"navigation",title=prof["map_id"],round_id=round_id,
                             provenance=provenance)

    stats.update(round_evidence_id=round_id,round_evidence_closed=False)
    _enemy_round(prof.get("map_id") if isinstance(prof, dict) else None)

    try:
        while not stopped():
            cycle_started = time.perf_counter()
            decision_work.begin()
            if session_runtime is not None:
                status = session_runtime.poll(m, drv)
                if session_runtime.signature() != role_signature:
                    return 'role_changed'
                if not observe_only and status['control_player'] is None:
                    return 'control_unavailable'
            now = clock()
            before_observation = dict(stats)
            try:
                snap = decision_work.call('snapshot', drv.snapshot, m)
                where = decision_work.call('screen', drv.screen, m, snap)
            except OSError as error:
                # A missing sample is not a game decision. Release this bot's
                # keys, preserve its round, then re-read for a bounded interval.
                hold(set())
                delay = read_retry.failed(error, now)
                if delay is None:
                    raise
                sleep(delay)
                continue
            except Exception as exc:                 # noqa: BLE001 - a reader's bug costs the tick (TICK_ERRORS_MAX)
                tick_errors = tick_failed(exc, tick_errors)
                continue
            read_retry.recovered(now)
            if snap.get('scoring_players') == 2:
                solo_native_round = False
            if session_runtime is not None:
                session_runtime.poll(m, drv, snap)
            stats["screen"] = where
            if ring_step is not None and hasattr(ring_step, 'observe'):
                ring_step.observe(snap, stats, where == 'playing')
            if where == "playing":
                stats.pop("screen_note", None)
            if damage is not None:
                from .damage import Backpressure
                try:
                    decision_work.call('damage_before', damage.before, snap, where, m, bot, held, now)
                except Backpressure as exc:
                    stats.update(player_damage_status="backpressure", player_damage_error=str(exc)[:300])
                    log("player_damage_backpressure", error=str(exc)[:300])
                    return "evidence_backpressure"      # finally releases held input before returning
            observe_round = getattr(bot, "observe_round", None)
            if observe_round is not None:
                decision_work.call('observe_round', observe_round, snap, where, now)
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
                decision_work.call('damage_after', damage.after, snap, where, now)
            if tactical is not None:                  # the tactical map: who is where, what the bot means to do
                try:
                    decision_work.call('tactical', tactical, snap, bot, where)
                except Exception:                     # noqa: BLE001 - the map never costs the round a tick
                    pass
            if where in D.IN_ROUND:
                # Capture must see this sample's identity, including an unreadable one, before
                # it can latch a preceding round's stage from the reused autoplay stats.
                stats.update(drv.progress(snap))
            if capture is not None:                   # the run map: a sample 5 times a second (appends; never raises)
                decision_work.call('capture', capture.observe, now, where, snap, bot, stats,
                                controls={'keys': sorted(held), 'timing': 'pre_decision',
                                          'source': 'transport_tracked_held_state'})
            if where not in D.IN_ROUND:
                if where == "results":
                    last_stats = dict(stats)
                    for key in ("timer","kills","score","combo"):
                        value = snap.get(key)
                        if value is not None and (key not in ("kills","score") or
                                isinstance(value,(int,float)) and value>=max(0,last_stats.get(key) or 0)):
                            last_stats[key] = value
                    native_done = bool(callable(getattr(drv, "mission_complete", None)) and drv.mission_complete(m, snap))
                    if outcome != "died":
                        # a title whose missions end on their own objective (Mercenaries 3D: "take down all hostiles")
                        # says so from its own end state (driver.mission_complete); the clock may still run then
                        outcome = "completed" if last_stats.get("timer") == 0 or (last_stats.get("kills") or 0)>=150                             or native_done else "ended"
                    hold(set())
                    result_ready = getattr(drv,"result_ready",None)
                    if not round_closed and callable(result_ready) and not result_ready(snap,now):
                        stats["result_tally_status"] = "observing terminal score count-up with inputs released"
                        sleep(.1)
                        continue
                    stats["result_tally_status"] = "terminal evidence closed"
                    terminal_witness = {'screen':'results','playing_observed':native_playing_seen,
                        'player_verified':native_playing_seen,'tally_ready':callable(result_ready),
                        'timer':last_stats.get('timer'),'kills':last_stats.get('kills'),
                        **({'mission_complete':True} if native_done else {})}
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
                                or (last_stats.get("kills") or 0) >= 150
                                or (terminal_witness or {}).get("mission_complete") is True) else "ended"
                        log("round", stats={k: v for k, v in stats.items() if isinstance(v, (int, float, str))})
                        return "round"
                sleep(0.1)
                continue
            gone_since = lost_since = None
            progress += 1
            if where == "dead":
                outcome = "died"
            last_stats = dict(stats)
            if where == "dead":
                hold(set())
                hp=(snap.get('player') or {}).get('hp') if isinstance(snap.get('player'),dict) else None
                hp=snap.get('hp') if hp is None else hp
                terminal_witness = {'screen':'dead','playing_observed':native_playing_seen,
                    'player_verified':bool(snap.get('player')),'hp':hp}
                native_death = getattr(drv, 'death_witness', None)
                if callable(native_death):
                    extra = native_death(snap)
                    if isinstance(extra, dict) and isinstance(extra.get('game_over_ui'), dict):
                        terminal_witness['game_over_ui'] = extra['game_over_ui']
                finish_evidence(now,outcome,last_stats)
                if stats.get('mercmode_rotate_requested'):
                    return 'mercmode_boundary'
            if notebook is not None and remembered is None and where == "playing":
                stage_fn = getattr(drv, "learning_stage", None)
                stage = stage_fn(snap) if callable(stage_fn) else D.Driver.learning_stage(drv, snap)
                if stage is not None:                # an unreadable native ID must not latch an unrelated bucket
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
            # RE5 native reactions run beside QTE input. The prompt branch
            # below can skip bot.tick and the ordinary periodic ring entirely.
            if where == 'playing':
                for name, reaction in (('reactive_ring', getattr(ring_step, 'react', None)),
                                       ('reactive_mines', getattr(bot, 'observe_reactions', None)),
                                       ('remote_deadlines', getattr(remote_step, 'observe', None))):
                    if callable(reaction):
                        try:
                            args = ((snap, now) if name == 'reactive_mines' else
                                    (snap, stats, clock() if name == 'remote_deadlines' else now))
                            decision_work.call(name, reaction, *args)
                        except Exception as exc:       # an optional native reaction never suppresses the QTE
                            stats[name + '_error'] = f'{type(exc).__name__}: {exc}'[:200]
            from .primary_weapon import release_for_handover, quiescing
            if not stats.get('operator_control') and quiescing(stats, snap):
                release_for_handover(stats, snap, hold)
                next_frame()
                continue
            chords = pp.step(now, ok=lambda b: bot.prompt_ok(b, snap, now))
            if chords:                                # the game asks for a button: let go, press it
                hold(set())
                if capture is not None:
                    capture.prompt(now, chords)
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
            try:
                act = decision_work.call('bot', bot.tick, snap)
                tick_errors = 0
            except Exception as exc:                 # noqa: BLE001 - TICK_ERRORS_MAX: a bad tick never ends the round
                tick_errors = tick_failed(exc, tick_errors)
                continue
            if trace is not None:
                trace.observe(snap, bot, stats, now, act.get("hold", ()), "decision", act.get("tap"))
            if combo_step is not None and where == "playing":
                try:
                    decision_work.call('combo_report', combo_step, stats, snap, now, doing=getattr(bot, "doing", None),
                               why=getattr(bot, "why", None))
                except Exception as exc:              # noqa: BLE001 - a follow report never ends the round
                    stats["combo_report_error"] = f"{type(exc).__name__}: {exc}"[:200]
            if hit_step is not None and where == "playing":
                # Every playing tick (the module keeps the hp baseline and its own counter; the reports fire on the
                # rise), with the attackers the bot is tracking or, while it is busy elsewhere, the snapshot's near ones.
                try:
                    decision_work.call('hit_report', hit_step, stats, snap, now, attackers=_attackers(bot, snap),
                             doing=getattr(bot, "doing", None), why=getattr(bot, "why", None))
                except Exception as exc:              # noqa: BLE001 - a follow report never ends the round
                    stats["hit_report_error"] = f"{type(exc).__name__}: {exc}"[:200]
            if director is not None and where == "playing":
                try:
                    director.observe(doctrine.view(snap, drv, title_mod), act, now)
                except Exception as exc:              # noqa: BLE001 - the doctrine never costs the round a tick
                    stats["doctrine_error"] = f"{type(exc).__name__}: {exc}"[:160]
            vi = frame_fn.vi(m) if frame_fn is not None and hasattr(frame_fn, "vi") else None
            lat.observe(bot, snap, act, held, vi)
            if ring_step is not None and where == "playing" and not stats.get('mine_deadline_pending'):
                try:
                    ring_out = decision_work.call('grenade_ring', ring_step, snap, stats, now, hold)
                except Exception as exc:             # noqa: BLE001 - a ring never ends the round
                    stats["ring_error"] = f"{type(exc).__name__}: {exc}"[:200]
                else:
                    receipt = ring_out.get('receipt') or {}
                    flash_only = receipt.get('kind') == 'flash' or receipt.get('kinds') == ['flash']
                    if ring_out.get("fired") and not flash_only:
                        # Native blasts have already executed. A camera-relative
                        # backstep cannot establish escape and can undo the title's
                        # final mine, wall, QTE and stage-hazard guards. Submit its
                        # decision on this tick, including an explicit blocked hold.
                        stats['ring_driver_actions_retained'] = int(stats.get('ring_driver_actions_retained') or 0) + 1
                        stats['ring_movement_policy'] = 'title driver action retained; no engine escape asserted'
            if remote_step is not None and where == "playing":   # the RE6 remote-mine rings and flag detonation
                try:
                    remote_out = decision_work.call('remote_mines', remote_step, snap, stats, clock(), hold)
                except Exception as exc:             # noqa: BLE001 - a mine rule never ends the round
                    stats["remote_mines_error"] = f"{type(exc).__name__}: {exc}"[:200]
                else:
                    if remote_out.get("fired"):
                        # Native remote flags need no pad release. Preserve the
                        # bot's measured escape route instead of replacing it
                        # with 2.5 seconds of camera-relative backward input.
                        stats['remote_mines_last_action'] = remote_out.get('op')
            run = stats.get("player_damage_run")
            if run is not None and run != damage_run:    # a new round's damage run: its count starts at 0
                damage_run, hits_seen = run, 0
            taken_now = (int(stats.get("player_damage_events") or 0) if run is not None
                         else int(stats.get("hits_taken") or 0))
            if taken_now > hits_seen:                    # what hit him, for the lessons (the damage observer's count)
                hits_seen = taken_now
                attackers = _attackers(bot, snap)
                log("hit_taken", player_r=list((snap.get("player") or {}).get("r") or ()), attackers=attackers)
                if hit_step is not None:             # the operator: every hurt files a follow report
                    try:
                        decision_work.call('hit_report', hit_step, stats, snap, now, attackers=attackers, doing=getattr(bot, "doing", None),
                                 why=getattr(bot, "why", None))
                    except Exception as exc:         # noqa: BLE001 - a follow report never ends the round
                        stats["hit_report_error"] = f"{type(exc).__name__}: {exc}"[:200]
            if "tap" in act:
                hold(set())
                sleep(0.15)
                send([{"key": act["tap"], "down": True}])
                sleep(TAP_DOWN_S)
                send([{"key": act["tap"], "down": False}])
                sleep(TAP_REST_S)
                continue
            decision_work.call('input', hold, set(act.get("hold", ())))
            next_frame()
        return "stopped"
    finally:
        if ring_step is not None and hasattr(ring_step, 'close'):
            ring_step.close()
        if remote_step is not None and hasattr(remote_step, 'close'):
            remote_step.close()
        read_retry.stopped()
        try:
            hold(set())
        finally:
            finish_evidence(clock(),outcome,last_stats)
            try:
                bot.save()
            except Exception:                        # noqa: BLE001
                pass
