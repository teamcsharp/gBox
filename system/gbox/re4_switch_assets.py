"""RE4 (Switch, title 010099A00BC1E000) asset files: UDAS/DAT packs, HD BIN models, TPL tables and ImagePackHD archives.

Every reader here keeps what it does not interpret, so `parse(x).build() == x` holds for the real files (measured on
the 27 player packs, eight Ganado packs, `etc/core.udas`, the loose `etc/pl*.bin|tpl` and the 27 player texture
archives - see docs/research/re4-switch-model-replacement.md). A file that round-trips is not a working mod: nothing
in this module has been seen by the running game.

The layouts are the "PS4/NS" (64-bit pointer) variant of the 2014 UHD formats. Where a field name comes from the public
UHD tooling rather than from a measurement here, the docstring says so.

    UDAS  0x20 fill, 32-byte entries (type, size, 0, offset), 0xFFFFFFFF, sections at 0x400+; a second header block
          (sound) follows the DAT. The bytes between the two are residue of the build tool and are kept verbatim.
    DAT   count, 12 zero bytes, u32 offsets, 4-char extensions, slots back to back (each a multiple of 32 bytes).
    BIN   0x98 header of 64-bit section offsets and counts, then sections (bones, weight sets, positions, normals, ...).
    TPL   0x12345678, count, 16-byte table, 40-byte image headers, then (pack id, index) per image. No pixels.
    FEN   `<pack id:08x>.pack.fen`: u32 raw size + zlib (level 6) of: pack id, count, u64 offsets, 16-byte wrapper + DDS.

The texture join is TPL image -> (pack id, index) -> `bio4/imagepackhd/<pack id:08x>.pack.fen` entry `index`.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

import numpy as np

UDAS_FILL = bytes.fromhex("cab6be20") * 8
UDAS_HEAD = 0x400
TPL_MAGIC = 0x12345678
BIN_HEAD = 0x98
#: Section offsets in the BIN header: name -> (field offset, field size in bytes).
BIN_POINTERS = {"bones": (0x00, 8), "colors": (0x10, 8), "uvs": (0x18, 8), "weights": (0x20, 8),
                "materials": (0x30, 8), "morph": (0x44, 4), "positions": (0x48, 8), "normals": (0x50, 8),
                "bonepair": (0x60, 8), "adjacent": (0x68, 8), "weight_index": (0x70, 8),
                "weight_index2": (0x78, 8)}
#: 32-bit copies of two offsets, each exactly 0x38 below the 64-bit one (0x38 = this header minus the PC one).
BIN_LEGACY = {"weight_index": 0x80, "weight_index2": 0x84}
PRIM_LIST, PRIM_STRIP, PRIM_QUADS = 5, 6, 8
#: Length of a native normal: the port stores the GameCube's signed-byte normals as floats scaled by 2**32.
NORMAL_SCALE = 127.0 * 2.0 ** 32
FEN_ZLIB_LEVEL = 6


class AssetError(ValueError):
    """The bytes are not the layout this module measured; nothing is guessed past that point."""


def _need(ok: bool, message: str) -> None:
    if not ok:
        raise AssetError(message)


def _pad(data: bytes, align: int = 32, phase: int = 0) -> bytes:
    """`data` zero-padded so its length is `phase` modulo `align`."""
    return data + b"\0" * ((phase - len(data)) % align)


# ----------------------------------------------------------------------------------------------------------- UDAS

@dataclass
class Udas:
    """A `.udas` pack. `dat` is the model/animation DAT; everything else is carried verbatim.

    `head` is the first 0x400 bytes (its size and offset fields are rewritten by `build`), `lead` the bytes between
    0x400 and the DAT, `slack` the bytes between the DAT and the next section, `rest` everything from that section on
    (the sound block: its own 0x400 header, whose offsets are relative to itself, and its data).
    """
    head: bytes
    lead: bytes
    dat: bytes
    slack: bytes
    rest: bytes
    entries: list[tuple[int, int, int]] = field(default_factory=list)      # (type, size, offset) as parsed

    @classmethod
    def parse(cls, data: bytes) -> "Udas":
        _need(len(data) >= UDAS_HEAD and data[:0x20] == UDAS_FILL, "not a little-endian UDAS (fill at 0x00)")
        entries, at = [], 0x20
        while True:
            _need(at + 4 <= UDAS_HEAD, "UDAS table has no 0xFFFFFFFF terminator inside 0x400 bytes")
            if struct.unpack_from("<I", data, at)[0] == 0xFFFFFFFF:
                break
            kind, size, _zero, offset = struct.unpack_from("<4I", data, at)
            entries.append((kind, size, offset))
            at += 32
        _need(bool(entries) and entries[0][0] == 0, "the first UDAS entry is not a DAT (type 0)")
        _kind, size, offset = entries[0]
        end = offset + size
        _need(UDAS_HEAD <= offset and end <= len(data), "the DAT entry is outside the file")
        if len(entries) > 1:
            following = entries[1][2]
            _need(end <= following <= len(data), "the section after the DAT is misplaced")
            _need(all(e[2] >= following for e in entries[1:]), "UDAS sections are not in file order")
        else:
            following = end
        return cls(head=data[:UDAS_HEAD], lead=data[UDAS_HEAD:offset], dat=data[offset:end],
                   slack=data[end:following], rest=data[following:], entries=entries)

    def build(self) -> bytes:
        head = bytearray(self.head)
        offset = UDAS_HEAD + len(self.lead)
        shift = offset + len(self.dat) + len(self.slack) - (self.entries[1][2] if len(self.entries) > 1 else 0)
        struct.pack_into("<I", head, 0x24, len(self.dat))
        struct.pack_into("<I", head, 0x2C, offset)
        for index in range(1, len(self.entries)):
            struct.pack_into("<I", head, 0x20 + 32 * index + 12, self.entries[index][2] + shift)
        return bytes(head) + self.lead + self.dat + self.slack + self.rest


# ------------------------------------------------------------------------------------------------------------ DAT

@dataclass
class Dat:
    """A DAT: ordered slots of (extension, bytes). An empty slot has extension '' and no bytes.

    The game addresses slots by index (a player pack keeps the body at 0, its texture table at 1, the head at 2 ...),
    so a writer replaces a slot's bytes and never reorders.
    """
    slots: list[tuple[str, bytes]]
    reserved: bytes = b"\0" * 12          # the 12 bytes after the count
    gap: bytes = b""                      # the bytes between the tables and the first slot

    @classmethod
    def parse(cls, data: bytes) -> "Dat":
        _need(len(data) >= 16, "DAT too short")
        count = struct.unpack_from("<I", data, 0)[0]
        table = 16 + 8 * count
        _need(0 < count and table <= len(data), f"not a DAT (count {count} in {len(data)} bytes)")
        offsets = list(struct.unpack_from(f"<{count}I", data, 16))
        _need(offsets[0] >= table and all(a <= b for a, b in zip(offsets, offsets[1:])) and offsets[-1] <= len(data),
              "DAT offsets are not ascending inside the file")
        slots = []
        for index, start in enumerate(offsets):
            raw = data[16 + 4 * count + 4 * index:20 + 4 * count + 4 * index]
            stop = offsets[index + 1] if index + 1 < count else len(data)
            slots.append((raw.rstrip(b"\0").decode("latin-1"), data[start:stop]))
        return cls(slots=slots, reserved=data[4:16], gap=data[table:offsets[0]])

    def build(self) -> bytes:
        count = len(self.slots)
        _need(count > 0, "a DAT needs at least one slot")
        at = 16 + 8 * count + len(self.gap)
        offsets = []
        for _ext, payload in self.slots:
            offsets.append(at)
            at += len(payload)
        names = b"".join(ext.encode("latin-1")[:4].ljust(4, b"\0") for ext, _payload in self.slots)
        return (struct.pack("<I", count) + self.reserved + struct.pack(f"<{count}I", *offsets) + names + self.gap
                + b"".join(payload for _ext, payload in self.slots))

    def replace(self, index: int, payload: bytes | None, ext: str | None = None) -> None:
        """Put `payload` in slot `index` (None empties it). A payload must be a multiple of 32 bytes."""
        _need(0 <= index < len(self.slots), f"this DAT has {len(self.slots)} slots; {index} is out of range")
        if payload is None:
            self.slots[index] = ("", b"")
            return
        _need(len(payload) % 32 == 0, "a DAT slot is a multiple of 32 bytes")
        self.slots[index] = (self.slots[index][0] if ext is None else ext, bytes(payload))


def pack_slots(udas: bytes) -> tuple[Udas, Dat]:
    pack = Udas.parse(udas)
    return pack, Dat.parse(pack.dat)


def pack_build(pack: Udas, dat: Dat) -> bytes:
    pack.dat = dat.build()
    return pack.build()


# ------------------------------------------------------------------------------------------------------------ BIN

@dataclass
class Material:
    """One material record: a 24-byte header and the primitive runs drawn with it.

    The texture bytes are indices into the TPL the game binds to this BIN (which TPL that is, is decided by the
    game's code, not by the BIN). Byte 12 = diffuse is measured (the render samples the right art through it);
    the other names follow the public UHD tooling: 11 flag, 13 bump, 14 opacity, 15 specular map, 16-18 specular
    colour, 21 specular scale, 23 custom specular map. 0xFF means none.
    """
    header: bytes
    prims: list[tuple[int, int]]          # (primitive type, vertex count); vertices are consumed in order

    diffuse = property(lambda self: self.header[12])

    @property
    def vertex_count(self) -> int:
        return sum(count for _kind, count in self.prims)

    @property
    def triangle_count(self) -> int:
        total = 0
        for kind, count in self.prims:
            total += count // 3 if kind == PRIM_LIST else count - 2 if kind == PRIM_STRIP else count // 2
        return total

    def textures(self) -> list[int]:
        return [self.header[i] for i in (12, 13, 14, 15, 23) if self.header[i] != 0xFF]

    def remapped(self, table: dict[int, int]) -> "Material":
        header = bytearray(self.header)
        for i in (12, 13, 14, 15, 23):
            if header[i] != 0xFF:
                _need(header[i] in table, f"material texture index {header[i]} has no remap")
                header[i] = table[header[i]]
        return Material(bytes(header), list(self.prims))

    def encode(self) -> bytes:
        body = struct.pack("<I", len(self.prims)) + b"".join(struct.pack("<HH", k, c) for k, c in self.prims)
        body = _pad(body)
        return self.header + struct.pack("<II", len(body), self.triangle_count) + body


def _materials(section: bytes, count: int) -> tuple[list[Material], int]:
    out, at = [], 0
    for index in range(count):
        _need(at + 0x24 <= len(section), f"material {index} starts outside the table")
        size, triangles, prims = struct.unpack_from("<III", section, at + 0x18)
        _need(size == (4 + 4 * prims + 31) // 32 * 32 and at + 0x20 + size <= len(section),
              f"material {index}: primitive block of {size} bytes does not hold {prims} runs")
        runs = [struct.unpack_from("<HH", section, at + 0x24 + 4 * k) for k in range(prims)]
        _need(all(kind in (PRIM_LIST, PRIM_STRIP, PRIM_QUADS) for kind, _n in runs),
              f"material {index}: unknown primitive type")
        material = Material(section[at:at + 0x18], [(int(k), int(n)) for k, n in runs])
        _need(material.triangle_count == triangles, f"material {index}: triangle count disagrees with its runs")
        out.append(material)
        at += 0x20 + size
    return out, at


def triangles(materials: list[Material]) -> list[np.ndarray]:
    """Per material, an (n, 3) array of vertex indices. A strip alternates winding; quads split 0-1-2, 0-2-3.

    Strip (not fan) is measured: face normals from this reading agree with the stored vertex normals (mean dot 0.96
    on the Leon body), the fan reading gives 0.21.
    """
    out, base = [], 0
    for material in materials:
        faces = []
        for kind, count in material.prims:
            if kind == PRIM_LIST:
                faces += [(base + k, base + k + 1, base + k + 2) for k in range(0, count - 2, 3)]
            elif kind == PRIM_STRIP:
                faces += [(base + k, base + k + 1, base + k + 2) if k % 2 == 0 else (base + k + 1, base + k, base + k + 2)
                          for k in range(count - 2)]
            else:
                for k in range(0, count - 3, 4):
                    faces += [(base + k, base + k + 1, base + k + 2), (base + k, base + k + 2, base + k + 3)]
            base += count
        out.append(np.asarray(faces, np.int64).reshape(-1, 3))
    return out


@dataclass
class HdBin:
    """A model. `header` is the 0x98 bytes as read; `sections` are the raw section bytes in file order.

    Counts live in the header: weight sets u8@0x28 (and u16@0x42), bones u8@0x29, materials u16@0x2A, textures
    u32@0x3C, vertices u16@0x58 (normals u16@0x5A), version u32@0x5C (0x20030818 or 0x20010801).
    """
    header: bytes
    sections: dict[str, bytes]
    legacy: bool = True                    # the two 32-bit offset copies follow the 64-bit ones

    # -- counts ------------------------------------------------------------------------------------------------
    weight_count = property(lambda self: self.header[0x28])
    bone_count = property(lambda self: self.header[0x29])
    material_count = property(lambda self: struct.unpack_from("<H", self.header, 0x2A)[0])
    texture_count = property(lambda self: struct.unpack_from("<I", self.header, 0x3C)[0])
    vertex_count = property(lambda self: struct.unpack_from("<H", self.header, 0x58)[0])
    version = property(lambda self: struct.unpack_from("<I", self.header, 0x5C)[0])

    @classmethod
    def parse(cls, data: bytes, *, verify: bool = True) -> "HdBin":
        _need(len(data) >= BIN_HEAD, "BIN shorter than its header")
        _need(struct.unpack_from("<Q", data, 0)[0] == BIN_HEAD,
              "not an HD BIN: the bone table is not at 0x98 (the GameCube BIN header is 0x40/0x60)")
        found = []
        for name, (at, size) in BIN_POINTERS.items():
            value = struct.unpack_from("<Q" if size == 8 else "<I", data, at)[0]
            if value:
                _need(BIN_HEAD <= value < len(data), f"BIN section '{name}' at {value:#x} is outside the file")
                found.append((value, name))
        found.sort()
        _need(len({offset for offset, _n in found}) == len(found), "two BIN sections share one offset")
        _need(found[0] == (BIN_HEAD, "bones") and found[-1][1] == "materials",
              "BIN sections are not bones-first, materials-last")
        ends = [offset for offset, _n in found[1:]] + [len(data)]
        sections = {name: data[offset:end] for (offset, name), end in zip(found, ends)}
        legacy = all(struct.unpack_from("<I", data, at)[0] == struct.unpack_from("<Q", data, BIN_POINTERS[name][0])[0] - 0x38
                     for name, at in BIN_LEGACY.items() if name in sections)
        model = cls(header=data[:BIN_HEAD], sections=sections, legacy=legacy)
        if verify:
            model.check()
        return model

    def build(self) -> bytes:
        header = bytearray(self.header)
        offset = BIN_HEAD
        for name, payload in self.sections.items():
            at, size = BIN_POINTERS[name]
            struct.pack_into("<Q" if size == 8 else "<I", header, at, offset)
            if self.legacy and name in BIN_LEGACY:
                struct.pack_into("<I", header, BIN_LEGACY[name], offset - 0x38)
            offset += len(payload)
        return bytes(header) + b"".join(self.sections.values())

    # -- decoded views -----------------------------------------------------------------------------------------
    def _array(self, name: str, dtype: str, width: int) -> np.ndarray:
        count = self.vertex_count
        return np.frombuffer(self.sections[name], dtype, count * width).reshape(count, width)

    def positions(self) -> np.ndarray:
        return self._array("positions", "<f4", 3)

    def normals(self) -> np.ndarray:
        """Stored normals: 3 floats, direction only (native length is about 127 * 2**32)."""
        return self._array("normals", "<f4", 3)

    def uvs(self) -> np.ndarray:
        return self._array("uvs", "<f4", 2)

    def colors(self) -> np.ndarray:
        return self._array("colors", "u1", 4)

    def weight_index(self) -> np.ndarray:
        return np.frombuffer(self.sections["weight_index"], "<u2", self.vertex_count)

    def bones(self) -> list[tuple[int, int, tuple[float, float, float]]]:
        """[(id, parent or 0xFF, parent-relative bind translation)]."""
        raw = self.sections["bones"]
        return [(raw[16 * i], raw[16 * i + 1], struct.unpack_from("<3f", raw, 16 * i + 4))
                for i in range(self.bone_count)]

    def bone_world(self) -> np.ndarray:
        """Bind position of each bone in model space (translations only: the bind pose carries no rotation)."""
        table = self.bones()
        out = np.zeros((len(table), 3))
        for index, (_ident, parent, local) in enumerate(table):
            _need(parent == 0xFF or parent < index, f"bone {index} has parent {parent} after itself")
            out[index] = np.asarray(local) + (out[parent] if parent != 0xFF else 0.0)
        return out

    def weights(self) -> list[tuple[tuple[int, int], ...]]:
        """Weight sets: per set up to three (bone, percent). Vertices pick a set through `weight_index`."""
        raw = self.sections["weights"]
        out = []
        for i in range(self.weight_count):
            b0, b1, b2, count, w0, w1, w2, _pad_byte = raw[8 * i:8 * i + 8]
            _need(1 <= count <= 3, f"weight set {i} lists {count} bones")
            out.append(tuple(zip((b0, b1, b2)[:count], (w0, w1, w2)[:count])))
        return out

    def materials(self) -> list[Material]:
        return _materials(self.sections["materials"], self.material_count)[0]

    def check(self) -> None:
        """Counts against section sizes, every index against its table, primitives against the vertex count."""
        count = self.vertex_count
        for name, width in (("positions", 12), ("normals", 12), ("uvs", 8), ("colors", 4), ("weight_index", 2),
                            ("weight_index2", 2)):
            _need(name in self.sections and len(self.sections[name]) >= count * width,
                  f"BIN section '{name}' does not hold {count} vertices")
        _need(len(self.sections["bones"]) >= 16 * self.bone_count, "bone table shorter than its count")
        _need(len(self.sections["weights"]) >= 8 * self.weight_count, "weight table shorter than its count")
        if count:
            _need(int(self.weight_index().max()) < self.weight_count, "a vertex names a weight set past the table")
        materials = self.materials()
        _need(sum(m.vertex_count for m in materials) == count, "primitive runs do not consume the vertex array exactly")

    # -- edits -------------------------------------------------------------------------------------------------
    def _with(self, header: bytearray, sections: dict[str, bytes]) -> "HdBin":
        model = HdBin(bytes(header), sections, self.legacy)
        model.check()
        return model

    def with_materials(self, materials: list[Material], *, texture_count: int | None = None) -> "HdBin":
        """The same geometry drawn with other material headers (e.g. remapped texture indices)."""
        _need([m.prims for m in materials] == [m.prims for m in self.materials()],
              "with_materials keeps the primitive runs; use with_geometry to change them")
        header = bytearray(self.header)
        if texture_count is not None:
            struct.pack_into("<I", header, 0x3C, texture_count)
        sections = dict(self.sections)
        tail = self.sections["materials"][_materials(self.sections["materials"], self.material_count)[1]:]
        sections["materials"] = b"".join(m.encode() for m in materials) + tail
        return self._with(header, sections)

    def with_positions(self, positions: np.ndarray) -> "HdBin":
        """Same topology, moved vertices: the one kind of edit the earlier live rounds saw drawn."""
        positions = np.asarray(positions, "<f4")
        _need(positions.shape == (self.vertex_count, 3) and np.isfinite(positions).all(), "positions do not fit")
        sections = dict(self.sections)
        body = positions.tobytes()
        sections["positions"] = body + self.sections["positions"][len(body):]
        return self._with(bytearray(self.header), sections)

    def with_geometry(self, *, positions, normals, uvs, weight_sets, weight_index, materials: list[Material],
                      colors=None, texture_count: int | None = None) -> "HdBin":
        """A new surface on this model's skeleton: header constants, bones, bonepair and adjacency are kept.

        Vertices must already be in drawing order (materials consume them sequentially). `weight_sets` is a list of
        up to 255 sets, each up to three (bone, percent) pairs summing to 100. Normals are any length; they are
        stored at the native length. Nothing is clamped or recentred.
        """
        positions = np.asarray(positions, "<f4").reshape(-1, 3)
        count = len(positions)
        normals = np.asarray(normals, np.float64).reshape(-1, 3)
        uvs = np.asarray(uvs, "<f4").reshape(-1, 2)
        index = np.asarray(weight_index, np.int64).reshape(-1)
        _need(0 < count <= 0xFFFF and len(normals) == len(uvs) == len(index) == count, "vertex arrays disagree")
        _need(np.isfinite(positions).all() and np.isfinite(normals).all() and np.isfinite(uvs).all(), "non-finite vertex data")
        _need(0 < len(weight_sets) <= 0xFF and index.min() >= 0 and index.max() < len(weight_sets),
              "weight sets: at most 255, and every vertex must name one")
        _need("morph" not in self.sections, "a model with morph data keeps its vertex count")
        lengths = np.linalg.norm(normals, axis=1)
        _need(bool((lengths > 1e-12).all()), "a zero-length normal")
        stored = (normals / lengths[:, None] * NORMAL_SCALE).astype("<f4")
        records = b""
        for number, entry in enumerate(weight_sets):
            _need(1 <= len(entry) <= 3 and sum(w for _b, w in entry) == 100 and all(w > 0 for _b, w in entry)
                  and all(0 <= b < self.bone_count for b, _w in entry), f"weight set {number} is not 1-3 bones at 100%")
            bones = [b for b, _w in entry] + [0] * (3 - len(entry))
            shares = [w for _b, w in entry] + [0] * (3 - len(entry))
            records += bytes(bones + [len(entry)] + shares + [0])
        colour = np.full((count, 4), 0xFF, "u1") if colors is None else np.asarray(colors, "u1").reshape(count, 4)
        indices = index.astype("<u2").tobytes()
        fresh = {"weights": records, "positions": positions.tobytes(), "weight_index": indices,
                 "normals": stored.tobytes(), "weight_index2": indices, "colors": colour.tobytes(),
                 "uvs": uvs.tobytes()}
        sections = {}
        for name, payload in self.sections.items():
            if name == "materials":
                sections[name] = b"".join(m.encode() for m in materials) + b"\0" * 8
            else:
                sections[name] = _pad(fresh[name]) if name in fresh else payload
        header = bytearray(self.header)
        header[0x28] = len(weight_sets)
        struct.pack_into("<H", header, 0x2A, len(materials))
        struct.pack_into("<H", header, 0x42, len(weight_sets))
        struct.pack_into("<HH", header, 0x58, count, count)
        if texture_count is not None:
            struct.pack_into("<I", header, 0x3C, texture_count)
        return self._with(header, sections)


def soup(faces_by_material: list[np.ndarray]) -> tuple[np.ndarray, list[list[tuple[int, int]]]]:
    """Triangle lists in drawing order: (source vertex index per output vertex, primitive runs per material).

    One output vertex per triangle corner, which is how the format stores a mesh (it has no index buffer).
    """
    order, runs = [], []
    for faces in faces_by_material:
        faces = np.asarray(faces, np.int64).reshape(-1, 3)
        _need(len(faces) > 0, "a material without triangles")
        order.append(faces.reshape(-1))
        corners, chunk, prims = 3 * len(faces), 0xFFFF // 3 * 3, []
        while corners:
            prims.append((PRIM_LIST, min(chunk, corners)))
            corners -= prims[-1][1]
        runs.append(prims)
    return np.concatenate(order), runs


def weight_table(influences: list[list[tuple[int, float]]], *, limit: int = 255) -> tuple[list[tuple], np.ndarray, int]:
    """Per-vertex (bone, weight) lists -> (weight sets, set index per vertex, percent step used).

    Each vertex keeps its three strongest bones, in percent; the step coarsens (1, 2, 4, 5, 10, 20, 25, 50, 100)
    until the model needs no more than `limit` distinct sets, because the count is one byte.
    """
    for step in (1, 2, 4, 5, 10, 20, 25, 50, 100):
        table, index = {}, []
        for entry in influences:
            merged: dict[int, float] = {}
            for bone, weight in entry:
                merged[int(bone)] = merged.get(int(bone), 0.0) + float(weight)
            top = sorted(merged.items(), key=lambda pair: (-pair[1], pair[0]))[:3]
            total = sum(w for _b, w in top)
            _need(total > 0, "a vertex without a positive weight")
            units = 100 // step
            shares = [int(round(w / total * units)) for _b, w in top]
            shares[0] += units - sum(shares)
            if shares[0] <= 0:                      # rounding starved the strongest bone
                shares = [units] + [0] * (len(shares) - 1)
            key = tuple((b, s * step) for (b, _w), s in zip(top, shares) if s > 0)
            index.append(table.setdefault(key, len(table)))
        if len(table) <= limit:
            return list(table), np.asarray(index, np.int64), step
    raise AssetError("the model needs more than 255 weight sets even at whole-bone weights")


# ------------------------------------------------------------------------------------------------------------ TPL

@dataclass
class TplImage:
    """A texture reference: nominal size and GX format word, and where the pixels are (pack id, index).

    `width`/`height` are the GameCube-era size (the HD surface is 4x or 8x larger); format 0x0E is the GX CMPR
    number on colour maps, 3 on bump maps. The sampler words are kept as read.
    """
    width: int
    height: int
    format: int
    pack_id: int
    index: int
    sampler: bytes = struct.pack("<4If4B", 1, 1, 1, 1, 0.0, 0, 0, 0, 0)

    def archive(self) -> str:
        return f"{self.pack_id:08x}.pack.fen"


@dataclass
class Tpl:
    """A texture table. `tail` is whatever followed the references when parsed (a DAT slot pads to 32 bytes; a
    loose `.tpl` has none), so a parsed table rebuilds to its own bytes. A new or edited table goes into a DAT
    slot through `slot()`."""
    images: list[TplImage]
    tail: bytes = b""

    @classmethod
    def parse(cls, data: bytes) -> "Tpl":
        _need(len(data) >= 16 and struct.unpack_from("<I", data, 0)[0] == TPL_MAGIC,
              "not an HD TPL (magic 0x12345678; the GameCube TPL is 0x0020AF30)")
        count, table = struct.unpack_from("<II", data, 4)
        _need(table == 0x10 and 16 + 16 * count <= len(data), "TPL table is not at 0x10")
        images = []
        for i in range(count):
            head, palette = struct.unpack_from("<QQ", data, 16 + 16 * i)
            _need(palette == 0 and head + 40 <= len(data), f"TPL image {i}: header outside the table or a palette")
            height, width, fmt, pixels = struct.unpack_from("<HHIQ", data, head)
            _need(pixels + 8 <= len(data), f"TPL image {i}: reference outside the table")
            pack_id, index = struct.unpack_from("<II", data, pixels)
            images.append(TplImage(width, height, fmt, pack_id, index, data[head + 16:head + 40]))
        return cls(images, data[16 + 64 * count:])

    def build(self) -> bytes:
        count = len(self.images)
        heads = 16 + 16 * count
        refs = heads + 40 * count
        out = struct.pack("<4I", TPL_MAGIC, count, 0x10, 0)
        out += b"".join(struct.pack("<QQ", heads + 40 * i, 0) for i in range(count))
        for i, image in enumerate(self.images):
            _need(len(image.sampler) == 24, "a TPL sampler block is 24 bytes")
            out += struct.pack("<HHIQ", image.height, image.width, image.format, refs + 8 * i) + image.sampler
        out += b"".join(struct.pack("<II", image.pack_id, image.index) for image in self.images)
        return out + self.tail

    def slot(self) -> bytes:
        """The table as a DAT slot: canonical bytes zero-padded to a multiple of 32."""
        return _pad(Tpl(self.images).build())


def tpl_has_palette(data: bytes) -> bool:
    """True for the paletted TPL variant (a second header per image), which `Tpl` refuses rather than misreads."""
    if len(data) < 32 or struct.unpack_from("<I", data, 0)[0] != TPL_MAGIC:
        return False
    count = struct.unpack_from("<I", data, 4)[0]
    return any(struct.unpack_from("<Q", data, 24 + 16 * i)[0] for i in range(count) if 32 + 16 * i <= len(data))


# ------------------------------------------------------------------------------------------------- ImagePackHD

def dds_info(dds: bytes) -> dict:
    _need(len(dds) >= 128 and dds[:4] == b"DDS " and struct.unpack_from("<I", dds, 4)[0] == 124, "not a DDS")
    height, width = struct.unpack_from("<II", dds, 12)
    return {"width": width, "height": height, "mipmaps": struct.unpack_from("<I", dds, 28)[0],
            "fourcc": dds[84:88].rstrip(b"\0").decode("latin-1"), "bytes": len(dds)}


@dataclass
class ImagePack:
    """A `.pack.fen` texture archive. Entry `i` is what a TPL image with this pack id and index `i` draws."""
    pack_id: int
    entries: list[tuple[bytes, bytes, bytes]]      # (16-byte wrapper, DDS file, padding after it)
    lead: bytes = b""                              # bytes between the offset table and the first entry

    @classmethod
    def parse(cls, data: bytes) -> "ImagePack":
        _need(len(data) > 6, "FEN too short")
        declared = struct.unpack_from("<I", data, 0)[0]
        try:
            body = zlib.decompress(data[4:])
        except zlib.error as error:
            raise AssetError(f"FEN is not a zlib stream: {error}") from None
        _need(len(body) == declared, "FEN declares a size its stream does not have")
        return cls.parse_body(body)

    @classmethod
    def parse_body(cls, body: bytes) -> "ImagePack":
        _need(len(body) >= 8, "image pack too short")
        pack_id, count = struct.unpack_from("<II", body, 0)
        table = 8 + 8 * count
        _need(count > 0 and table <= len(body), "image pack count runs past the body")
        offsets = list(struct.unpack_from(f"<{count}Q", body, 8))
        _need(offsets[0] >= table and all(a < b for a, b in zip(offsets, offsets[1:])) and offsets[-1] < len(body),
              "image pack offsets are not ascending inside the body")
        entries = []
        for start, stop in zip(offsets, offsets[1:] + [len(body)]):
            size, marker, owner, _zero = struct.unpack_from("<4I", body, start)
            _need(marker == 0xFFFFFFFF and owner == pack_id and start + 16 + size <= stop,
                  "image pack entry wrapper is not (size, -1, pack id, 0)")
            entries.append((body[start:start + 16], body[start + 16:start + 16 + size], body[start + 16 + size:stop]))
        return cls(pack_id, entries, body[table:offsets[0]])

    def body(self) -> bytes:
        at = 8 + 8 * len(self.entries) + len(self.lead)
        offsets, blob = [], b""
        for wrapper, dds, tail in self.entries:
            offsets.append(at + len(blob))
            blob += wrapper + dds + tail
        return (struct.pack("<II", self.pack_id, len(self.entries)) + struct.pack(f"<{len(offsets)}Q", *offsets)
                + self.lead + blob)

    def build(self) -> bytes:
        body = self.body()
        return struct.pack("<I", len(body)) + zlib.compress(body, FEN_ZLIB_LEVEL)

    def textures(self) -> list[dict]:
        return [dds_info(dds) for _wrapper, dds, _tail in self.entries]

    def append(self, dds: bytes) -> int:
        """Add a surface at the end; returns its index.

        Measured on the 27 player archives: every DDS starts on a multiple of 128 bytes (its 16-byte wrapper just
        before), with zeros in between. The table grows by 8 bytes per entry, so the zeros after it are recomputed.
        """
        dds_info(dds)
        _need(not any(self.lead), "the bytes after the offset table are not padding")
        count = len(self.entries) + 1
        self.lead = bytes(-(8 + 8 * count + 16) % 128)
        if self.entries:
            wrapper, last, tail = self.entries[-1]
            end = len(self.body()) + 8                       # the table has not grown yet
            self.entries[-1] = (wrapper, last, tail + bytes(-(end + 16) % 128))
        self.entries.append((struct.pack("<4I", len(dds), 0xFFFFFFFF, self.pack_id, 0), bytes(dds), b""))
        return count - 1


def _bc1_blocks(rgb: np.ndarray) -> np.ndarray:
    """Range-fit BC1 colour blocks (4-colour mode) for an (h, w, 3) image whose sides are multiples of 4."""
    h, w, _c = rgb.shape
    cells = rgb.reshape(h // 4, 4, w // 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 3).astype(np.int32)
    high, low = cells.max(1), cells.min(1)

    def to565(c):
        return ((c[:, 0] >> 3) << 11) | ((c[:, 1] >> 2) << 5) | (c[:, 2] >> 3)

    def from565(v):
        r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
        return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], 1)

    c0, c1 = to565(high), to565(low)
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    flat = c0 == c1                                   # equal endpoints select 3-colour mode: index 0 everywhere
    e0, e1 = from565(c0), from565(c1)
    palette = np.stack([e0, e1, (2 * e0 + e1) // 3, (e0 + 2 * e1) // 3], 1)
    distance = ((cells[:, :, None, :] - palette[:, None, :, :]) ** 2).sum(3)
    choice = np.where(flat[:, None], 0, distance.argmin(2)).astype(np.uint32)
    bits = (choice << (2 * np.arange(16, dtype=np.uint32))[None, :]).sum(1).astype(np.uint32)
    out = np.zeros((len(cells), 8), np.uint8)
    out[:, 0:2] = c0.astype("<u2").view(np.uint8).reshape(-1, 2)
    out[:, 2:4] = c1.astype("<u2").view(np.uint8).reshape(-1, 2)
    out[:, 4:8] = bits.astype("<u4").view(np.uint8).reshape(-1, 4)
    return out


def encode_dds(rgba: np.ndarray, *, mipmaps: bool = True) -> bytes:
    """An opaque-or-alpha RGBA image as a DXT5 DDS with a full mip chain (the layout the player archives use).

    Alpha is stored as the block's two extremes with the nearest of the eight interpolants per texel.
    """
    from PIL import Image

    rgba = np.asarray(rgba, np.uint8)
    _need(rgba.ndim == 3 and rgba.shape[2] == 4 and rgba.shape[0] % 4 == 0 and rgba.shape[1] % 4 == 0,
          "encode_dds takes an RGBA image whose sides are multiples of 4")
    height, width = rgba.shape[:2]
    levels, image = [], Image.fromarray(rgba, "RGBA")
    while True:
        levels.append(np.asarray(image, np.uint8))
        if not mipmaps or (image.width == 1 and image.height == 1):
            break
        image = image.resize((max(1, image.width // 2), max(1, image.height // 2)), Image.BOX)
    data = b""
    for level in levels:
        h, w = level.shape[:2]
        if h % 4 or w % 4:                              # the last levels are smaller than a block: replicate
            level = np.pad(level, ((0, -h % 4), (0, -w % 4), (0, 0)), mode="edge")
            h, w = level.shape[:2]
        colour = _bc1_blocks(level[:, :, :3])
        alpha = level[:, :, 3].reshape(h // 4, 4, w // 4, 4).transpose(0, 2, 1, 3).reshape(-1, 16).astype(np.int32)
        a0, a1 = alpha.max(1), alpha.min(1)
        steps = np.where((a0 > a1)[:, None],
                         np.stack([a0, a1] + [((7 - k) * a0 + k * a1) // 7 for k in range(1, 7)], 1),
                         np.repeat(a0[:, None], 8, 1))
        pick = np.abs(alpha[:, :, None] - steps[:, None, :]).argmin(2).astype(np.uint64)
        pick = np.where((a0 > a1)[:, None], pick, 0).astype(np.uint64)
        bits = (pick << (3 * np.arange(16, dtype=np.uint64))[None, :]).sum(1).astype(np.uint64)
        block = np.zeros((len(colour), 16), np.uint8)
        block[:, 0], block[:, 1] = a0, a1
        block[:, 2:8] = bits.astype("<u8").view(np.uint8).reshape(-1, 8)[:, :6]
        block[:, 8:] = colour
        data += block.tobytes()
    header = bytearray(128)
    header[:4] = b"DDS "
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000 | (0x20000 if len(levels) > 1 else 0)
    struct.pack_into("<7I", header, 4, 124, flags, height, width, max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * 16,
                     0, len(levels))
    struct.pack_into("<II4s", header, 76, 32, 0x4, b"DXT5")
    struct.pack_into("<I", header, 108, 0x1000 | (0x400008 if len(levels) > 1 else 0))
    return bytes(header) + data


# ----------------------------------------------------------------------------------------------------- summaries

def slot_summary(udas: bytes) -> list[dict]:
    """Every DAT slot of a pack: BIN slots with their counts, TPL slots with the archive entries they name."""
    _pack, dat = pack_slots(udas)
    out = []
    for index, (ext, payload) in enumerate(dat.slots):
        row = {"slot": index, "ext": ext, "bytes": len(payload)}
        if ext == "BIN":
            model = HdBin.parse(payload)
            row.update(vertices=model.vertex_count, bones=model.bone_count, weight_sets=model.weight_count,
                       materials=model.material_count, textures=model.texture_count,
                       triangles=sum(m.triangle_count for m in model.materials()),
                       version=f"{model.version:#x}", morph="morph" in model.sections)
        elif ext == "TPL":
            row["images"] = [{"width": i.width, "height": i.height, "format": i.format, "archive": i.archive(),
                              "index": i.index} for i in Tpl.parse(payload).images]
        out.append(row)
    return out


def roundtrip(name: str, data: bytes) -> dict:
    """Parse and rebuild one file (a `.udas` is rebuilt through every BIN and TPL slot); report byte equality."""
    lower = name.lower()
    report = {"file": name, "bytes": len(data), "bin": 0, "tpl": 0, "other_bin": 0, "palette_tpl": 0}
    if lower.endswith(".udas"):
        pack, dat = pack_slots(data)
        rebuilt = []
        for ext, payload in dat.slots:
            if ext == "BIN" and payload[:8] != struct.pack("<Q", BIN_HEAD):
                report["other_bin"] += 1               # a "BIN" slot that is not a model (etc/core.udas has some)
            elif ext == "BIN":
                payload, report["bin"] = HdBin.parse(payload).build(), report["bin"] + 1
            elif ext == "TPL" and tpl_has_palette(payload):
                report["palette_tpl"] += 1             # not decoded (one font table in etc/core.udas); kept as is
            elif ext == "TPL":
                payload, report["tpl"] = Tpl.parse(payload).build(), report["tpl"] + 1
            rebuilt.append((ext, payload))
        out = pack_build(pack, Dat(rebuilt, dat.reserved, dat.gap))
    elif lower.endswith(".bin"):
        out, report["bin"] = HdBin.parse(data).build(), 1
    elif lower.endswith(".tpl"):
        out, report["tpl"] = Tpl.parse(data).build(), 1
    elif lower.endswith(".pack.fen"):
        pack = ImagePack.parse(data)
        out = pack.build()
        report["textures"] = len(pack.entries)
    else:
        raise AssetError(f"{name}: no reader for this extension")
    report["identical"] = out == data
    return report


def main(argv=None) -> int:
    import argparse
    import hashlib
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="RE4 Switch asset files: round-trip check and slot listing")
    parser.add_argument("command", choices=("verify", "slots"))
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)
    failed = 0
    for path in args.files:
        data = path.read_bytes()
        if args.command == "slots":
            print(json.dumps({"file": path.name, "sha256": hashlib.sha256(data).hexdigest(),
                              "slots": slot_summary(data)}))
            continue
        try:
            report = roundtrip(path.name, data)
        except AssetError as error:
            report = {"file": path.name, "identical": False, "error": str(error)}
        failed += not report["identical"]
        print(json.dumps(report))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
