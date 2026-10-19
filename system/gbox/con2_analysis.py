"""Naruto: Clash of Ninja 2 (GameCube, GNUEDA) -- main.dol name tables and the HSD scene_data layout.

The inventory stage (`gbox.con2_inventory`) proved the .fpk pack directory, the Eighting PRS codec and the
HAL SysDolphin (HSD) archive header.  This module is the analysis stage: it maps the 24 fighter `chr` codes
to display names from main.dol and probes the structure of a costume model `0000.dat` (HSD archive whose
single root is `scene_data`) so a reader can walk the JObj/DObj/PObj/MObj/TObj object graph.

main.dol is a PPC big-endian DOL; the string/table file offsets below are section-relative (section 2
0x187380 -> 0x8018a380, section 5 0x18c980 -> 0x8018f980, section 7 0x1a4c60 -> 0x801f9300):

  0x18e3fc  u32[24] pointer table (RAM 0x801913fc) to the 24 chr codes in roster order
            "ali bak bus mar she stu uli yug chr fan ino sik nej hin gai kan kar kib dog gar sa2 oro obo miz"
  0x1a573c  the packed 3-letter code strings ("chr" first, then the table order) -- the pointer targets
  0x1896a8  debug format string "No%02d name%s chr%s " (the loader's character debug print)
  0x189b64  debug name strings -- the 8 default fighters, in print order
  0x1899ac  unlockable-character name block (Iruka, Kakashi, Neji, Zabuza, Guy, Nine-Tailed Naruto,
            Kakashi w/ Sharingan, Sasuke w/ Sharingan, Orochimaru, then stage names)
  0x1a6110  second unlockable name block (Gaara, Kankuro, Haku, Crow, Akamaru, Mizuki)

The debug print iterates a name/chr table, so the two name blocks plus the debug block are the display
names; only the codes whose name appears as an unambiguous substring of a known Naruto character are
asserted here (the full 24-code assignment is still unproven and belongs to the reader stage).

HSD 0000.dat (e.g. `fpack/chr/ali0000.fpk` -> `hr/ali/0000.dat`, 363195 B):  header 0x20 = file size,
data size (355792), relocation count (1838), root count (1), ref count (0), 12 reserved bytes; then the
data block, the relocation table (u32 offset of every pointer field in the data block), the root table
(u32 offset, u32 name offset) and the string table.  A data-block offset is a pointer iff it is listed in
the relocation table.

Data block layout (verified on ali): a pointer-free float prefix (vertex/attribute arrays; the PObj
attribute data pointers point into it), then the object graph.  HSD_Material is 0x2c bytes:
next ptr, u32 0, u32 0, ambient RGBA8, diffuse RGBA8, specular RGBA8, alpha f32, shininess f32, u32 0,
u32 1, u32 0 (ali's first material reads ambient 0x808080FF, diffuse 0x000000FF, specular 0xFFFFFFFF,
alpha 1.0, shininess 50.0).  The scene_data root object sits at the END of the data block (ali 0x56dc0)
and holds four relocated pointers into the scene-info chain that leads to the JObj tree (whose header
differs from Melee's HAL variant, so the JObj walk is reader-stage work).
"""
from __future__ import annotations

import struct
from collections import Counter

from .con2_inventory import Dol, hsd_header

# file offsets / RAM constants for the main.dol tables (section-relative file offsets)
CODE_TABLE = 0x18E3FC          # u32[24] -> chr code strings
CODE_TABLE_RAM = 0x801913FC
CODE_STRINGS = 0x1A573C        # packed 3-letter code strings (chr first, then roster order)
DEBUG_FMT = 0x1896A8           # "No%02d name%s chr%s "

ROSTER = ["ali", "bak", "bus", "mar", "she", "stu", "uli", "yug", "chr", "fan", "ino", "sik", "nej",
          "hin", "gai", "kan", "kar", "kib", "dog", "gar", "sa2", "oro", "obo", "miz"]

# file offsets of the packed 4-byte-aligned name blocks (section 5 0x18c980 -> 0x8018f980,
# section 7 0x1a4c60 -> 0x801f9300):
UNLOCK_NAMES_A = 0x1899AC          # Iruka ... Orochimaru, then stage names and bonus items
DEBUG_NAMES = 0x189B64             # 8 default fighters, then item names, "Story mode", "kuro/shop"
UNLOCK_NAMES_B = 0x1A6110          # Gaara, Kankuro, Haku, Crow, Akamaru, Mizuki
_DEBUG_NAMES_END = 0x189E00        # just past "kuro/shop"
_UNLOCK_B_END = 0x1A6140           # just past "Mizuki" (before "Gallery")

# code -> display name, only where a known Naruto character name is an unambiguous substring of the code.
_NAMED = {
    "ino": "Ino",
    "nej": "Neji",
    "hin": "Hinata",
    "gai": "Might Guy",
    "kan": "Kankuro",
    "kib": "Kiba",
    "gar": "Gaara",
    "oro": "Orochimaru",
    "miz": "Mizuki",
    "dog": "Akamaru",        # Kiba's dog; the "dog" code, name "Akamaru" in the unlock block
    "obo": "Oboro",          # "Oboro Mode" string + the Chunin-exams character
}


def code_table(dol: bytes) -> list[str]:
    """The 24 chr codes in roster order, read from the pointer table at file offset 0x18e3fc."""
    d = Dol(dol)
    out = []
    for i in range(24):
        p = struct.unpack_from(">I", dol, CODE_TABLE + 4 * i)[0]
        s = d.cstr(p) if p else None
        if not s or len(s) != 3:
            raise ValueError(f"code table entry {i} at {CODE_TABLE + 4 * i:#x} is not a 3-letter code ({s!r})")
        out.append(s)
    return out


def _names(dol: bytes, start: int, end: int) -> list[str]:
    """4-byte-aligned NUL-terminated strings in [start, end), skipping blanks/non-text."""
    out, p = [], start
    while p < end:
        z = dol.find(b"\0", p, end)
        if z < 0:
            break
        s = dol[p:z].decode("latin-1")
        if s.strip() and any(c.isalnum() for c in s):
            out.append(s)
        p = (z + 4) & ~3
    return out


def char_names(dol: bytes) -> dict:
    """main.dol character-name tables: codes, default names, unlock names, and the confident mapping."""
    debug = _names(dol, DEBUG_NAMES, _DEBUG_NAMES_END)
    return {
        "roster": code_table(dol),
        "debug_format": _cstr(dol, DEBUG_FMT),
        "debug_names": debug,
        "default_names": debug[:8],                     # the 8 default fighters precede the item names
        "unlock_names_a": _names(dol, UNLOCK_NAMES_A, DEBUG_NAMES),
        "unlock_names_b": _names(dol, UNLOCK_NAMES_B, _UNLOCK_B_END),
        "named": dict(_NAMED),
    }


def _cstr(dol: bytes, fo: int) -> str:
    z = dol.find(b"\0", fo)
    return dol[fo:z].decode("latin-1") if z > fo else ""


def hsd_scene(data: bytes) -> dict:
    """Structural probe of a costume 0000.dat HSD archive: header, root, pointer-free prefix, materials.

    Returns the sizes/relocations from `hsd_header`, the data-block offset of the `scene_data` root, the
    extent of the pointer-free float prefix (vertex/attribute arrays), the root object's relocated
    pointers, and the first HSD_Material's fields (0x2c-byte struct)."""
    h = hsd_header(data)                       # validates file size / relocations / roots
    size, dsz, nrel, nroot, nref = struct.unpack_from(">5I", data, 0)
    rel = list(struct.unpack_from(f">{nrel}I", data, 0x20 + dsz)) if nrel else []
    root_tab = 0x20 + dsz + 4 * nrel
    roots = {}
    for i in range(nroot):
        off, so = struct.unpack_from(">II", data, root_tab + 8 * i)
        strs = root_tab + 8 * (nroot + nref)
        name = data[strs + so:data.index(b"\0", strs + so)].decode("latin-1")
        roots[name] = off
    if "scene_data" not in roots:
        raise ValueError("no scene_data root")
    root = roots["scene_data"]
    d = data[0x20:0x20 + dsz]
    rset = set(rel)
    # the pointer-free prefix: every byte before the first relocation has no pointer fields
    float_hi = min(rel) if rel else dsz
    # scene root's relocated pointers (the scene-info chain)
    scene_ptrs = [struct.unpack_from(">I", d, root + 4 * k)[0] for k in range(4)
                  if root + 4 * k in rset]
    # first material (0x2c-byte HAL HSD_Material) at the first relocation, if it looks like one
    mat = None
    if rel and min(rel) + 0x2C <= dsz:
        o = min(rel)
        nxt, a, b = struct.unpack_from(">3I", d, o)
        amb, dif, spc = struct.unpack_from(">3I", d, o + 0x0C)
        alpha, shin = struct.unpack_from(">2f", d, o + 0x18)
        mat = {"offset": o, "next": nxt, "ambient": f"{amb:08x}", "diffuse": f"{dif:08x}",
               "specular": f"{spc:08x}", "alpha": alpha, "shininess": shin}
    return {"size": size, "data_size": dsz, "relocations": nrel, "roots": list(roots),
            "root_name": "scene_data", "root_offset": root,
            "float_region": (0, float_hi), "float_floats": float_hi // 4,
            "scene_ptrs": scene_ptrs, "material0": mat}
