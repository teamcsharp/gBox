"""Sonic Adventure (Dreamcast) writer foundation: the basic-model (NJS_MODEL) data span — the writer budget a
donor must fit — and a lossless decompose / re-encode that reproduces a model's binary exactly (the no-op roundtrip
a native reimport builds on).

SA1 predates SA2's chunk models: a character is a tree of classic 0x34-byte NJS_OBJECTs whose 0x28-byte NJS_MODELs
are "basic" models (points, normals, meshsets of tris / quads / strips with per-corner u16 index arrays and s16
vertuv, 0x14-byte materials). All pointers are absolute SH-4 addresses (1ST_READ.BIN loads at 0x8C010000). Replacing
a model means writing new points / normals / index arrays / vertuv and repointing the model + meshset records;
``data_span`` measures the exact in-file bytes one tree's models occupy (the footprint a donor must fit, in place or
relocated), and ``model_data`` / ``encode_model`` prove the format round-trips losslessly.

    python -m gbox.sa1_writer DISC.gdi --char sonic
"""
from __future__ import annotations

import struct

from .sa1_inventory import KEY, MODEL_SIZE, MESHSET_SIZE, MAT_SIZE, Exe


# ------------------------------------------------------------------ lossless decompose / re-encode

def model_data(ex: Exe, model: int) -> dict:
    """Lossless decomposition of one basic NJS_MODEL into typed structures. Strips keep their raw head u16
    (count | flip<<15), so kind 2/3 meshes round-trip byte-for-byte."""
    pts, nrm, n, msets, mats, nms, nmat = ex.u("IIiIIHH", model)
    cx, cy, cz, r = ex.u("4f", model + 0x18)
    points = [ex.u("3f", pts + 12 * i) for i in range(n)]
    normals = [ex.u("3f", nrm + 12 * i) for i in range(n)] if nrm else None
    materials = [ex.u("IIfII", mats + MAT_SIZE * i) for i in range(nmat)]
    ms = []
    for i in range(nms):
        tm, nmesh, mp, attrs, mnrm, mcol, uvs = ex.u("HHIIIII", msets + MESHSET_SIZE * i)
        kind, mat = tm >> 14, tm & 0x3FFF
        meshes, uvlist, p, corners = [], [], mp, 0
        for _ in range(nmesh):
            if kind in (0, 1):
                k = 3 + kind
                meshes.append(list(ex.u(f"{k}H", p)))
                p += 2 * k
                corners += k
            else:
                head = ex.u("H", p)[0]
                p += 2
                cnt = head & 0x3FFF
                meshes.append((head, list(ex.u(f"{cnt}H", p))))
                p += 2 * cnt
                corners += cnt
        uvlist = [ex.u("hh", uvs + 4 * c) for c in range(corners)] if uvs else []
        ms.append({"kind": kind, "mat": mat, "meshes": meshes, "uvs": uvlist,
                   "attrs": attrs, "nrm": mnrm, "col": mcol})
    return {"points": points, "normals": normals, "materials": materials, "meshsets": ms,
            "center": (cx, cy, cz), "radius": r}


def encode_model(d: dict, base: int = KEY) -> tuple[bytes, int]:
    """Canonical re-serialization -> (bytes, model_address). Layout: points, normals, materials, then per meshset
    [index array, vertuv], then the meshset records, then the model header. Pointers are absolute (base + offset)."""
    out = bytearray()

    def put(b: bytes) -> int:
        nonlocal out
        a = len(out)
        out += b + b"\0" * ((-len(b)) & 3)
        return base + a

    pts = put(b"".join(struct.pack("<3f", *p) for p in d["points"]))
    nrm = put(b"".join(struct.pack("<3f", *n) for n in d["normals"])) if d["normals"] else 0
    mats = put(b"".join(struct.pack("<IIfII", *m) for m in d["materials"])) if d["materials"] else 0
    rows = []
    for ms in d["meshsets"]:
        idx = bytearray()
        for m in ms["meshes"]:
            if ms["kind"] in (0, 1):
                idx += struct.pack(f"<{len(m)}H", *m)
            else:
                head, lst = m
                idx += struct.pack("<H", head) + struct.pack(f"<{len(lst)}H", *lst)
        mp = put(bytes(idx))
        up = put(b"".join(struct.pack("<hh", *uv) for uv in ms["uvs"])) if ms["uvs"] else 0
        rows.append((ms["kind"] << 14 | ms["mat"], len(ms["meshes"]), mp, ms["attrs"], ms["nrm"], ms["col"], up))
    msets = put(b"".join(struct.pack("<HHIIIII", *r) for r in rows))
    hdr = len(out)
    out += struct.pack("<IIiIIHH4f", pts, nrm, len(d["points"]), msets, mats, len(rows), len(d["materials"]),
                       *d["center"], d["radius"])
    return bytes(out), base + hdr


def roundtrip(ex: Exe, model: int) -> tuple[dict, dict, bool]:
    """decompose -> re-encode -> re-parse; returns (original, rebuilt, identical). Identical means the typed
    structures match exactly (the game would load the same model from the re-encoded bytes)."""
    d = model_data(ex, model)
    buf, addr = encode_model(d, ex.key)
    d2 = model_data(Exe(buf, ex.key), addr)
    return d, d2, d == d2


# ------------------------------------------------------------------ writer budget

def model_span(ex: Exe, model: int) -> dict:
    """The in-file byte ranges one NJS_MODEL references: header, points, normals, materials, meshset records and
    each meshset's index array + vertuv."""
    pts, nrm, n, msets, mats, nms, nmat = ex.u("IIiIIHH", model)
    ranges = [("model", model, MODEL_SIZE), ("points", pts, n * 12)]
    if nrm:
        ranges.append(("normals", nrm, n * 12))
    if nmat:
        ranges.append(("materials", mats, nmat * MAT_SIZE))
    ranges.append(("meshsets", msets, nms * MESHSET_SIZE))
    for i in range(nms):
        tm, nmesh, mp, _a, _mn, _mc, uvs = ex.u("HHIIIII", msets + MESHSET_SIZE * i)
        kind = tm >> 14
        p, nbytes, corners = mp, 0, 0
        for _ in range(nmesh):
            if kind in (0, 1):
                k = 3 + kind
                p += 2 * k
                nbytes += 2 * k
                corners += k
            else:
                cnt = ex.u("H", p)[0] & 0x3FFF
                p += 2 + 2 * cnt
                nbytes += 2 + 2 * cnt
                corners += cnt
        ranges.append(("indices", mp, nbytes))
        if uvs:
            ranges.append(("vertuv", uvs, corners * 4))
    lo = min(r[1] for r in ranges)
    hi = max(r[1] + r[2] for r in ranges)
    return {"model": f"0x{model:08X}", "min": lo, "max": hi, "span": hi - lo,
            "referenced_bytes": sum(r[2] for r in ranges),
            "ranges": [{"kind": r[0], "offset": r[1], "size": r[2]} for r in ranges]}


def data_span(ex: Exe, root: int) -> dict:
    """The writer budget for one tree: the byte range and total bytes all its models occupy in the executable."""
    nodes = ex.tree(root)
    if not nodes:
        raise ValueError(f"invalid tree at {root:#x}")
    per = [model_span(ex, n["model"]) for n in nodes if n["model"]]
    if not per:
        raise ValueError(f"tree at {root:#x} has no models")
    lo = min(p["min"] for p in per)
    hi = max(p["max"] for p in per)
    return {"root": f"0x{root:08X}", "nodes": len(nodes), "models": len(per),
            "min": lo, "max": hi, "span": hi - lo,
            "referenced_bytes": sum(p["referenced_bytes"] for p in per), "per_model": per}


# ------------------------------------------------------------------ CLI

def main(argv=None) -> int:
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(description="Sonic Adventure (DC) basic-model writer budget + no-op roundtrip")
    ap.add_argument("gdi")
    ap.add_argument("--char", default="sonic")
    ap.add_argument("--out", help="write the span JSON here")
    a = ap.parse_args(argv)
    from . import sa1_chars as S
    disc = __import__("gbox.gdrom", fromlist=["GDRom"]).GDRom(a.gdi)
    ex, root, src = S.locate(disc, a.char)
    span = data_span(ex, root)
    nodes = ex.tree(root) or []
    # no-op roundtrip of every model (semantic equality)
    ok = all(roundtrip(ex, n["model"])[2] for n in nodes if n["model"])
    import json
    span["source"] = src
    span["roundtrip_all_models_lossless"] = bool(ok)
    text = json.dumps(span, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
