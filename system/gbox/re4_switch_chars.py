"""RE4 (Nintendo Switch, 010099A00BC1E000) character reader: player `plXX.udas` packs -> textured, skinned GLB.

Reuses the measured container/model parsers in `re4_switch_assets` (UDAS -> DAT -> HD BIN + TPL -> ImagePackHD).
Slot 0 of a player DAT is the body BIN, slot 1 its TPL; each TPL image names an imagepackhd/<id>.pack.fen entry
(a DDS) that a BIN material's byte 12 (diffuse) indexes. All counts are bounded by the source extents by the
parsers; this module only adds the glTF assembly and the source lookup.
"""
from __future__ import annotations

import hashlib
import io
import json
import struct
from pathlib import Path

import numpy as np

from .re4_switch_assets import AssetError, Dat, HdBin, ImagePack, Tpl, Udas, triangles

TITLE_ID = "010099A00BC1E000"
READER_VERSION = 1
# Body BIN / texture TPL slots of a player pack (measured by re4_switch_assets.slot_summary).
BODY_SLOT, TPL_SLOT = 0, 1

# Player slots present in the owned build's bio4/ tree (pl13 and pl1b-pl20 are absent from the romfs).
PLAYER_IDS = [f"pl{i:02x}" for i in (*range(0x13), *range(0x14, 0x1B), 0x21)]
NAMES = {"pl00": "Leon (default)"}


def roster() -> list[dict]:
    return [{"key": cid, "slug": f"re4switch_{cid}", "name": NAMES.get(cid, cid.upper()),
             "aliases": [cid, cid.upper()], "kind": "character"} for cid in PLAYER_IDS]


def _romfs_root(game: dict) -> Path:
    cands = [Path.home() / "gBox_alt" / "switch" / "romfs" / TITLE_ID / "bio4"]
    for p in game.get("source_paths") or []:
        pp = Path(p)
        if pp.is_dir():
            cands += [pp / "bio4", pp]
    for c in cands:
        if (c / "imagepackhd").is_dir():
            return c
    raise FileNotFoundError(f"no extracted RE4 Switch romfs (bio4/imagepackhd) for {game.get('game_id')}; "
                            f"tried {[str(c) for c in cands]}")


def _glb(js: dict, blob: bytes) -> bytes:
    j = json.dumps(js, separators=(",", ":")).encode()
    j += b" " * (-len(j) % 4)
    blob += b"\0" * (-len(blob) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 28 + len(j) + len(blob)) + struct.pack("<II", len(j), 0x4E4F534A) + j
            + struct.pack("<II", len(blob), 0x004E4942) + blob)


def dds_to_png(dds: bytes) -> bytes:
    from PIL import Image
    img = Image.open(io.BytesIO(dds)).convert("RGBA")
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def build_glb(bin_bytes: bytes, tpl_bytes: bytes | None, root: Path | None) -> tuple[bytes, dict]:
    """Return (glb, stats). Textures are embedded when the TPL's image packs are found under `root`."""
    m = HdBin.parse(bin_bytes)
    pos = m.positions().astype(np.float32)
    nrm = m.normals().astype(np.float64)
    nrm = (nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)).astype(np.float32)
    uv = m.uvs().astype(np.float32)
    bones = m.bones()
    world = m.bone_world()
    wsets = m.weights()
    widx = m.weight_index()
    if len(widx) and wsets:
        if int(widx.max()) >= len(wsets):
            raise AssetError("vertex weight index outside the weight table")
    # glTF skin: one joint per bone id (first occurrence)
    ids = []
    for ident, _p, _t in bones:
        if ident not in ids:
            ids.append(ident)
    jnode = {ident: i for i, ident in enumerate(ids)}
    nodes: list[dict] = [{"name": f"bone_{ident}"} for ident in ids]
    for ident, parent, local in bones:
        nodes[jnode[ident]]["translation"] = [float(x) for x in local]
        if parent in jnode and parent != ident:
            nodes[jnode[parent]].setdefault("children", []).append(jnode[ident])
    has_parent = {c for n in nodes for c in n.get("children", [])}
    roots = [i for i in range(len(ids)) if i not in has_parent]

    joints = np.zeros((len(pos), 4), np.uint16)
    wts = np.zeros((len(pos), 4), np.float32)
    if wsets:
        table_j = np.zeros((len(wsets), 4), np.uint16)
        table_w = np.zeros((len(wsets), 4), np.float32)
        for si, ws in enumerate(wsets):
            tot = sum(w for _b, w in ws) or 1
            for k, (b, w) in enumerate(ws):
                table_j[si, k] = jnode.get(b, 0)
                table_w[si, k] = w / tot
        joints, wts = table_j[widx], table_w[widx]
    else:
        wts[:, 0] = 1.0

    # textures
    images: list[dict] = []
    textures_gltf: list[dict] = []
    tex_for_material: dict = {}
    blob = bytearray()
    views: list[dict] = []
    accessors: list[dict] = []

    def view(raw: bytes, target: int | None = None) -> int:
        while len(blob) % 4:
            blob.append(0)
        v: dict = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(raw)}
        if target:
            v["target"] = target
        blob.extend(raw)
        views.append(v)
        return len(views) - 1

    def accessor(arr: np.ndarray, ctype: int, atype: str, target: int | None = 34962, bounds=False) -> int:
        a: dict = {"bufferView": view(arr.tobytes(), target), "componentType": ctype, "count": int(arr.shape[0]),
             "type": atype}
        if bounds:
            a["min"] = [float(x) for x in arr.min(axis=0)]
            a["max"] = [float(x) for x in arr.max(axis=0)]
        accessors.append(a)
        return len(accessors) - 1

    tex_ok, tex_missing = 0, 0
    if tpl_bytes is not None and root is not None:
        try:
            tpl = Tpl.parse(tpl_bytes)
        except AssetError:                      # pl07 carries a TPL variant (magic 0x12345678) not yet measured
            tpl = None
            tex_missing = -1
        cache: dict[int, ImagePack] = {}
        for ti, img in enumerate(tpl.images if tpl else []):
            tex_index = None
            try:
                if img.pack_id not in cache:
                    cache[img.pack_id] = ImagePack.parse((root / "imagepackhd" / img.archive()).read_bytes())
                pack = cache[img.pack_id]
                if img.index >= len(pack.entries):
                    raise AssetError("TPL image index outside its pack")
                png = dds_to_png(pack.entries[img.index][1])
                images.append({"bufferView": view(png), "mimeType": "image/png", "name": f"tpl{ti}"})
                textures_gltf.append({"source": len(images) - 1})
                tex_index = len(textures_gltf) - 1
                tex_ok += 1
            except (OSError, AssetError, ValueError, KeyError):
                tex_missing += 1
            tex_for_material[ti] = tex_index

    a_pos = accessor(pos, 5126, "VEC3", bounds=True)
    a_nrm = accessor(nrm, 5126, "VEC3")
    a_uv = accessor(uv, 5126, "VEC2")
    a_j = accessor(joints, 5123, "VEC4")
    a_w = accessor(wts, 5126, "VEC4")
    prims, mats = [], []
    for mi, (mat, tris) in enumerate(zip(m.materials(), triangles(m.materials()))):
        if not len(tris):
            continue
        if int(tris.max()) >= len(pos):
            raise AssetError(f"material {mi}: triangle index outside the vertex table")
        a_idx = accessor(tris.reshape(-1).astype(np.uint32), 5125, "SCALAR", 34963)
        pbr = {"metallicFactor": 0.0, "roughnessFactor": 1.0}
        t = tex_for_material.get(mat.diffuse)
        if t is not None:
            pbr["baseColorTexture"] = {"index": t}
        mats.append({"name": f"mat{mi}", "pbrMetallicRoughness": pbr, "doubleSided": True})
        prims.append({"attributes": {"POSITION": a_pos, "NORMAL": a_nrm, "TEXCOORD_0": a_uv, "JOINTS_0": a_j,
                                     "WEIGHTS_0": a_w}, "indices": a_idx, "material": len(mats) - 1})
    ibm = np.zeros((len(ids), 4, 4), np.float32)
    for ident in ids:
        mtx = np.eye(4, dtype=np.float32)
        mtx[3, :3] = -np.asarray(world.get(ident, np.zeros(3)), np.float32)     # column-major translation
        ibm[jnode[ident]] = mtx
    a_ibm = accessor(ibm.reshape(-1, 16), 5126, "MAT4", None)
    accessors[a_ibm]["count"] = len(ids)
    nodes.append({"name": "mesh", "mesh": 0, "skin": 0})
    gltf = {"asset": {"version": "2.0", "generator": "gbox.re4_switch_chars"},
            "scene": 0, "scenes": [{"nodes": roots + [len(nodes) - 1]}], "nodes": nodes,
            "meshes": [{"primitives": prims}], "materials": mats,
            "skins": [{"joints": list(range(len(ids))), "inverseBindMatrices": a_ibm,
                       **({"skeleton": roots[0]} if roots else {})}],
            "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(blob)}]}
    if images:
        gltf["images"], gltf["textures"] = images, textures_gltf
    stats = {"vertices": len(pos), "triangles": int(sum(len(t) for t in triangles(m.materials()))),
             "bones": len(ids), "materials": len(mats), "textures_embedded": tex_ok, "textures_missing": tex_missing}
    return _glb(gltf, bytes(blob)), stats


def export_udas(udas: bytes, root: Path | None) -> tuple[bytes, dict]:
    _pack, dat = (lambda p: (p, Dat.parse(p.dat)))(Udas.parse(udas))
    if len(dat.slots) <= BODY_SLOT or not dat.slots[BODY_SLOT][1]:
        raise AssetError("pack has no body BIN in slot 0")
    tpl = dat.slots[TPL_SLOT][1] if len(dat.slots) > TPL_SLOT and dat.slots[TPL_SLOT][1] else None
    return build_glb(dat.slots[BODY_SLOT][1], tpl, root)


def extract_run(ctx, game: dict, e: dict, work) -> dict:
    """DEDICATED runner: export one RE4 Switch player model to GLB (+ embedded textures)."""
    work = Path(work)
    root = _romfs_root(game)
    src = root / "em" / f"{e['key']}.udas"
    if not src.is_file():
        raise FileNotFoundError(f"{src} not in the owned build")
    data = src.read_bytes()
    glb, stats = export_udas(data, root)
    out = work / "model.glb"
    out.write_bytes(glb)
    return {"files": [str(out)], "tool": "gbox.re4_switch_chars", "source_files": [f"bio4/em/{e['key']}.udas"],
            "source_sha256": hashlib.sha256(data).hexdigest(), "reader_version": READER_VERSION,
            "notes": f"RE4 Switch HD BIN (slot 0) + TPL (slot 1) -> skinned GLB; {stats}. Bind pose is "
                     "translation-only (no rotations in the bone table); UV orientation unvalidated in a renderer."}


if __name__ == "__main__":
    import sys
    p = Path(sys.argv[1])
    g, s = export_udas(p.read_bytes(), Path(sys.argv[3]) if len(sys.argv) > 3 else None)
    Path(sys.argv[2]).write_bytes(g)
    print(len(g), s)
