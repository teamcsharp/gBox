"""Semantic game state from live memory (plan §8, Phase 2).

A *profile* (system/profiles/*.json) describes where a game keeps its state: an entity table, struct fields per entity
kind, and globals. Every field records how it was verified (evidence), and the extractor checks invariants on every
read, so a dashboard only shows state that is both documented and self-consistent.

The extractor only needs `read(address, length) -> bytes`, so it runs next to the emulator (worker side, fast).
"""
import json
import math
import struct
from pathlib import Path

PROFILES = Path(__file__).resolve().parent.parent / "profiles"
FMT = {"u8": "B", "i8": "b", "u16": "H", "i16": "h", "u32": "I", "i32": "i", "f32": "f"}


def _int(v):
    return int(v, 16) if isinstance(v, str) else int(v)


def load_profiles() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(PROFILES.glob("*.json"))]


def match(game: dict, read=None) -> dict | None:
    """Profile for a running game: platform + title, then an optional memory signature (disc ID etc.)."""
    for prof in load_profiles():
        if "entities" not in prof:                         # e.g. script-patch-only profiles
            continue
        m = prof["match"]
        if m.get("platform") and m["platform"] != game.get("platform"):
            continue
        if m.get("title_contains") and m["title_contains"].lower() not in (game.get("title") or "").lower():
            continue
        sig = m.get("memory")
        if sig and read:
            try:
                want = sig["equals"].encode() if isinstance(sig["equals"], str) else bytes(sig["equals"])
                if read(_int(sig["address"]), len(want)) != want:
                    continue
            except Exception:
                continue
        return prof
    return None


class Extractor:
    def __init__(self, profile: dict, read):
        self.p, self.read = profile, read
        self.end = ">" if profile.get("endian", "little") == "big" else "<"
        self._names: dict = {}

    def _fields(self, blob: bytes, fields: dict) -> dict:
        out = {}
        for name, (typ, off) in fields.items():
            off = _int(off)
            if typ == "ptrstr":                                  # pointer to a C string (e.g. PSO class names)
                ptr = struct.unpack_from(self.end + "I", blob, off)[0]
                key = ptr
                if key not in self._names:
                    try:
                        self._names[key] = self.read(ptr, 48).split(b"\0")[0].decode("latin-1", "replace")
                    except Exception:
                        self._names[key] = "?"
                out[name] = self._names[key]
                continue
            if typ.startswith("str"):
                n = int(typ[3:])
                out[name] = blob[off:off + n].split(b"\0")[0].decode("latin-1", "replace")
                continue
            v = struct.unpack_from(self.end + FMT[typ], blob, off)[0]
            out[name] = round(v, 3) if typ == "f32" else v
        return out

    def _kind(self, e: dict) -> dict | None:
        for k in self.p["entities"]["kinds"]:              # class-name rules first, then entity-id ranges
            if "name_prefix" in k and any(str(e.get("class", "")).startswith(p) for p in k["name_prefix"]):
                return k
        for k in self.p["entities"]["kinds"]:
            if "entity_id" in k and k["entity_id"][0] <= e.get("entity_id", -1) <= k["entity_id"][1]:
                return k
        return None

    def entities(self, limit: int | None = None) -> list[dict]:
        ent = self.p["entities"]
        n = int(limit or ent.get("max", 256))
        table = self.read(_int(ent["table"]), 4 * n)
        ptrs = struct.unpack(self.end + f"{n}I", table)
        size = _int(ent["struct_size"])
        lo, hi = (_int(x) for x in ent.get("pointer_range", ["0x0", "0xFFFFFFFF"]))
        out = []
        for i, ptr in enumerate(ptrs):
            if ptr == 0:
                if ent.get("null_terminated", True):
                    break
                continue
            if not lo <= ptr < hi:
                continue
            blob = self.read(ptr, size)
            e = {"slot": i, "ptr": f"{ptr:08X}"} | self._fields(blob, ent["fields"])
            kind = self._kind(e)
            e["kind"] = kind["name"] if kind else "unknown"
            if kind:
                e |= self._fields(blob, kind.get("fields", {}))
            if "angle" in e:
                e["heading_deg"] = round((e["angle"] * 360 / 65536) % 360, 1)
            out.append(e)
        return out

    def state(self, player_only: bool = False) -> dict:
        ents = self.entities(limit=1 if player_only else None)     # players come first in the table
        g = {}
        for name, spec in self.p.get("globals", {}).items():
            typ, addr = spec[:2]
            n = struct.calcsize(FMT.get(typ, "I")) if not typ.startswith("str") else int(typ[3:])
            g |= self._fields(self.read(_int(addr), n), {name: (typ, 0)})
        st = {"profile": self.p["id"], "globals": g, "entities": ents,
              "player": next((e for e in ents if e["kind"] == "player"), None)}
        st["checks"] = self.check(st)
        st["verified"] = all(c["ok"] for c in st["checks"])
        return st

    def check(self, st: dict) -> list[dict]:
        """Invariants that must hold if the profile is right (a wrong address fails these quickly)."""
        out = []
        pl = st.get("player")
        out.append({"check": "player present", "ok": pl is not None})
        for e in st["entities"]:
            pos = [e.get(k) for k in ("x", "y", "z") if k in e]
            if pos and not all(isinstance(v, float) and math.isfinite(v) and abs(v) < 1e5 for v in pos):
                out.append({"check": f"slot {e['slot']} position finite", "ok": False})
            if "hp" in e and "hp_max" in e and not (0 <= e["hp"] <= e["hp_max"] and e["hp_max"] > 0):
                out.append({"check": f"slot {e['slot']} 0<=hp<=hp_max", "ok": False, "value": [e["hp"], e["hp_max"]]})
        if pl and "hp" in pl:
            out.append({"check": "player 0<=hp<=hp_max", "ok": 0 <= pl["hp"] <= pl.get("hp_max", 1 << 16) and pl.get("hp_max", 1) > 0})
        return out


def _selftest():
    # fake big-endian memory: table with one player and one npc
    mem = {}
    def put(addr, data):
        for i, b in enumerate(data):
            mem[addr + i] = b
    put(0x100, struct.pack(">3I", 0x200, 0x800, 0))
    p = bytearray(0x340)
    struct.pack_into(">H", p, 0x1C, 0)
    struct.pack_into(">3f", p, 0x38, 1.0, 2.0, 3.0)
    struct.pack_into(">i", p, 0x60, 16384)
    struct.pack_into(">2H", p, 0x2B8, 40, 29)
    struct.pack_into(">2H", p, 0x32C, 35, 29)
    put(0x200, p)
    q = bytearray(0x340)
    struct.pack_into(">H", q, 0x1C, 0x1001)
    put(0x800, q)
    read = lambda a, n: bytes(mem.get(a + i, 0) for i in range(n))
    prof = json.loads((PROFILES / "pso-gc-plus-us.json").read_text())
    prof["entities"]["table"] = "0x100"
    prof["entities"]["max"] = 3
    prof["entities"].pop("pointer_range", None)
    st = Extractor(prof, read).state()
    assert st["player"]["hp"] == 35 and st["player"]["heading_deg"] == 90.0 and st["player"]["x"] == 1.0, st["player"]
    assert [e["kind"] for e in st["entities"]] == ["player", "npc"] and st["verified"], st
    print("semantic selftest ok")


if __name__ == "__main__":
    _selftest()
