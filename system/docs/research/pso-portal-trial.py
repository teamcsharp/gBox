"""portal-trial - one controller-only trial of Pioneer 2's warp pad, with a hash-chained receipt.

The handoff (``PSO_EPISODE_I_CAMPAIGN_AUTOPLAYER_MANDATE.md``) asks for a *verified* town-portal identity and
activation sequence before any more campaign runs, and then for T0: town -> Forest 1, ten times, controller-only,
no memory warp. This script is the one-trial primitive that T0 will repeat, and it deliberately does not write
memory or call any native travel helper:

    * it walks to Pioneer 2's pad at ``(360,26)`` with measured controller taps (``gbox.pso_bounded.ProbeMotion``);
    * it presses the interaction button **once** at a sequence of measured distances (the handoff's round-89
      counterexample was "A at 1.6 and 2.6 units and walking through it produced no verified warp");
    * after every press it samples the game's own transition state (floor, phase, ``travelling``, travel
      destination, player, entity count) for a bounded window, so "nothing happened" and "a transition began but
      did not finish" are different results;
    * it writes every step to a hash-chained JSONL ledger plus a summary JSON, and verifies the chain before it
      reports success.

A trial succeeds only when the game itself reports the area change (``FLOOR`` 0 -> 1) with the stage-flag array
unchanged, which is what "controller-only, no progression writes" means in observable terms.

    python pso-portal-trial.py trial --via 186,179 209,164 227,100 255,-5 340,50 360,26 --seconds 420
    python pso-portal-trial.py freeze
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import struct
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import pso_bounded as B                 # noqa: E402
from gbox import pso_evidence as E                # noqa: E402

BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:8765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate")
OPERATOR_FLAG = pathlib.Path(r"D:\gBox\pso-ds\operator-playing.flag")
LOCK = OUT / "portal-trial.lock"

PAD = (360.0, 26.0)
PHASE = 0x804FE120
FLOOR = 0x805D5FC0
EPISODE = 0x805D6060
DIFFICULTY = 0x805D5550
TRAVELLING = 0x805D49B8
TRAVEL_STATE = 0x80515BA0
TRAVEL_DESTINATION = TRAVEL_STATE + 0xC
STAGE_FLAGS = 0x80515CC8
STAGE_FLAGS_LEN = 576
ROOM = 0x28

DIFFICULTY_NAMES = {0: "Normal", 1: "Hard", 2: "VeryHard", 3: "Ultimate"}


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {str(message).encode('ascii', 'replace').decode('ascii')}", flush=True)


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path, payload=None, method="GET", timeout=60):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + token(), "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                       # noqa: BLE001
        return {"err": type(exc).__name__, "detail": str(exc)}


def live() -> list:
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return [row for row in rows if row.get("state") in ("running", "starting")]


def claim() -> bool:
    OUT.mkdir(parents=True, exist_ok=True)
    if LOCK.exists():
        try:
            holder = json.loads(LOCK.read_text(encoding="utf-8")).get("pid")
            age = time.time() - LOCK.stat().st_mtime
        except (OSError, ValueError):
            holder, age = None, 1e9
        if holder:
            try:
                os.kill(int(holder), 0)
                if age < 30:
                    log(f"another portal trial holds the lock (pid {holder})")
                    return False
            except OSError:
                pass
    LOCK.write_text(json.dumps({"pid": os.getpid(), "at": time.time()}), encoding="utf-8")
    return True


def release() -> None:
    try:
        LOCK.unlink()
    except OSError:
        pass


class Probe:
    """The bounded reads the receipt needs. Every field has a documented source (see gbox.pso_ram)."""

    def __init__(self, world) -> None:
        self.world = world

    def u8(self, address):
        raw = self.world.read(address, 1)
        return raw[0] if len(raw) == 1 else None

    def u32(self, address):
        raw = self.world.read(address, 4)
        return struct.unpack(">I", raw)[0] if len(raw) == 4 else None

    def flags(self):
        raw = self.world.read(STAGE_FLAGS, STAGE_FLAGS_LEN)
        if len(raw) != STAGE_FLAGS_LEN:
            return None, None
        return hashlib.sha256(raw).hexdigest(), [sum(bin(byte).count("1") for byte in raw[g * 32:(g + 1) * 32])
                                                 for g in range(18)]

    def state(self) -> dict:
        full = self.world.observe() or {}
        player = full.get("player") or {}
        digest, bits = self.flags()
        return {
            "player": player,
            "entities": len(full.get("entities") or []),
            "floor": self.u32(FLOOR),
            "episode": (self.u32(EPISODE) or 0) + 1 if self.u32(EPISODE) is not None else None,
            "phase": self.u8(PHASE),
            "difficulty": self.u32(DIFFICULTY),
            "travelling": bool(self.u32(TRAVELLING)),
            "destination": self.u32(TRAVEL_DESTINATION),
            "flags_sha": digest,
            "flags_bits": bits,
        }

    def slim(self) -> dict:
        """The transition-relevant subset for a fast poll (player, floor, phase, travelling, destination)."""
        return {
            "player": (self.world.observe(player_only=True) or {}).get("player") or {},
            "floor": self.u32(FLOOR),
            "phase": self.u8(PHASE),
            "travelling": bool(self.u32(TRAVELLING)),
            "destination": self.u32(TRAVEL_DESTINATION),
        }


def transition_snapshot(probe: Probe, prefix: str = "") -> dict:
    state = probe.state()
    return {"digest": E.digest({k: v for k, v in state.items() if k != "player"}) + prefix,
            "player": state["player"], "extra": {"floor": state["floor"], "phase": state["phase"],
                                                 "difficulty": state["difficulty"], "travelling": state["travelling"],
                                                 "destination": state["destination"], "entities": state["entities"],
                                                 "flags_sha": state["flags_sha"], "flags_bits": state["flags_bits"]}}


def poll_transition(probe: Probe, ledger: E.Ledger, *, seconds: float) -> dict:
    """Watch the game's own transition state for a bounded window after one press.

    Returns the first sample that shows the area change, or the full series when nothing changes. The series is
    recorded in the ledger so a claim ("the press did nothing") is backed by a measured window, not by one read.
    """
    deadline = time.monotonic() + seconds
    series, changed, first = [], None, None
    last = None
    while time.monotonic() < deadline:
        sample = probe.slim()
        key = (sample["floor"], sample["travelling"], sample["destination"], sample["phase"],
               (sample["player"] or {}).get("room"))
        if key != last:
            series.append({"t": round(time.monotonic(), 3), **sample})
            last = key
            if sample["floor"] not in (0, None) or sample["travelling"] or (sample["destination"] or 0) > 0:
                changed = sample
                if first is None:
                    first = sample
        if changed is not None and not sample["travelling"] and sample["floor"] == 1 and sample["player"]:
            break
        time.sleep(0.12)
    return {"changed": changed, "series": series[:40], "final": probe.slim()}


def walk_to(world, motion, ledger: E.Ledger, probe: Probe, target, *, tolerance: float, seconds: float,
            label: str) -> dict:
    """Bounded probe-walk toward one coordinate. Returns the last measured position and the distance closed."""
    deadline = time.monotonic() + seconds
    start = None
    actions = 0
    while time.monotonic() < deadline:
        player = ((world.observe(player_only=True) or {}).get("player")) or {}
        if not player:
            break
        here = (float(player.get("x") or 0), float(player.get("z") or 0))
        start = start or here
        if math.dist(here, target) <= tolerance:
            break
        action = motion.step({"x": here[0], "z": here[1], "heading_deg": player.get("heading_deg")},
                             target, label)
        if action is None:
            break
        before = {"digest": None, "player": player}
        world.act(action, time.monotonic() + 2.0)
        after_player = ((world.observe(player_only=True) or {}).get("player")) or {}
        learn = getattr(motion, "learn", None)
        if callable(learn):
            learn(action, player, after_player)
        landed = (float(after_player.get("x") or 0), float(after_player.get("z") or 0))
        closed = math.dist(here, target) - math.dist(landed, target)
        ledger.record("tick", action=action.as_dict(), before=before,
                      after={"digest": None, "player": after_player,
                             "extra": {"floor": probe.u32(FLOOR)}},
                      extra={"label": label, "moved": round(math.dist(here, landed), 2),
                             "closed": round(closed, 2),
                             "distance": round(math.dist(landed, target), 2)})
        actions += 1
        time.sleep(0.45 if action.kind == "press" else 0.10)
        if actions % 20 == 0:
            log(f"  {label}: {actions} actions, at ({here[0]:.0f},{here[1]:.0f}), "
                f"d={math.dist(here, target):.0f}")
    player = ((world.observe(player_only=True) or {}).get("player")) or {}
    here = (float(player.get("x") or 0), float(player.get("z") or 0))
    return {"label": label, "actions": actions, "at": here,
            "distance": round(math.dist(here, target), 2), "room": player.get("room")}


def freeze(probe: Probe, session: str, row: dict) -> dict:
    state = probe.state()
    receipt = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "session": session,
               "rom": {"catalog_id": "436e0bb84d5337d1",
                       "title": "Phantasy Star Online Episode I & II Plus (USA)", "serial": "GPOE8P",
                       "executable": "PsoV3.dol",
                       "dol_sha256": "1f80fb82b41c05b26b6d0545b1ba9c0aa60b52e6589cf32fbb2ffe644692a61a",
                       "adapter": row.get("adapter")},
               "mode": {"kind": "offline single-player", "episode": state["episode"]},
               "difficulty": {"index": state["difficulty"],
                              "name": DIFFICULTY_NAMES.get(state["difficulty"])},
               "floor": state["floor"], "phase": state["phase"],
               "stage_flags": {"sha256": state["flags_sha"], "set_bits": state["flags_bits"]},
               "player": state["player"], "entity_count": state["entities"]}
    return receipt


def trial(args) -> int:
    if not claim():
        return 3
    try:
        rows = live()
        if args.session:
            session = args.session
            row = next((r for r in rows if r.get("session_id") == session), {})
        elif rows:
            row = rows[0]
            session = row["session_id"]
        else:
            log("no live session; launch the game first")
            return 2
        OUT.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        ledger = E.Ledger(OUT / f"portal-trial-{stamp}.jsonl", run=f"portal-trial-{stamp}")
        world = B.SessionWorld(session, call, worker=session.split("-")[0])
        probe = Probe(world)
        operator = B.OperatorGuard(OPERATOR_FLAG)
        motion = B.ProbeMotion(arrive=min(4.0, max(2.0, args.tolerance * 0.4)),
                               lock_points=load_lock_points(), min_gain=1.0)

        start = freeze(probe, session, row)
        log(f"session {session}: floor {start['floor']} difficulty {start['difficulty']} "
            f"({start['difficulty']['name']}) at {start['player'].get('x')},{start['player'].get('z')} "
            f"room {start['player'].get('room')}")

        waypoint_reports = []
        points = [tuple(float(v) for v in item.replace(",", " ").split()) for item in args.via]
        for index, point in enumerate(points):
            if operator.active(time.monotonic()):
                log("operator holds the pad - standing down")
                world.release()
                ledger.record("preempted", note="operator flag appeared during the approach")
                return 4
            report = walk_to(world, motion, ledger, probe, point, tolerance=args.tolerance,
                             seconds=args.per_hop, label=f"hop {index + 1}/{len(points)}")
            waypoint_reports.append(report)
            log(f"hop {index + 1}/{len(points)} {tuple(round(v) for v in point)}: "
                f"d={report['distance']} at {tuple(round(v) for v in report['at'])} room {report['room']} "
                f"({report['actions']} actions)")

        # Stage the presses: one interaction press per measured distance, closest last, with a walk-through as the
        # final fallback. This is the handoff's "test hypotheses one at a time" with the distances made explicit.
        stages = [float(v) for v in (args.stages or "").split(",") if v.strip()]
        presses = []
        for stage in stages:
            if operator.active(time.monotonic()):
                log("operator holds the pad - standing down mid-experiment")
                world.release()
                ledger.record("preempted", note="operator flag appeared during the presses")
                return 4
            here = ((world.observe(player_only=True) or {}).get("player")) or {}
            distance = math.hypot(float(here.get("x") or 0) - PAD[0], float(here.get("z") or 0) - PAD[1])
            if distance > stage + 0.5:
                report = walk_to(world, motion, ledger, probe, PAD, tolerance=max(2.0, stage - 1.0),
                                 seconds=args.per_stage, label=f"approach {stage:.0f}")
                waypoint_reports.append(report)
                distance = report["distance"]
            here = ((world.observe(player_only=True) or {}).get("player")) or {}
            distance = math.hypot(float(here.get("x") or 0) - PAD[0], float(here.get("z") or 0) - PAD[1])
            before = transition_snapshot(probe, "press")
            log(f"press at {distance:.1f} units from the pad (stage {stage:.0f}): A once")
            world.act(B.press("a", f"activate the pad at {distance:.1f} units"), time.monotonic() + 3.0)
            result = poll_transition(probe, ledger, seconds=args.poll_seconds)
            ledger.record("press", action=B.press("a", f"activate the pad ({distance:.1f} units)").as_dict(),
                          before=before, after=transition_snapshot(probe, "after"),
                          note=f"stage {stage:.0f}", extra={"distance": round(distance, 2),
                                                            "series": result["series"][:12]})
            presses.append({"stage": stage, "distance": round(distance, 2),
                            "changed": bool(result["changed"]),
                            "final": result["final"], "series": result["series"]})
            log(f"  result: {'AREA CHANGE ' + str(result['changed']) if result['changed'] else 'no change'}")
            if result["changed"] and result["final"].get("floor") == 1 and not result["final"].get("travelling"):
                break
        # Walking through the pad is the last controller-only hypothesis in the handoff's round-89 counterexample.
        if not any(press["changed"] for press in presses):
            for target in ((360.0, -40.0), (380.0, 26.0), (340.0, 26.0)):
                if operator.active(time.monotonic()):
                    world.release()
                    return 4
                before = transition_snapshot(probe, "through")
                report = walk_to(world, motion, ledger, probe, target, tolerance=4.0, seconds=args.per_stage,
                                 label=f"through {tuple(round(v) for v in target)}")
                waypoint_reports.append(report)
                result = poll_transition(probe, ledger, seconds=args.poll_seconds)
                ledger.record("walk-through", before=before, after=transition_snapshot(probe, "after"),
                              note=f"walk through toward {target}", extra={"series": result["series"][:12]})
                presses.append({"stage": "through", "target": target, "changed": bool(result["changed"]),
                                "final": result["final"], "series": result["series"]})
                log(f"  walk-through {tuple(round(v) for v in target)}: "
                    f"{'AREA CHANGE' if result['changed'] else 'no change'} (d={report['distance']})")
                if result["changed"] and result["final"].get("floor") == 1 and not result["final"].get("travelling"):
                    break

        # Wait for a transition, if one started, to settle, then record the arrival receipt.
        arrival, settled = None, None
        deadline = time.monotonic() + max(0.0, args.arrive_seconds)
        while time.monotonic() < deadline:
            sample = probe.slim()
            if sample["floor"] == 1 and not sample["travelling"] and sample["player"]:
                arrival = probe.state()
                break
            time.sleep(0.25)
        success = bool(arrival and arrival["floor"] == 1 and arrival["flags_sha"] == start["flags_sha"])
        if arrival:
            settled = {"floor": arrival["floor"], "phase": arrival["phase"],
                       "room": arrival["player"].get("room"), "at": (arrival["player"].get("x"),
                                                                    arrival["player"].get("z")),
                       "entities": arrival["entities"], "flags_sha": arrival["flags_sha"],
                       "flags_unchanged": arrival["flags_sha"] == start["flags_sha"]}

        ok, reason = ledger.verify()
        summary = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "session": session, "start": start,
            "route": waypoint_reports, "presses": presses, "arrival": settled,
            "success": success, "ledger": str(ledger.path), "ledger_verified": ok,
            "ledger_reason": reason, "operator_present": operator.active(time.monotonic()),
        }
        summary_path = OUT / f"portal-trial-{stamp}-summary.json"
        summary_path.write_text(json.dumps(summary, indent=1), encoding="utf-8")
        log(f"success={success} ledger_verified={ok} summary={summary_path}")
        if settled:
            log(f"arrival: floor {settled['floor']} room {settled['room']} at {settled['at']} "
                f"entities {settled['entities']} flags_unchanged {settled['flags_unchanged']}")
        return 0 if success else 1
    finally:
        try:
            rows = live()
        except Exception:                                           # noqa: BLE001
            rows = []
        release()


LOCK_POINTS_FILE = pathlib.Path(r"D:\gBox\pso-ds\lock-points.json")


def load_lock_points():
    try:
        rows = json.loads(LOCK_POINTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [(float(row["x"]), float(row["z"])) for row in rows
            if isinstance(row, dict) and "x" in row and "z" in row]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="one controller-only trial of the Pioneer 2 warp pad")
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("freeze", help="write the state receipt (ROM, mode, difficulty, flags) and exit")
    trial_parser = sub.add_parser("trial", help="walk to the pad, press A at measured distances, record the result")
    trial_parser.add_argument("--via", nargs="+", metavar="X,Z", required=True)
    trial_parser.add_argument("--stages", default="40,25,15,10,6,2",
                              help="distances (units) at which to stop and press A once, closest last")
    trial_parser.add_argument("--tolerance", type=float, default=9.0)
    trial_parser.add_argument("--per-hop", type=float, default=75.0)
    trial_parser.add_argument("--per-stage", type=float, default=45.0)
    trial_parser.add_argument("--seconds", type=float, default=420.0)
    trial_parser.add_argument("--poll-seconds", type=float, default=6.0)
    trial_parser.add_argument("--arrive-seconds", type=float, default=30.0)
    trial_parser.add_argument("--session", default="")
    args = parser.parse_args(argv)
    if args.mode == "freeze":
        rows = live()
        if not rows:
            print("no live session")
            return 2
        row = rows[0]
        world = B.SessionWorld(row["session_id"], call, worker=row["session_id"].split("-")[0])
        receipt = freeze(Probe(world), row["session_id"], row)
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"freeze-{time.strftime('%Y%m%d-%H%M%S')}.json"
        path.write_text(json.dumps(receipt, indent=1), encoding="utf-8")
        print(json.dumps(receipt, indent=1))
        return 0
    return trial(args)


if __name__ == "__main__":
    raise SystemExit(main())

