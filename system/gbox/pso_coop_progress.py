"""Durable historical PSO buddy progress, never a source of input authorization.

A new controller must observe its own route, boss, difficulty and menus. Only the
next requested episode/difficulty and already recorded totals survive relaunch.
This file does not resume autoplay, launch an emulator, or modify a memory card.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from .registry import Unsupported


COUNTERS = ("episodes", "cycles", "difficulty_cycles", "route_episodes", "route_cycles",
            "route_difficulty_cycles", "training_episodes", "training_native_episode_routes")
LIMIT = 256 * 1024


def card_binding(authorization, context):
    """Check the live slot against the private campaign root without opening it."""
    root = authorization.get("path")
    actual = ((context.get("slots") or {}).get("A") or {}).get("path")
    if not root and not actual:
        return None  # No persistent card binding: session-scoped callers only.
    if not root or not actual or authorization.get("isolated") is not True:
        raise Unsupported("PSO progress requires the verified isolated buddy card in slot A")
    expected = os.path.normcase(str((Path(root) / "dolphin" / "A.USA.raw").resolve()))
    actual = os.path.normcase(str(Path(actual).resolve()))
    if actual != expected:
        raise Unsupported("PSO progress card binding changed; preserve both cards and inspect slot A")
    return actual


class Checkpoint:
    def __init__(self, path, card_identity, characters, *, card_path=None):
        self.path = Path(path)
        self.card_identity = str(card_identity)
        self.card_path = card_path
        identities = [{key: row[key] for key in ("player", "name", "class")} for row in characters]
        self.characters_sha256 = hashlib.sha256(json.dumps(identities, sort_keys=True).encode()).hexdigest()
        self._last = None

    def _payload(self, ledger):
        return {"version": 1, "card_identity": self.card_identity, "card_path": self.card_path,
                "characters_sha256": self.characters_sha256,
                "target": ledger.target, "difficulty": ledger.difficulty,
                "counters": {key: getattr(ledger, key, 0) for key in COUNTERS},
                "receipts": ledger.receipts[-32:]}

    def _validate(self, value):
        if (not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1
                or value.get("card_identity") != self.card_identity
                or value.get("card_path") != self.card_path
                or value.get("characters_sha256") != self.characters_sha256
                or type(value.get("target")) is not int or value["target"] not in (1, 2)
                or type(value.get("difficulty")) is not int or value["difficulty"] not in range(4)):
            raise ValueError("checkpoint identity or target is invalid")
        counters, receipts = value.get("counters"), value.get("receipts")
        if (not isinstance(counters, dict) or set(counters) != set(COUNTERS)
                or any(type(n) is not int or not 0 <= n <= 2**53 for n in counters.values())
                or not isinstance(receipts, list) or len(receipts) > 32
                or any(not isinstance(row, dict) for row in receipts)):
            raise ValueError("checkpoint history is invalid")
        # Reject non-finite values rather than producing a checkpoint that cannot
        # be read by JSON consumers. Receipts are historical display data only.
        encoded = json.dumps(value, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > LIMIT:
            raise ValueError("checkpoint exceeds the bounded history size")
        return encoded

    def restore(self, ledger):
        """Populate a fresh ledger, retaining none of an old process's observations."""
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(LIMIT + 1)
        except FileNotFoundError:
            return False
        try:
            if len(raw) > LIMIT:
                raise ValueError("checkpoint exceeds the bounded history size")
            value = json.loads(raw)
            self._last = self._validate(value)
        except (ValueError, TypeError, UnicodeError) as exc:
            raise Unsupported("Saved PSO buddy progress is invalid or belongs to different buddies; "
                              "preserve the checkpoint and inspect it before continuing") from exc
        # Do not restore awaiting_entry: a previous save/quit request is not
        # permission to quit this newly observed emulator or accept a menu.
        ledger.target, ledger.difficulty = value["target"], value["difficulty"]
        for key, count in value["counters"].items():
            setattr(ledger, key, count)
        ledger.receipts = value["receipts"]
        return True

    def save(self, ledger):
        encoded = self._validate(self._payload(ledger))
        if encoded == self._last:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self._last = encoded
        return True
