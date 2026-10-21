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

from . import driver as D
from .reactions import PromptPresser

READY = False
ROUND_GONE_S, LOST_S = 1.0, 20.0
TAP_DOWN_S, TAP_REST_S = 0.25, 0.4
FRAME_WAIT_S, FRAME_POLL_S = 0.05, 0.002      # frame sync: wait for the game's next frame this long, polling this often
MASH_DOWN_S, MASH_UP_S = 0.045, 0.035         # a mash (a grab's SHAKE OFF): each press down / up this long - two game
                                              # frames down, one up, so every press is a new one to the game


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
               tick_s: float = 0.05, driver=None, brain=None, learn_dir=None, tactical=None, damage=None) -> str:
    drv = driver or D.load(prof)
    if damage is not None:
        damage.bind(drv, prof)
    bot = brain or drv.brain(m, stats, clock, learn_dir=learn_dir)
    pp = PromptPresser(drv.prompt_source(m, stats), keys=drv.prompt_keys, stats=stats,
                       unknown=getattr(drv, "prompt_unknown", (LookupError,)))
    held: set = set()
    gone_since = lost_since = None
    hits_seen = stats.get("hits_taken", 0)
    progress = 0
    frame_fn = getattr(drv, "frame", None)
    clock_frame = [None]                              # the game's frame (driver.frame) at the last decision
    lat = Latency(stats)

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
                pass

    try:
        while not stopped():
            now = clock()
            snap = drv.snapshot(m)
            where = drv.screen(m, snap)
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
            if damage is not None:
                damage.after(snap, where, now)
            if tactical is not None:                  # the tactical map: who is where, what the bot means to do
                try:
                    tactical(snap, bot, where)
                except Exception:                     # noqa: BLE001 - the map never costs the round a tick
                    pass
            if where not in D.IN_ROUND:
                hold(set())
                if where == "loading" or not snap.get("player"):
                    lost_since = lost_since or now
                    if now - lost_since > LOST_S:
                        return "lost"
                else:
                    gone_since = gone_since or now
                    if now - gone_since > ROUND_GONE_S:
                        log("round", stats={k: v for k, v in stats.items() if isinstance(v, (int, float, str))})
                        return "round"
                sleep(0.1)
                continue
            gone_since = lost_since = None
            progress += 1
            stats.update(drv.progress(snap))
            stats["ram_progress"] = progress
            chords = pp.step(now, ok=lambda b: bot.prompt_ok(b, snap, now))
            if chords:                                # the game asks for a button: let go, press it
                hold(set())
                mash = getattr(pp, "mashing", False)  # a grab: as fast as the game takes new presses (30 a second)
                for chord in chords:
                    send([{"key": k, "down": True} for k in chord])
                    sleep(MASH_DOWN_S if mash else (0.12 if len(chords) == 1 else 0.06))
                    send([{"key": k, "down": False} for k in chord])
                    if mash or len(chords) > 1:
                        sleep(MASH_UP_S if mash else 0.04)
                if not mash:
                    sleep(0.15)
                continue
            act = bot.tick(snap)
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
        try:
            hold(set())
        finally:
            try:
                bot.save()
            except Exception:                        # noqa: BLE001
                pass
