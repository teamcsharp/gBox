"""Evidence for the PSO autoplayer: one canonical snapshot, one hash-chained ledger.

The engineering mandate (`system/docs/pso-handoff/PSO_ENGINEERING_AND_AUTOPLAY_RECOVERY.md`, sections 2 and 9)
requires every controller action to be reported as *pre-state -> action -> post-state* with the observed delta, and
section 12 requires a compact evidence ledger after each reproducible test. This module is that recorder and only
that: it never decides, never reads the game, and never writes memory. Callers hand it what they observed.

Two properties make the ledger checkable rather than descriptive:

* **The snapshot is canonical.** Entity lists are sorted by stable identity, floats are rounded to a fixed
  precision, and the JSON is dumped with sorted keys, so two observations of the same state produce the same bytes
  and the same sha256. A claim that "the switch opened the door" can then be compared across two sessions.
* **The ledger is hash-chained.** Each line carries the hash of the previous line, so a trace that was edited
  after the fact no longer verifies. `Ledger.verify()` is cheap and is meant to be run before any trace is quoted
  as proof.

Nothing here is PSO-specific except the field names of the profile the session channel already returns.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

SCHEMA = "pso/evidence/1"

PLAYER_FIELDS = ("class", "ptr", "room", "x", "y", "z", "heading_deg", "hp", "hp_max", "tp", "tp_max")
ENTITY_FIELDS = ("class", "kind", "ptr", "entity_id", "room", "slot", "x", "y", "z", "heading_deg", "hp")
VECTOR_FIELDS = ("x", "y", "z", "heading_deg")
#: 18 groups of 32 bytes: the verified native stage-flag array (`pso_coop_gates.STAGE_FLAG_BASE`).
STAGE_FLAG_GROUPS = 18
STAGE_GROUP_SIZE = 32


def _number(value, precision):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, precision)


def canonical(value) -> str:
    """The one serialisation used for every digest: sorted keys, no insignificant whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("ascii")).hexdigest()


def snapshot(state, *, flags=None, precision=3) -> dict:
    """A deterministic, comparable view of one live state read.

    `state` is the profile the session channel returns (`player`, `entities`, ...). `flags`, when given, are the raw
    bytes of the stage-flag array; only their digest and per-group population count are kept, because 576 bytes of
    mostly-zero data in every ledger line would bury the deltas that matter.
    """
    state = state or {}
    player = state.get("player") or {}
    px = _number(player.get("x"), precision)
    pz = _number(player.get("z"), precision)

    rows = {"enemy": [], "gate": [], "object": [], "other": []}
    for entity in state.get("entities") or []:
        if not isinstance(entity, dict) or str(entity.get("kind")) == "player":
            continue                     # the player has its own row; a duplicate would double every diff
        row = {}
        for name in ENTITY_FIELDS:
            value = entity.get(name)
            if name in VECTOR_FIELDS:
                row[name] = _number(value, precision)
            elif value is not None:
                row[name] = value
        x, z = row.get("x"), row.get("z")
        if px is not None and pz is not None and x is not None and z is not None:
            row["distance"] = round(math.hypot(x - px, z - pz), precision)
        bucket = rows.get(str(entity.get("kind")), rows["other"])
        bucket.append(row)
    for bucket in rows.values():
        bucket.sort(key=lambda row: (str(row.get("class")), str(row.get("ptr")), row.get("slot") or -1))

    player_row = {}
    for name in PLAYER_FIELDS:
        value = player.get(name)
        player_row[name] = _number(value, precision) if name in VECTOR_FIELDS else value
    body = {
        "schema": SCHEMA,
        "player": player_row,
        "entities": rows,
        "counts": {kind: len(rows[kind]) for kind in ("enemy", "gate", "object", "other")},
    }
    if flags is not None:
        body["stage_flags"] = _flag_view(flags)
    body["digest"] = digest(body)
    return body


def _flag_view(raw) -> dict:
    try:
        data = bytes(raw)
    except (TypeError, ValueError):
        return {"bytes": 0, "sha256": None, "groups": []}
    groups = []
    for group in range(min(STAGE_FLAG_GROUPS, (len(data) + STAGE_GROUP_SIZE - 1) // STAGE_GROUP_SIZE)):
        chunk = data[group * STAGE_GROUP_SIZE:(group + 1) * STAGE_GROUP_SIZE]
        groups.append(sum(bin(byte).count("1") for byte in chunk))
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "groups": groups}


def with_flags(snap: dict, raw) -> dict:
    """Attach a stage-flag read to an existing snapshot and re-seal its digest.

    Re-sealing matters: a snapshot with flags and the same snapshot without them are different observations, and a
    digest that ignored the flags would let a flag delta hide inside an unchanged "same state" claim.
    """
    out = {key: value for key, value in (snap or {}).items() if key != "digest"}
    out["stage_flags"] = _flag_view(raw)
    out["digest"] = digest(out)
    return out


def changed_bits(before: bytes, after: bytes, *, limit=64) -> dict:
    """Which stage-flag bits changed, as (group, index) pairs.

    'The switch was pressed' is an input; a changed bit is a state transition. This function is how the second is
    separated from the first, and it reports `truncated` rather than silently dropping bits past the limit.
    """
    before = bytes(before or b"")
    after = bytes(after or b"")
    width = min(len(before), len(after))
    turned_on, turned_off = [], []
    for offset in range(width):
        delta = before[offset] ^ after[offset]
        if not delta:
            continue
        for bit in range(8):
            if not delta & (0x80 >> bit):
                continue
            index = offset * 8 + bit
            target = turned_on if after[offset] & (0x80 >> bit) else turned_off
            if len(target) < limit:
                target.append({"group": index // (STAGE_GROUP_SIZE * 8),
                               "index": index % (STAGE_GROUP_SIZE * 8)})
    return {"turned_on": turned_on, "turned_off": turned_off,
            "truncated": len(turned_on) >= limit or len(turned_off) >= limit}


def diff(before: dict, after: dict, *, precision=3) -> dict:
    """What changed between two snapshots: motion, room, enemy HP, entity set, stage flags."""
    before = before or {}
    after = after or {}
    out = {"moved": 0.0, "room": [None, None], "enemies": [], "entities": {"appeared": [], "vanished": []},
           "stage_flags": None, "counts": [before.get("counts"), after.get("counts")]}
    first, second = before.get("player") or {}, after.get("player") or {}
    if first.get("x") is not None and second.get("x") is not None:
        out["moved"] = round(math.hypot((second["x"] or 0) - (first["x"] or 0),
                                        (second["z"] or 0) - (first["z"] or 0)), precision)
    if first.get("room") != second.get("room"):
        out["room"] = [first.get("room"), second.get("room")]

    old = {str(row.get("ptr")): row for row in (before.get("entities") or {}).get("enemy", [])}
    new = {str(row.get("ptr")): row for row in (after.get("entities") or {}).get("enemy", [])}
    for ptr, row in sorted(new.items()):
        previous = old.get(ptr)
        if previous is None:
            continue
        hp_before, hp_after = previous.get("hp"), row.get("hp")
        if hp_before != hp_after:
            out["enemies"].append({"ptr": ptr, "class": row.get("class"), "hp": [hp_before, hp_after],
                                   "delta": None if (hp_before is None or hp_after is None)
                                   else round(float(hp_after) - float(hp_before), precision),
                                   "died": hp_after is not None and float(hp_after) <= 0})
    seen_before = {str(row.get("ptr")) for kind in ("enemy", "gate", "object", "other")
                   for row in (before.get("entities") or {}).get(kind, [])}
    seen_after = {str(row.get("ptr")) for kind in ("enemy", "gate", "object", "other")
                  for row in (after.get("entities") or {}).get(kind, [])}
    out["entities"]["appeared"] = sorted(seen_after - seen_before)
    out["entities"]["vanished"] = sorted(seen_before - seen_after)
    if "stage_flags" in before and "stage_flags" in after:
        out["stage_flags"] = [before["stage_flags"].get("sha256"), after["stage_flags"].get("sha256")]
    return out


class Ledger:
    """An append-only, hash-chained JSON-lines trace of ticks, probes and failures.

    One line per event keeps the file greppable and streamable. `record()` is deliberately synchronous: a trace that
    is still buffered when the process dies is not evidence.
    """

    def __init__(self, path, *, clock=time.time, run: str = "") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.run = run
        self.previous = "genesis"
        self.count = 0
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entry = json.loads(line)
                    self.previous = entry.get("hash", self.previous)
                    self.count += 1

    def record(self, kind: str, *, action=None, before=None, after=None, note: str = "", extra=None) -> dict:
        entry = {
            "schema": SCHEMA,
            "run": self.run,
            "seq": self.count + 1,
            "t": round(self.clock(), 3),
            "kind": str(kind),
            "action": action,
            "before": {"digest": (before or {}).get("digest"), "player": (before or {}).get("player")},
            "after": {"digest": (after or {}).get("digest"), "player": (after or {}).get("player")},
            "delta": diff(before, after) if (before and after) else None,
            "note": str(note),
            "extra": extra,
            "prev": self.previous,
        }
        entry["hash"] = digest(entry)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical(entry) + "\n")
            handle.flush()
        self.previous = entry["hash"]
        self.count += 1
        return entry

    def verify(self) -> tuple:
        """Recompute the chain. Returns (ok, reason). A tampered or truncated line breaks the chain."""
        previous = "genesis"
        if not self.path.exists():
            return True, "empty"
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            entry = json.loads(line)
            claimed = entry.pop("hash", None)
            if entry.get("prev") != previous:
                return False, f"line {number}: prev does not match the previous hash"
            if digest(entry) != claimed:
                return False, f"line {number}: hash does not match its contents"
            previous = claimed
        return True, f"{number} entries verified"

    def summary(self) -> dict:
        kinds, last = {}, None
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                kinds[entry.get("kind")] = kinds.get(entry.get("kind"), 0) + 1
                last = entry
        return {"entries": sum(kinds.values()), "kinds": kinds, "last": last}


def failure_fixture(snapshot_now: dict, history, *, reason: str, note: str = "") -> dict:
    """The reproducible failing case the mandate asks for instead of a silent loop (section 9)."""
    return {
        "schema": "pso/failure-fixture/1",
        "reason": str(reason),
        "note": str(note),
        "state": snapshot_now,
        "history": list(history or []),
    }
