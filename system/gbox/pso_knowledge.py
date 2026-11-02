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

import json
import time
from pathlib import Path


class KnowledgeStore:
    VERSION = 1

    def __init__(self, path=None, limit=4000):
        self.path = Path(path) if path else None
        self.limit = int(limit)
        self.rooms: dict[str, dict] = {}
        if self.path and self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("version") == self.VERSION and isinstance(data.get("rooms"), dict):
                    self.rooms = {k: v for k, v in data["rooms"].items()
                                  if isinstance(k, str) and isinstance(v, dict)}
            except (OSError, ValueError, TypeError):
                self.rooms = {}

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
            payload = {"version": self.VERSION, "rooms": self.rooms}
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
