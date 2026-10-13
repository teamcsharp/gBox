"""Collection character -> a Sega Ninja (NJCM chunk) player model: the shared half of the SA2 (gbox.sa2_chars) and
PSO (gbox.pso_player) swap writers.

The character is retargeted onto the game model's own node tree (gbox.sm64_swap.retarget with a role -> node map,
the node tree's bind pose as the target pose), decimated in Blender to a triangle budget, and cut into rigid
per-node geometry: every triangle rides one node (the majority of its corners), its vertices are stored in that
node's space as chunk vertices 0x29 (position + normal) and drawn by the same node as 3-vertex strips (0x41, UVs on
the strips) with one texture: all of the character's textures packed into one square atlas (gbox.re6_models._pack),
written as a VQ PVR (gbox.ninja.pvr_vq). The game keeps its node tree, so its own motions animate the character.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import ninja


def target_from_nj(nj: ninja.NJ, roles: dict[str, int], head_nodes: set[int] | None = None) -> dict:
    """The tree's bind pose as a gbox.sm64_swap.retarget target. nj: parsed (gbox.ninja / sa2_chars.load_object)
    with a root matrix that makes the model face +Z with its left at +X."""
    W = [np.array(b["m"], float) for b in nj.bones]
    T = np.array([w[:3, 3] for w in W])
    pts, heads = [], []
    head_nodes = head_nodes or set()
    for tris in nj.tris.values():
        for tri in tris:
            for c in tri:
                v = c[2] if len(c) > 2 and c[2] else nj.vbuf.get(c[0])
                if v:
                    pts.append(v["pos"])
                    if max(v["joints"], key=lambda jw: jw[1])[0] in head_nodes:
                        heads.append(v["pos"])
    pts = np.array(pts) if pts else T
    heads = np.array(heads) if heads else pts[pts[:, 1] > np.percentile(pts[:, 1], 80)]
    return {"T": T, "W": W, "parent": [-1 if b["parent"] is None else b["parent"] for b in nj.bones],
            "ground": float(pts[:, 1].min()), "head_h": float(np.ptp(heads[:, 1])), "joints": len(W),
            "height": float(np.ptp(pts[:, 1])), "roles": roles}


def _dedupe_textures(prims: list[dict]) -> None:
    seen = {}
    for p in prims:
        t = p.get("tex")
        if t is not None:
            p["tex"] = seen.setdefault(hash(np.ascontiguousarray(t).tobytes()), t)


def fit(model: Path, src_roles: dict, tgt: dict, work: Path, name: str, budgets, blender: str | None, encode,
        atlas: int = 256, scale: dict | None = None, progress=lambda p, m: None) -> dict:
    """Retarget + decimate until encode(geometry) fits. encode({node: (pos, nrm, tris)}) -> bytes or raises
    ValueError (too big). budgets: triangle counts to try, largest first. -> {data, atlas (PIL), report, rigged}."""
    from . import re6_models, sm64_swap as S
    from .re4gc_enemies import decimate
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    rig = S.load_rig(Path(model), src_roles)
    prims, rep = S.retarget(rig, tgt, scale, jmap=tgt["roles"])
    rigged = S.write_rigged(prims, tgt, work / "rigged.gltf", name)
    src_tris = sum(len(p["tris"]) for p in prims)
    rep["source_triangles"] = src_tris
    last = None
    from . import fit_events as FE
    if FE.active():                                        # every vertex rides one node (the game's own tree)
        collapse = tgt.get("collapse") or {}
        names = {int(n): f"{r} (node {n})" for r, n in (tgt.get("roles") or {}).items()}
        counts = FE.per_limb(prims, names, owner=lambda j: int(collapse.get(j, j)))
        FE.stage("weights", data={"mode": "rigid per node (one node per vertex)", "nodes": len(counts),
                                  "skeleton_nodes": tgt.get("joints"), "vertices": int(sum(counts.values())),
                                  "per_limb": counts})
    for k, budget in enumerate(budgets):
        src = rigged
        if src_tris <= budget and k == 0:
            FE.stage("decimate", "skipped", {"from": src_tris, "triangles": src_tris, "budget": budget})
        if src_tris > budget:
            if not blender:
                raise ValueError(f"{src_tris} triangles (budget {budget}) and no Blender on this node to decimate")
            progress(40, f"Decimating {name} to {budget} triangles (Blender)")
            FE.stage("decimate", "running", {"from": src_tris, "to": budget})
            src = decimate(rigged, work / f"dec_{budget}.glb", float(budget), blender)
        rp = S.read_rigged(src)
        if src is not rigged:
            FE.stage("decimate", data={"from": src_tris, "to": budget,
                                       "triangles": int(sum(len(p["tris"]) for p in rp))}, prims=rp)
        _dedupe_textures(rp)
        for p in rp:
            p["J"] = np.asarray(p["jid"])[:, None] if np.ndim(p["jid"]) == 1 else np.asarray(p["jid"])
        img = re6_models._pack(rp, atlas)                  # un-indexes the prims, uv -> atlas
        if img.size != (atlas, atlas):                     # a 3x3 grid packs 255 px; uvs are fractions: resize
            img = img.resize((atlas, atlas))
        geo = split_nodes(rp, tgt)
        try:
            data = encode(geo)
        except ValueError as e:
            last = e
            FE.stage("encode", "running", {"budget": budget, "result": str(e)[:120]})
            continue
        tris = sum(len(g[2]) for g in geo.values())
        FE.stage("encode", data={"budget": budget, "triangles": tris, "nodes": len(geo),
                                 "bytes": len(data) if isinstance(data, (bytes, bytearray)) else None})
        return {"data": data, "atlas": img, "rigged": rigged, "geometry": geo,
                "report": rep | {"triangles": tris, "budget": budget, "nodes": sorted(int(k) for k in geo)}}
    raise last or ValueError("no triangle budget fits")


def split_nodes(prims: list[dict], tgt: dict) -> dict:
    """Un-indexed prims (world positions in the bind pose, joint per vertex in J[:, 0]) -> {node: (pos, nrm,
    [((i0, i1, i2), ((u, v) x3))])} in node space, one vertex per position within a node. tgt["collapse"] {joint:
    node}: geometry fitted to a joint the game can't draw from (a marker node, a virtual limb end: gbox.pso_enemy)
    is stored on that node instead."""
    inv = [np.linalg.inv(w) for w in tgt["W"]]
    collapse = tgt.get("collapse") or {}
    out: dict = {}
    keys: dict = {}
    for p in prims:
        P, N, UV = np.asarray(p["pos"], float), np.asarray(p["nrm"], float), np.asarray(p["uv"], float)
        J = np.asarray(p["J"]).reshape(len(P), -1)[:, 0]
        for t in np.asarray(p["tris"]).reshape(-1, 3):
            j = int(np.bincount(J[t]).argmax())
            j = int(collapse.get(j, j))
            M = inv[j]
            pos, nrm, tris = out.setdefault(j, ([], [], []))
            kk = keys.setdefault(j, {})
            idx = []
            for i in t:
                q = M[:3, :3] @ P[i] + M[:3, 3]
                n = M[:3, :3] @ N[i]
                n = n / (np.linalg.norm(n) or 1)
                key = tuple(np.round(q, 3))                 # one vertex per position (UVs live on the strips);
                if key not in kk:                           # its normal = the mean of the corners' normals
                    kk[key] = len(pos)
                    pos.append(q)
                    nrm.append(np.zeros(3))
                nrm[kk[key]] = nrm[kk[key]] + n
                idx.append(kk[key])
            tris.append((tuple(idx), tuple((float(UV[i][0]), float(UV[i][1])) for i in t)))
    res = {}
    for j, (a, b, c) in out.items():
        b = np.array(b)
        b /= np.maximum(np.linalg.norm(b, axis=1, keepdims=True), 1e-9)
        res[j] = (np.array(a), b, c)
    return res


def preview(rigged: Path, out: Path) -> Path:
    from . import characters as C
    return C.render_preview(Path(rigged), Path(out))


def report_json(rep: dict) -> str:
    return json.dumps(rep, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
