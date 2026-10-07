"""Play-as-anyone for Resident Evil 4 (GameCube, G4BE08): put a retargeted character (.glb skinned to Leon's b### bones)
into Leon's model packs and build a launchable file mod with its own disc-image name.

Pipeline (see the KB entries "play as Mario pipeline" and "RE4 GC: play as HUcast / Sonic"):
  1. source model -> glTF with a skeleton (gbox.pso_player, gbox.ninja, gbox.sm64_mario ...)
  2. glb_single_mesh(): one mesh object (retarget_rigid.py retargets the first mesh only); glb_merge_joints() when
     one rigid part (a shoe, a hand + cuff) is split over several source joints
  3. Blender: scripts/retarget_rigid.py target=Leon bin000.gltf, source, scripts/retarget_<char>_to_re4leon.json
  4. build_mod(): re4gc_models.swap_body on em/pl00, pl08, pl09, pl10 (Mercenaries Leon uses one of pl08/09/10),
     hiding Leon's head / hair / jacket / hand-pose BINs; every rebuilt .drs must stay <= its size on disc 1 (the disc
     is full); writes cache/mods/<game_id>/<name>/<image name>.iso + .gbox-mod.json so launch_game(mod=<name>) works.
     The image gets its own file name: gBox stages a mod image into cache/<game_id>/<file name> and reuses a staged
     file with the same name + size, so two mods sharing the vanilla name would boot each other's image.
"""
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

from . import re4gc_models as R

RE4_GAME_ID = "78ab9efa2e310db4"          # Resident Evil 4 (USA) (Disc 1), GameCube
# BINs collapsed per pack: head base, face, hair, jacket, eyes, cutscene head, extra parts, hand poses (14..21)
HIDE = {"em/pl00.drs": [2, 4, 5, 6, 7, 8, 9, 10] + list(range(14, 22)),
        "em/pl08.drs": [2, 4, 5, 6, 7, 8, 9, 10, 12] + list(range(14, 22)),
        "em/pl09.drs": [2, 4, 5, 6, 7, 8, 9, 10, 12] + list(range(14, 22)),
        "em/pl10.drs": [2, 4, 5, 6, 7, 8, 9, 10, 12] + list(range(14, 22))}


def glb_single_mesh(src: Path, dst: Path) -> Path:
    """Merge every mesh of a .glb into the first mesh (one primitive per original mesh) and drop the other mesh nodes'
    mesh/skin, so tools that take "the" mesh (retarget_rigid.py) see the whole character. Node indices are kept."""
    d = Path(src).read_bytes()
    jl = struct.unpack_from("<I", d, 12)[0]
    gl = json.loads(d[20:20 + jl])
    blob = d[20 + jl + 8:]
    mesh_nodes = [i for i, n in enumerate(gl["nodes"]) if "mesh" in n]
    if len(mesh_nodes) > 1:
        first = gl["nodes"][mesh_nodes[0]]
        prims = []
        for i in mesh_nodes:
            prims += gl["meshes"][gl["nodes"][i]["mesh"]]["primitives"]
        gl["meshes"][first["mesh"]]["primitives"] = prims
        for i in mesh_nodes[1:]:
            gl["nodes"][i].pop("mesh", None)
            gl["nodes"][i].pop("skin", None)
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    out = (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob)) + struct.pack("<II", len(js), 0x4E4F534A)
           + js + struct.pack("<II", len(blob), 0x004E4942) + blob)
    Path(dst).write_bytes(out)
    return Path(dst)


def glb_merge_joints(src: Path, dst: Path, merge: dict[str, str]) -> Path:
    """Re-skin the vertices of joint A to joint B ({A name: B name}) so a retarget rule moves them as one rigid part
    (e.g. a shoe split over two Ninja nodes). Only JOINTS_0 values change; the skeleton stays."""
    import numpy as np
    d = Path(src).read_bytes()
    jl = struct.unpack_from("<I", d, 12)[0]
    gl = json.loads(d[20:20 + jl])
    blob = bytearray(d[20 + jl + 8:])
    for skin in gl.get("skins", []):
        names = [gl["nodes"][j].get("name") for j in skin["joints"]]
        remap = {names.index(a): names.index(b) for a, b in merge.items() if a in names and b in names}
        for mesh in gl["meshes"]:
            for pr in mesh["primitives"]:
                if "JOINTS_0" not in pr["attributes"]:
                    continue
                acc = gl["accessors"][pr["attributes"]["JOINTS_0"]]
                bv = gl["bufferViews"][acc["bufferView"]]
                dt = np.uint16 if acc["componentType"] == 5123 else np.uint8
                off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
                n = acc["count"] * 4
                arr = np.frombuffer(bytes(blob[off:off + n * np.dtype(dt).itemsize]), dt).copy()
                for a, b in remap.items():
                    arr[arr == a] = b
                blob[off:off + arr.nbytes] = arr.tobytes()
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    Path(dst).write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob))
                          + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + blob)
    return Path(dst)


def swap_packs(iso: Path, glb: Path, out_dir: Path, max_tex: int = 128, packs=None) -> dict:
    """Rebuild the player packs with the new body; writes <out_dir>/<plXX>.drs and returns per-pack stats. Raises if a
    pack would grow (lower max_tex or decimate the model then)."""
    from .gcdisc import GCDisc
    if Path(iso).is_dir():                                   # an extracted Wii disc (gbox/re4wii.py): same pack formats
        from .re4wii import FolderDisc
        disc = FolderDisc(iso)
    else:
        disc = GCDisc(iso)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rep = {}
    try:
        for name in (packs or HIDE):
            orig = disc.read(name)
            pk = R.ModelPack(orig)
            st = R.swap_body(pk, glb, 0, hide=HIDE[name], max_tex=max_tex, shrink_hidden=True)
            new = pk.to_bytes()
            if len(new) > len(orig):
                raise ValueError(f"{name}: {len(new)} bytes > {len(orig)} on disc; lower max_tex or the triangle count")
            (out_dir / Path(name).name).write_bytes(new)
            rep[name] = {**st, "bytes": len(new), "disc_bytes": len(orig)}
    finally:
        disc.f.close()
    return rep


def build_mod(cache: Path, iso: Path, drs_dir: Path, name: str, image_name: str, game_id: str = RE4_GAME_ID) -> dict:
    """A file mod (same layout filemods.build_image writes) whose image has its own file name."""
    import types
    from . import filemods
    link = Path(drs_dir) / image_name                       # build_image names the image after the rom it copies
    if link.exists():
        link.unlink()
    os.link(iso, link)
    stale = Path(cache) / game_id / image_name                 # a staged copy of an older build has the same name +
    if stale.exists():                                         # size and would be reused by launch_game
        stale.unlink()
    try:
        changes = {f"em/{p.name}": {"from": str(p)} for p in sorted(Path(drs_dir).glob("pl*.drs"))}
        return filemods.build_image(types.SimpleNamespace(cache=Path(cache)), game_id, link, name, changes)
    finally:
        link.unlink()


def gltf_texture_count(glb: Path) -> int:
    d = Path(glb).read_bytes()
    jl = struct.unpack_from("<I", d, 12)[0]
    return len(json.loads(d[20:20 + jl]).get("images", []))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("single-mesh")
    a1.add_argument("src")
    a1.add_argument("dst")
    a2 = sub.add_parser("packs")
    a2.add_argument("iso")
    a2.add_argument("glb")
    a2.add_argument("out_dir")
    a2.add_argument("--max-tex", type=int, default=128)
    a4 = sub.add_parser("merge-joints")
    a4.add_argument("src")
    a4.add_argument("dst")
    a4.add_argument("pairs", nargs="+", help="from=to joint names, e.g. node014=node013")
    a3 = sub.add_parser("mod")
    a3.add_argument("cache")
    a3.add_argument("iso")
    a3.add_argument("drs_dir")
    a3.add_argument("name")
    a3.add_argument("image_name")
    a = ap.parse_args()
    if a.cmd == "single-mesh":
        print(glb_single_mesh(Path(a.src), Path(a.dst)))
    elif a.cmd == "merge-joints":
        print(glb_merge_joints(Path(a.src), Path(a.dst), dict(x.split("=") for x in a.pairs)))
    elif a.cmd == "packs":
        print(json.dumps(swap_packs(Path(a.iso), Path(a.glb), Path(a.out_dir), a.max_tex), indent=1))
    else:
        print(json.dumps(build_mod(Path(a.cache), Path(a.iso), Path(a.drs_dir), a.name, a.image_name), indent=1))
