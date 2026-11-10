"""Nintendogs (NDS, gamecode ADG*) reader: owned .7z/.nds -> breed slots (DogArc/*.narc) -> editable NSBMD.

Layout measured from the USA Dachshund & Friends ROM: ``DogArc/<Breed>_<variant>.narc`` holds one
``.nsbmd`` (BMD0 model, textured), ``.NCLR`` palette, ``.bncl`` and ``.nce.bncd`` per coat variant;
``Dog/Model/Tan_model.nsbmd`` and ``Dog/Anm/Keep.narc`` / ``Dog/Anm/Load/*.nsbca`` are shared
skeleton/animation assets.
"""
from __future__ import annotations

import hashlib
import struct
import subprocess
import tempfile
from pathlib import Path

from .nitro import NitroROM, narc


def sha256_stream(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_nds_from_7z(archive: str | Path, outdir: str | Path) -> Path:
    """Extract the first .nds member with 7z (gBox cannot list .7z itself)."""
    subprocess.run(["7z", "x", "-y", f"-o{outdir}", str(archive), "*.nds"], check=True, capture_output=True)
    found = sorted(Path(outdir).rglob("*.nds"))
    if not found:
        raise FileNotFoundError("no .nds member in archive")
    return found[0]


def parse_bmd0(blob: bytes) -> dict:
    """NSBMD header: magic, size, and the block table (MDL0 model / TEX0 textures)."""
    if blob[:4] != b"BMD0":
        raise ValueError("not a BMD0/NSBMD")
    bom, ver, size, hsize, nblk = struct.unpack_from("<HHIHH", blob, 4)
    if bom != 0xFEFF or size != len(blob):
        raise ValueError(f"bad BMD0 header bom={bom:#x} size={size} actual={len(blob)}")
    offs = struct.unpack_from(f"<{nblk}I", blob, 16)
    blocks = {}
    for o in offs:
        tag, bsize = blob[o:o + 4].decode("latin-1"), struct.unpack_from("<I", blob, o + 4)[0]
        if o + bsize > len(blob):
            raise ValueError(f"block {tag} overruns file")
        blocks[tag] = (o, bsize)
    return {"size": size, "blocks": blocks}


class Nintendogs:
    def __init__(self, rom_bytes: bytes):
        self.rom = NitroROM(rom_bytes)
        if not self.rom.gamecode.startswith("ADG"):
            raise ValueError(f"not Nintendogs: gamecode {self.rom.gamecode!r}")

    def slots(self) -> list[str]:
        """Breed/coat slot names, e.g. 'Bgl_a'."""
        return [p.split("/")[1][:-5] for p in self.rom.paths() if p.startswith("DogArc/") and p.endswith(".narc")]

    def slot_members(self, slot: str) -> dict[str, bytes]:
        return dict(narc(self.rom.raw(f"DogArc/{slot}.narc")))

    def export_model(self, slot: str) -> tuple[str, bytes, dict]:
        for name, data in self.slot_members(slot).items():
            if name.lower().endswith(".nsbmd"):
                return name, data, parse_bmd0(data)
        raise KeyError(f"slot {slot} has no nsbmd")

    def shared_animations(self) -> list[str]:
        return [p for p in self.rom.paths() if p.startswith("Dog/Anm/Load/") and p.endswith(".nsbca")]


# ---- analysis: MDL0 / TEX0 structure (Nitro 3D) ----------------------------------------------
TEX_FORMATS = {0: "none", 1: "A3I5", 2: "pal4", 3: "pal16", 4: "pal256", 5: "tex4x4", 6: "A5I3", 7: "direct"}


def parse_dict(blob: bytes, pos: int) -> tuple[list[str], list[bytes]]:
    """Nitro 3D dict at ``pos``: head(dummy,count,u16 size,u32 hdr) + (count+1) tree nodes,
    then u16 unit size, u16 section size, count data units, count 16-byte names."""
    count = blob[pos + 1]
    dsize = struct.unpack_from("<H", blob, pos + 2)[0]
    if pos + dsize > len(blob):
        raise ValueError("3D dict overruns blob")
    unit_at = pos + 8 + 4 * (count + 1)
    unit_size = struct.unpack_from("<H", blob, unit_at)[0]
    data_at = unit_at + 4
    names_at = data_at + unit_size * count
    if names_at + 16 * count != pos + dsize:
        raise ValueError(f"3D dict size mismatch: {names_at + 16 * count - pos} != {dsize}")
    names = [blob[names_at + 16 * i:names_at + 16 * i + 16].split(b"\0")[0].decode("latin-1") for i in range(count)]
    datas = [blob[data_at + unit_size * i:data_at + unit_size * (i + 1)] for i in range(count)]
    return names, datas


def parse_mdl0(blob: bytes, mdl_off: int) -> dict:
    """Model summary: name, bone/material/shape counts, vertex totals, node/material/shape names."""
    names, datas = parse_dict(blob, mdl_off + 8)
    models = []
    for name, d in zip(names, datas):
        m = mdl_off + struct.unpack("<I", d[:4])[0]
        size, sbc, mat, shp, evp = struct.unpack_from("<5I", blob, m)
        sbc_type, scale_rule, texscale_rule, n_node, n_mat, n_shp, first_unused = struct.unpack_from("<7B", blob, m + 0x14)
        pos_scale, inv_scale = struct.unpack_from("<ii", blob, m + 0x1C)
        n_vert, n_surf, n_tri, n_quad = struct.unpack_from("<4H", blob, m + 0x24)
        node_names, _ = parse_dict(blob, m + 0x40)
        models.append({
            "name": name, "offset": m, "size": size, "n_bones": n_node, "n_materials": n_mat, "n_shapes": n_shp,
            "pos_scale": pos_scale, "n_vertices": n_vert, "n_surfaces": n_surf, "n_tris": n_tri, "n_quads": n_quad,
            "bones": node_names,
        })
    return {"models": models}


def parse_tex0(blob: bytes, tex_off: int) -> dict:
    """Embedded textures: name, format, size. Texture info dict is at TEX0+u16@0x0E."""
    info_off = struct.unpack_from("<H", blob, tex_off + 0x0E)[0]
    names, datas = parse_dict(blob, tex_off + info_off)
    tex = []
    for name, d in zip(names, datas):
        off8, param, width = struct.unpack_from("<HHH", d, 0)
        fmt = (param >> 10) & 7
        w, h = 8 << ((param >> 4) & 7), 8 << ((param >> 7) & 7)
        bpp = {1: 8, 2: 2, 3: 4, 4: 8, 5: 2, 6: 8, 7: 16}.get(fmt, 0)
        tex.append({
            "name": name, "format": TEX_FORMATS[fmt], "width": w, "height": h, "param": param,
            "data_off": off8 << 3, "data_bytes": w * h * bpp // 8,
            "color0_transparent": bool(param & 0x2000),
        })
    return {"textures": tex}


def analyze_nsbmd(blob: bytes) -> dict:
    info = parse_bmd0(blob)
    out = {"size": info["size"], "blocks": info["blocks"]}
    if "MDL0" in info["blocks"]:
        out.update(parse_mdl0(blob, info["blocks"]["MDL0"][0]))
    if "TEX0" in info["blocks"]:
        out.update(parse_tex0(blob, info["blocks"]["TEX0"][0]))
    return out
