"""Phantasy Star Online Ver.2 (Dreamcast) player characters -> one skinned model (body + head) with its colour textures.

Disc layout (US 2OEF, found by gBox): per class a letter A..I (class id 0..8: HUmar, HUnewearl, HUcast, RAmar, RAcast,
RAcaseal, FOmarl, FOnewm, FOnewearl): PSO/PL<x>NJ.BML (plXbdy00.nj body + plXhedNN.nj heads; the same models also lie
loose as PSO/PL<x>BDY00.NJ, PL<x>HEDNN.NJ) and PSO/PL<x>TEX.AFS (PVR textures, no names).

The body is one weighted Ninja chunk model (64 nodes for HUcast). Its polygon lists are cached (chunk bits 4) and drawn
from a later node (bits 5) once every bone has written its share of the weighted vertices; gbox.ninja handles that.
Heads are separate one-node models drawn at the neck mount node (HUcast: node 59, identity rotation at the neck).

HUcast (PLC) texture layout in PLCTEX.AFS (110 PVRs), matched by drawing each texture id's UV layout over the images:
  0..44   9 colours x 5: torso, legs/upper parts, limbs, hands (64x64), glow (32x32)
          colours: 0 red, 1 blue, 2 yellow, 3 green, 4 purple, 5 black, 6 white, 7 navy, 8 brown
          body Ninja tex ids: 0 = section ID emblem quad (AFS 99 + section id), 1..4 = AFS 5 * colour + 0..3
  45..62  head 0: 9 colours x 2 (head tex 0 = head, tex 1 = visor glow)
  63..71, 72..80, 81..89  heads 1..3: one texture per colour (63 + 9 * (head - 1) + colour); 90..98 head 4 (unverified)
  99..108 section ID emblems (Viridia .. Whitill), 109 blank
The appearance in a character save (newserv PlayerVisualConfig): class u8 +0x31, costume u16 +0x38, skin +0x3A,
face +0x3C, head +0x3E, hair +0x40 (TObjPlayer + 0xC24 holds this block live on DC, after the 0x24-byte stats).
"""
from __future__ import annotations

import struct
from pathlib import Path

from . import ninja, uap

CLASSES = ["HUmar", "HUnewearl", "HUcast", "RAmar", "RAcast", "RAcaseal", "FOmarl", "FOnewm", "FOnewearl"]
HUCAST_COLOURS = ["red", "blue", "yellow", "green", "purple", "black", "white", "navy", "brown"]
HEAD_MOUNT = {"C": 59}


def afs(data: bytes) -> list[bytes]:
    n = struct.unpack_from("<I", data, 4)[0]
    return [data[o:o + s] for o, s in (struct.unpack_from("<II", data, 8 + 8 * i) for i in range(n))]


SECTION_IDS = ["Viridia", "Greenill", "Skyly", "Bluefull", "Purplenum", "Pinkal", "Redria", "Oran", "Yellowboze", "Whitill"]


def hucast_textures(colour: int, head: int, section_id: int = 7) -> tuple[list[int], list[int]]:
    """AFS entry per Ninja texture id: (body ids 0..4, head ids)."""
    body = [99 + section_id] + [5 * colour + t for t in range(4)]
    if head == 0:
        hd = [45 + 2 * colour, 46 + 2 * colour]
    elif head in (1, 2, 3):
        hd = [63 + 9 * (head - 1) + colour, 5 * colour + 4]
    else:
        hd = [90 + colour, 5 * colour + 4]
    return body, hd


def _mat_point(m, p):
    return [m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3] for i in range(3)]


def _mat_dir(m, p):
    return [m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] for i in range(3)]


def build(disc, cls: str = "C", head: int = 0, colour: int = 0, out_dir: Path | None = None, name: str | None = None,
          section_id: int = 7):
    """-> uap.Manifest (textures written as PNGs under out_dir/textures). disc: a gbox.gdrom.GDRom."""
    cls = cls.upper()
    body_nj = ninja.NJ(disc.read(f"PSO/PL{cls}BDY00.NJ"))
    head_nj = ninja.NJ(disc.read(f"PSO/PL{cls}HED{head:02d}.NJ"))
    mount = HEAD_MOUNT.get(cls, 59)
    mw = body_nj.bones[mount]["m"]
    # put the head's triangles into the body as extra texture ids (100 + id), moved to the mount, weighted to it
    for tex, tris in head_nj.tris.items():
        out = body_nj.tris.setdefault(100 + tex, [])
        for tri in tris:
            c2 = []
            for vi, t, *snap in tri:
                v = snap[0] if snap and snap[0] else head_nj.vbuf.get(vi)
                if v is None:
                    break
                c2.append((vi, t, {"pos": _mat_point(mw, v["pos"]), "nrm": _mat_dir(mw, v["nrm"]) if v["nrm"] else None,
                                   "joints": [(mount, 1.0)]}))
            else:
                out.append(tuple(c2))
    name = name or f"pso_{CLASSES['ABCDEFGHI'.index(cls)].lower()}_h{head}_c{colour}"
    tex_files: list[str | None] = [None] * 102
    if out_dir is not None:
        ents = afs(disc.read(f"PSO/PL{cls}TEX.AFS"))
        if cls == "C":
            b_ids, h_ids = hucast_textures(colour, head, section_id)
        else:                                               # ponytail: other classes' AFS layouts not mapped yet
            b_ids, h_ids = list(range(5)), []
        (Path(out_dir) / "textures").mkdir(parents=True, exist_ok=True)
        for slot, idx in [(t, i) for t, i in enumerate(b_ids)] + [(100 + t, i) for t, i in enumerate(h_ids)]:
            w, h, rgba, _ = ninja.pvr_decode(ents[idx])
            rel = f"textures/afs{idx:03d}.png"
            (Path(out_dir) / rel).write_bytes(ninja.png(w, h, rgba))
            tex_files[slot] = rel
    m = ninja.to_manifest(body_nj, name, {"game": "Phantasy Star Online Ver.2 (DC, US)", "class": cls, "head": head,
                                          "colour": colour, "section_id": section_id, "files": [f"PSO/PL{cls}BDY00.NJ", f"PSO/PL{cls}HED{head:02d}.NJ",
                                                                      f"PSO/PL{cls}TEX.AFS"],
                                          "extraction_method": "gbox.pso_player"}, tex_files)
    m.unit_scale_m = 0.1
    return m


def export(gdi: str, out_dir: str, cls: str = "C", head: int = 0, colour: int = 0, section_id: int = 7) -> Path:
    from .gdrom import GDRom
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    m = build(GDRom(gdi), cls, head, colour, out, section_id=section_id)
    (out / "manifest.json").write_text(m.model_dump_json())
    glb = out / f"{m.name}.glb"
    glb.write_bytes(uap.to_glb(m, out))
    return glb


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("out")
    ap.add_argument("--cls", default="C")
    ap.add_argument("--head", type=int, default=0)
    ap.add_argument("--colour", type=int, default=0)
    ap.add_argument("--section", type=int, default=7)
    a = ap.parse_args()
    print(export(a.gdi, a.out, a.cls, a.head, a.colour, a.section))
