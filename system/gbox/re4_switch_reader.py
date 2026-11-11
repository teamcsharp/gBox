"""RE4 (Switch, 010099A00BC1E000) character model reader: bio4/em/<id>.udas -> skinned GLB + PNG textures.

Read-only: opens the extracted RomFS (``~/gBox_alt/switch/romfs/<title>/bio4``) and never writes to it. Built on
``gbox.re4_switch_assets`` (UDAS/DAT, HD BIN, TPL, imagepackhd FEN) - the same readers the model-replacement tools use.
DEDICATED-reader interface: ``roster()`` and ``extract_run(ctx, game, e, work)``.
"""
from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import numpy as np

from . import re4_switch_assets as A

TITLE_ID = "010099A00BC1E000"
GAME_ID = "270a15eb98dab4d7"
NAMES = {"pl00": "Leon (default)", "pl06": "HUNK", "pl08": "Leon", "pl0a": "Krauser", "pl0b": "Ada", "pl0d": "Wesker"}


def romfs_root(game: dict | None = None) -> Path:
    cands = []
    for p in (game or {}).get("source_paths") or []:
        cands.append(Path(p))
    cands.append(Path.home() / "gBox_alt" / "switch" / "romfs" / TITLE_ID)
    for c in cands:
        if (c / "bio4" / "em").is_dir():
            return c
    raise FileNotFoundError(f"no extracted RE4 Switch RomFS ({TITLE_ID}) with bio4/em")


def roster(root: Path | None = None) -> list[dict]:
    """Every pl*/em* UDAS pack in bio4/em when the RomFS is present, else the known player range."""
    try:
        ids = sorted(p.stem for p in (Path(root) if root else romfs_root()).joinpath("bio4", "em").glob("*.udas"))
    except FileNotFoundError:
        ids = [f"pl{i:02x}" for i in range(0x1B)]
    return [{"key": c, "slug": f"re4sw_{c}", "name": NAMES.get(c, c.upper()), "aliases": [c, c.upper()],
             "kind": "character"} for c in ids if c[:2] in ("pl", "em")]


def _png(rgba: np.ndarray) -> bytes:
    h, w = rgba.shape[:2]
    raw = b"".join(b"\0" + rgba[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _c565(v: np.ndarray) -> np.ndarray:
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    return np.stack([(r * 255 + 15) // 31, (g * 255 + 31) // 63, (b * 255 + 15) // 31], -1).astype(np.uint16)


def _bc1(blocks: np.ndarray, alpha_ok: bool) -> np.ndarray:
    """blocks (n, 8) u8 -> (n, 16, 4) u8."""
    c0 = blocks[:, 0].astype(np.uint16) | (blocks[:, 1].astype(np.uint16) << 8)
    c1 = blocks[:, 2].astype(np.uint16) | (blocks[:, 3].astype(np.uint16) << 8)
    p0, p1 = _c565(c0), _c565(c1)
    four = (c0 > c1)[:, None]
    pal = np.zeros((len(blocks), 4, 4), np.uint16)
    pal[:, 0, :3], pal[:, 1, :3] = p0, p1
    pal[:, 2, :3] = np.where(four, (2 * p0 + p1) // 3, (p0 + p1) // 2)
    pal[:, 3, :3] = np.where(four, (p0 + 2 * p1) // 3, 0)
    pal[:, :, 3] = 255
    if alpha_ok:
        pal[:, 3, 3] = np.where(four[:, 0], 255, 0)
    bits = blocks[:, 4:8].copy().view("<u4")[:, 0]
    idx = (bits[:, None] >> (2 * np.arange(16))[None, :]) & 3
    return np.take_along_axis(pal, idx[:, :, None], 1).astype(np.uint8)


def decode_dds(dds: bytes) -> np.ndarray | None:
    """Top mip of a DXT1/DXT3/DXT5 DDS as (h, w, 4) RGBA; None for other formats."""
    info = A.dds_info(dds)
    w, h, cc = info["width"], info["height"], info["fourcc"]
    bw, bh = (w + 3) // 4, (h + 3) // 4
    if cc == "DXT1":
        px = _bc1(np.frombuffer(dds, np.uint8, bw * bh * 8, 128).reshape(-1, 8), True)
    elif cc in ("DXT3", "DXT5"):
        raw = np.frombuffer(dds, np.uint8, bw * bh * 16, 128).reshape(-1, 16)
        px = _bc1(raw[:, 8:], False)
        if cc == "DXT3":
            a = np.stack([raw[:, 0:8][:, i // 2] >> (4 * (i % 2)) & 15 for i in range(16)], 1) * 17
        else:
            a0, a1 = raw[:, 0].astype(np.int64), raw[:, 1].astype(np.int64)
            bits = np.zeros(len(raw), np.uint64)
            for i in range(6):
                bits |= raw[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
            code = ((bits[:, None] >> (3 * np.arange(16, dtype=np.uint64))[None, :]) & np.uint64(7)).astype(np.int64)
            tab = np.zeros((len(raw), 8), np.int64)
            tab[:, 0], tab[:, 1] = a0, a1
            eight = a0 > a1
            for k in range(1, 7):
                tab[:, k + 1] = np.where(eight, ((7 - k) * a0 + k * a1) // 7,
                                         ((6 - k) * a0 + k * a1) // 5 if k <= 4 else (0 if k == 5 else 255))
            a = np.take_along_axis(tab, code, 1)
        px[:, :, 3] = a.astype(np.uint8)
    else:
        return None
    img = px.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return np.ascontiguousarray(img[:h, :w])


def _glb(gltf: dict, blob: bytes) -> bytes:
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    blob += b"\0" * (-len(blob) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(blob)) + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(blob), 0x004E4942) + blob)


def build_glb(bins: list[tuple[int, A.HdBin]], images: list[bytes], tex_of: dict) -> tuple[bytes, dict]:
    """One skinned glTF: the body skeleton (largest BIN's bones) + every BIN's mesh (positions in mm -> metres)."""
    body = max(bins, key=lambda t: t[1].bone_count)[1]
    bones = body.bones()
    node_of = {ident: i for i, (ident, _p, _t) in enumerate(bones)}
    nodes = [{"name": f"bone_{ident}", "translation": [t[0] / 1000, t[1] / 1000, t[2] / 1000]}
             for ident, _p, t in bones]
    roots = []
    for ident, parent, _t in bones:
        if parent in node_of and parent != ident:
            nodes[node_of[parent]].setdefault("children", []).append(node_of[ident])
        else:
            roots.append(node_of[ident])
    blob = bytearray(); views = []; accs = []

    def add(arr: np.ndarray, ctype: int, typ: str, target=None):
        arr = np.ascontiguousarray(arr)
        blob.extend(b"\0" * (-len(blob) % 4))
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": arr.nbytes, **({"target": target} if target else {})})
        blob.extend(arr.tobytes())
        acc = {"bufferView": len(views) - 1, "componentType": ctype, "count": int(arr.shape[0]), "type": typ}
        if typ == "VEC3" and ctype == 5126:
            acc["min"], acc["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(acc)
        return len(accs) - 1

    meshes, mesh_nodes, mats, used_tex = [], [], [], {}
    mat_index = {}
    stats = {"vertices": 0, "triangles": 0}
    for slot, b in bins:
        pos = (b.positions().astype(np.float32) / 1000.0)
        nrm = b.normals().astype(np.float64)
        ln = np.linalg.norm(nrm, axis=1, keepdims=True)
        nrm = (nrm / np.where(ln == 0, 1, ln)).astype(np.float32)
        uv = b.uvs().astype(np.float32)
        wsets = b.weights()
        wi = b.weight_index()
        joints = np.zeros((len(pos), 4), np.uint16); wts = np.zeros((len(pos), 4), np.float32)
        for s, ws in enumerate(wsets):
            sel = wi == s
            if not sel.any():
                continue
            tot = sum(p for _b, p in ws) or 1
            for k, (bone, pct) in enumerate(ws):
                joints[sel, k] = node_of.get(bone, 0); wts[sel, k] = pct / tot
        attrs = {"POSITION": add(pos, 5126, "VEC3", 34962), "NORMAL": add(nrm, 5126, "VEC3", 34962),
                 "TEXCOORD_0": add(uv, 5126, "VEC2", 34962), "JOINTS_0": add(joints, 5123, "VEC4", 34962),
                 "WEIGHTS_0": add(wts, 5126, "VEC4", 34962)}
        prims = []
        for m, tris in zip(b.materials(), A.triangles(b.materials())):
            if not len(tris):
                continue
            tex = tex_of.get((slot, m.diffuse))
            key = tex
            if key not in mat_index:
                mat = {"name": f"mat_{len(mats)}", "doubleSided": True}
                if tex is not None:
                    used_tex.setdefault(tex, len(used_tex))
                    mat["pbrMetallicRoughness"] = {"baseColorTexture": {"index": used_tex[tex]}, "metallicFactor": 0.0}
                mat_index[key] = len(mats); mats.append(mat)
            idx = add(tris.astype(np.uint32).reshape(-1), 5125, "SCALAR", 34963)
            prims.append({"attributes": attrs, "indices": idx, "material": mat_index[key]})
            stats["triangles"] += int(len(tris))
        stats["vertices"] += int(len(pos))
        meshes.append({"name": f"slot_{slot}", "primitives": prims})
    skin_nodes = [node_of[i] for i, _p, _t in bones]
    inv = np.tile(np.eye(4, dtype=np.float32), (len(bones), 1, 1))
    world = body.bone_world()
    for ident, i in node_of.items():
        if ident in world:
            inv[i, 3, :3] = -np.asarray(world[ident], np.float32) / 1000.0     # column-major translation
    ibm = add(inv.reshape(-1, 16), 5126, "MAT4")
    for i in range(len(meshes)):
        nodes.append({"name": meshes[i]["name"], "mesh": i, "skin": 0}); mesh_nodes.append(len(nodes) - 1)
    gltf = {"asset": {"version": "2.0", "generator": "gbox.re4_switch_reader"},
            "scenes": [{"nodes": roots + mesh_nodes}], "nodes": nodes, "meshes": meshes, "materials": mats,
            "skins": [{"joints": skin_nodes, "inverseBindMatrices": ibm, "skeleton": roots[0]}] if roots else [],
            "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": len(blob)}]}
    if used_tex:
        ordered = sorted(used_tex, key=used_tex.get)
        gltf["textures"] = [{"source": i, "sampler": 0} for i in range(len(ordered))]
        gltf["images"] = [{"uri": f"tex_{k[0]}_{k[1]}.png", "mimeType": "image/png"} for k in ordered]
        gltf["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]
    if not gltf["skins"]:
        del gltf["skins"]
        for n in nodes:
            n.pop("skin", None)
    return _glb(gltf, bytes(blob)), {**stats, "bones": len(bones), "materials": len(mats), "textures": len(used_tex)}


def load_pack(root: Path, key: str):
    data = (Path(root) / "bio4" / "em" / f"{key}.udas").read_bytes()
    return A.pack_slots(data)


def export_pack(root: Path, key: str, work: Path) -> dict:
    """Decode one pack: every non-empty BIN slot + the TPL that follows it (or the pack's first TPL)."""
    root, work = Path(root), Path(work)
    work.mkdir(parents=True, exist_ok=True)
    _udas, dat = load_pack(root, key)
    bins, tpls = [], {}
    for i, (ext, payload) in enumerate(dat.slots):
        if not payload:
            continue
        try:
            if A.struct.unpack_from("<I", payload, 0)[0] == A.TPL_MAGIC:
                tpls[i] = A.Tpl.parse(payload); continue
        except (A.AssetError, struct.error):
            pass
        try:
            bins.append((i, A.HdBin.parse(payload, verify=False)))
        except Exception:
            continue
    if not bins:
        raise A.AssetError(f"{key}: no HD BIN slot decoded")
    tpl = tpls[min(tpls)] if tpls else None
    packs, png_files, tex_of = {}, [], {}
    if tpl:
        wanted = {(slot, m.diffuse) for slot, b in bins for m in b.materials() if m.diffuse != 0xFF and m.diffuse < len(tpl.images)}
        for slot, di in wanted:
            im = tpl.images[di]
            fen = root / "bio4" / "imagepackhd" / im.archive()
            if not fen.exists():
                continue
            ip = packs.get(im.pack_id) or packs.setdefault(im.pack_id, A.ImagePack.parse(fen.read_bytes()))
            if im.index >= len(ip.entries):
                continue
            rgba = decode_dds(ip.entries[im.index][1])
            if rgba is None:
                continue
            tex_of[(slot, di)] = (im.pack_id, im.index)
            p = work / f"tex_{im.pack_id}_{im.index}.png"
            if str(p) not in png_files:
                p.write_bytes(_png(rgba)); png_files.append(str(p))
    glb, stats = build_glb(bins, [], tex_of)
    out = work / "model.glb"
    out.write_bytes(glb)
    return {"glb": str(out), "pngs": png_files, **stats, "bin_slots": [s for s, _ in bins]}


def extract_run(ctx, game: dict, e: dict, work) -> dict:
    """DEDICATED runner: export one RE4 Switch character pack to GLB + PNG textures (read-only on the RomFS)."""
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    root = romfs_root(game)
    res = export_pack(root, e["key"], work)
    return {"files": [res["glb"], *res["pngs"]], "tool": "gbox.re4_switch_reader",
            "source_files": [f"bio4/em/{e['key']}.udas"],
            "notes": f"RE4 Switch HD BIN -> skinned GLB: {res['vertices']} verts, {res['triangles']} tris, "
                     f"{res['bones']} bones, {res['textures']} diffuse textures (BC1/BC3 -> PNG); BIN slots {res['bin_slots']}."}
