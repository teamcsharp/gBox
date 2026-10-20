"""RAM maps (docs/ram_maps.md): a game's memory by name, read through any reader.

A map (profiles/gamedata/<map id>-ram.json, format gbox-ram-map/1) names fields at static addresses or at the end of
Cheat Engine style pointer chains, with their type, endianness, scale and units, enum / flags tables, arrays (count,
stride) and struct arrays with a live condition (RE4's EmMgr slots). Fields added from the inspector's search live in
an overlay (gbox-data/ram_maps/<map id>-ram.json, OVERLAY_DIRS) loaded over the repo map.

Playbooks read named fields instead of hard-coded offsets:

    from gbox import ram_map
    m = ram_map.load("G4BE08")              # a map id, a catalog game id, a session/game dict or a path
    v = m.read(reader)                      # reader: read(addr, n) -> bytes, or anything with .read / .rd / .read_memory
    v["merc.timer"], v["player.pos"]        # 87.3, [x, y, z]
    v.label("pad.held")                     # "A, R"
    v["enemies"]                            # [{"index": 3, "address": ..., "pos": [...], "hp": 1000, ...}] live slots only

read() batches its reads: every field's next step is gathered, coalesced into ranges and read together (one read_many
call per pointer level when the reader has one: one RPC round trip through the session channel), so a 25-field map
with a pointer level and a struct array costs three batched reads.
"""
from __future__ import annotations

import bisect
import json
import math
import re
import struct
import threading
import time
from pathlib import Path

FORMAT = "gbox-ram-map/1"
GAMEDATA = Path(__file__).resolve().parent.parent / "profiles" / "gamedata"
OVERLAY_DIRS: list[Path] = []                   # the server adds gbox-data/ram_maps: fields promoted from the inspector
SUFFIX = "-ram.json"
TYPES = {"u8": ("B", 1), "u16": ("H", 2), "u32": ("I", 4), "u64": ("Q", 8), "s8": ("b", 1), "s16": ("h", 2),
         "s32": ("i", 4), "s64": ("q", 8), "f32": ("f", 4), "f64": ("d", 8), "bool": ("B", 1)}
ALIASES = {"i8": "s8", "i16": "s16", "i32": "s32", "i64": "s64", "float": "f32", "double": "f64"}
OTHER_TYPES = {"ptr", "bytes", "str", "struct"}
SOURCES = ("ghidra", "scan", "manual")
OPS = ("eq", "ne", "lt", "le", "gt", "ge", "in")
NAME = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")
SUB_NAME = re.compile(r"^[a-z0-9_]+$")
MAX_COUNT = 256                                  # elements per array unless a field says "max"
MAX_ELEMENTS = 4096
COALESCE_GAP = 256                               # merge ranges this close (a reader can ask for more: coalesce_gap)
MAX_BLOCK = 1 << 20
FIELD_KEYS = {"address", "pointer", "offset", "type", "length", "endian", "count", "stride", "first", "max", "fields",
              "live", "mask", "shift", "scale", "bias", "units", "enum", "flags", "format", "valid", "watch", "group",
              "description", "source", "evidence", "added", "by", "notes"}
# main RAM where a pointer may point, per platform (as gbox.tools.MAIN_RAM addresses it); big-endian platforms
RAM_RANGE = {"gamecube": (0x80000000, 0x81800000), "wii": (0x80000000, 0x94000000), "n64": (0x80000000, 0x80800000),
             "psx": (0x80000000, 0x80200000), "dreamcast": (0x8C000000, 0x8D000000), "ps2": (0x00000000, 0x02000000),
             "gba": (0x02000000, 0x03008000), "nds": (0x02000000, 0x02400000)}
BIG = {"ps3", "gamecube", "wii", "n64", "n64dd", "genesis", "segacd", "sega32x", "saturn", "x68000", "xbox360"}


class MapError(ValueError):
    """A map that does not follow the format (the message names the field)."""


def num(v, what: str = "number") -> int:
    """A JSON number or a "0x..." / decimal string."""
    if isinstance(v, bool):
        raise MapError(f"{what}: {v!r} is not a number")
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        try:
            return int(v.strip(), 0)
        except ValueError:
            pass
    raise MapError(f"{what}: {v!r} is not a number")


def hexa(a: int | None) -> str | None:
    return None if a is None else f"0x{a:08X}"


# --- conditions (struct arrays' "live") -------------------------------------------------------------------------------
def _cond_check(c, subs: set, where: str) -> list[str]:
    if not isinstance(c, dict):
        return [f"{where}: a condition is an object"]
    for k in ("all", "any"):
        if k in c:
            return [p for x in (c[k] or []) for p in _cond_check(x, subs, where)] if isinstance(c[k], list) \
                else [f"{where}: {k} takes a list"]
    if "not" in c:
        return _cond_check(c["not"], subs, where)
    out = []
    if c.get("field") not in subs:
        out.append(f"{where}: condition field {c.get('field')!r} is not a sub-field")
    ops = [o for o in OPS if o in c]
    if len(ops) != 1:
        out.append(f"{where}: a condition has one of {', '.join(OPS)}")
    return out


def _cond(c, row: dict) -> bool:
    if "all" in c:
        return all(_cond(x, row) for x in c["all"])
    if "any" in c:
        return any(_cond(x, row) for x in c["any"])
    if "not" in c:
        return not _cond(c["not"], row)
    v = row.get(c["field"])
    if v is None:
        return False
    if isinstance(v, list):
        v = v[0] if v else None
    if "mask" in c and isinstance(v, int):
        v &= num(c["mask"], "mask")
    for op in OPS:
        if op in c:
            want = c[op]
            if op == "in":
                return v in [num(x) if isinstance(x, str) else x for x in want]
            want = num(want) if isinstance(want, str) else want
            return {"eq": v == want, "ne": v != want, "lt": v < want, "le": v <= want, "gt": v > want,
                    "ge": v >= want}[op]
    return False


# --- fields -------------------------------------------------------------------------------------------------------------
class Field:
    """One named field of a map (or a struct's sub-field), parsed and checked."""

    def __init__(self, name: str, spec: dict, rmap: "RamMap", sub: bool = False):
        if not isinstance(spec, dict):
            raise MapError(f"{name}: a field is an object")
        self.name, self.spec, self.sub = name, spec, sub
        unknown = set(spec) - FIELD_KEYS
        if unknown:
            raise MapError(f"{name}: unknown key(s) {', '.join(sorted(unknown))}")
        if not (SUB_NAME if sub else NAME).match(name):
            raise MapError(f"{name}: names are lowercase {'words' if sub else 'dotted words'} (a-z 0-9 _)")
        t = str(spec.get("type") or "")
        self.type = ALIASES.get(t, t)
        if self.type not in TYPES and self.type not in OTHER_TYPES:
            raise MapError(f"{name}: unknown type {t!r}")
        self.endian = {"big": ">", "little": "<"}.get(spec.get("endian") or rmap.endian_name)
        if self.endian is None:
            raise MapError(f"{name}: endian is big or little")
        self.psize = rmap.pointer_size
        if self.type == "ptr":
            self.fmt, self.size = {4: "I", 8: "Q", 2: "H"}[self.psize], self.psize
        elif self.type in ("bytes", "str"):
            self.fmt, self.size = None, num(spec.get("length", 0), f"{name}: length")
            if not 0 < self.size <= 4096:
                raise MapError(f"{name}: {self.type} needs a length of 1..4096 bytes")
        elif self.type == "struct":
            self.fmt, self.size = None, 0
        else:
            self.fmt, self.size = TYPES[self.type]
        # location
        locs = [k for k in ("address", "pointer", "offset") if k in spec]
        if sub:
            if locs != ["offset"]:
                raise MapError(f"{name}: a struct's sub-field has an offset (and no address / pointer)")
            self.offset = num(spec["offset"], f"{name}: offset")
        elif len(locs) != 1 or locs[0] == "offset":
            raise MapError(f"{name}: give an address or a pointer")
        self.address = num(spec["address"], f"{name}: address") if "address" in spec else None
        self.base, self.offsets = None, []
        if "pointer" in spec:
            p = spec["pointer"]
            if isinstance(p, list) and len(p) >= 2:
                p = {"base": p[0], "offsets": p[1:]}
            if not isinstance(p, dict) or "base" not in p or not isinstance(p.get("offsets"), list) or not p["offsets"]:
                raise MapError(f"{name}: pointer is {{\"base\": B, \"offsets\": [o1, ...]}} with at least one offset")
            self.base = num(p["base"], f"{name}: pointer base")
            self.offsets = [num(o, f"{name}: pointer offset") for o in p["offsets"]]
        # arrays
        c = spec.get("count", 1)
        self.count_ref = c[1:] if isinstance(c, str) and c.startswith("@") else None
        self.count = None if self.count_ref else num(c, f"{name}: count")
        if sub and self.count_ref:
            raise MapError(f"{name}: a sub-field's count is a number")
        self.first = num(spec.get("first", 0), f"{name}: first")
        self.max = num(spec.get("max", MAX_COUNT), f"{name}: max")
        if self.type == "struct":
            if sub:
                raise MapError(f"{name}: structs do not nest")
            subs = spec.get("fields")
            if not isinstance(subs, dict) or not subs:
                raise MapError(f"{name}: a struct has fields")
            try:
                self.fields = {k: Field(k, v, rmap, sub=True) for k, v in subs.items()}
            except MapError as e:
                raise MapError(f"{name}.{e}") from None              # "enemies.hp: ..."
            self.lo = min(f.offset for f in self.fields.values())
            self.hi = max(f.offset + f.extent for f in self.fields.values())
            if "stride" not in spec:
                raise MapError(f"{name}: a struct array has a stride")
        else:
            self.fields = {}
        st = spec.get("stride", self.size)
        self.stride_ref = st[1:] if isinstance(st, str) and st.startswith("@") else None
        if sub and self.stride_ref:
            raise MapError(f"{name}: a sub-field's stride is a number")
        self.stride = 0 if self.stride_ref else num(st, f"{name}: stride")
        if not self.stride_ref and self.stride <= 0 and (self.count_ref or (self.count or 0) > 1):
            raise MapError(f"{name}: stride must be positive")
        self.refs = [r for r in (self.count_ref, self.stride_ref) if r]
        self.array = bool(self.count_ref) or (self.count or 0) != 1 or self.first != 0 or self.type == "struct"
        self.live = spec.get("live")
        if self.live is not None:
            if self.type != "struct":
                raise MapError(f"{name}: live is for struct arrays")
            problems = _cond_check(self.live, set(self.fields), name)
            if problems:
                raise MapError("; ".join(problems))
        # value
        self.mask = num(spec["mask"], f"{name}: mask") if "mask" in spec else None
        self.shift = num(spec.get("shift", 0), f"{name}: shift")
        self.scale = float(spec["scale"]) if "scale" in spec else None
        self.bias = float(spec["bias"]) if "bias" in spec else None
        self.units = spec.get("units") or ""
        self.enum = {num(k, f"{name}: enum key"): str(v) for k, v in (spec.get("enum") or {}).items()}
        self.flags = [(num(k, f"{name}: flag"), str(v)) for k, v in (spec.get("flags") or {}).items()]   # map order
        self.format = spec.get("format") or ""
        v = spec.get("valid")
        self.valid = (float(v[0]), float(v[1])) if isinstance(v, list) and len(v) == 2 else None
        self.watch = bool(spec["watch"]) if "watch" in spec else bool(self.enum or self.flags)
        self.group = spec.get("group") or (name.split(".", 1)[0] if not sub else "")
        self.description = spec.get("description") or ""
        self.source = spec.get("source") or ""
        if self.source and self.source not in SOURCES:
            raise MapError(f"{name}: source is one of {', '.join(SOURCES)}")

    @property
    def extent(self) -> int:
        """Bytes from the field's start to the end of its last element (a sub-field's span inside the element)."""
        n = self.count if self.count is not None else 1
        return (max(1, n) - 1) * self.stride + self.size

    def decode(self, data: bytes, at: int = 0):
        """(value, raw int or None) of one element at data[at:]."""
        if self.type == "struct":
            raise MapError("decode a struct through its fields")
        if self.type == "bytes":
            return data[at:at + self.size].hex(), None
        if self.type == "str":
            return data[at:at + self.size].split(b"\0")[0].decode("latin-1"), None
        raw = struct.unpack_from(self.endian + self.fmt, data, at)[0]
        if self.type == "bool":
            return raw != 0, int(raw)
        if isinstance(raw, float):
            v = raw
            if self.scale is not None:
                v *= self.scale
            if self.bias is not None:
                v += self.bias
            return v, None
        if self.mask is not None:
            raw &= self.mask
        raw >>= self.shift
        v = raw
        if self.scale is not None or self.bias is not None:
            v = raw * (self.scale if self.scale is not None else 1.0) + (self.bias or 0.0)
        return v, raw

    def label(self, raw) -> str | None:
        if raw is None or isinstance(raw, bool):
            return None
        if self.enum:
            return self.enum.get(raw)
        if self.flags:
            names = [n for bit, n in self.flags if raw & bit == bit and bit]
            rest = raw & ~sum(bit for bit, _ in self.flags)
            if rest:
                names.append(f"0x{rest:X}")
            return ", ".join(names) if names else "none"
        return None

    def describe(self) -> dict:
        """The static facts the panel shows next to the value."""
        loc = ({"address": hexa(self.address)} if self.address is not None else
               {"pointer": {"base": hexa(self.base), "offsets": [f"0x{o:X}" for o in self.offsets]}} if self.base is not None
               else {"offset": f"0x{self.offset:X}"})
        out = {"name": self.name, "type": self.type, "group": self.group, **loc, "units": self.units,
               "description": self.description, "source": self.source, "watch": self.watch, "format": self.format}
        if self.enum:
            out["enum"] = {str(k): v for k, v in self.enum.items()}
        if self.flags:
            out["flags"] = {f"0x{k:X}": v for k, v in self.flags}
        if self.array:
            out["count"] = f"@{self.count_ref}" if self.count_ref else self.count
            out["stride"] = f"@{self.stride_ref}" if self.stride_ref else self.stride
        if self.fields:
            out["fields"] = [f.describe() for f in self.fields.values()]
        if self.spec.get("evidence"):
            out["evidence"] = self.spec["evidence"]
        return out


# --- values -------------------------------------------------------------------------------------------------------------
def _json_num(v):
    if isinstance(v, float):
        if not math.isfinite(v):
            return None
        return float(f"{v:.6g}")
    return v


class RamValues(dict):
    """name -> value (numbers after mask / shift / scale; lists for arrays; rows for struct arrays; None unreadable),
    plus raw ints (enum / flags lookups), resolved addresses and errors."""

    def __init__(self, rmap: "RamMap", at: float):
        super().__init__()
        self.map, self.at = rmap, at
        self.raw: dict = {}
        self.address: dict = {}
        self.errors: dict = {}
        self.counts: dict = {}

    def label(self, name: str) -> str | None:
        """The enum / flags label of a field's value (the first element's for arrays)."""
        f = self.map.fields.get(name)
        raw = self.raw.get(name)
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        return f.label(raw) if f else None

    def display(self, name: str) -> str:
        f, v = self.map.fields[name], self.get(name)
        if name in self.errors:
            return "?"
        return _show(f, v, self.raw.get(name))

    def suspect(self, name: str) -> bool:
        f, v = self.map.fields.get(name), self.get(name)
        if f is None or f.valid is None or v is None:
            return False
        vals = v if isinstance(v, list) else [v]
        return any(isinstance(x, (int, float)) and not isinstance(x, bool) and
                   (not math.isfinite(x) or not f.valid[0] <= x <= f.valid[1]) for x in vals)

    def rows(self) -> list[dict]:
        """JSON-safe rows for the inspector panel, in map order."""
        out = []
        for name, f in self.map.fields.items():
            if name not in self and name not in self.errors:
                continue
            v = self.get(name)
            row = {"name": name, "group": f.group, "type": f.type, "units": f.units, "watch": f.watch,
                   "address": self.address.get(name) if not isinstance(self.address.get(name), int)
                   else hexa(self.address[name])}
            if name in self.errors:
                row["error"] = self.errors[name]
            if f.type == "struct":
                row["rows"] = [{k: ([_json_num(x) for x in val] if isinstance(val, list) else
                                    hexa(val) if k == "address" else _json_num(val)) for k, val in r.items()}
                               for r in (v or [])]
                row["display"] = f"{len(v or [])} live of {self.counts.get(name, 0)}" if f.live else \
                    f"{len(v or [])} elements"
                row["sub"] = {k: {"type": s.type, "units": s.units, "format": s.format} for k, s in f.fields.items()}
                row["value"] = None
            else:
                row["value"] = [_json_num(x) for x in v] if isinstance(v, list) else _json_num(v)
                row["display"] = self.display(name)
                lab = self.label(name)
                if lab is not None:
                    row["label"] = lab
                if f.format:
                    row["format"] = f.format
            if self.suspect(name):
                row["suspect"] = True
            out.append(row)
        return out


def _show(f: Field, v, raw) -> str:
    if v is None:
        return "null"
    if isinstance(v, list):
        return "[" + ", ".join(_show(f, x, r) for x, r in zip(v, raw if isinstance(raw, list) else [None] * len(v))) + "]"
    lab = f.label(raw) if raw is not None else None
    if f.format == "hex" and isinstance(v, int) and not isinstance(v, bool):
        s = f"0x{v:0{max(2, f.size * 2)}X}"
    elif f.type == "ptr":
        s = f"0x{v:08X}"
    elif f.format == "deg" and isinstance(v, float):
        s = f"{math.degrees(v):.1f}°" if math.isfinite(v) else str(v)
    elif f.format == "bin" and isinstance(v, int):
        s = f"0b{v:0{f.size * 8}b}"
    elif isinstance(v, float):
        s = f"{v:.6g}"
    else:
        s = str(v)
    if f.units and f.format != "deg" and not isinstance(v, str):
        s += f" {f.units}"
    if lab is not None and (f.enum or f.flags):
        s = f"{lab} ({s})" if f.enum else f"{s} [{lab}]"
    return s


# --- reading ------------------------------------------------------------------------------------------------------------
def read_fn(reader):
    """read(addr, n) -> bytes for any reader shape: a function, .read, .rd (the bots' ShmMem / AdMem), .read_memory."""
    if callable(reader) and not hasattr(reader, "read") and not hasattr(reader, "rd"):
        return reader
    for attr in ("read", "rd", "read_memory"):
        fn = getattr(reader, attr, None)
        if callable(fn):
            return fn
    raise TypeError(f"{type(reader).__name__} cannot read memory (no read / rd / read_memory)")


def coalesce(ranges, gap: int = COALESCE_GAP, max_block: int = MAX_BLOCK) -> list[tuple[int, int]]:
    """Sorted, merged (addr, n) ranges: neighbours closer than gap become one read, never longer than max_block."""
    out: list[list[int]] = []
    for a, n in sorted((int(a), int(n)) for a, n in ranges if n > 0):
        if out and a <= out[-1][0] + out[-1][1] + gap and max(out[-1][0] + out[-1][1], a + n) - out[-1][0] <= max_block:
            out[-1][1] = max(out[-1][0] + out[-1][1], a + n) - out[-1][0]
        else:
            out.append([a, n])
    return [(a, n) for a, n in out]


class Mem:
    """A batch of reads: prefetch() reads coalesced ranges (read_many when the reader has it), get() serves from them."""

    def __init__(self, reader, wait: float | None = None):
        self.one = read_fn(reader)
        self.many = getattr(reader, "read_many", None)
        self.wait = wait if getattr(reader, "budget", None) is not None else None   # a gbox.ram_reader.Reader's budget
        self.gap = int(getattr(reader, "coalesce_gap", COALESCE_GAP))
        self.max_block = int(getattr(reader, "max_block", MAX_BLOCK))
        self.starts: list[int] = []
        self.blocks: list[tuple[int, bytes]] = []
        self.failed: list[tuple[int, int, str]] = []
        self.reads = self.bytes = self.longest = 0

    def _put(self, a: int, data: bytes):
        i = bisect.bisect_left(self.starts, a)
        self.starts.insert(i, a)
        self.blocks.insert(i, (a, data))
        self.longest = max(self.longest, len(data))

    def _have(self, a: int, n: int) -> bytes | None:
        i = bisect.bisect_right(self.starts, a) - 1
        while i >= 0:
            s, d = self.blocks[i]
            if a + n <= s + len(d):
                return d[a - s:a - s + n]
            if s < a - self.longest:                   # no block that starts earlier reaches a
                break
            i -= 1
        return None

    def prefetch(self, ranges):
        todo = coalesce([(a, n) for a, n in ranges if self._have(a, n) is None], self.gap, self.max_block)
        if not todo:
            return
        if self.many is not None:
            got = self.many(todo) if self.wait is None else self.many(todo, wait=self.wait)
        else:
            got = []
            for a, n in todo:
                try:
                    got.append(bytes(self.one(a, n)))
                except Exception as e:                 # noqa: BLE001 - unmapped / emulator busy: that range fails
                    got.append(e)
        self.reads += len(todo)
        for (a, n), d in zip(todo, got):
            if isinstance(d, (bytes, bytearray)) and len(d) >= n:
                self._put(a, bytes(d[:n]))
                self.bytes += n
            else:
                self.failed.append((a, n, f"{type(d).__name__}: {d}" if isinstance(d, Exception) else "short read"))

    def get(self, a: int, n: int) -> bytes | None:
        d = self._have(a, n)
        if d is None and not any(fa <= a < fa + fn for fa, fn, _ in self.failed):
            self.prefetch([(a, n)])
            d = self._have(a, n)
        return d

    def error(self, a: int) -> str:
        return next((e for fa, fn, e in self.failed if fa <= a < fa + fn), "unreadable")


# --- maps ---------------------------------------------------------------------------------------------------------------
class RamMap:
    """A loaded map: fields in file order, read(reader) -> RamValues."""

    def __init__(self, spec: dict, path: Path | None = None, overlay: dict | None = None):
        if not isinstance(spec, dict):
            raise MapError("a map is a JSON object")
        if spec.get("format", FORMAT) != FORMAT:
            raise MapError(f"format {spec.get('format')!r} (want {FORMAT})")
        self.path, self.overlay_path = path, None
        spec = dict(spec)
        self.overlay_fields: list[str] = []
        if overlay:
            spec["fields"] = {**(spec.get("fields") or {}), **(overlay.get("fields") or {})}
            self.overlay_fields = list((overlay.get("fields") or {}).keys())
            for k in ("title", "platform", "match"):
                if k not in spec and k in overlay:
                    spec[k] = overlay[k]
        self.spec = spec
        self.id = str(spec.get("id") or (path.name[:-len(SUFFIX)] if path and path.name.endswith(SUFFIX) else ""))
        if not self.id:
            raise MapError("a map has an id")
        self.title = spec.get("title") or self.id
        self.platform = str(spec.get("platform") or "")
        self.endian_name = spec.get("endian") or ("big" if self.platform in BIG else "little")
        self.pointer_size = num(spec.get("pointer_size", 4), "pointer_size")
        if self.pointer_size not in (2, 4, 8):
            raise MapError("pointer_size is 2, 4 or 8")
        pr = spec.get("pointer_range") or RAM_RANGE.get(self.platform)
        self.pointer_range = (num(pr[0], "pointer_range"), num(pr[1], "pointer_range")) if pr else (1, 1 << 64)
        self.match = spec.get("match") or {}
        self.regions = [(r.get("name") or f"region {i}", num(r["base"], "region base"), num(r["size"], "region size"))
                        for i, r in enumerate(spec.get("regions") or [])]
        self.groups = spec.get("groups") or {}
        fields = spec.get("fields") or {}
        if not isinstance(fields, dict):
            raise MapError("fields is an object (name -> field)")
        self.fields: dict[str, Field] = {}
        problems = []
        for name, f in fields.items():
            try:
                self.fields[name] = Field(name, f, self)
            except MapError as e:
                problems.append(str(e))
        for f in self.fields.values():
            for ref in f.refs:
                if ref not in self.fields:
                    problems.append(f"{f.name}: @{ref} is not a field")
                elif self.fields[ref].array or self.fields[ref].type in ("bytes", "str"):
                    problems.append(f"{f.name}: @{ref} must be a field with one number")
        if problems:
            raise MapError("; ".join(problems))

    def __repr__(self):
        return f"RamMap({self.id!r}, {len(self.fields)} fields)"

    def describe(self) -> dict:
        return {"id": self.id, "title": self.title, "platform": self.platform, "endian": self.endian_name,
                "groups": self.groups, "fields": [f.describe() for f in self.fields.values()],
                "overlay_fields": self.overlay_fields,
                "regions": [{"name": n, "base": hexa(b), "size": s} for n, b, s in self.regions],
                "path": str(self.path) if self.path else None}

    def watched(self) -> list[str]:
        return [n for n, f in self.fields.items() if f.watch or any(s.watch for s in f.fields.values())]

    # -- evaluation --
    def _ok_ptr(self, p: int) -> bool:
        return self.pointer_range[0] <= p < self.pointer_range[1]

    def _eval(self, f: Field, mem: Mem, vals: RamValues):
        """A generator: yields the ranges it needs next, then fills vals[f.name]."""
        if f.address is not None:
            addr = f.address
        else:
            addr = f.base
            for step, off in enumerate(f.offsets):
                yield [(addr, f.psize)]
                d = mem.get(addr, f.psize)
                if d is None:
                    vals.errors[f.name] = f"pointer at {hexa(addr)}: {mem.error(addr)}"
                    vals[f.name] = None
                    return
                p = struct.unpack(f.endian + {2: "H", 4: "I", 8: "Q"}[f.psize], d)[0]
                if not self._ok_ptr(p):
                    vals.errors[f.name] = f"null pointer: {hexa(addr)} holds {hexa(p)}" + (f" (step {step + 1})" if step else "")
                    vals[f.name] = None
                    return
                addr = p + off
        def ref(name):
            v = vals.get(name)
            return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else 0
        n = ref(f.count_ref) if f.count_ref else f.count
        n = max(0, min(n, f.max, MAX_ELEMENTS))
        stride = ref(f.stride_ref) if f.stride_ref else f.stride
        if f.stride_ref and not (f.hi - f.lo if f.type == "struct" else f.size) <= stride <= 1 << 20:
            vals.errors[f.name] = f"stride @{f.stride_ref} = {stride}: not a plausible element size"
            vals[f.name] = None
            return
        idx = range(f.first, n) if f.array else range(0, 1)
        vals.counts[f.name] = n
        if f.type == "struct":
            yield [(addr + i * stride + f.lo, f.hi - f.lo) for i in idx]
            rows = []
            for i in idx:
                at = addr + i * stride
                d = mem.get(at + f.lo, f.hi - f.lo)
                if d is None:
                    vals.errors[f.name] = f"element {i} at {hexa(at)}: {mem.error(at + f.lo)}"
                    continue
                row = {"index": i, "address": at}
                for s in f.fields.values():
                    vs = [s.decode(d, s.offset - f.lo + k * s.stride)[0] for k in range(s.count or 1)]
                    row[s.name] = vs if s.array or (s.count or 1) != 1 else vs[0]
                if f.live is None or _cond(f.live, row):
                    rows.append(row)
            vals[f.name] = rows
            vals.address[f.name] = addr
            return
        yield [(addr + i * stride, f.size) for i in idx]
        out, raws = [], []
        for i in idx:
            a = addr + i * stride
            d = mem.get(a, f.size)
            if d is None:
                vals.errors[f.name] = f"{hexa(a)}: {mem.error(a)}"
                out.append(None)
                raws.append(None)
                continue
            v, r = f.decode(d)
            out.append(v)
            raws.append(r)
        if f.array:
            vals[f.name], vals.raw[f.name] = out, raws
        else:
            vals[f.name], vals.raw[f.name] = out[0], raws[0]
        vals.address[f.name] = addr

    def read(self, reader, names=None, clock=time.time) -> RamValues:
        """Every field (or just `names` and what their counts need) read through reader, batched per pointer level."""
        mem = reader if isinstance(reader, Mem) else Mem(reader)
        want = list(self.fields) if names is None else [n for n in self.fields if n in set(names)]
        need = set(want) | {r for n in want for r in self.fields[n].refs}
        first = [n for n in self.fields if n in need and not self.fields[n].refs]
        second = [n for n in self.fields if n in need and self.fields[n].refs]
        vals = RamValues(self, clock())
        for wave in (first, second):
            gens = {}
            for n in wave:
                g = self._eval(self.fields[n], mem, vals)
                try:
                    gens[n] = (g, next(g))
                except StopIteration:
                    pass
            while gens:
                mem.prefetch([r for _, ranges in gens.values() for r in ranges])
                nxt = {}
                for n, (g, _) in gens.items():
                    try:
                        nxt[n] = (g, next(g))
                    except StopIteration:
                        pass
                    except (struct.error, MapError) as e:
                        vals.errors[n] = f"{type(e).__name__}: {e}"
                        vals.setdefault(n, None)
                gens = nxt
        for n in list(vals):
            if n not in want:
                vals.pop(n, None)
        vals.reads, vals.bytes = mem.reads, mem.bytes
        return vals


# --- events -------------------------------------------------------------------------------------------------------------
def changes(prev: RamValues | None, cur: RamValues) -> list[dict]:
    """The watched fields that changed between two reads: [{field, old, new, old_label, new_label}] (struct arrays:
    per element, "enemies[5].state"; elements that appear or disappear when the struct itself is watched)."""
    if prev is None:
        return []
    out = []
    for name in cur.map.watched():
        f = cur.map.fields[name]
        if name not in cur or name not in prev or name in cur.errors or name in prev.errors:
            continue
        if f.type == "struct":
            old = {r["index"]: r for r in prev.get(name) or []}
            new = {r["index"]: r for r in cur.get(name) or []}
            if f.watch:
                for i in sorted(set(new) - set(old)):
                    out.append({"field": f"{name}[{i}]", "old": None, "new": "live", "old_label": None, "new_label": "live"})
                for i in sorted(set(old) - set(new)):
                    out.append({"field": f"{name}[{i}]", "old": "live", "new": None, "old_label": "live", "new_label": None})
            for i in sorted(set(new) & set(old)):
                for s in f.fields.values():
                    if s.watch and old[i].get(s.name) != new[i].get(s.name):
                        a, b = old[i].get(s.name), new[i].get(s.name)
                        out.append({"field": f"{name}[{i}].{s.name}", "old": a, "new": b,
                                    "old_label": s.label(a if isinstance(a, int) else None),
                                    "new_label": s.label(b if isinstance(b, int) else None)})
            continue
        a, b = prev.get(name), cur.get(name)
        if a != b:
            out.append({"field": name, "old": a, "new": b, "old_label": prev.label(name), "new_label": cur.label(name)})
    return out


# --- finding and loading maps -------------------------------------------------------------------------------------------
_cache: dict[Path, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _json(path: Path) -> dict | None:
    try:
        mt = path.stat().st_mtime
    except OSError:
        return None
    with _cache_lock:
        hit = _cache.get(path)
        if hit and hit[0] == mt:
            return hit[1]
    data = json.loads(path.read_text(encoding="utf-8"))
    with _cache_lock:
        _cache[path] = (mt, data)
    return data


def _files(dirs) -> dict[str, Path]:
    out = {}
    for d in dirs:
        for p in sorted(Path(d).glob("*" + SUFFIX)) if Path(d).is_dir() else []:
            out.setdefault(p.name[:-len(SUFFIX)], p)
    return out


def overlay_path(map_id: str) -> Path | None:
    return Path(OVERLAY_DIRS[0]) / f"{map_id}{SUFFIX}" if OVERLAY_DIRS else None


def _overlay(map_id: str) -> tuple[dict | None, Path | None]:
    for d in OVERLAY_DIRS:
        p = Path(d) / f"{map_id}{SUFFIX}"
        data = _json(p) if p.is_file() else None
        if data:
            return data, p
    return None, None


def _spec_files() -> dict[str, Path]:
    """map id -> the file that says which game it is: the repo map, else the overlay of a game without one."""
    return {**_files(OVERLAY_DIRS), **_files([GAMEDATA])}


def map_ids() -> list[str]:
    return sorted(_spec_files())


def _keys(game) -> list[str]:
    if isinstance(game, dict):
        return [str(k) for k in (game.get("ram_map"), game.get("disc_id"), game.get("gecko_id"), game.get("game_id"))
                if k]
    return [str(game)] if game else []


def resolve(game) -> str | None:
    """The map id for a map id, a disc id, a catalog game id or a game / session dict."""
    keys, files = _keys(game), _spec_files()
    for k in keys:
        if k in files:
            return k
    for mid, path in files.items():
        m = (_json(path) or {}).get("match") or {}
        if any(k in (m.get("game_ids") or []) or k == m.get("disc_id") for k in keys):
            return mid
    return None


def find(game) -> RamMap | None:
    """The game's map (repo map + overlay), or None when it has none."""
    if isinstance(game, (str, Path)) and str(game).endswith(".json") and Path(game).is_file():
        return RamMap(json.loads(Path(game).read_text(encoding="utf-8")), Path(game))
    mid = resolve(game)
    if not mid:
        return None
    path = _files([GAMEDATA]).get(mid)
    spec = _json(path) if path else None
    over, opath = _overlay(mid)
    if spec is None:
        if not over:
            return None
        spec, over = {**over, "id": mid, "fields": {}}, over        # a game with only promoted fields
    m = RamMap(spec, path, over)
    m.overlay_path = opath
    return m


def load(game) -> RamMap:
    """find() that raises LookupError when the game has no map."""
    m = find(game)
    if m is None:
        raise LookupError(f"no RAM map for {game!r} (profiles/gamedata/<id>{SUFFIX}; docs/ram_maps.md)")
    return m


def detect(read, platform: str = "") -> str | None:
    """A map id from the game's own memory: the disc id at 0x80000000 (GameCube / Wii), else the maps' match.memory."""
    rd = read_fn(read)
    for mid, path in _spec_files().items():
        spec = _json(path) or {}
        if platform and spec.get("platform") and spec["platform"] != platform:
            continue
        sig = (spec.get("match") or {}).get("memory")
        if not sig:
            continue
        want = bytes.fromhex(sig["hex"]) if isinstance(sig.get("hex"), str) else str(sig.get("equals", "")).encode()
        try:
            if want and bytes(rd(num(sig["address"]), len(want))) == want:
                return mid
        except Exception:                               # noqa: BLE001 - unmapped: not this game
            continue
    return None


def summaries() -> list[dict]:
    out = []
    for mid in map_ids():
        try:
            m = find(mid)
        except (MapError, ValueError) as e:
            out.append({"id": mid, "error": str(e)})
            continue
        if m:
            out.append({"id": m.id, "title": m.title, "platform": m.platform, "fields": len(m.fields),
                        "overlay_fields": len(m.overlay_fields), "game_ids": (m.match or {}).get("game_ids") or []})
    return out


# --- promoting a found address ------------------------------------------------------------------------------------------
_write_lock = threading.Lock()


def promote(map_id: str, name: str, spec: dict, base: dict | None = None) -> RamMap:
    """Add (or replace) one field in the map's overlay (gbox-data/ram_maps/<id>-ram.json); returns the merged map.
    base: title / platform / match for a game that has no map yet."""
    if not re.match(r"^[A-Za-z0-9_-]{1,64}$", map_id or ""):
        raise MapError(f"map id {map_id!r}")
    path = overlay_path(map_id)
    if path is None:
        raise MapError("no overlay folder (the server sets ram_map.OVERLAY_DIRS)")
    with _write_lock:
        cur = (_json(path) if path.is_file() else None) or {"format": FORMAT, "id": map_id, **(base or {}), "fields": {}}
        new = {**cur, "fields": {**(cur.get("fields") or {}), name: spec}}
        repo = _files([GAMEDATA]).get(map_id)
        spec_repo = _json(repo) if repo else {"format": FORMAT, "id": map_id, **(base or {}), "fields": {}}
        RamMap(spec_repo, repo, new)                 # the merged map must load: refuse a field that breaks it
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(new, indent=1) + "\n", encoding="utf-8")
        tmp.replace(path)
        with _cache_lock:
            _cache.pop(path, None)
    return load(map_id)


def unpromote(map_id: str, name: str) -> bool:
    path = overlay_path(map_id)
    if path is None or not path.is_file():
        return False
    with _write_lock:
        cur = _json(path) or {}
        if name not in (cur.get("fields") or {}):
            return False
        cur = {**cur, "fields": {k: v for k, v in cur["fields"].items() if k != name}}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur, indent=1) + "\n", encoding="utf-8")
        tmp.replace(path)
        with _cache_lock:
            _cache.pop(path, None)
    return True


def check(path) -> list[str]:
    """Problems with a map file ([] = it loads)."""
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
        m = RamMap(spec, Path(path))
    except (OSError, ValueError) as e:
        return [str(e)]
    out = []
    if not Path(path).name.startswith(m.id):
        out.append(f"file name should be {m.id}{SUFFIX}")
    for f in m.fields.values():
        if not f.source:
            out.append(f"{f.name}: no source (ghidra | scan | manual)")
    return out


def main(argv=None) -> int:
    """python -m gbox.ram_map check <map.json>... | read <map id> --pid <dolphin pid> [--names a,b]"""
    import argparse
    ap = argparse.ArgumentParser(prog="python -m gbox.ram_map")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="validate map files")
    c.add_argument("files", nargs="+")
    r = sub.add_parser("read", help="read a map once from a running Dolphin (Linux, read-only shared memory)")
    r.add_argument("map")
    r.add_argument("--pid", type=int, required=True, help="the session's Dolphin (or its flatpak / bwrap parent)")
    r.add_argument("--names", default="")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        bad = 0
        for f in a.files:
            problems = check(f)
            print(f"{f}: " + ("ok" if not problems else "; ".join(problems)))
            bad += bool(problems)
        return 1 if bad else 0
    from .ram_reader import shm_for_pid
    shm = shm_for_pid(a.pid)
    if shm is None:
        print(f"no Dolphin RAM view under pid {a.pid}")
        return 1
    m = load(a.map)
    vals = m.read(shm, names=[n for n in a.names.split(",") if n] or None)
    for row in vals.rows():
        print(f"{row['name']:28} {row.get('display')}" + (f"   ! {row['error']}" if row.get("error") else ""))
        for r_ in row.get("rows") or []:
            print(f"{'':30}{r_}")
    print(f"({vals.reads} reads, {vals.bytes} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
