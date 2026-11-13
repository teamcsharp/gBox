"""calibrate - measure PSO's input primitives before any steering code trusts them.

Round 1's live calibrations disagreed with each other and with the handoff (`up` read dead in four of five passes, a
tap appeared to swing the heading by 60-170 degrees), and the most likely reason is momentum: the position was read
immediately after the input job acknowledged, while the character was still moving. This probe fixes that by
**settling** after every action - polling until two consecutive reads agree - and then taking the measurement.

It measures, per direction key:

* five single taps (down+up in one job), each with its own settled before/after sample;
* one five-tap batch, to see whether repeated taps in one batch accumulate or are eaten;
* one hold (down, wait, release) at 0.30 s, for units per second.

and reports medians with spreads instead of a single number. `heading_deg` is recorded for every sample so it is
possible to say whether it tracks the character's facing or the camera's.

Usage:
    python pso-calibrate.py --samples 5
    python pso-calibrate.py --samples 5 --json D:\\gBox\\pso-ds\\bounded\\calibration.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:18765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
OUT = pathlib.Path(r"D:\gBox\pso-ds\bounded")
LOCK = OUT / "calibrate.lock"
LOCK_STALE_S = 30.0
KEYS = ("up", "down", "left", "right")


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {str(message).encode('ascii', 'replace').decode('ascii')}", flush=True)


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path, payload=None, method="GET", timeout=30):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + token(), "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                       # noqa: BLE001
        return {"err": type(exc).__name__}


def live_session() -> str:
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    live = [row for row in rows if row.get("state") in ("running", "starting")]
    return live[0]["session_id"] if live else ""


def claim() -> bool:
    OUT.mkdir(parents=True, exist_ok=True)
    if LOCK.exists() and (time.time() - LOCK.stat().st_mtime) < LOCK_STALE_S:
        log("another calibrate run holds the lock")
        return False
    LOCK.write_text(str(time.time()), encoding="utf-8")
    return True


def release() -> None:
    try:
        LOCK.unlink()
    except OSError:
        pass


class Pad:
    """The minimum needed for measurement: read the player, apply one job, release."""

    def __init__(self, sid: str) -> None:
        self.sid = sid
        self.worker = sid.split("-")[0]
        self.sent = 0

    def player(self) -> dict:
        state = call(f"/api/sessions/{self.sid}/rpc", {"op": "state", "args": {}}, "POST")
        return (state if isinstance(state, dict) else {}).get("player") or {}

    def job(self, events: list) -> str:
        started = time.monotonic()
        job = call("/api/jobs", {"tool": "session_op", "require_worker": self.worker,
                                 "input": {"session_id": self.sid, "op": "send_input",
                                           "args": {"events": events}}}, "POST")
        job_id = job.get("id") if isinstance(job, dict) else None
        if not job_id:
            return "no-job"
        while time.monotonic() - started < 10:
            row = call("/api/jobs/" + job_id)
            if isinstance(row, dict) and row.get("state") in ("succeeded", "failed", "cancelled"):
                return str(row.get("state"))
            time.sleep(0.03)
        return "timeout"

    def tap(self, key: str) -> str:
        self.sent += 1
        return self.job([{"key": key, "down": True}, {"key": key, "down": False}])

    def batch(self, key: str, count: int) -> str:
        self.sent += 1
        events = []
        for _ in range(count):
            events += [{"key": key, "down": True}, {"key": key, "down": False}]
        return self.job(events)

    def hold(self, key: str, seconds: float) -> str:
        self.sent += 1
        state = self.job([{"key": key, "down": True}])
        time.sleep(seconds)
        self.job([{"key": key, "down": False} for key in KEYS])
        return state

    def release(self) -> None:
        self.job([{"key": key, "down": False} for key in KEYS])


class Meter:
    """Read the player only once it has stopped moving, so a measurement is not momentum."""

    def __init__(self, pad: Pad, *, settle_s: float = 1.2, settle_step: float = 0.08) -> None:
        self.pad = pad
        self.settle_s = settle_s
        self.settle_step = settle_step

    def still(self) -> dict:
        deadline = time.monotonic() + self.settle_s
        previous = self.pad.player()
        while time.monotonic() < deadline:
            time.sleep(self.settle_step)
            current = self.pad.player()
            if abs(float(current.get("x") or 0) - float(previous.get("x") or 0)) < 0.4 \
                    and abs(float(current.get("z") or 0) - float(previous.get("z") or 0)) < 0.4:
                return current
            previous = current
        return previous


def sample(meter: Meter, action) -> dict:
    before = meter.still()
    state = action()
    after = meter.still()
    dx = float(after.get("x") or 0) - float(before.get("x") or 0)
    dz = float(after.get("z") or 0) - float(before.get("z") or 0)
    heading = ((float(after.get("heading_deg") or 0) - float(before.get("heading_deg") or 0) + 540.0)
               % 360.0) - 180.0
    return {"job": state, "dx": round(dx, 3), "dz": round(dz, 3),
            "moved": round((dx * dx + dz * dz) ** 0.5, 3), "heading": round(heading, 1),
            "from": [round(float(before.get("x") or 0), 1), round(float(before.get("z") or 0), 1)],
            "to": [round(float(after.get("x") or 0), 1), round(float(after.get("z") or 0), 1)]}


def summarise(rows: list) -> dict:
    if not rows:
        return {}
    moved = [row["moved"] for row in rows]
    heading = [row["heading"] for row in rows]
    dx = statistics.median(row["dx"] for row in rows)
    dz = statistics.median(row["dz"] for row in rows)
    return {"n": len(rows), "moved_median": round(statistics.median(moved), 2),
            "moved_min": round(min(moved), 2), "moved_max": round(max(moved), 2),
            "dx_median": round(dx, 2), "dz_median": round(dz, 2),
            "heading_median": round(statistics.median(heading), 1),
            "heading_min": round(min(heading), 1), "heading_max": round(max(heading), 1),
            "direction": [round(dx, 2), round(dz, 2)] if (dx * dx + dz * dz) ** 0.5 > 0.4 else None}


def run(args) -> int:
    sid = args.session or live_session()
    if not sid:
        log("no live session")
        return 2
    if not claim():
        return 3
    pad = Pad(sid)
    meter = Meter(pad, settle_s=args.settle)
    report = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "session": sid, "samples": args.samples,
              "taps": {}, "batch": {}, "hold": {}, "player_at_start": meter.still()}
    try:
        for key in args.keys:
            rows = [sample(meter, lambda key=key: pad.tap(key)) for _ in range(args.samples)]
            report["taps"][key] = {"samples": rows, **summarise(rows)}
            log(f"tap {key:5s}: moved {report['taps'][key]['moved_median']:5.2f} "
                f"range [{report['taps'][key]['moved_min']:.2f},{report['taps'][key]['moved_max']:.2f}]  "
                f"dir {report['taps'][key]['direction']}  "
                f"heading {report['taps'][key]['heading_median']:+.1f} "
                f"[{report['taps'][key]['heading_min']:+.1f},{report['taps'][key]['heading_max']:+.1f}]")
        if args.batch:
            for key in args.keys:
                row = sample(meter, lambda key=key: pad.batch(key, args.batch))
                report["batch"][key] = {**row, "per_tap": round(row["moved"] / args.batch, 2),
                                        "taps": args.batch}
                log(f"batch {key:5s} x{args.batch}: moved {row['moved']:5.2f} "
                    f"({row['moved'] / args.batch:.2f}/tap) heading {row['heading']:+.1f}")
        for key in args.hold_keys:
            row = sample(meter, lambda key=key: pad.hold(key, args.hold_seconds))
            report["hold"][key] = {**row, "seconds": args.hold_seconds,
                                   "units_per_s": round(row["moved"] / args.hold_seconds, 2)}
            log(f"hold {key:5s} {args.hold_seconds:.2f}s: moved {row['moved']:5.2f} "
                f"({report['hold'][key]['units_per_s']:.2f}/s) heading {row['heading']:+.1f}")
    finally:
        pad.release()
        release()
    report["player_at_end"] = meter.still()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = pathlib.Path(args.json) if args.json else OUT / f"calibration-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    log(f"wrote {path}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="measure PSO's input primitives")
    parser.add_argument("--session", default="")
    parser.add_argument("--keys", nargs="+", default=list(KEYS))
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--batch", type=int, default=5, help="taps per batch (0 disables)")
    parser.add_argument("--hold-keys", nargs="*", default=["up"])
    parser.add_argument("--hold-seconds", type=float, default=0.30)
    parser.add_argument("--settle", type=float, default=1.2)
    parser.add_argument("--json", default="")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
