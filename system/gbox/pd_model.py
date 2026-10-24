"""Parse a Perfect Dark N64 model file (chr/prop/gun) from a decompressed blob.

The in-ROM files are Rare 0x1173 zip containers.  Once decompressed, the
model layout matches the n64decomp/perfect_dark C structs:

    struct modeldef {
        struct modelnode *rootnode;   // offset relative to VMA 0x05000000
        struct skeleton  *skel;       // skeleton table index
        struct modelnode **parts;     // -> parts[0] at file offset 0x1c
        s16 numparts;
        s16 nummatrices;
        f32 scale;
        s16 rwdatalen;      // words, assigned at runtime
        s16 numtexconfigs;
        struct textureconfig *texconfigs;
    };

modelnode (0x18 bytes):
    u16 type;  (plus 2 bytes padding)
    u32 rodata;
    u32 parent, next, prev, child;

Offsets inside model files are relative to virtual memory address 0x05000000
(the value passed to model_promote_offsets_to_pointers by modeldef_load).

This module only *reads* the format; it does not render or re-serialise it.
"""
from __future__ import annotations

import json
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from gbox import n64_rom, pd_inventory

VMA = 0x05000000
MODELDEF_SIZE = 0x1C
NODE_SIZE = 0x18
TEXTURECONFIG_SIZE = 0x10

# From include/constants.h
NODE_TYPES = {
    0x01: "CHRINFO",
    0x02: "POSITION",
    0x04: "GUNDL",
    0x05: "TYPE05",
    0x08: "DISTANCE",
    0x09: "REORDER",
    0x0A: "BBOX",
    0x0B: "TYPE0B",
    0x0C: "CHRGUNFIRE",
    0x0D: "TYPE0D",
    0x0E: "TYPE0E",
    0x0F: "TYPE0F",
    0x11: "TYPE11",
    0x12: "TOGGLE",
    0x15: "POSITIONHELD",
    0x16: "STARGUNFIRE",
    0x17: "HEADSPOT",
    0x18: "DL",
    0x19: "GEO",
}


def _ptr_off(p: int) -> Optional[int]:
    """Convert an in-file pointer to a file offset; NULL stays None."""
    if p == 0:
        return None
    if p < VMA:
        raise ValueError(f"pointer 0x{p:08x} is below VMA 0x{VMA:08x}")
    return p - VMA


def _read_u16(data: bytes, off: int) -> int:
    return struct.unpack_from(">H", data, off)[0]


def _read_s16(data: bytes, off: int) -> int:
    return struct.unpack_from(">h", data, off)[0]


def _read_u32(data: bytes, off: int) -> int:
    return struct.unpack_from(">I", data, off)[0]


def _read_s32(data: bytes, off: int) -> int:
    return struct.unpack_from(">i", data, off)[0]


def _read_f32(data: bytes, off: int) -> float:
    return struct.unpack_from(">f", data, off)[0]


def _read_ptr(data: bytes, off: int) -> Optional[int]:
    return _ptr_off(_read_u32(data, off))


@dataclass
class TextureConfig:
    texturenum: int
    width: int
    height: int
    level: int
    fmt: int
    depth: int
    s: int
    t: int
    unk0b: int
    file_offset: int

    def as_dict(self) -> dict:
        return {
            "texturenum": self.texturenum,
            "width": self.width,
            "height": self.height,
            "level": self.level,
            "format": self.fmt,
            "depth": self.depth,
            "s": self.s,
            "t": self.t,
            "unk0b": self.unk0b,
            "file_offset": self.file_offset,
        }


@dataclass
class Node:
    type_code: int
    type_name: str
    file_offset: int
    rodata_offset: Optional[int]
    parent_offset: Optional[int]
    next_offset: Optional[int]
    prev_offset: Optional[int]
    child_offset: Optional[int]
    rodata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = {
            "type_code": self.type_code,
            "type_name": self.type_name,
            "file_offset": self.file_offset,
            "rodata_offset": self.rodata_offset,
            "parent_offset": self.parent_offset,
            "next_offset": self.next_offset,
            "prev_offset": self.prev_offset,
            "child_offset": self.child_offset,
        }
        d.update(self.rodata)
        return d


@dataclass
class ModelDef:
    file_offset: int  # always 0 for a standalone model blob
    rootnode_offset: Optional[int]
    skel_index: int
    numparts: int
    nummatrices: int
    scale: float
    numtexconfigs: int
    texconfigs: list[TextureConfig]
    parts_offsets: list[int]
    part_numbers: list[int]
    nodes: list[Node]

    def node_count(self) -> int:
        return len(self.nodes)

    def node_type_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for n in self.nodes:
            counts[n.type_name] = counts.get(n.type_name, 0) + 1
        return counts

    def as_dict(self) -> dict:
        return {
            "file_offset": self.file_offset,
            "rootnode_offset": self.rootnode_offset,
            "skel_index": self.skel_index,
            "numparts": self.numparts,
            "nummatrices": self.nummatrices,
            "scale": self.scale,
            "numtexconfigs": self.numtexconfigs,
            "texconfigs": [t.as_dict() for t in self.texconfigs],
            "parts_offsets": self.parts_offsets,
            "part_numbers": self.part_numbers,
            "node_count": len(self.nodes),
            "node_type_counts": self.node_type_counts(),
            "nodes": [n.as_dict() for n in self.nodes],
        }


def _parse_texconfigs(data: bytes, off: int, count: int) -> list[TextureConfig]:
    configs: list[TextureConfig] = []
    for i in range(count):
        pos = off + i * TEXTURECONFIG_SIZE
        texnum = _read_s32(data, pos)
        width = data[pos + 4]
        height = data[pos + 5]
        level = data[pos + 6]
        fmt = data[pos + 7]
        depth = data[pos + 8]
        s = data[pos + 9]
        t = data[pos + 10]
        unk0b = data[pos + 11]
        configs.append(
            TextureConfig(
                texturenum=texnum,
                width=width,
                height=height,
                level=level,
                fmt=fmt,
                depth=depth,
                s=s,
                t=t,
                unk0b=unk0b,
                file_offset=pos,
            )
        )
    return configs


def _parse_rodata(data: bytes, node: Node) -> dict[str, Any]:
    off = node.rodata_offset
    if off is None:
        return {}
    t = node.type_code & 0xFF
    ro: dict[str, Any] = {"rodata_file_offset": off}

    if t == 0x01:  # CHRINFO
        ro["animpart"] = _read_u16(data, off)
        ro["mtxindex"] = _read_s16(data, off + 2)
        ro["unk04"] = _read_f32(data, off + 4)
        ro["rwdataindex"] = _read_u16(data, off + 8)
    elif t == 0x02:  # POSITION
        ro["pos"] = {
            "x": _read_f32(data, off),
            "y": _read_f32(data, off + 4),
            "z": _read_f32(data, off + 8),
        }
        ro["part"] = _read_u16(data, off + 12)
        ro["mtxindex0"] = _read_s16(data, off + 14)
        ro["mtxindex1"] = _read_s16(data, off + 16)
        ro["mtxindex2"] = _read_s16(data, off + 18)
        ro["drawdist"] = _read_f32(data, off + 20)
    elif t == 0x04:  # GUNDL
        ro["opagdl_offset"] = _read_ptr(data, off)
        ro["xlugdl_offset"] = _read_ptr(data, off + 4)
        ro["baseaddr_offset"] = _read_ptr(data, off + 8)
        ro["vertices_offset"] = _read_ptr(data, off + 12)
        ro["numvertices"] = _read_s16(data, off + 16)
        ro["rendermode"] = _read_s16(data, off + 18)
    elif t == 0x08:  # DISTANCE
        ro["near"] = _read_f32(data, off)
        ro["far"] = _read_f32(data, off + 4)
        ro["target_offset"] = _read_ptr(data, off + 8)
        ro["rwdataindex"] = _read_u16(data, off + 12)
    elif t == 0x0A:  # BBOX
        ro["hitpart"] = _read_s32(data, off)
        ro["xmin"] = _read_f32(data, off + 4)
        ro["xmax"] = _read_f32(data, off + 8)
        ro["ymin"] = _read_f32(data, off + 12)
        ro["ymax"] = _read_f32(data, off + 16)
        ro["zmin"] = _read_f32(data, off + 20)
        ro["zmax"] = _read_f32(data, off + 24)
    elif t == 0x12:  # TOGGLE
        ro["target_offset"] = _read_ptr(data, off)
        ro["rwdataindex"] = _read_u16(data, off + 4)
    elif t == 0x17:  # HEADSPOT
        ro["rwdataindex"] = _read_u16(data, off)
    elif t == 0x18:  # DL
        ro["opagdl_offset"] = _read_ptr(data, off)
        ro["xlugdl_offset"] = _read_ptr(data, off + 4)
        ro["colours_offset"] = _read_ptr(data, off + 8)
        ro["vertices_offset"] = _read_ptr(data, off + 12)
        ro["numvertices"] = _read_s16(data, off + 16)
        ro["rendermode"] = _read_s16(data, off + 18)
        ro["rwdataindex"] = _read_u16(data, off + 20)
        ro["numcolours"] = _read_u16(data, off + 22)
    elif t == 0x19:  # GEO
        ro["numvertices"] = _read_s32(data, off)
        verts = []
        for i in range(4):
            base = off + 4 + i * 12
            verts.append(
                {
                    "x": _read_f32(data, base),
                    "y": _read_f32(data, base + 4),
                    "z": _read_f32(data, base + 8),
                }
            )
        ro["vertices"] = verts

    return ro


def _walk_nodes(data: bytes, root_off: Optional[int]) -> list[Node]:
    if root_off is None:
        return []
    nodes: list[Node] = []
    seen: set[int] = set()
    stack: list[int] = [root_off]

    while stack:
        off = stack.pop()
        if off is None or off in seen:
            continue
        seen.add(off)
        if off + NODE_SIZE > len(data):
            raise ValueError(f"modelnode at 0x{off:x} extends past file end")

        type_code = _read_u16(data, off)
        type_name = NODE_TYPES.get(type_code & 0xFF, f"TYPE_{type_code:04x}")
        rodata_off = _read_ptr(data, off + 4)
        parent_off = _read_ptr(data, off + 8)
        next_off = _read_ptr(data, off + 12)
        prev_off = _read_ptr(data, off + 16)
        child_off = _read_ptr(data, off + 20)

        node = Node(
            type_code=type_code,
            type_name=type_name,
            file_offset=off,
            rodata_offset=rodata_off,
            parent_offset=parent_off,
            next_offset=next_off,
            prev_offset=prev_off,
            child_offset=child_off,
        )
        node.rodata = _parse_rodata(data, node)
        nodes.append(node)

        if child_off is not None:
            stack.append(child_off)
        if next_off is not None:
            stack.append(next_off)

    return nodes


def parse(data: bytes, file_offset: int = 0) -> ModelDef:
    """Parse a decompressed Perfect Dark model file."""
    if len(data) < MODELDEF_SIZE:
        raise ValueError(f"model file too small ({len(data)} bytes)")

    rootnode_ptr, skel_index, parts_ptr_raw, counts, scale, rw_numtex, texconfigs_ptr = (
        struct.unpack_from(">IIIIfII", data, 0)
    )
    numparts = (counts >> 16) & 0xFFFF
    nummatrices = counts & 0xFFFF
    numtexconfigs = rw_numtex & 0xFFFF
    _rwdatalen = (rw_numtex >> 16) & 0xFFFF

    rootnode_off = _ptr_off(rootnode_ptr)
    parts_off = _ptr_off(parts_ptr_raw)
    texconfigs_off = _ptr_off(texconfigs_ptr)

    # Parse parts pointer array and part numbers
    parts_offsets: list[int] = []
    part_numbers: list[int] = []
    if parts_off is not None:
        if parts_off + numparts * 4 > len(data):
            raise ValueError("parts array extends past file end")
        parts_offsets = [_read_ptr(data, parts_off + i * 4) or 0 for i in range(numparts)]
        nums_off = parts_off + numparts * 4
        # part numbers are s16[] and then padded to the texconfigs offset
        part_numbers = [_read_s16(data, nums_off + i * 2) for i in range(numparts)]

    texconfigs: list[TextureConfig] = []
    if texconfigs_off is not None:
        if texconfigs_off + numtexconfigs * TEXTURECONFIG_SIZE > len(data):
            raise ValueError("texconfigs array extends past file end")
        texconfigs = _parse_texconfigs(data, texconfigs_off, numtexconfigs)

    nodes = _walk_nodes(data, rootnode_off)

    return ModelDef(
        file_offset=file_offset,
        rootnode_offset=rootnode_off,
        skel_index=skel_index,
        numparts=numparts,
        nummatrices=nummatrices,
        scale=scale,
        numtexconfigs=numtexconfigs,
        texconfigs=texconfigs,
        parts_offsets=parts_offsets,
        part_numbers=part_numbers,
        nodes=nodes,
    )


def load_from_rom(rom: bytes, name: str) -> ModelDef:
    """Extract and parse the named model file from a Perfect Dark ROM."""
    manifest = pd_inventory.inventory(rom)
    entry = next((f for f in manifest["files"] if f["name"] == name), None)
    if entry is None:
        raise ValueError(f"model {name!r} not found in ROM")
    blob = rom[entry["offset"] : entry["end"]]
    if entry["zipped"]:
        data, _ = pd_inventory.unzip_pd(blob)
    else:
        data = blob
    return parse(data, entry["offset"])


def load_from_file(path: Path) -> ModelDef:
    """Parse a standalone decompressed model blob."""
    return parse(Path(path).read_bytes())


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    out: Path | None = None
    if "--out" in argv:
        i = argv.index("--out")
        out = Path(argv[i + 1])
        del argv[i : i + 2]
    if len(argv) != 2:
        print(
            "usage: python -m gbox.pd_model ROM NAME [--out probe.json]",
            file=sys.stderr,
        )
        return 2
    rom_path, name = argv[0], argv[1]
    rom = n64_rom.read(Path(rom_path))
    model = load_from_rom(rom, name)
    d = model.as_dict()
    if out:
        out.write_text(json.dumps(d, indent=2))
        print(f"wrote {out}")
    print(
        f"{name}: skel={model.skel_index} numparts={model.numparts} "
        f"nummatrices={model.nummatrices} nodes={model.node_count()} "
        f"texconfigs={model.numtexconfigs} types={model.node_type_counts()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
