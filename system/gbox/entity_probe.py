"""Generic entity probe: name the game entity under a screen point from live (or dumped) memory and a profile.

The probe only needs `read(address, length) -> bytes` (an adapter's read_memory, or any callable) and a semantic profile
(profiles/*.json) whose `entities` block uses layout "struct_array" and whose `camera` block uses layout
"pos_angles_fov".  It walks the game's own entity table, reads each entity's class, model reference and world position,
projects the entity's world box through the game's own camera, and answers `under_point(x, y)`.

Profile contract (every address is a hex string or int; every field spec is [type, offset] or [type, offset, scope]):

  entities:
    layout          "struct_array"
    base_pointer    address of the u32 that holds the table base (or `base`: a fixed table address)
    count           address of the u32 entity count (or `count_fixed`), `count_max` caps it (default 1024)
    stride          record size in bytes
    pointer_range   [lo, hi]: table base and object pointers must fall inside (bad memory is skipped, not raised)
    inuse           optional record field; a zero value means the slot is free
    object          optional record field ("ptr"): the per-entity object that object-scoped fields are read from
    fields          name -> spec.  Scope "record" reads from the table record, "object" from the object (default:
                    object when `object` exists, else record).  Types: u8 i8 u16 i16 u32 i32 f32 ptr f32x3
                    cstr<N> (inline chars) ptrstr (pointer to chars) strobj (pointer -> {char *data,...} -> chars)
                    vptr (u32 looked up in `classes`).
    classes         vtable address -> {"name", "super", "size"} (the C++ class table recovered from the executable)
    kind_roots      ordered [[class, kind], ...]: an entity's kind is the first root found in its superclass chain
    kinds           optional classic rules ({"name", "name_prefix": [...]}) matched against the class name
    position        name of the field holding the world position (default "position")
    box             optional {"min": field, "max": field, "world": bool}: world-space AABB fields, or local
                    mins/maxs that are added to the position
    viewer          optional {"field": name, "equals": "camera_client"}: marks the entity that owns the camera
    flags           optional [{"name", "field", "mask"}]: named bits of an integer field (e.g. hidden, rendered)
  camera:
    layout          "pos_angles_fov"
    clients_pointer address of the u32 that holds the client-array base (or `base`: a fixed address)
    client_stride   address of a u32 holding the stride, or an int
    client_index    address of a u32 holding the viewed client index, or an int (default 0)
    client_count    optional address of a u32 bound for the index
    eye, angles, fov  client-scoped specs (f32x3, f32x3, f32)
    override        optional {"flags": spec, "mask": int, "eye", "angles", "fov"}: a scripted camera that replaces
                    the player view while (flags & mask) != 0
    angles          "quake": [pitch, yaw, roll] degrees, z up, forward = (cos p cos y, cos p sin y, -sin p)
    fov_axis        "vertical" | "horizontal" (which axis `fov` spans)
    aspect          "4:3" | "16:9" | number (default 4:3), near (default 1.0)

Nothing here raises on garbage memory: unreadable or implausible values are skipped and listed in `diagnostics`.
"""
from __future__ import annotations

import math
import struct

FMT = {"u8": "B", "i8": "b", "u16": "H", "i16": "h", "u32": "I", "i32": "i", "f32": "f", "ptr": "I"}
SIZES = {k: struct.calcsize(v) for k, v in FMT.items()}
SIZES["f32x3"] = 12
SIZES["vptr"] = 4
SIZES["ptrstr"] = 4
SIZES["strobj"] = 4
MAX_STRING = 96
KIND_RANK = {"bot": 0, "npc": 0, "player": 1, "corpse": 2, "vehicle": 3, "item": 4, "weapon": 5, "other": 6}


def _int(v) -> int:
    return int(v, 16) if isinstance(v, str) else int(v)


def _ratio(v) -> float:
    if isinstance(v, str) and ":" in v:
        a, b = v.split(":", 1)
        return float(a) / float(b)
    return float(v)


def _printable(b: bytes) -> str:
    s = b.split(b"\0")[0]
    return s.decode("latin-1", "replace") if all(32 <= c < 127 for c in s) else ""


def validate_profile(profile: dict) -> list[str]:
    """Everything the probe does not understand in a profile, as messages (empty = fine)."""
    problems = []
    ent = profile.get("entities") or {}
    if ent.get("layout") != "struct_array":
        problems.append("entities.layout must be 'struct_array'")
    if not (ent.get("base_pointer") or ent.get("base")):
        problems.append("entities needs base_pointer or base")
    if not (ent.get("count") or ent.get("count_fixed")):
        problems.append("entities needs count or count_fixed")
    if not ent.get("stride"):
        problems.append("entities needs stride")
    specs = dict(ent.get("fields") or {})
    for k in ("inuse", "object"):
        if ent.get(k):
            specs[k] = ent[k]
    for name, spec in specs.items():
        if not isinstance(spec, (list, tuple)) or len(spec) < 2:
            problems.append(f"field {name}: spec must be [type, offset(, scope)]")
            continue
        typ = spec[0]
        if not (typ in SIZES or (typ.startswith("cstr") and typ[4:].isdigit())):
            problems.append(f"field {name}: unknown type {typ}")
        if len(spec) > 2 and spec[2] not in ("record", "object"):
            problems.append(f"field {name}: scope must be record or object")
        try:
            _int(spec[1])
        except (TypeError, ValueError):
            problems.append(f"field {name}: bad offset {spec[1]!r}")
    pos = ent.get("position", "position")
    if pos not in (ent.get("fields") or {}):
        problems.append(f"entities.fields has no position field {pos!r}")
    for rule in ent.get("flags") or []:
        if not {"name", "field", "mask"} <= set(rule) or rule["field"] not in (ent.get("fields") or {}):
            problems.append(f"flags: bad rule {rule!r}")
    box = ent.get("box")
    if box and not ({"min", "max"} <= set(box) and box["min"] in ent.get("fields", {}) and box["max"] in ent.get("fields", {})):
        problems.append("entities.box must name min/max fields")
    viewer = ent.get("viewer")
    if viewer and viewer.get("field") not in (ent.get("fields") or {}):
        problems.append("entities.viewer.field must be a field")
    for cls, info in (ent.get("classes") or {}).items():
        try:
            _int(cls)
        except (TypeError, ValueError):
            problems.append(f"classes: bad vtable key {cls!r}")
        if not isinstance(info, dict) or "name" not in info:
            problems.append(f"classes[{cls}]: needs a name")
    cam = profile.get("camera") or {}
    if cam.get("layout") != "pos_angles_fov":
        problems.append("camera.layout must be 'pos_angles_fov'")
    if not (cam.get("clients_pointer") or cam.get("base")):
        problems.append("camera needs clients_pointer or base")
    for k in ("eye", "angles", "fov"):
        if k not in cam:
            problems.append(f"camera needs {k}")
    for k, want in (("eye", "f32x3"), ("angles", "f32x3"), ("fov", "f32")):
        if k in cam and cam[k][0] != want:
            problems.append(f"camera.{k} must be {want}")
    if cam.get("fov_axis", "vertical") not in ("vertical", "horizontal"):
        problems.append("camera.fov_axis must be vertical or horizontal")
    if cam.get("angles_convention", "quake") != "quake":
        problems.append("camera.angles_convention: only 'quake' is implemented")
    return problems


class Camera:
    """A look-through camera: eye, orthonormal basis, field of view. project() maps world -> normalized screen."""

    def __init__(self, eye, angles, fov_deg, fov_axis="vertical", aspect=4 / 3, near=1.0, source="view"):
        self.eye = [float(v) for v in eye]
        self.angles = [float(v) for v in angles]
        self.fov_deg = float(fov_deg)
        self.fov_axis = fov_axis
        self.aspect = float(aspect)
        self.near = float(near)
        self.source = source
        p, y, r = (math.radians(a) for a in self.angles)
        sp, cp, sy, cy, sr, cr = math.sin(p), math.cos(p), math.sin(y), math.cos(y), math.sin(r), math.cos(r)
        self.forward = [cp * cy, cp * sy, -sp]                                   # Quake AngleVectors (z up)
        self.right = [-sr * sp * cy + cr * sy, -sr * sp * sy - cr * cy, -sr * cp]
        self.up = [cr * sp * cy + sr * sy, cr * sp * sy - sr * cy, cr * cp]
        fov = min(max(self.fov_deg, 1.0), 179.0)
        self.cot = 1.0 / math.tan(math.radians(fov) / 2)

    def project(self, point):
        """(sx, sy, depth) with sx, sy in 0..1 across/down the picture; None when behind the near plane."""
        d = [float(point[i]) - self.eye[i] for i in range(3)]
        zc = sum(d[i] * self.forward[i] for i in range(3))
        if not math.isfinite(zc) or zc <= self.near:
            return None
        xc = sum(d[i] * self.right[i] for i in range(3))
        yc = sum(d[i] * self.up[i] for i in range(3))
        if self.fov_axis == "vertical":
            sx = 0.5 + 0.5 * (xc / zc) * self.cot / self.aspect
            sy = 0.5 - 0.5 * (yc / zc) * self.cot
        else:
            sx = 0.5 + 0.5 * (xc / zc) * self.cot
            sy = 0.5 - 0.5 * (yc / zc) * self.cot * self.aspect
        return sx, sy, zc

    def as_dict(self) -> dict:
        return {"eye": [round(v, 3) for v in self.eye], "angles": [round(v, 3) for v in self.angles],
                "fov": round(self.fov_deg, 3), "fov_axis": self.fov_axis, "aspect": round(self.aspect, 4),
                "forward": [round(v, 4) for v in self.forward], "source": self.source}


def _cam_fields(c) -> tuple | None:
    if c is None:
        return None
    if isinstance(c, Camera):
        return c.eye, c.angles, c.fov_deg, c.source
    return c.get("eye"), c.get("angles"), c.get("fov"), c.get("source")


def camera_delta(a, b, cut_eye: float = 64.0, cut_angle: float = 15.0) -> dict:
    """How far the camera moved between two reads (Camera or Camera.as_dict()). `cut` is true for a shot change: the
    scripted/view source flipped, the fov changed, the eye jumped more than `cut_eye` world units or an angle turned more
    than `cut_angle` degrees. A pick or drop-point frame paired with RAM across a cut names the wrong entity (#1438 m3)."""
    fa, fb = _cam_fields(a), _cam_fields(b)
    ok_a = fa is not None and None not in fa[:3]
    ok_b = fb is not None and None not in fb[:3]
    if not (ok_a and ok_b):
        # neither read has a camera (title, FMV, loading: AUF's g_entities/gClientArr are null, seen live on the Spark
        # 2026-10-13): nothing to compare, so no cut. A camera that appears or vanishes between the reads is a cut.
        return {"eye": None, "angle": None, "fov": None, "source_changed": None, "cut": ok_a != ok_b, "readable": False}
    eye = math.dist([float(v) for v in fa[0]], [float(v) for v in fb[0]])
    ang = max(abs((float(x) - float(y) + 180.0) % 360.0 - 180.0) for x, y in zip(fa[1], fb[1]))
    fov = abs(float(fa[2]) - float(fb[2]))
    src = fa[3] != fb[3]
    cut = bool(src or fov > 0.5 or eye > cut_eye or ang > cut_angle)
    return {"eye": round(eye, 3), "angle": round(ang, 3), "fov": round(fov, 3), "source_changed": src, "cut": cut,
            "readable": True}


class Probe:
    def __init__(self, profile: dict, read, max_entities: int | None = None):
        self.p = profile
        self._read = read.read_memory if hasattr(read, "read_memory") else read
        self.end = ">" if profile.get("endian", "big") == "big" else "<"
        self.diagnostics: list[str] = []
        ent = profile["entities"]
        self.max_entities = int(max_entities or ent.get("count_max", 1024))
        lo, hi = ent.get("pointer_range", ["0x0", "0xFFFFFFFF"])
        self.lo, self.hi = _int(lo), _int(hi)
        self._classes = {_int(k): v for k, v in (ent.get("classes") or {}).items()}
        self._by_name = {v["name"]: v for v in self._classes.values()}
        self._kind_cache: dict = {}
        self._str_cache: dict = {}

    # --- memory ---------------------------------------------------------------------------------------------------
    def read(self, addr: int, n: int) -> bytes | None:
        if addr < 0 or addr + n > 0xFFFFFFFF or n <= 0:
            return None
        try:
            b = self._read(addr, n)
        except Exception as e:                                             # noqa: BLE001 - garbage memory never raises
            self._note(f"read {addr:#010x}+{n}: {type(e).__name__}: {e}")
            return None
        if not isinstance(b, (bytes, bytearray)) or len(b) < n:
            self._note(f"read {addr:#010x}+{n}: short read")
            return None
        return bytes(b)

    def _note(self, msg: str):
        if len(self.diagnostics) < 200:
            self.diagnostics.append(msg)

    def u32(self, addr: int) -> int | None:
        b = self.read(addr, 4)
        return struct.unpack(self.end + "I", b)[0] if b else None

    def _addr_or_value(self, v, deref: bool):
        """Profile values are either an address to read a u32 from (deref) or a literal."""
        if v is None:
            return None
        return self.u32(_int(v)) if deref else _int(v)

    def in_range(self, ptr: int | None) -> bool:
        return ptr is not None and self.lo <= ptr < self.hi

    def cstring(self, addr: int) -> str | None:
        if addr in self._str_cache:
            return self._str_cache[addr]
        out = None
        if self.in_range(addr):
            b = self.read(addr, MAX_STRING)
            out = _printable(b) if b else None
            out = out or None
        self._str_cache[addr] = out
        return out

    def field(self, blob: bytes, base: int, spec) -> object:
        """One field from a record/object blob already read from `base`."""
        typ, off = spec[0], _int(spec[1])
        if typ.startswith("cstr"):
            n = int(typ[4:])
            return _printable(blob[off:off + n]) if off + n <= len(blob) else None
        size = SIZES.get(typ)
        if size is None or off + size > len(blob):
            return None
        if typ == "f32x3":
            v = struct.unpack_from(self.end + "3f", blob, off)
            return [round(x, 3) for x in v] if all(math.isfinite(x) for x in v) else None
        raw = struct.unpack_from(self.end + FMT.get(typ, "I"), blob, off)[0]
        if typ == "f32":
            return round(raw, 3) if math.isfinite(raw) else None
        if typ == "ptrstr":
            return self.cstring(raw)
        if typ == "strobj":                                   # str -> strdata {char *data, refcount, alloced, len}
            if not self.in_range(raw):
                return None
            data = self.u32(raw)
            return self.cstring(data) if self.in_range(data) else None
        if typ == "vptr":
            info = self._classes.get(raw)
            return info["name"] if info else None
        return raw

    # --- classes ----------------------------------------------------------------------------------------------------
    def class_chain(self, name: str | None) -> list[str]:
        out, seen = [], set()
        while name and name in self._by_name and name not in seen:
            out.append(name)
            seen.add(name)
            name = self._by_name[name].get("super")
        return out

    def kind_of(self, class_name: str | None) -> str:
        if class_name in self._kind_cache:
            return self._kind_cache[class_name]
        kind = "unknown"
        chain = self.class_chain(class_name)
        for root, k in self.p["entities"].get("kind_roots", []):
            if root in chain:
                kind = k
                break
        else:
            for rule in self.p["entities"].get("kinds", []):
                if "name_prefix" in rule and class_name and any(class_name.startswith(x) for x in rule["name_prefix"]):
                    kind = rule["name"]
                    break
            else:
                if chain:
                    kind = "other"
        self._kind_cache[class_name] = kind
        return kind

    # --- entities ---------------------------------------------------------------------------------------------------
    def table(self) -> tuple[int, int, int] | None:
        """(base, count, stride) of the entity table, or None with a diagnostic."""
        ent = self.p["entities"]
        base = self._addr_or_value(ent.get("base_pointer"), True) if ent.get("base_pointer") else _int(ent["base"])
        if not self.in_range(base):
            self._note(f"entity table base {base!r} outside pointer_range")
            return None
        count = self._addr_or_value(ent.get("count"), True) if ent.get("count") else _int(ent.get("count_fixed", 0))
        if count is None:
            self._note("entity count unreadable")
            return None
        if count > self.max_entities:
            self._note(f"entity count {count} capped to {self.max_entities}")
            count = self.max_entities
        stride = _int(ent["stride"])
        if stride <= 0 or count < 0:
            self._note(f"bad stride/count {stride}/{count}")
            return None
        return base, count, stride

    def entities(self) -> list[dict]:
        ent = self.p["entities"]
        t = self.table()
        if not t:
            return []
        base, count, stride = t
        fields = ent.get("fields") or {}
        obj_spec = ent.get("object")
        default_scope = "object" if obj_spec else "record"
        obj_size = max([_int(s[1]) + SIZES.get(s[0], int(s[0][4:]) if s[0].startswith("cstr") else 4)
                        for s in fields.values() if (s[2] if len(s) > 2 else default_scope) == "object"] + [0])
        out = []
        for i in range(count):
            rec_addr = base + i * stride
            rec = self.read(rec_addr, stride)
            if rec is None:
                self._note(f"slot {i}: record unreadable")
                continue
            if ent.get("inuse") and not self.field(rec, rec_addr, ent["inuse"]):
                continue
            obj_addr, obj = None, None
            if obj_spec:
                obj_addr = self.field(rec, rec_addr, obj_spec)
                if not self.in_range(obj_addr):
                    if obj_addr:
                        self._note(f"slot {i}: object pointer {obj_addr:#010x} outside pointer_range")
                    continue
                obj = self.read(obj_addr, obj_size)
                if obj is None:
                    self._note(f"slot {i}: object {obj_addr:#010x} unreadable")
                    continue
            e = {"index": i, "record": rec_addr, "object": obj_addr, "ptr": f"{(obj_addr or rec_addr):08X}", "slot": i}
            for name, spec in fields.items():
                scope = spec[2] if len(spec) > 2 else default_scope
                if scope == "object":
                    e[name] = self.field(obj, obj_addr, spec) if obj is not None else None
                else:
                    e[name] = self.field(rec, rec_addr, spec)
            pos = e.get(ent.get("position", "position"))
            if not (isinstance(pos, list) and len(pos) == 3 and all(abs(v) < 1e6 for v in pos)):
                self._note(f"slot {i}: no finite position")
                continue
            e["x"], e["y"], e["z"] = pos
            cls = e.get("class")
            e["kind"] = self.kind_of(cls) if cls else (self.kind_of(e.get("classname")) if e.get("classname") else "unknown")
            if "class" not in e:
                e["class"] = e.get("classname")
            info = self._by_name.get(cls or "")
            if info:
                e["class_size"] = info.get("size")
            for rule in ent.get("flags", []):
                v = e.get(rule["field"])
                e[rule["name"]] = bool(v & _int(rule["mask"])) if isinstance(v, int) else None
            e["box"] = self._world_box(e)
            out.append(e)
        return out

    def _world_box(self, e: dict) -> list | None:
        box = self.p["entities"].get("box")
        if not box:
            return None
        lo, hi = e.get(box["min"]), e.get(box["max"])
        if not (isinstance(lo, list) and isinstance(hi, list)):
            return None
        if not box.get("world", True):
            lo = [e["x"] + lo[0], e["y"] + lo[1], e["z"] + lo[2]]
            hi = [e["x"] + hi[0], e["y"] + hi[1], e["z"] + hi[2]]
        if any(hi[i] < lo[i] for i in range(3)) or any(abs(v) > 1e6 for v in lo + hi):
            return None
        if all(hi[i] - lo[i] < 1e-3 for i in range(3)):           # degenerate (unlinked) box: no use for picking
            return None
        return [lo, hi]

    # --- camera -----------------------------------------------------------------------------------------------------
    def camera_client(self) -> int | None:
        cam = self.p["camera"]
        base = self._addr_or_value(cam.get("clients_pointer"), True) if cam.get("clients_pointer") else _int(cam["base"])
        if not self.in_range(base):
            self._note(f"client array base {base!r} outside pointer_range")
            return None
        stride = cam.get("client_stride", 0)
        stride = self.u32(_int(stride)) if isinstance(stride, str) else int(stride)
        idx = cam.get("client_index", 0)
        idx = self.u32(_int(idx)) if isinstance(idx, str) else int(idx)
        if stride is None or idx is None or stride <= 0 or stride > 0x100000 or idx < 0 or idx > 64:
            self._note(f"implausible client stride/index {stride}/{idx}")
            return None
        if cam.get("client_count"):
            n = self.u32(_int(cam["client_count"]))
            if n is not None and idx >= n:
                self._note(f"client index {idx} >= count {n}; using 0")
                idx = 0
        return base + idx * stride

    def camera(self) -> Camera | None:
        cam = self.p["camera"]
        client = self.camera_client()
        if client is None:
            return None
        size = max(_int(s[1]) + SIZES[s[0]] for s in (cam["eye"], cam["angles"], cam["fov"]))
        ov = cam.get("override")
        if ov:
            size = max(size, *(_int(s[1]) + SIZES[s[0]] for s in (ov["eye"], ov["angles"], ov["fov"], ov["flags"])))
        blob = self.read(client, size)
        if blob is None:
            self._note(f"client {client:#010x} unreadable")
            return None
        source = "view"
        eye, angles, fov = (self.field(blob, client, cam[k]) for k in ("eye", "angles", "fov"))
        if ov:
            flags = self.field(blob, client, ov["flags"])
            if flags is not None and flags & _int(ov.get("mask", 0xFFFFFFFF)):
                e2, a2, f2 = (self.field(blob, client, ov[k]) for k in ("eye", "angles", "fov"))
                if e2 and a2 and f2:
                    eye, angles, fov, source = e2, a2, f2, "scripted"
        if not (eye and angles and fov and 0.5 < fov < 179 and all(abs(v) < 1e6 for v in eye + angles)):
            self._note(f"implausible camera eye={eye} angles={angles} fov={fov}")
            return None
        return Camera(eye, angles, fov, cam.get("fov_axis", "vertical"), _ratio(cam.get("aspect", "4:3")),
                      float(cam.get("near", 1.0)), source)

    # --- projection and picking -------------------------------------------------------------------------------------
    def _cut_limits(self) -> tuple[float, float]:
        cam = self.p.get("camera") or {}
        return float(cam.get("cut_eye", 64.0)), float(cam.get("cut_angle", 15.0))

    def recheck(self, scan: dict) -> dict:
        """Read the camera again and compare it with the one `scan` projected through. Call it right after the frame
        the operator clicked was taken: `cut` true means RAM and picture show different shots, so re-take both."""
        before = scan.get("camera")
        now = self.camera()
        d = camera_delta(before, now, *self._cut_limits())
        d["stable"] = not d["cut"]
        d["camera_now"] = now.as_dict() if now else None
        return d

    def scan(self, width: int = 640, height: int = 480, entities: list | None = None,
             camera_before=None, retries: int = 1) -> dict:
        """Entities with screen coordinates in pixels (width x height) and the camera used; what fails is reported.
        `entities` reuses a list this probe (or semantic.Extractor) already read instead of walking the table again;
        pass `camera_before` (a camera read before that list) so a shot change during the read is still detected.
        When the probe walks the table itself it reads the camera before and after, and re-walks up to `retries` times
        if a cut fell in between. scan["camera_check"] reports whether entities and camera belong to one shot."""
        limits = self._cut_limits()
        if entities is None:
            first = self.camera()
            ents = self.entities()
            cam = self.camera()
            tries = 0
            while first is not None and cam is not None and camera_delta(first, cam, *limits)["cut"] and tries < retries:
                tries += 1
                first, ents, cam = cam, self.entities(), self.camera()
            check = camera_delta(first, cam, *limits) if first is not None else None
        else:
            ents = entities
            cam = self.camera()
            tries = 0
            check = camera_delta(camera_before, cam, *limits) if camera_before is not None else None
        if check is not None:
            check["stable"] = not check["cut"]
            check["retried"] = tries
            if check["cut"]:
                self._note(f"camera cut while reading entities (eye {check['eye']}, angle {check['angle']}, "
                           f"fov {check['fov']}); screen boxes may belong to the previous shot")
        viewer = self.p["entities"].get("viewer")
        client = self.camera_client() if viewer else None
        for e in ents:
            e["is_viewer"] = bool(viewer and client is not None and e.get(viewer["field"]) == client)
            e["screen"], e["screen_box"], e["depth"] = None, None, None
            if cam is None:
                continue
            p = cam.project((e["x"], e["y"], e["z"]))
            if p:
                e["screen"] = [round(p[0] * width, 1), round(p[1] * height, 1)]
                e["depth"] = round(p[2], 2)
            if e.get("box"):
                lo, hi = e["box"]
                pts = [cam.project((x, y, z)) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
                vis = [q for q in pts if q]
                if len(vis) == 8:
                    xs, ys = [q[0] * width for q in vis], [q[1] * height for q in vis]
                    e["screen_box"] = [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)]
                    e["depth"] = round(min(q[2] for q in vis), 2)
                elif vis:
                    e["screen_box"] = None
                    e["box_partial"] = True
            if e["screen"] is None and e["screen_box"] is None:
                e["behind_camera"] = True
        return {"entities": ents, "camera": cam.as_dict() if cam else None, "frame": [width, height],
                "camera_check": check, "diagnostics": list(self.diagnostics)}

    @staticmethod
    def under_point(x: float, y: float, scan: dict, tolerance: float = 0.06, include_viewer: bool = False) -> dict:
        """Nearest entity whose projected box (or point, within `tolerance` of the frame width) contains (x, y) pixels.
        Creatures (bots/NPCs/players) win over props at the same spot; nearer wins among equals."""
        w, h = scan.get("frame", [640, 480])
        tol = tolerance * w
        hits, near = [], []
        ents = scan.get("entities", [])
        owners = {_twin_key(e): e for e in ents if e.get("class") not in TWIN_CLASSES}
        for e in ents:
            if (e.get("is_viewer") and not include_viewer) or e.get("kind") == "world":
                continue
            if e.get("class") in TWIN_CLASSES and (o := owners.get(_twin_key(e))) is not None:
                continue                      # AUF live table: each player/bot has a ClonePlayer twin; name the owner
            rank = KIND_RANK.get(e.get("kind"), 6)
            box = e.get("screen_box")
            if box:
                x0, y0, x1, y1 = box
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                if x0 - 2 <= x <= x1 + 2 and y0 - 2 <= y <= y1 + 2:
                    hits.append((rank, e.get("depth") or 1e9, math.hypot(x - cx, y - cy), e))
                    continue
                d = math.hypot(max(x0 - x, 0, x - x1), max(y0 - y, 0, y - y1))
            elif e.get("screen"):
                d = math.hypot(x - e["screen"][0], y - e["screen"][1])
            else:
                continue
            if d <= tol:
                near.append((d, rank, e.get("depth") or 1e9, e))
        if hits:
            hits.sort(key=lambda t: (t[0], t[1], t[2]))
            best = hits[0][3]
            return {"entity": best, "contained": True, "miss": 0.0,
                    "others": [t[3] for t in hits[1:4]] + [t[3] for t in sorted(near)[:2]]}
        if near:
            near.sort(key=lambda t: (t[0], t[1], t[2]))
            return {"entity": near[0][3], "contained": False, "miss": round(near[0][0], 1), "others": [t[3] for t in near[1:4]]}
        return {"entity": None, "contained": False, "miss": None, "others": []}


# Render twins that copy their owner's model and origin every frame (AUF multiplayer, verified live on
# JAYBUILTFINALE 2026-10-12: records 108/111/114/117 mirror the player and bots 0..3).
TWIN_CLASSES = {"ClonePlayer"}


def _twin_key(e: dict):
    return (e.get("model"), round(e.get("x") or 0.0, 1), round(e.get("y") or 0.0, 1), round(e.get("z") or 0.0, 1))


def scan(profile: dict, read, width: int = 640, height: int = 480) -> dict:
    return Probe(profile, read).scan(width, height)


def under_point(profile: dict, read, x: float, y: float, width: int = 640, height: int = 480) -> dict:
    s = Probe(profile, read).scan(width, height)
    out = Probe.under_point(x, y, s)
    out["camera"], out["diagnostics"], out["count"] = s["camera"], s["diagnostics"], len(s["entities"])
    return out


def summary(e: dict) -> dict:
    """The compact per-entity record the pick tool and the UI show."""
    keys = ("index", "ptr", "class", "kind", "model", "modelindex", "classname", "x", "y", "z", "screen", "screen_box",
            "depth", "is_viewer", "hidden", "class_size")
    return {k: e.get(k) for k in keys if k in e}


def _main(argv=None):
    """Offline check on a RAM dump: python -m gbox.entity_probe PROFILE.json ram.raw [--base 0x80000000]
    [--frame 640x480] [--point X,Y].  Dolphin's "Dump MEM1" writes the 24 MiB at 0x80000000."""
    import argparse
    import json
    ap = argparse.ArgumentParser(description=_main.__doc__)
    ap.add_argument("profile")
    ap.add_argument("dump")
    ap.add_argument("--base", default="0x80000000")
    ap.add_argument("--frame", default="640x480")
    ap.add_argument("--point", help="X,Y in frame pixels: name what is under it")
    ap.add_argument("--all", action="store_true", help="print every entity, not only creatures")
    a = ap.parse_args(argv)
    profile = json.load(open(a.profile, encoding="utf-8"))
    data, base = open(a.dump, "rb").read(), int(a.base, 16)

    def read(addr, n):
        o = addr - base
        if o < 0 or o + n > len(data):
            raise ValueError(f"{addr:#010x} outside the dump")
        return data[o:o + n]
    w, h = (int(v) for v in a.frame.lower().split("x"))
    pr = Probe(profile, read)
    s = pr.scan(w, h)
    print(json.dumps({"camera": s["camera"], "entities": len(s["entities"]), "diagnostics": s["diagnostics"][:10]}, indent=1))
    for e in s["entities"]:
        if a.all or e.get("kind") in ("player", "bot", "npc", "corpse", "vehicle"):
            print(json.dumps(summary(e)))
    if a.point:
        x, y = (float(v) for v in a.point.split(","))
        hit = Probe.under_point(x, y, s)
        print("under point:", json.dumps(summary(hit["entity"]) if hit["entity"] else None), "miss", hit["miss"])


if __name__ == "__main__":
    _main()
