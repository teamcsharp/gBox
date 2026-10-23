"""Local RE5 route evidence and an offline SVG report. No new game writes or hooks.

Run: py -m gbox.mercs.route_trace path/to/run.jsonl --output route-report
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import queue
import threading
import uuid

from . import tactical

COUNTERS = ("stuck", "routes_blocked", "routes_given_up", "crossings_avoided", "idle_breakouts", "route_replans", "nav_recoveries",
            "hits_taken", "mine_attempts", "mines_placed", "mine_detonations_observed", "mine_retreats_completed",
            "mine_pickups_avoided", "qte_presses")
BONUS_CORRELATION_S = 3.0
BONUS_PICKUP_RADIUS = 250.0       # same-floor proximity in game centimetres, at both observations
BONUS_MIN_CLOCK_GAIN = 25.0       # the smallest hourglass is 30 s; ordinary +5/+10 kill credits are insufficient
BONUS_ABSENCE_S = .25            # one transient missing actor sample is not a confirmed pickup


class Recorder:
    def __init__(self, log, *, atlas_root=None, title="BLUS30491", round_id=None):
        self.log = log
        self.round = round_id or uuid.uuid4().hex
        self.tracker = tactical.Tracker(title)
        self.stages = set()
        self.last_at = -math.inf
        self.counters = {}
        self.atlas = _AtlasWriter(atlas_root, title) if atlas_root is not None else None
        self.atlas_stages = set()
        self.acquired = set()
        self.bonus_context = None
        self.bonus_previous = None
        self.bonus_gains = []
        self.bonus_removals = {}
        self.bonus_missing = set()
        self.mine_event_seen = {}

    def _bonus_acquisitions(self, snap, frame, key, now):
        """Correlate clock credit and actor removal through the hourglass's destruction animation.

        Both orders occur in independently sampled RAM. Each gain credits only one nearby time actor;
        stable kill counters exclude kill bonuses, and a brief missing actor must remain absent.
        """
        player = (frame.get("player") or {}).get("pos")
        timer, kills = snap.get("timer"), snap.get("kills")
        valid = player is not None and type(timer) in (int, float) and math.isfinite(timer) \
            and type(kills) is int and kills >= 0
        if key != self.bonus_context or self.bonus_previous is not None \
                and (now < self.bonus_previous[0] or now-self.bonus_previous[0] > BONUS_CORRELATION_S):
            self.bonus_previous = None
            self.bonus_gains.clear()
            self.bonus_removals.clear()
            self.bonus_missing.clear()
        self.bonus_context = key
        if not valid:
            self.bonus_previous = None
            self.bonus_gains.clear()
            self.bonus_removals.clear()
            return {}
        bonuses = [b for b in frame.get("bonuses", ())
                   if b.get("kind") == "time" and b.get("id") is not None and b.get("pos")]
        present = {b["id"] for b in bonuses if not b.get("taken")}
        self.bonus_missing.difference_update(present)
        for actor in present:
            self.bonus_removals.pop(actor, None)
        # Keep a little room for the second absent sample; the two evidence event
        # timestamps themselves must still be no more than three seconds apart.
        lifetime = BONUS_CORRELATION_S + .75
        self.bonus_gains = [g for g in self.bonus_gains if now-g["at"] <= lifetime]
        self.bonus_removals = {a:r for a,r in self.bonus_removals.items()
                              if now-r["at"] <= lifetime}
        if self.bonus_previous is not None:
            previous_at, previous_timer, previous_kills = self.bonus_previous
            gain = timer-previous_timer
            if 0 < now-previous_at <= BONUS_CORRELATION_S and kills == previous_kills and gain >= BONUS_MIN_CLOCK_GAIN:
                nearby = {b["id"]: math.dist(player, b["pos"]) for b in bonuses
                          if math.dist(player, b["pos"]) <= BONUS_PICKUP_RADIUS}
                if nearby:
                    self.bonus_gains.append({"at": now, "seconds": gain, "kills": kills, "nearby": nearby})
        self.bonus_previous = (now, timer, kills)
        for bonus in bonuses:
            actor = bonus["id"]
            if not bonus.get("taken") or actor in self.bonus_missing:
                continue
            self.bonus_missing.add(actor)
            distance = math.dist(player, bonus["pos"])
            if (key, actor) not in self.acquired and distance <= BONUS_PICKUP_RADIUS:
                self.bonus_removals[actor] = {"at": now, "kills": kills, "distance": distance}
        confirmed = {}
        for gain in list(self.bonus_gains):
            candidates = [(gain["nearby"][actor], actor, removal) for actor, removal in self.bonus_removals.items()
                          if actor in gain["nearby"] and abs(gain["at"]-removal["at"]) <= BONUS_CORRELATION_S
                          and gain["kills"] == removal["kills"]
                          and now-removal["at"] >= BONUS_ABSENCE_S]
            if not candidates:
                continue
            _, actor, removal = min(candidates)
            self.bonus_gains.remove(gain)
            del self.bonus_removals[actor]
            self.acquired.add((key, actor))
            confirmed[actor] = {"transition": "actor_removed_with_clock_gain", "clock_gain_at": gain["at"],
                                "clock_gain_s": gain["seconds"], "actor_removed_at": removal["at"],
                                "kills_unchanged": gain["kills"], "player_distance_cm": removal["distance"]}
        return confirmed

    def finish(self, now, outcome, metrics=None, *, wait_s=2.):
        """Queue durable maps/review on the writer, bounded wait after input is released."""
        if self.atlas is None:
            return {}
        self.atlas.finish(now, outcome, metrics or {}, wait_s=wait_s)
        return dict(self.atlas.status)

    def observe(self, snap, bot, stats, now, keys, source, tap=None):
        try:
            self._observe(snap, bot, stats, now, keys, source, tap)
        except Exception as exc:
            stats["navigation_trace_errors"] = stats.get("navigation_trace_errors", 0) + 1
            stats["navigation_trace_error"] = str(exc)[:200]

    def _observe(self, snap, bot, stats, now, keys, source, tap=None):
        changed = {k: stats.get(k, 0) for k in COUNTERS
                   if stats.get(k, 0) > self.counters.get(k, 0)}
        mine_events = []
        for event in list(getattr(getattr(bot, "mines", None), "events", ()))[-128:]:
            if not isinstance(event, dict):
                continue
            signature = hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
            if signature not in self.mine_event_seen:
                mine_events.append((signature, dict(event)))
        # Before-decision samples also cover engine-owned QTE frames. Event samples bypass throttling.
        if not changed and not mine_events and source == "before_decision" and now - self.last_at < .5:
            return
        if not changed and not mine_events and source == "decision":
            return
        plan = tactical.take_plan(bot)
        frame = self.tracker.frame(snap, plan, "playing", now)
        ground = snap.get("ground_mines") or {}
        if isinstance(ground, dict):
            frame["mines"] = [{"actor": ptr, **dict(row)} for ptr,row in list(ground.items())[:256] if isinstance(row,dict)]
            frame["mine_snapshot_truncated"] = max(0,len(ground)-256)
        if mine_events:
            frame["mine_events"] = [event for _,event in mine_events]
        stage = frame["stage"]
        if stage and stage not in self.stages:
            self.log("navigation_stage", round_id=self.round, stage=self.tracker.stages[stage])
            self.stages.add(stage)
        if self.atlas is not None and snap.get("nav") is not None:
            mesh = snap["nav"]
            key = mesh.learning_sig
            atlas_round = self.round + ":" + key
            metadata = {"mode": stats.get("mercenaries_mode"), "character": stats.get("character"),
                        "stage_name": stats.get("stage_name"), "game_stage": stats.get("stage")}
            if key not in self.atlas_stages:
                if self.atlas.put(("begin", atlas_round, mesh, now, metadata)):
                    self.atlas_stages.add(key)
            observations = []
            acquisitions = self._bonus_acquisitions(snap, frame, key, now)
            for bonus in frame.get("bonuses", ()):
                if not bonus.get("pos"):
                    continue
                evidence = {"source": "ram_bonus_actor", "actor": bonus.get("id")}
                acquired = bonus.get("id") in acquisitions
                if acquired:
                    evidence.update(acquisitions[bonus["id"]])
                observations.append({"kind": bonus.get("kind", "unclassified_bonus"), "pos": bonus["pos"],
                                     "evidence": evidence, "acquired": acquired})
            for landmark in snap.get("landmarks") or ():
                # Title adapters must supply verified source/type evidence for object semantics.
                if isinstance(landmark, dict) and landmark.get("evidence"):
                    observations.append(dict(landmark))
            if (snap.get("prompt") or snap.get("stage_prompt")) and frame.get("player"):
                observations.append({"kind": "action_prompt", "pos": frame["player"]["pos"],
                                     "evidence": {"source": "ram_action_prompt", "token": snap.get("prompt"),
                                                  "stage_prompt": snap.get("stage_prompt")}})
            if key in self.atlas_stages:
                self.atlas.put(("sample", atlas_round, now, frame, tuple(sorted(keys)),
                                snap.get("prompt"), changed, observations))
            stats.update(self.atlas.status)
        self.log("navigation_event" if changed or mine_events else "navigation_sample", round_id=self.round,
                 frame=frame, inputs=sorted(keys), tap=tap, source=source,
                 prompt=snap.get("prompt"), stage_prompt=snap.get("stage_prompt"),
                 events=changed, diagnostics={k: stats.get(k) for k in
                     (*COUNTERS, "route", "phase", "sight", "aim", "bonus_target")},
                 nav_available=snap.get("nav") is not None)
        self.counters = {k: stats.get(k, 0) for k in COUNTERS}
        for signature,_ in mine_events:
            self.mine_event_seen[signature] = True
        while len(self.mine_event_seen) > 512:
            del self.mine_event_seen[next(iter(self.mine_event_seen))]
        self.last_at = now


class _AtlasWriter:
    """Disk and geometry serialization stay off the frame-synchronized input thread."""
    def __init__(self, root, title):
        self.root, self.title = root, title
        self.queue = queue.Queue(maxsize=512)
        self.status = {"navigation_atlas_queued": 0, "navigation_atlas_dropped": 0}
        self.thread = threading.Thread(target=self._run, name="mercs-navigation-atlas", daemon=True)
        self.thread.start()

    def put(self, message):
        try:
            self.queue.put_nowait(message)
            self.status["navigation_atlas_queued"] += 1
            return True
        except queue.Full:
            self.status["navigation_atlas_dropped"] += 1
            return False

    def finish(self, now, outcome, metrics, wait_s):
        # There are at most .5-second samples in the queue; never block gameplay to flush.
        # A full queue is a visible evidence gap and the writer still drains/ends naturally.
        self.closing = (now, outcome, metrics)
        self.thread.join(max(0., min(5., wait_s)))

    def _run(self):
        from .atlas import NavigationAtlas
        atlas = None
        try:
            atlas = NavigationAtlas(self.root, self.title)
            self.status["navigation_atlas_db"] = str(atlas.root / "atlas.sqlite")
            while True:
                try:
                    message = self.queue.get(timeout=.1)
                except queue.Empty:
                    if hasattr(self, "closing"):
                        break
                    continue
                try:
                    operation, *args = message
                    if operation == "begin":
                        round_id, mesh, now, metadata = args
                        atlas.begin(round_id, atlas.stage(mesh, metadata), now, metadata)
                    elif operation == "sample":
                        round_id, now, frame, keys, prompt, events, observations = args
                        atlas.sample(round_id, now, frame, inputs=keys, prompt=prompt, events=events, observations=observations)
                finally:
                    self.queue.task_done()
            now, outcome, metrics = self.closing
            for round_id in tuple(atlas.active):
                saved = atlas.finish(round_id, now, outcome, metrics)
                self.status["navigation_atlas_round"] = saved["json"]
                self.status["navigation_atlas_map"] = saved["map"]
                self.status["navigation_atlas_review"] = saved["review"]
                self.status.update(navigation_distance=saved["review"]["distance"],
                                   navigation_commanded_stationary_s=saved["review"]["commanded_stationary_s"],
                                   nav_oscillations=saved["review"]["oscillations"],
                                   navigation_target_changes=saved["review"]["target_changes"],
                                   navigation_bonuses_confirmed=saved["review"]["time_bonuses_acquired"],
                                   navigation_mine_placements=saved["review"]["mines"]["placements_verified"],
                                   navigation_mine_detonations=saved["review"]["mines"]["detonation_events_observed"],
                                   navigation_mine_retreats=saved["review"]["mines"]["retreats_completed"])
        except Exception as exc:
            self.status["navigation_atlas_error"] = str(exc)[:300]
        finally:
            if atlas is not None:
                atlas.close()


def report(path, output):
    """One SVG per mesh, with actual travel, planned routes and exact failure context in tooltips."""
    stages, frames, menus = {}, {}, []
    with Path(path).open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                # A crash can leave an incomplete last line; keep earlier evidence usable.
                continue
            if row.get("kind") == "navigation_stage":
                stages[row["stage"]["key"]] = row["stage"]
            elif row.get("kind") in ("navigation_sample", "navigation_event"):
                frames.setdefault(row["frame"].get("stage") or "unknown", []).append(row)
            elif row.get("kind") == "navigation_menu":
                menus.append(row)
    dest = Path(output)
    dest.mkdir(parents=True, exist_ok=True)
    summary = {"source": str(path), "stages": {}, "menus": menus}
    for index, (key, rows) in enumerate(frames.items()):
        stage = stages.get(key, {})
        pts = stage.get("points", [])
        positions = [r["frame"]["player"]["pos"] for r in rows if "player" in r["frame"]]
        if not positions:
            continue
        xs = pts[0::3] + [p[0] for p in positions]
        zs = pts[2::3] + [p[2] for p in positions]
        x0, z0 = min(xs)-100, min(zs)-100
        width, height = max(xs)-x0+100, max(zs)-z0+100
        body = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0} {z0} {width} {height}">',
                '<rect x="%s" y="%s" width="%s" height="%s" fill="#101820"/>' % (x0,z0,width,height)]
        walls = stage.get("walls", [])
        for a,b in zip(walls[::2], walls[1::2]):
            body.append(f'<path d="M {pts[a*3]} {pts[a*3+2]} L {pts[b*3]} {pts[b*3+2]}" stroke="#6b7785" stroke-width="8"/>')
        previous = None
        events = []
        for row in rows:
            f = row["frame"]
            if "player" not in f:
                previous = None
                continue
            p = f["player"]["pos"]
            route = f.get("plan", {}).get("route") or []
            if route:
                coords = " ".join(f'{q[0]},{q[2]}' for q in [p, *route])
                body.append(f'<polyline points="{coords}" fill="none" stroke="#f4c95d" stroke-opacity=".12" stroke-width="6"/>')
            if previous and previous[0] == row["round_id"]:
                q = previous[1]
                body.append(f'<path d="M {q[0]} {q[2]} L {p[0]} {p[2]}" stroke="#42d9f3" stroke-width="12"/>')
            previous = (row["round_id"], p)
            if row.get("events"):
                events.append(row)
                tip = html.escape(json.dumps(row, ensure_ascii=True))
                body.append(f'<circle cx="{p[0]}" cy="{p[2]}" r="45" fill="#ff554d"><title>{tip}</title></circle>')
        body.append('</svg>')
        filename = f'stage-{index}.svg'
        (dest / filename).write_text('\n'.join(body), encoding="utf-8")
        summary["stages"][key] = {"map": filename, "samples": len(rows), "events": events}
    (dest / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace")
    parser.add_argument("--output", default="route-report")
    args = parser.parse_args()
    report(args.trace, args.output)
