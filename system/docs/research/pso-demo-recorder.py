"""demo-recorder - record the operator's PSO play as synchronized input + RAM state, then segment it.

The operator's instruction (2026-11-13, "Map-First Learning Architecture"): whenever they take the controller the
bot must yield and **record a synchronized trace** - frames/timestamps, controller buttons and sticks, player map
coordinates/heading/animation/room, nearby doors/switches/enemies and their RAM state, progression flags, and the
changes each action caused - then segment the demonstration into reusable skills with success criteria and a
version history.

This tool is the capture half of that. It is a passive observer: it sends no input and writes no memory.

Input channels (both are needed because the operator can drive either way on this node):

* **XInput** - the physical pad, polled on all four slots through ``xinput1_4``. A controller that reaches the game
  through the emulator's ``XInput/0/Gamepad`` binding shows up here.
* **Keyboard** - the binding gBox writes into Dolphin's ``GCPadNew.ini`` (A=X, B=Z, X=S, Y=A, Z=E, Start=RETURN,
  stick=arrows, C-stick=K/I/J/L, L=Q, R=W, D-pad=T/G/F/H, ...). The app's synthetic presses and an operator on the
  keyboard both land in the global key state, which is what this polls.

State sampling is split so the trace stays dense without flooding the worker: the player record every tick, the full
entity census a few times a second, and the movement-wide facts (floor, episode, difficulty, transition, stage-flag
digest) once a second.

Outputs (under ``--out``, default ``D:\\gBox\\pso-ds\\mandate``):

* ``demo-<stamp>.jsonl``   one line per event: input changes, samples, derived events (room change, flag change, ...)
* ``demo-<stamp>.json``    the analysis: segments with start/end state, classification, deltas, route summary
* ``demo-<stamp>-route.jsonl``  the player positions only, replayable by ``pso-bounded.py walk --route-file``
* ``skills.json``          the versioned skill store, appended (never rewritten) with each segment

Usage:

    python pso-demo-recorder.py --seconds 120
    python pso-demo-recorder.py --seconds 0            # until Ctrl+C
    python pso-demo-recorder.py --analyse demo-....jsonl
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import pathlib
import struct
import sys
import threading
import time
import urllib.request
from ctypes import wintypes

BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:8765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate")
OPERATOR_FLAG = pathlib.Path(r"D:\gBox\pso-ds\operator-playing.flag")

PHASE = 0x804FE120
FLOOR = 0x805D5FC0
EPISODE = 0x805D6060
DIFFICULTY = 0x805D5550
TRAVELLING = 0x805D49B8
TRAVEL_DESTINATION = 0x80515BA0 + 0xC
STAGE_FLAGS = 0x80515CC8
STAGE_FLAGS_LEN = 576

# The Dolphin GCPad1 bindings gBox writes (GCPadNew.ini), as virtual-key codes polled with GetAsyncKeyState.
BUTTON_KEYS = {
    "A": 0x58, "B": 0x5A, "X": 0x53, "Y": 0x41, "Z": 0x45, "Start": 0x0D,
    "StickUp": 0x26, "StickDown": 0x28, "StickLeft": 0x25, "StickRight": 0x27,
    "CUp": 0x4B, "CDown": 0x49, "CLeft": 0x4A, "CRight": 0x4C,
    "L": 0x51, "R": 0x57,
    "DUp": 0x54, "DDown": 0x47, "DLeft": 0x46, "DRight": 0x48,
}
XINPUT_BUTTONS = {0x0001: "DUp", 0x0002: "DDown", 0x0004: "DLeft", 0x0008: "DRight", 0x0010: "Start",
                  0x0020: "Z", 0x0040: "L", 0x0080: "R", 0x0100: "A", 0x0200: "B", 0x0400: "X", 0x0800: "Y"}
XINPUT_SLOTS = 4


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {str(message).encode('ascii', 'replace').decode('ascii')}", flush=True)


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path, payload=None, method="GET", timeout=25):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + token(), "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                     # noqa: BLE001
        return {"err": type(exc).__name__}
    finally:
        pass


def live() -> str:
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    alive = [row for row in rows if row.get("state") in ("running", "starting")]
    return alive[0]["session_id"] if alive else ""


# ----------------------------------------------------------------------------------------------- input capture

class XInput(ctypes.Structure):
    _fields_ = [("wButtons", wintypes.WORD), ("bLeftTrigger", wintypes.BYTE), ("bRightTrigger", wintypes.BYTE),
                ("sThumbLX", wintypes.SHORT), ("sThumbLY", wintypes.SHORT),
                ("sThumbRX", wintypes.SHORT), ("sThumbRY", wintypes.SHORT)]


class XInputState(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", XInput)]


class InputWatcher:
    """Poll XInput slots and the Dolphin keyboard bindings, and emit one record per change."""

    def __init__(self, sink, *, hz: float = 125.0) -> None:
        self.sink = sink
        self.interval = 1.0 / max(hz, 1.0)
        self.stop = threading.Event()
        self.thread = None
        self.xinput = None
        for name in ("xinput1_4.dll", "xinput9_1_0.dll"):
            try:
                self.xinput = ctypes.WinDLL(name)
                break
            except OSError:
                continue
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.last_xinput = {}
        self.last_keys = {}
        self.last_packet = {}
        self.changes = 0

    def poll_xinput(self) -> list:
        out = []
        if self.xinput is None:
            return out
        for slot in range(XINPUT_SLOTS):
            state = XInputState()
            try:
                code = self.xinput.XInputGetState(slot, ctypes.byref(state))
            except Exception:                                    # noqa: BLE001
                continue
            if code != 0:
                continue
            pad = state.Gamepad
            buttons = [name for bit, name in XINPUT_BUTTONS.items() if pad.wButtons & bit]
            signature = (tuple(buttons), pad.sThumbLX, pad.sThumbLY, pad.sThumbRX, pad.sThumbRY,
                         pad.bLeftTrigger, pad.bRightTrigger)
            if self.last_xinput.get(slot) == signature:
                continue
            self.last_xinput[slot] = signature
            out.append({"slot": slot, "buttons": buttons,
                        "lx": pad.sThumbLX, "ly": pad.sThumbLY, "rx": pad.sThumbRX, "ry": pad.sThumbRY,
                        "lt": pad.bLeftTrigger, "rt": pad.bRightTrigger})
        return out

    def poll_keys(self) -> list:
        down = {}
        for name, key in BUTTON_KEYS.items():
            try:
                if self.user32.GetAsyncKeyState(key) & 0x8000:
                    down[name] = True
            except Exception:                                    # noqa: BLE001
                pass
        if down == self.last_keys:
            return []
        self.last_keys = down
        return [{"keys": sorted(down)}]

    def run(self) -> None:
        while not self.stop.is_set():
            t = time.monotonic()
            for pad in self.poll_xinput():
                self.sink({"kind": "input", "src": "xinput", "t": round(t, 4), **pad})
                self.changes += 1
            for keys in self.poll_keys():
                self.sink({"kind": "input", "src": "keyboard", "t": round(t, 4), **keys})
                self.changes += 1
            time.sleep(self.interval)

    def start(self) -> None:
        self.thread = threading.Thread(target=self.run, daemon=True, name="pso-input-watch")
        self.thread.start()

    def close(self) -> None:
        self.stop.set()


# ----------------------------------------------------------------------------------------------- state sampling

class PadWatcher:
    """Poll the app's session-pad view: the button set and stick the operator holds, whichever app path delivered them.

    This is the channel the operator's own play uses (the desktop app posts pad events into the session input queue and
    the control plane keeps the held set for its controller glyph), so polling ``GET /api/sessions/{sid}/pad`` sees the
    operator's buttons and analog stick without touching the input queue itself.
    """

    def __init__(self, sid: str, sink) -> None:
        self.sid = sid
        self.sink = sink
        self.stop = threading.Event()
        self.thread = None
        self.last = None

    def poll(self) -> None:
        t0 = time.monotonic()
        view = call(f"/api/sessions/{self.sid}/pad", None, "GET", 10)
        t1 = time.monotonic()
        if not isinstance(view, dict):
            return
        held = sorted(view.get("held") or [])
        sources = view.get("sources") or {}
        stick, rstick = view.get("stick"), view.get("rstick")
        signature = (tuple(held), json.dumps(stick, sort_keys=True), json.dumps(rstick, sort_keys=True))
        if signature == self.last:
            return
        self.last = signature
        self.sink({"kind": "input", "src": "app-pad", "t": round(t1, 4), "t_before": round(t0, 4), "t_after": round(t1, 4),
                   "buttons": held, "sources": sources, "stick": stick, "rstick": rstick,
                   "player_touch_age_s": (round(time.time() - view["ts"], 2) if view.get("ts") else None)})

    def run(self) -> None:
        while not self.stop.is_set():
            try:
                self.poll()
            except Exception:                                  # noqa: BLE001 - a recorder must not die on one read
                pass
            time.sleep(0.03)

    def start(self) -> None:
        self.thread = threading.Thread(target=self.run, daemon=True, name="pso-pad-watch")
        self.thread.start()

    def close(self) -> None:
        self.stop.set()


class Reader:
    """Minimal big-endian reads over the session RPC."""

    def __init__(self, sid: str) -> None:
        self.sid = sid

    def rpc(self, op, **args):
        return call(f"/api/sessions/{self.sid}/rpc", {"op": op, "args": args}, "POST", 25)

    def u8(self, address):
        raw = self.rpc("read_memory", address=address, length=1)
        return raw[0] if isinstance(raw, str) and len(raw) == 2 else None

    def u32(self, address):
        raw = self.rpc("read_memory", address=address, length=4)
        return struct.unpack(">I", bytes.fromhex(raw))[0] if isinstance(raw, str) and len(raw) == 8 else None

    def flags(self):
        raw = self.rpc("read_memory", address=STAGE_FLAGS, length=STAGE_FLAGS_LEN)
        if not isinstance(raw, str):
            return None, None
        data = bytes.fromhex(raw)
        if len(data) != STAGE_FLAGS_LEN:
            return None, None
        import hashlib
        return hashlib.sha256(data).hexdigest(), [sum(bin(byte).count("1") for byte in data[g * 32:(g + 1) * 32])
                                                  for g in range(18)]


def slim_entity(entity: dict) -> dict:
    keep = ("class", "ptr", "room", "x", "y", "z", "hp", "hp_max", "entity_id", "kind")
    return {key: entity.get(key) for key in keep if entity.get(key) is not None}


class Sampler:
    def __init__(self, sid: str, sink) -> None:
        self.reader = Reader(sid)
        self.sink = sink
        self.stop = threading.Event()
        self.thread = None
        self.sample_index = 0
        self.last_flags = None
        self.last_room = None
        self.last_floor = None
        self.last_entity_sig = None

    def run(self) -> None:
        next_sample = time.monotonic()
        while not self.stop.is_set():
            t = time.monotonic()
            sample = self.sample()
            if sample is not None:
                self.sink(sample)
            next_sample += 0.066
            time.sleep(max(0.0, next_sample - time.monotonic()))
            if next_sample < time.monotonic() - 1.0:
                next_sample = time.monotonic()

    def sample(self):
        self.sample_index += 1
        player_state = self.reader.rpc("state", player_only=True)
        player = (player_state or {}).get("player") or {}
        if player.get("x") is None:
            return None
        row = {"kind": "sample", "t": round(time.monotonic(), 4), "player": player}
        # Full entity census at ~2.5 Hz: enough to catch a door/switch/enemy state change without flooding the worker.
        if self.sample_index % 6 == 1:
            full = self.reader.rpc("state") or {}
            entities = [slim_entity(entity) for entity in (full.get("entities") or [])]
            row["entities"] = entities
            signature = tuple((e.get("ptr"), e.get("class"), e.get("hp"), e.get("room")) for e in entities)
            if signature != self.last_entity_sig:
                self.sink({"kind": "entity-change", "t": row["t"],
                           "count": len(entities),
                           "entities": [e for e in entities if e.get("class") not in (None,)][:400]})
                self.last_entity_sig = signature
        # Slow-moving progress facts at ~1 Hz.
        if self.sample_index % 15 == 1:
            digest, bits = self.reader.flags()
            facts = {"phase": self.reader.u8(PHASE), "floor": self.reader.u32(FLOOR),
                     "episode": (self.reader.u32(EPISODE) or 0) + 1 if self.reader.u32(EPISODE) is not None else None,
                     "difficulty": self.reader.u32(DIFFICULTY),
                     "travelling": bool(self.reader.u32(TRAVELLING)),
                     "destination": self.reader.u32(TRAVEL_DESTINATION),
                     "flags_sha": digest, "flags_bits": bits}
            row["facts"] = facts
            if digest != self.last_flags:
                self.sink({"kind": "flag-change", "t": row["t"], "flags_sha": digest, "flags_bits": bits})
                self.last_flags = digest
            if facts["floor"] != self.last_floor:
                self.sink({"kind": "floor-change", "t": row["t"], "floor": facts["floor"],
                           "travelling": facts["travelling"], "destination": facts["destination"]})
                self.last_floor = facts["floor"]
        room = player.get("room")
        if self.last_room is not None and room != self.last_room:
            self.sink({"kind": "room-change", "t": row["t"], "from": self.last_room, "to": room,
                       "x": player.get("x"), "z": player.get("z")})
        self.last_room = room
        return row

    def start(self) -> None:
        self.thread = threading.Thread(target=self.run, daemon=True, name="pso-state-sample")
        self.thread.start()

    def close(self) -> None:
        self.stop.set()


# ----------------------------------------------------------------------------------------------- analysis

def _room(value):
    """The game's room id, with its 'no room' sentinel (0xFFFF) folded to None."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return None if number in (0, 0xFFFF) else number


def _facts(samples: list, index: int, step: int) -> dict:
    """The nearest progress-facts block at or before/after `index` (facts are sampled ~1 Hz, not every tick)."""
    for offset in range(0, len(samples)):
        for probe in (index - offset, index + offset):
            if 0 <= probe < len(samples) and samples[probe].get("facts"):
                return samples[probe]["facts"]
    return {}


def classify_segment(segment: dict, door_candidates: list) -> dict:
    """Name what a demonstration segment did, from the state deltas rather than from interpretation."""
    start_player = segment["start"].get("player") or {}
    end_player = segment["end"].get("player") or {}
    start_facts, end_facts = segment.get("start_facts") or {}, segment.get("end_facts") or {}
    start_room, end_room = _room(start_player.get("room")), _room(end_player.get("room"))
    result = {"start": {"x": start_player.get("x"), "z": start_player.get("z"), "room": start_room},
              "end": {"x": end_player.get("x"), "z": end_player.get("z"), "room": end_room},
              "seconds": segment["seconds"], "samples": segment["samples"], "inputs": segment["inputs"]}
    start_floor, end_floor = start_facts.get("floor"), end_facts.get("floor")
    if isinstance(start_floor, int) and isinstance(end_floor, int) and start_floor != end_floor:
        result["kind"] = "floor-transition"
        result["detail"] = {"floor": [start_floor, end_floor],
                            "destination": end_facts.get("destination"),
                            "travelling_cleared": not end_facts.get("travelling")}
    elif start_room is not None and end_room is not None and start_room != end_room:
        end_x = float(end_player.get("x") or 0)
        end_z = float(end_player.get("z") or 0)
        near = sorted(((math.hypot(float(entity["x"]) - end_x, float(entity["z"]) - end_z), entity)
                       for entity in door_candidates
                       if entity.get("x") is not None and entity.get("z") is not None), key=lambda pair: pair[0])
        result["kind"] = "room-transition"
        result["detail"] = {"room": [start_room, end_room],
                            "nearest_door": (near[0][1] if near and near[0][0] <= 40.0 else None),
                            "crossing": {"x": end_player.get("x"), "z": end_player.get("z")}}
    elif (start_facts.get("flags_sha") and end_facts.get("flags_sha")
          and start_facts["flags_sha"] != end_facts["flags_sha"]):
        result["kind"] = "switch-flag"
        result["detail"] = {"flags": [start_facts.get("flags_bits"), end_facts.get("flags_bits")]}
    else:
        result["kind"] = "movement"
        result["detail"] = {"hp": [start_player.get("hp"), end_player.get("hp")],
                            "moved": round(math.dist((float(start_player.get("x") or 0),
                                                      float(start_player.get("z") or 0)),
                                                     (float(end_player.get("x") or 0),
                                                      float(end_player.get("z") or 0))), 1)}
    return result


def analyse(trace_path: pathlib.Path, out_dir: pathlib.Path) -> dict:
    rows = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    samples = [row for row in rows if row["kind"] == "sample"]
    inputs = [row for row in rows if row["kind"] == "input"]
    events = [row for row in rows if row["kind"] in
              ("room-change", "flag-change", "floor-change", "entity-change")]
    if not samples:
        return {"error": "no samples in the trace", "trace": str(trace_path)}
    # Segment boundaries: an input gap longer than GAP, or a room/floor/flag change. Both are what an operator's own
    # demonstration is naturally made of - one behaviour per burst of input, ending when the game state changes.
    change_times = sorted(row["t"] for row in events if row["kind"] in ("room-change", "floor-change", "flag-change"))
    segments, current = [], {"start_index": 0, "end_index": 0, "inputs": 0}
    last_input_t, input_index, next_change = None, 0, 0
    for index, sample in enumerate(samples):
        while input_index < len(inputs) and inputs[input_index]["t"] <= sample["t"]:
            last_input_t = inputs[input_index]["t"]
            current["inputs"] += 1
            input_index += 1
        boundary_change = next_change < len(change_times) and change_times[next_change] <= sample["t"]
        idle_boundary = last_input_t is not None and sample["t"] - last_input_t > 2.0
        long_enough = sample["t"] - samples[current["start_index"]]["t"] > 1.0
        if (boundary_change or (idle_boundary and long_enough)) and index > current["start_index"]:
            if boundary_change:
                while next_change < len(change_times) and change_times[next_change] <= sample["t"]:
                    next_change += 1
            current["end_index"] = index
            segments.append(current)
            current = {"start_index": index, "end_index": index, "inputs": 0}
        current["end_index"] = index
    segments.append(current)
    door_candidates = []
    for row in rows:
        if row["kind"] == "entity-change":
            door_candidates.extend(entity for entity in row.get("entities") or []
                                   if "Door" in str(entity.get("class")) or "Warp" in str(entity.get("class")))
    seen = set()
    analysed = []
    for segment in segments:
        start_sample = samples[segment["start_index"]]
        end_sample = samples[segment["end_index"]]
        seconds = round(end_sample["t"] - start_sample["t"], 2)
        count = segment["end_index"] - segment["start_index"] + 1
        # A segment with no input and no state change is loading or idle, not a demonstrated behaviour.
        segment_doc = {"start": start_sample, "end": end_sample, "seconds": seconds, "samples": count,
                       "inputs": segment["inputs"],
                       "start_facts": _facts(samples, segment["start_index"], 1),
                       "end_facts": _facts(samples, segment["end_index"], -1)}
        result = classify_segment(segment_doc, door_candidates)
        signature = (result["kind"], result["start"]["room"], result["end"]["room"],
                     round(result["start"]["x"] or 0), round(result["start"]["z"] or 0),
                     result["detail"].get("floor") if isinstance(result["detail"].get("floor"), list) else None)
        if signature in seen:
            continue
        seen.add(signature)
        if result["kind"] == "movement" and segment["inputs"] == 0 and seconds < 2.0:
            continue
        analysed.append(result)
    path = [(sample["player"]["x"], sample["player"]["z"]) for sample in samples if sample["player"].get("x") is not None]
    waypoints, moved = [], 0.0
    for x, z in path:
        if not waypoints or math.hypot(x - waypoints[-1][0], z - waypoints[-1][1]) >= 4.0:
            if waypoints:
                moved += math.hypot(waypoints[-1][0] - x, waypoints[-1][1] - z)
            waypoints.append((round(x, 1), round(z, 1)))
    rooms = sorted({_room(sample["player"].get("room")) for sample in samples} - {None})
    summary = {"trace": str(trace_path), "samples": len(samples), "inputs": len(inputs),
               "input_sources": sorted({row.get("src") for row in inputs}),
               "events": events, "path_length": round(moved, 1), "waypoints": waypoints, "rooms": rooms,
               "segments": analysed}
    route_path = out_dir / (trace_path.stem + "-route.jsonl")
    route_path.write_text("\n".join(json.dumps({"x": x, "z": z}) for x, z in waypoints) + "\n", encoding="utf-8")
    summary["route"] = str(route_path)
    return summary

def append_skills(summary: dict, store_path: pathlib.Path) -> dict:
    store = {"schema": "pso/skills/1", "skills": []}
    if store_path.exists():
        try:
            store = json.loads(store_path.read_text(encoding="utf-8"))
        except ValueError:
            store = {"schema": "pso/skills/1", "skills": []}
    skills = []
    for index, segment in enumerate(summary.get("segments") or []):
        if segment["kind"] == "movement" and segment["seconds"] < 1.5:
            continue
        skills.append({
            "id": f"{pathlib.Path(summary['trace']).stem}-{index}",
            "kind": segment["kind"],
            "detail": segment.get("detail"),
            "source_trace": summary["trace"],
            "seconds": segment["seconds"],
            "inputs": segment["inputs"],
            "start": segment["start"], "end": segment["end"],
            "success_criteria": {
                "room-transition": "player.room changes and the arrival position is within 40 units of a door",
                "floor-transition": "floor changes and travelling finishes",
                "switch-flag": "stage-flag digest changes",
                "movement": "path recorded; replay must start and end within tolerance of the recorded endpoints",
            }[segment["kind"]],
            "validation": {"state": "observed", "runs": 0, "proved": False},
        })
    store.setdefault("skills", []).extend(skills)
    store_path.write_text(json.dumps(store, indent=1), encoding="utf-8")
    return {"skills_added": len(skills), "skills_total": len(store["skills"]), "store": str(store_path)}


# ----------------------------------------------------------------------------------------------- main

def record(args) -> int:
    sid = args.session or live()
    if not sid:
        log("no live session; start the game first")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    trace_path = OUT / f"demo-{stamp}.jsonl"
    summary_path = OUT / f"demo-{stamp}.json"
    trace = trace_path.open("w", encoding="utf-8")
    started = time.monotonic()
    counts = {"input": 0, "sample": 0, "events": 0}
    lock = threading.Lock()

    def sink(row):
        row.setdefault("t", round(time.monotonic() - started, 4))
        with lock:
            trace.write(json.dumps(row) + "\n")
            counts["input" if row["kind"] == "input" else "sample"] += 1

    watcher = InputWatcher(sink)
    pad_watcher = PadWatcher(sid, sink)
    sampler = Sampler(sid, sink)
    created_flag = False
    if not OPERATOR_FLAG.exists():
        try:
            OPERATOR_FLAG.write_text(json.dumps({"by": "pso-demo-recorder", "at": time.time()}), encoding="utf-8")
            created_flag = True
        except OSError:
            pass
    log(f"recording session {sid} -> {trace_path.name}; operator, take the controller and play")
    watcher.start()
    pad_watcher.start()
    sampler.start()
    last_report = 0.0
    stop_file = pathlib.Path(args.stop_file) if args.stop_file else None
    try:
        while args.seconds <= 0 or time.monotonic() - started < args.seconds:
            time.sleep(0.5)
            if stop_file is not None and stop_file.exists():
                log(f"stop file {stop_file} appeared - ending the recording")
                break
            now = time.monotonic()
            if now - last_report >= 3.0:
                last_report = now
                log(f"  t+{now - started:5.1f}s inputs {counts['input']:5d} samples {counts['sample']:5d} "
                    f"operator-flag {OPERATOR_FLAG.exists()}")
    except KeyboardInterrupt:
        log("interrupted")
    finally:
        watcher.close()
        pad_watcher.close()
        sampler.close()
        time.sleep(0.5)
        if created_flag:
            try:
                OPERATOR_FLAG.unlink()
            except OSError:
                pass
        trace.close()
        summary = analyse(trace_path, OUT)
        skills = append_skills(summary, OUT / "skills.json")
        summary["skills"] = skills
        summary_path.write_text(json.dumps(summary, indent=1), encoding="utf-8")
        log(f"inputs {counts['input']} samples {counts['sample']} / segments {len(summary.get('segments') or [])} "
            f"/ path {summary.get('path_length')} units / rooms {summary.get('rooms')}")
        for segment in summary.get("segments") or []:
            log(f"  segment {segment['kind']:18s} {segment['seconds']:6.2f}s inputs {segment['inputs']:4d} "
                f"room {segment['start'].get('room')} -> {segment['end'].get('room')} "
                f"detail {json.dumps(segment.get('detail'))[:80]}")
        log(f"summary {summary_path}")
        log(f"route replayable: python pso-bounded.py walk --route-file {summary.get('route')}")
        log(f"skills {skills}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="record an operator PSO demonstration (input + RAM state)")
    parser.add_argument("--seconds", type=float, default=120.0, help="0 records until interrupted")
    parser.add_argument("--session", default="")
    parser.add_argument("--hz", type=float, default=125.0)
    parser.add_argument("--stop-file", default="", help="stop cleanly when this path appears")
    parser.add_argument("--analyse", default="", help="analyse an existing demo-*.jsonl instead of recording")
    args = parser.parse_args(argv)
    if args.analyse:
        summary = analyse(pathlib.Path(args.analyse), OUT)
        skills = append_skills(summary, OUT / "skills.json")
        print(json.dumps({**summary, "skills": skills}, indent=1)[:8000])
        return 0
    return record(args)


if __name__ == "__main__":
    raise SystemExit(main())





