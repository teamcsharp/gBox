"""Observed player HP loss, frozen before health maintenance, with a durable retry outbox.

An HP delta can combine multiple game hits between reads. Cause/self-damage is unknown: neither nearby enemies nor
held fire identifies the attacker. No game memory is written and no capture job is launched by this observer.
"""
from __future__ import annotations

import json
import base64
import bisect
import hashlib
import math
import marshal
import os
from pathlib import Path
import struct
import sys
import threading
import time
import uuid
import weakref
from collections import deque

EVENT_MAX = 256 * 1024
OUTBOX_MAX = 64 * 1024 * 1024
OUTBOX_COUNT = 2048
BASELINE_MAX_AGE_S = 2.0
FRAME_MAX = 128 * 1024
_locks_guard = threading.Lock()
_locks = weakref.WeakValueDictionary()


def directory_lock(path):
    with _locks_guard:
        return _locks.setdefault(str(Path(path).resolve()), threading.Lock())


def cached_frame(ad, now=time.time):
    """Copy an existing encoder cache only. Never create a stream, wait for a frame, or block its producer."""
    unavailable = {"state": "unavailable-at-hit"}
    stream = getattr(ad, "stream", None)
    if stream is None or not getattr(stream, "cond", None):
        return unavailable | {"detail": "no existing local stream cache"}
    if not stream.cond.acquire(blocking=False):
        return unavailable | {"detail": "local stream cache was busy at observation"}
    try:
        data = stream.latest
        if getattr(ad, "stream", None) is not stream or stream.closed or not isinstance(data, bytes):
            return unavailable | {"detail": "local stream cache changed, closed, or has no frame"}
        if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
            return unavailable | {"detail": "local cached frame is not a complete JPEG"}
        if len(data) > FRAME_MAX:
            return unavailable | {"detail": "local JPEG exceeds the 128 KiB event image limit", "bytes": len(data)}
        age, copied = stream.clock() - stream.last_frame, now()
        if not math.isfinite(age) or age < 0:
            return unavailable | {"detail": "local encoder timestamp is invalid"}
        return {"state": "cached-at-observation", "data_b64": base64.b64encode(data).decode("ascii"),
                "at": copied - age, "copied_at": copied, "age_s": age, "seq": stream.seq,
                "timestamp_basis": "encoder output monotonic timestamp converted to worker wall clock; not atomic with HP read"}
    except Exception as exc:
        return unavailable | {"detail": str(exc)[:200]}
    finally:
        stream.cond.release()


class Backpressure(RuntimeError):
    """Evidence could not be retained; the caller must report the failure, not silently discard the event."""


def clean(value, depth=0):
    if depth > 12:
        return {"unavailable": "nested value exceeds evidence depth limit"}
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"unavailable": "nonfinite value"}
    if isinstance(value, dict):
        return {str(k): clean(v, depth + 1) for k, v in value.items() if k != "nav"}
    if isinstance(value, (tuple, list)):
        return [clean(v, depth + 1) for v in value]
    return {"unavailable": f"non-JSON {type(value).__name__}"}


def hook_bytes(m, title, snap):
    """Small existing-driver fields, with addresses and exact hex bytes; not a whole-RAM dump or damage-cause hook."""
    if title != "BLUS30491":
        return {"state": "unsupported", "detail": "no verified raw damage field capture for this title"}
    from .titles import re5_ps3 as R
    from .titles import re5_combat as C
    out = {"state": "done", "title": title, "fields": [], "atomic": False,
           "detail": "existing RE5 driver field layout; sequential reads before health maintenance"}
    try:
        ptr = (snap.get("player") or {}).get("ptr")
        sp = R.u32(m, R.S_PLAYER)
        index = R.player_index(m)
        if index is None or not R.ptr_ok(sp) or R.player_pointer(m) != ptr or not R.ptr_ok(ptr):
            raise ValueError("current player changed before raw capture")
        out.update(player=ptr, player_index=index, player_scope_source='native scoped sPlayer actor')
        spans = [("player_vtable", ptr, 4), ("position_rotation", ptr + R.P_POS, 32),
                 ("action_byte", ptr + R.P_ACTION, 1), ("hp_max", ptr + R.P_HP, 4),
                 ("pitch", ptr + R.P_PITCH, 4), ("action_pointer", ptr + C.P_ACTION_OBJ, 4),
                 ("inventory", ptr + C.P_INV, C.INV_SLOT * C.INV_SLOTS),
                 ("fire_command", ptr + C.P_FIRE_CMD, 4), ("immunity_flags", ptr + 0x2F10, 4)]
        for name, address, size in spans:
            data = m.rd(address, size)
            if len(data) != size:
                raise ValueError(f"short read of {name}")
            out["fields"].append({"name": name, "address": hex(address), "size": size, "hex": data.hex()})
        ap = R.u32(m, ptr + C.P_ACTION_OBJ)
        if R.ptr_ok(ap):
            action = m.rd(ap, 0x24)
            if len(action) != 0x24:
                raise ValueError("short read of current_action")
            if index != 0 and struct.unpack_from('>I', action, 0x18)[0] != ptr:
                raise ValueError("scoped player does not own current_action")
            out["fields"].append({"name": "current_action", "address": hex(ap), "size": 0x24,
                                  "hex": action.hex()})
        if R.u32(m, R.S_PLAYER) != sp or R.player_index(m) != index or R.player_pointer(m) != ptr:
            raise ValueError("current player changed during raw capture")
        if index != 0 and R.ptr_ok(ap) and (R.u32(m, ptr + C.P_ACTION_OBJ) != ap \
                or R.u32(m, ap + 0x18) != ptr):
            raise ValueError("scoped action identity changed during raw capture")
        out["read_hp"], out["read_hp_max"] = struct.unpack(">hh", bytes.fromhex(
            next(x["hex"] for x in out["fields"] if x["name"] == "hp_max")))
        out["matches_snapshot_hp"] = out["read_hp"] == snap["player"]["hp"]
    except Exception as exc:
        out.update(state="failed", detail=str(exc)[:300])
    return out


class Observer:
    def __init__(self, emit, run_id, title, stats, raw=hook_bytes, clock=time.time):
        self.emit, self.run_id, self.title, self.stats, self.raw, self.clock = emit, run_id, title, stats, raw, clock
        self.round_id = uuid.uuid4().hex
        self.round_marker = stats.get("rounds")
        self.provenance = {"observer_schema": "gbox.player_damage/1",
                           "raw_layout": "re5-driver-fields/1" if title == "BLUS30491" else "unavailable for this title",
                           "debugger_trace": "not captured; these are driver reads, not a debugger snapshot"}
        self.previous = None
        self.previous_at = None
        self.history = deque(maxlen=60)
        self.history_at = -math.inf
        self.history_player = self.history_geometry = None
        self.stats.setdefault("player_damage_events", 0)

    def bind(self, driver, profile):
        fn = getattr(driver.snapshot, "__func__", driver.snapshot)
        code = getattr(fn, "__code__", None)
        self.provenance.update(driver_module=type(driver).__module__, driver_class=type(driver).__qualname__,
            loaded_snapshot_code_sha256=hashlib.sha256(marshal.dumps(code)).hexdigest() if code else None,
            profile={k: clean(profile[k]) for k in ("map_id", "platform", "driver", "build", "version") if k in profile},
            game_build=profile.get("build") or profile.get("version") or "not independently identified")
        module_snapshot = getattr(sys.modules.get(type(driver).__module__), "snapshot", None)
        actual_code = getattr(module_snapshot, "__code__", None)
        self.provenance["loaded_decoder_code_sha256"] = hashlib.sha256(marshal.dumps(actual_code)).hexdigest() if actual_code else None
        raw_code = getattr(self.raw, "__code__", None)
        self.provenance["loaded_raw_capture_code_sha256"] = hashlib.sha256(marshal.dumps(raw_code)).hexdigest() if raw_code else None
        effective = clean(profile)
        encoded = json.dumps(effective, sort_keys=True, allow_nan=False).encode()
        self.provenance["effective_profile_sha256"] = hashlib.sha256(encoded).hexdigest()
        self.provenance["effective_profile"] = effective if len(encoded) <= 16 * 1024 else {
            "omitted": "profile exceeds 16 KiB; canonical hash retained", "bytes": len(encoded)}

    @staticmethod
    def sample(snap, screen):
        p = snap.get("player") or {}
        hp, maximum = p.get("hp"), p.get("hp_max")
        if (screen not in ("playing", "dead") or not p.get("ptr") or type(hp) not in (int, float)
                or type(maximum) not in (int, float) or not math.isfinite(hp) or not math.isfinite(maximum)
                or not 0 <= hp <= maximum or maximum <= 0):
            return None
        return p["ptr"], hp, maximum

    def before(self, snap, screen, m, bot=None, held=(), now=None):
        at = self.clock() if now is None else now
        marker = self.stats.get('rounds')
        if type(marker) is int and marker != self.round_marker:
            self.round_id, self.round_marker = uuid.uuid4().hex, marker
            self.previous = self.previous_at = None
            self._reset_history()
        current, previous = self.sample(snap, screen), self.previous
        if current is None:
            self.previous = self.previous_at = None
            self._reset_history()
            return None
        nav = snap.get('nav')
        geometry = getattr(nav, 'learning_sig', None) or getattr(nav, 'sig', None)
        if geometry is not None and self.history_geometry not in (None, geometry):
            self.previous = previous = None             # a reused player pointer does not bridge different stages
            self.previous_at = None
        if (self.history_player != current[0]
                or (geometry is not None and self.history_geometry not in (None, geometry))
                or (self.previous_at is not None and not 0 <= at-self.previous_at <= BASELINE_MAX_AGE_S)):
            self._reset_history()
        self.history_player = current[0]
        if geometry is not None:
            self.history_geometry = geometry
        # Keep preceding movement/intent even on engine-owned QTE frames.
        from . import tactical as T
        if at-self.history_at >= .2:
            player = snap['player']
            mines = getattr(bot, 'mines', None)
            intent = T.take_plan(bot)
            intent = {k:v for k,v in intent.items() if k in ('phase','target','note','route')}
            if isinstance(intent.get('route'), (list, tuple)):
                intent['route'] = intent['route'][:8]
            self.history.append(clean({'at': at, 'pos': player.get('pos'), 'rot': player.get('rot'),
                'hp': player.get('hp'), 'action': player.get('action'), 'held': sorted(held),
                'plan': intent, 'prompt': snap.get('prompt'), 'score': snap.get('score'),
                'combo': snap.get('combo'), 'kills': snap.get('kills'),
                'navigation': {k:v for k,v in self.stats.items() if k in ('route','nav_recovery','stuck','phase')},
                'mine_events': list(getattr(mines, 'events', ()))[-1:]}))
            self.history_at = at
        if (previous is None or current[0] != previous[0] or current[2] != previous[2] or previous[1] <= 0
                or self.previous_at is None or not 0 <= at - self.previous_at <= BASELINE_MAX_AGE_S):
            self.previous = current
            return None
        if current[1] >= previous[1]:
            self.previous = current
            return None
        if self.title == 'BLUS30491':
            # The engine observes damage before Controller.tick annotates this
            # fresh snapshot. Read the mine actors at the hit, not last tick.
            from .titles.re5_mines import ground_mines
            snap['ground_mines'] = ground_mines(m)
        snapshot, plan = clean(snap), clean(T.take_plan(bot))
        event = {"schema": "gbox.player_damage/1", "event_id": uuid.uuid4().hex, "run_id": self.run_id,
                 "round_id": self.round_id, "title": self.title, "observed_at": at, "screen": screen,
                 "navigation_geometry": geometry,
                 "player": current[0], "hp_before": previous[1], "hp_after": current[1], "hp_max": current[2],
                 "loss": previous[1] - current[1], "cause": "unknown", "self_damage": "unknown",
                 "snapshot": snapshot, "plan": plan, "held": sorted(held), "logic": clean(dict(self.stats)),
                 "frame_at_hit": cached_frame(getattr(m, "adapter", None)),
                 "raw": self.raw(m, self.title, snap), "provenance": dict(self.provenance),
                 "preceding_history": list(self.history),
                 "limits": ["HP loss between sampled snapshots; multiple physical hits may be combined.",
                            "Zero-damage immunity contacts and damage between unread samples are not observable here.",
                            "Attacker and self-damage attribution are unverified.",
                            "Evidence sources are independent reads, not an atomic emulator state."]}
        from . import incident
        event['ram_witness'] = incident.ram_witness(m, self.title, snap)
        try:
            event['map_at_observation_svg'] = incident.map_svg(snap, self.history, plan)
        except Exception as exc:
            event['map_at_observation_error'] = str(exc)[:200]
        try:
            event["tactical"] = T.Tracker(self.title).frame(snapshot, plan, screen, at)
            if snap.get("nav") is not None:
                event["tactical"]["stage"] = T.stage_key(self.title, snap["nav"])
        except Exception as exc:
            event["tactical"] = {"v": 1, "title": self.title, "t": at, "screen": screen,
                                 "capture_error": str(exc)[:300]}
        self.emit(event)                              # durable before the title's health writes can run
        self.previous = current
        self.stats["player_damage_events"] += 1
        self.stats["player_damage_last_id"] = event["event_id"]
        self.stats["player_damage_last_loss"] = event["loss"]
        learner = getattr(bot, "nav_learning", None)
        learn = getattr(learner, "note_damage", None)
        if self.title == 'BLUS30491' and nav is not None and geometry == getattr(nav,'learning_sig',None) and callable(learn):
            try:
                # Evidence is durable before this optional bounded policy update.
                # Use only the exact sampled player/floor, never a guessed cause.
                p = snap.get('player') or {}
                accepted = p.get('ptr') == current[0] and p.get('hp') == current[1] and p.get('hp_max') == current[2] \
                    and learn(nav,p.get('pos'),event['event_id'],observed_at=at)
                if accepted:
                    self.stats['nav_damage_samples_learned'] = self.stats.get('nav_damage_samples_learned',0)+1
                    self.stats['nav_damage_learning_last_id'] = event['event_id']
                else:
                    self.stats['nav_damage_samples_rejected'] = self.stats.get('nav_damage_samples_rejected',0)+1
            except Exception as exc:
                self.stats["nav_damage_learning_errors"] = self.stats.get("nav_damage_learning_errors", 0) + 1
                self.stats["nav_damage_learning_error"] = type(exc).__name__
        return event

    def _reset_history(self):
        self.history.clear()
        self.history_at = -math.inf
        self.history_player = self.history_geometry = None

    def after(self, snap, screen, now=None):
        marker = self.stats.get("rounds")
        if type(marker) is int and marker != self.round_marker:
            # The title confirms its own restart, including restarts inside one play_round invocation.
            # Do not infer a round from a time bonus or HP maintenance.
            self.round_id = uuid.uuid4().hex
            self.round_marker = marker
            self._reset_history()
        # Maintenance may have raised HP/max in this snapshot. Use that same verified post-maintenance baseline.
        self.previous = self.sample(snap, screen)
        self.previous_at = self.clock() if now is None else now


class Outbox:
    """Bounded durable files; only an exact durable server acknowledgement removes a pending event.

    Existing session directories are replayed during later autoplay, using each event's original session ID.
    No oldest-event eviction, no in-memory-only queue. Offline shutdown leaves a visible durable pending inventory.
    """
    def __init__(self, root, sid, sink, stats, *, threaded=True, byte_limit=OUTBOX_MAX, count_limit=OUTBOX_COUNT):
        self.root, self.sid, self.sink, self.stats = Path(root), sid, sink, stats
        self.root.mkdir(parents=True, exist_ok=True)
        self.byte_limit, self.count_limit = byte_limit, count_limit
        self.capacity_blocked = (self.root / "000-backpressure.json").exists()
        self.lock, self.wake, self.stop = directory_lock(self.root), threading.Event(), threading.Event()
        self.replay_dirs, self.replay_turn = None, False
        self.thread = None
        if threaded:
            self.thread = threading.Thread(target=self._run, daemon=True, name="player-damage-outbox")
            self.thread.start()

    def files(self):
        return sorted(self.root.glob("*.json"))

    def emit(self, event):
        body = dict(event, session_id=self.sid)
        data = json.dumps(body, allow_nan=False, separators=(",", ":")).encode()
        if len(data) > EVENT_MAX and (body.get("frame_at_hit") or {}).get("data_b64"):
            # The optional image cannot consume the HP/raw/map receipt's remaining budget.
            image = body["frame_at_hit"]
            body["frame_at_hit"] = {k: v for k, v in image.items() if k != "data_b64"}
            body["frame_at_hit"].update(state="unavailable-at-hit", detail="JPEG omitted: complete event exceeds 256 KiB")
            data = json.dumps(body, allow_nan=False, separators=(",", ":")).encode()
        if len(data) > EVENT_MAX:
            from .incident import pack_context
            body = pack_context(body)
            data = json.dumps(body, allow_nan=False, separators=(",", ":")).encode()
        with self.lock:
            files = self.files()
            if len(data) > EVENT_MAX or len(files) >= self.count_limit or sum(p.stat().st_size for p in files) + len(data) > self.byte_limit:
                self.stats.update(player_damage_status="backpressure", player_damage_error="damage evidence outbox capacity reached")
                # One reserved <=4 KiB record preserves the triggering event's identity/HP metadata. The engine
                # stops through its input-release finally; restarting with this reserve occupied is refused.
                reserve = self.root / "000-backpressure.json"
                if not reserve.exists():
                    reduced = {k: body[k] for k in ("schema", "session_id", "event_id", "run_id", "round_id", "title",
                        "observed_at", "hp_before", "hp_after", "hp_max", "loss")}
                    reduced.update(snapshot={"player": (event.get("snapshot") or {}).get("player")},
                        raw={"state": "skipped-backpressure", "detail": "full evidence exceeded the durable outbox limit"},
                        evidence_backpressure=True, cause="unknown", self_damage="unknown")
                    emergency = json.dumps(reduced, allow_nan=False, separators=(",", ":")).encode()
                    if len(emergency) > 4096:
                        raise Backpressure("damage metadata exceeds emergency reserve")
                    try:
                        self._write(reserve, emergency)
                    except OSError as exc:
                        raise Backpressure(f"damage metadata could not be persisted: {exc}") from exc
                    self.capacity_blocked = True
                    self.wake.set()
                raise Backpressure("damage evidence outbox capacity reached; no event evicted")
            path = self.root / (event["event_id"] + ".json")
            try:
                self._write(path, data)
            except OSError as exc:
                self.stats.update(player_damage_status="failed", player_damage_error=str(exc)[:300])
                raise Backpressure(f"damage evidence could not be persisted: {exc}") from exc
            self.stats.update(player_damage_status="pending", player_damage_pending=len(files) + 1)
        self.wake.set()

    @staticmethod
    def _write(path, data):
        temp = path.with_suffix(".tmp")
        with temp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)

    def flush_one(self):
        # Alternate with old session directories so a continuous current run cannot strand a previous SID.
        self.replay_turn = not self.replay_turn
        try:
            directory = self._replay_directory() if self.replay_turn else None
            directory = directory or self.root
            lock = directory_lock(directory)
            with lock:
                files = sorted(directory.glob("*.json"))
                if not files:
                    return False
                # One tiny durable cursor per directory survives process restart and arbitrarily many old SIDs.
                # It is outside the receipt glob and never changes an event's identity or payload.
                cursor_path = directory / ".delivery-cursor"
                try:
                    with cursor_path.open("rb") as f:
                        raw_cursor = f.read(256)
                    cursor = raw_cursor.decode("ascii") if len(raw_cursor) < 256 else ""
                except (FileNotFoundError, UnicodeDecodeError):
                    cursor = ""
                index = bisect.bisect_right([p.name for p in files], cursor) % len(files)
                path = files[index]
                self._write(cursor_path, path.name.encode("ascii"))
                event = json.loads(path.read_text(encoding="utf-8"))
                if directory != self.root and hashlib.sha256(event["session_id"].encode()).hexdigest() != directory.name:
                    raise ValueError("old outbox directory does not match the event's exact session")
            result = self.sink.damage(event)
            if result.get("accepted") is not True or result.get("event_id") != event["event_id"]:
                raise ValueError("server did not acknowledge this durable damage event")
            with lock:
                path.unlink(missing_ok=True)
            with self.lock:
                remaining = len(self.files())
            self.stats.update(player_damage_status="pending" if remaining else "delivered",
                              player_damage_pending=remaining, player_damage_error="",
                              player_damage_last_delivered_session=event["session_id"])
            return True
        except Exception as exc:
            self.stats.update(player_damage_status="retrying", player_damage_error=str(exc)[:300],
                              player_damage_retry_session=(locals().get("event") or {}).get("session_id"))
            return False

    def _replay_directory(self):
        # Bounded scanning per pass, retaining an iterator so directories beyond the first page are visited.
        for _ in range(32):
            if self.replay_dirs is None:
                self.replay_dirs = iter(self.root.parent.iterdir())
            try:
                path = next(self.replay_dirs)
            except StopIteration:
                self.replay_dirs = None
                return None
            if path != self.root and path.is_dir() and len(path.name) == 64:
                with directory_lock(path):
                    if next(path.glob("*.json"), None) is not None:
                        self.stats["player_damage_replay_pending"] = True
                        return path
        return None

    def _run(self):
        while not self.stop.is_set():
            if self.flush_one():
                continue
            self.wake.wait(2.0)
            self.wake.clear()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(0.2)                   # remaining files are durable; shutdown never waits for the network


def run_delivery(data_dir, server, headers, stop, stats=None, *, sink_factory=None, poll_s=2.0):
    """Worker-lifetime retries, including when no game/autoplay is running. No game operations or capture jobs.

    A shutdown can interrupt HTTP acknowledgement: files remain until exact acceptance, and a later worker retries
    the same ID. This daemon does not delay idle shutdown for a network wait or discard durable pending files.
    """
    from .tactical import HttpSink
    stats = stats if stats is not None else {}
    sink = (sink_factory or HttpSink)(server, headers, "", timeout=3.0)
    box = Outbox(Path(data_dir) / "player-damage-outbox" / "_worker-replay", "", sink, stats, threaded=False)
    stats["delivery_service"] = "running"
    try:
        while not stop.is_set():
            box.replay_turn = False                  # this service has no current-session producer directory
            delivered = box.flush_one()
            # A successful delivery is per-event, not proof that every directory is empty.
            stats["delivery_service"] = "running"
            stats["pending_scope"] = "durable session directories; only the current retry is counted"
            if not delivered:
                stop.wait(poll_s)
    finally:
        box.close()
        sink.close()
        stats["delivery_service"] = "stopped; undelivered receipts remain on disk"
