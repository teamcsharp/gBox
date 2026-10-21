"""The Mercenaries engine's round loop (docs/mercenaries_engine.md, section 7): what the deployment playbook
(gbox/mercs_bot.py) calls while a round is up.

    from gbox.mercs import engine as E
    why = E.play_round(prof, m, send, stopped, stats, lessons)     # "round" | "lost" | "stopped"

prof: the title's mercs block (+ map_id, platform); m: the session's RAM, read only (rd(addr, n)); send(rows): gBox pad
events [{"key", "down"}]; stopped(): the caller's stop flag; stats: the live dict the watch panel shows (timer and
ram_progress keep moving while the round runs); lessons: entry -> lessons.append(map_id, entry, run=...) or None.

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


def play_round(prof, m, send, stopped, stats: dict, lessons=None, sleep=time.sleep, clock=time.time,
               tick_s: float = 0.05, driver=None, brain=None, learn_dir=None) -> str:
    drv = driver or D.load(prof)
    bot = brain or drv.brain(m, stats, clock, learn_dir=learn_dir)
    pp = PromptPresser(drv.prompt_source(m, stats), keys=drv.prompt_keys, stats=stats,
                       unknown=getattr(drv, "prompt_unknown", (LookupError,)))
    held: set = set()
    gone_since = lost_since = None
    hits_seen = stats.get("hits_taken", 0)
    progress = 0

    def hold(keys):
        nonlocal held
        rows = [{"key": k, "down": False} for k in sorted(held - keys)] + \
               [{"key": k, "down": True} for k in sorted(keys - held)]
        if rows:
            send(rows)
        held = set(keys)

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
                for chord in chords:
                    send([{"key": k, "down": True} for k in chord])
                    sleep(0.12 if len(chords) == 1 else 0.06)
                    send([{"key": k, "down": False} for k in chord])
                    if len(chords) > 1:
                        sleep(0.04)
                sleep(0.15)
                continue
            act = bot.tick(snap)
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
            sleep(tick_s)
        return "stopped"
    finally:
        hold(set())
        try:
            bot.save()
        except Exception:                            # noqa: BLE001
            pass
