"""Durable per-room-template knowledge for the PSO co-op campaign.

PSO areas are assembled from a finite set of room templates. Once a room's gate
is understood (which panels/switches, which stage flags open its forward gate,
where the exit is), that knowledge is PERSISTED keyed by the room's geometry /
landmark fingerprint (the same hash pso_coop_nav.room_key produces, which already
folds in episode, floor, room, verified geometry_identity and landmark layout).

On re-entering a recognized template the controller RECALLS the record and acts
on it immediately - set the known flags, head for the known exit - instead of
re-deriving it. A record is only trusted when its fingerprint matches the live
room (room_key already encodes the geometry), so a stale/mismatched record simply
is not found and the bot falls back to fresh exploration; it never acts on a
wrong recall. Bounded (oldest dropped past `limit`), best-effort on disk.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


def area_fingerprint(episode, floor, geometry_identity):
    """An AREA-level key (not per-room) for the learned room-adjacency graph and
    critical path. Keyed by the exact loaded collision layout, so the graph
    compounds across runs of the same area and never crosses a randomized variant."""
    if not isinstance(geometry_identity, str) or not geometry_identity:
        return None
    return hashlib.sha256(f"area|{episode}|{floor}|{geometry_identity}".encode()).hexdigest()


class KnowledgeStore:
    VERSION = 2

    def __init__(self, path=None, limit=4000):
        self.path = Path(path) if path else None
        self.limit = int(limit)
        self.rooms: dict[str, dict] = {}
        self.areas: dict[str, dict] = {}        # area_fingerprint -> {edges, path, updated}
        if self.path and self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data.get("rooms"), dict):
                    self.rooms = {k: v for k, v in data["rooms"].items()
                                  if isinstance(k, str) and isinstance(v, dict)}
                if isinstance(data.get("areas"), dict):
                    self.areas = {k: v for k, v in data["areas"].items()
                                  if isinstance(k, str) and isinstance(v, dict)}
            except (OSError, ValueError, TypeError):
                self.rooms, self.areas = {}, {}

    # --- room-adjacency graph + critical path (per area, compounds across runs) ---
    def _area(self, area):
        rec = self.areas.get(area)
        if not isinstance(rec, dict):
            rec = self.areas[area] = {"edges": {}, "path": []}
        rec.setdefault("edges", {})
        rec.setdefault("path", [])
        return rec

    def record_edge(self, area, from_room, door_key, to_room):
        """A directed observed crossing: from_room --door_key--> to_room. Persists
        so a room OWNS its outbound doors regardless of which room id the connector
        object is tagged to, and later runs recall where each door leads."""
        if not isinstance(area, str) or not area or type(from_room) is not int or type(to_room) is not int:
            return
        rec = self._area(area)
        rec["edges"].setdefault(str(from_room), {})[str(door_key)] = to_room
        rec["updated"] = time.time()
        while len(self.areas) > self.limit:
            oldest = min(self.areas, key=lambda k: self.areas[k].get("updated", 0))
            if oldest == area:
                break
            self.areas.pop(oldest, None)
        self.save()

    def area_edges(self, area):
        """{from_room:int -> {door_key:str -> to_room:int}} for this area, or {}."""
        rec = self.areas.get(area)
        if not isinstance(rec, dict) or not isinstance(rec.get("edges"), dict):
            return {}
        out = {}
        for fr, doors in rec["edges"].items():
            try:
                room = int(fr)
            except (ValueError, TypeError):
                continue
            if isinstance(doors, dict):
                out[room] = {str(k): v for k, v in doors.items() if type(v) is int}
        return out

    def record_path(self, area, path):
        """Record the ordered room sequence that advanced toward the area exit
        (the critical path), so later runs beeline it instead of re-exploring."""
        if not isinstance(area, str) or not area or not isinstance(path, (list, tuple)):
            return
        clean = [r for r in path if type(r) is int]
        if not clean:
            return
        rec = self._area(area)
        rec["path"] = clean
        rec["updated"] = time.time()
        self.save()

    def critical_path(self, area):
        rec = self.areas.get(area)
        p = rec.get("path") if isinstance(rec, dict) else None
        return [r for r in p if type(r) is int] if isinstance(p, list) else []

    def recall(self, fingerprint):
        """The stored record for this exact room fingerprint, or None."""
        rec = self.rooms.get(fingerprint)
        return rec if isinstance(rec, dict) else None

    def remember(self, fingerprint, **info):
        """Merge `info` into this room's record and persist (bounded)."""
        if not isinstance(fingerprint, str) or not fingerprint:
            return
        rec = dict(self.rooms.get(fingerprint) or {})
        rec.update(info)
        rec["updated"] = time.time()
        self.rooms[fingerprint] = rec
        while len(self.rooms) > self.limit:
            oldest = min(self.rooms, key=lambda k: self.rooms[k].get("updated", 0))
            if oldest == fingerprint:
                break
            self.rooms.pop(oldest, None)
        self.save()

    def save(self):
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": self.VERSION, "rooms": self.rooms, "areas": self.areas}
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            pass


def recalled_forward_flags(store, fingerprint, floor):
    """A validated list of stage-flag indices for this room's forward gate, or
    None. The fingerprint match is the geometry validation; `floor` must also
    agree (the flag group IS the floor), and every flag must be in range."""
    if store is None:
        return None
    rec = store.recall(fingerprint)
    if not rec or rec.get("gate") != "forced_flags" or rec.get("floor") != floor:
        return None
    flags = rec.get("forward_flags")
    if not isinstance(flags, list) or not flags:
        return None
    if not all(type(f) is int and 0 <= f <= 255 for f in flags):
        return None
    return sorted(set(flags))
