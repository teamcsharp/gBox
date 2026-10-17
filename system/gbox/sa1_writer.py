"""Sonic Adventure basic-model writer primitives.

Canonical encode/decode proves semantic equality for models without optional
mesh attributes, mesh normals or vertex colors. It is NOT a byte-identical
roundtrip and is not a complete routed donor writer. patch_points provides a
size-preserving geometry edit with a genuine byte-identical no-op.

Referenced spans describe occupied data, not free space: other trees may share
it and unrelated executable data may occupy every gap. Never use span as an
allocation budget. Preserve originals and prove alias ownership before reimport.
"""
from __future__ import annotations

import struct
import math

from .sa1_inventory import KEY, MODEL_SIZE, MESHSET_SIZE, MAT_SIZE, Exe


# ------------------------------------------------------------------ canonical decompose / re-encode

def _read(ex: Exe, fmt: str, address: int):
    size = struct.calcsize('<' + fmt)
    if not ex.ok(address, size, align=1):
        raise ValueError('Model reference is outside the owned source')
    return ex.u(fmt, address)


def _header(ex: Exe, model: int):
    header = _read(ex, 'IIiIIHH4f', model)
    pts, nrm, n, msets, mats, nms, nmat = header[:7]
    if n <= 0:
        raise ValueError('Nonpositive point count')
    for ptr, count, size in ((pts, n, 12), (nrm, n if nrm else 0, 12),
                             (msets, nms, MESHSET_SIZE), (mats, nmat, MAT_SIZE)):
        if count and not ex.ok(ptr, count * size):
            raise ValueError('Model array exceeds the owned source')
    return header[:7]


def patch_points(ex: Exe, model: int, points, *, normals=None) -> bytes:
    """Change existing geometry arrays only; no allocation, relocation or disc write.

    Caller must establish that these arrays belong to the intended slot (they
    may be shared by other models). All other bytes, including optional data,
    remain exactly unchanged. The vertex count and skeleton are preserved.
    """
    pts, nrm, n, *_ = _header(ex, model)
    cx, cy, cz, radius = _read(ex, '4f', model + 0x18)
    if not all(math.isfinite(v) for v in (cx, cy, cz, radius)) or radius < 0:
        raise ValueError('Invalid model bounds')
    if len(points) != n:
        raise ValueError('In-place edit must preserve the point count')
    if any(len(v) == 3 and tuple(v) != _read(ex, '3f', pts + j * 12) and sum((v[i] - (cx, cy, cz)[i]) ** 2 for i in range(3)) > radius ** 2 + 1e-5 for j, v in enumerate(points)):
        raise ValueError('Changed geometry exceeds the existing model bounds')
    edits = [(pts, points)]
    if normals is not None:
        if not nrm:
            raise ValueError('Model has no normal array')
        edits.append((nrm, normals))
    spans = []
    for ptr, vectors in edits:
        if len(vectors) != n:
            raise ValueError('In-place edit must preserve the point count')
        if any(len(v) != 3 or not all(math.isfinite(x) for x in v) for v in vectors):
            raise ValueError('Geometry must contain finite 3-component vectors')
        begin, end = ptr - ex.key, ptr - ex.key + n * 12
        if begin < model - ex.key + MODEL_SIZE and end > model - ex.key:
            raise ValueError('Geometry overlaps the model header')
        if any(begin < other_end and end > other_begin for other_begin, other_end, _ in spans):
            raise ValueError('Geometry arrays overlap')
        spans.append((begin, end, b''.join(struct.pack('<3f', *v) for v in vectors)))
    out = bytearray(ex.d)
    for begin, end, data in spans:
        out[begin:end] = data
    return bytes(out)


def model_data(ex: Exe, model: int) -> dict:
    """Semantic decomposition of one basic NJS_MODEL into typed structures. Strips keep their raw head u16
    (count | flip<<15), so kind 2/3 meshes round-trip byte-for-byte."""
    pts, nrm, n, msets, mats, nms, nmat = _header(ex, model)
    cx, cy, cz, r = _read(ex, "4f", model + 0x18)
    points = [_read(ex, "3f", pts + 12 * i) for i in range(n)]
    normals = [_read(ex, "3f", nrm + 12 * i) for i in range(n)] if nrm else None
    materials = [_read(ex, "IIfII", mats + MAT_SIZE * i) for i in range(nmat)]
    ms = []
    for i in range(nms):
        tm, nmesh, mp, attrs, mnrm, mcol, uvs = _read(ex, "HHIIIII", msets + MESHSET_SIZE * i)
        if attrs or mnrm or mcol:
            # NJS_MESHSET pointers: X-Hax/sadx-mod-loader include/ninja.h.
            # Copying pointer values would leave dangling references after relocation.
            raise ValueError('Canonical encoding does not support optional mesh arrays')
        kind, mat = tm >> 14, tm & 0x3FFF
        meshes, uvlist, p, corners = [], [], mp, 0
        for _ in range(nmesh):
            if kind in (0, 1):
                k = 3 + kind
                meshes.append(list(_read(ex, f"{k}H", p)))
                p += 2 * k
                corners += k
            else:
                head = _read(ex, "H", p)[0]
                p += 2
                cnt = head & 0x3FFF
                meshes.append((head, list(_read(ex, f"{cnt}H", p))))
                p += 2 * cnt
                corners += cnt
        indices = [v for mesh in meshes for v in (mesh if kind in (0, 1) else mesh[1])]
        if any(v >= n for v in indices):
            raise ValueError('Mesh vertex index exceeds the point array')
        uvlist = [_read(ex, "hh", uvs + 4 * c) for c in range(corners)] if uvs else []
        ms.append({"kind": kind, "mat": mat, "meshes": meshes, "uvs": uvlist,
                   "attrs": attrs, "nrm": mnrm, "col": mcol})
    return {"points": points, "normals": normals, "materials": materials, "meshsets": ms,
            "center": (cx, cy, cz), "radius": r}


def encode_model(d: dict, base: int = KEY) -> tuple[bytes, int]:
    """Canonical re-serialization -> (bytes, model_address). Layout: points, normals, materials, then per meshset
    [index array, vertuv], then the meshset records, then the model header. Pointers are absolute (base + offset)."""
    if base < 0 or base > 0xffffffff or base % 4:
        raise ValueError('Invalid aligned 32-bit model base')
    if any(ms.get(key) for ms in d['meshsets'] for key in ('attrs', 'nrm', 'col')):
        raise ValueError('Canonical encoding does not support optional mesh arrays')
    if d['normals'] is not None and len(d['normals']) != len(d['points']):
        raise ValueError('Normal count differs from point count')
    for ms in d['meshsets']:
        if ms['kind'] not in (0, 1, 2, 3) or not 0 <= ms['mat'] <= 0x3fff:
            raise ValueError('Invalid mesh kind or material')
        corners = 0
        for mesh in ms['meshes']:
            if ms['kind'] in (0, 1):
                values = mesh
                if len(values) != 3 + ms['kind']:
                    raise ValueError('Invalid fixed-size mesh')
            else:
                head, values = mesh
                if head & 0x3fff != len(values):
                    raise ValueError('Strip count differs from index count')
            if any(v < 0 or v >= len(d['points']) for v in values):
                raise ValueError('Mesh vertex index exceeds the point array')
            corners += len(values)
        if ms['uvs'] and len(ms['uvs']) != corners:
            raise ValueError('UV count differs from corner count')
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
    if base + len(out) > 0x100000000:
        raise ValueError('Encoded model exceeds the 32-bit address space')
    return bytes(out), base + hdr


def roundtrip(ex: Exe, model: int) -> tuple[dict, dict, bool]:
    """decompose -> re-encode -> re-parse; returns (original, rebuilt, identical). Identical means the typed
    structures match exactly (the game would load the same model from the re-encoded bytes)."""
    d = model_data(ex, model)
    buf, addr = encode_model(d, ex.key)
    d2 = model_data(Exe(buf, ex.key), addr)
    return d, d2, d == d2


# ------------------------------------------------------------------ occupied ranges

def model_span(ex: Exe, model: int) -> dict:
    """The in-file byte ranges one NJS_MODEL references: header, points, normals, materials, meshset records and
    each meshset's index array + vertuv."""
    pts, nrm, n, msets, mats, nms, nmat = _header(ex, model)
    model_data(ex, model)  # reject unsupported arrays and invalid indices before reporting occupied ranges
    ranges = [("model", model, MODEL_SIZE), ("points", pts, n * 12)]
    if nrm:
        ranges.append(("normals", nrm, n * 12))
    if nmat:
        ranges.append(("materials", mats, nmat * MAT_SIZE))
    ranges.append(("meshsets", msets, nms * MESHSET_SIZE))
    for i in range(nms):
        tm, nmesh, mp, _a, _mn, _mc, uvs = _read(ex, "HHIIIII", msets + MESHSET_SIZE * i)
        kind = tm >> 14
        p, nbytes, corners = mp, 0, 0
        for _ in range(nmesh):
            if kind in (0, 1):
                k = 3 + kind
                p += 2 * k
                nbytes += 2 * k
                corners += k
            else:
                cnt = _read(ex, "H", p)[0] & 0x3FFF
                p += 2 + 2 * cnt
                nbytes += 2 + 2 * cnt
                corners += cnt
        ranges.append(("indices", mp, nbytes))
        if uvs:
            ranges.append(("vertuv", uvs, corners * 4))
    ranges = [r for r in ranges if r[2] > 0]
    lo = min(r[1] for r in ranges)
    hi = max(r[1] + r[2] for r in ranges)
    return {"model": f"0x{model:08X}", "min": lo, "max": hi, "span": hi - lo, "allocation_safe": False,
            "referenced_bytes": sum(r[2] for r in ranges),
            "ranges": [{"kind": r[0], "offset": r[1], "size": r[2]} for r in ranges]}


def data_span(ex: Exe, root: int) -> dict:
    """Occupied model ranges; never a safe allocation or overwrite budget."""
    nodes = ex.tree(root)
    if not nodes:
        raise ValueError(f"invalid tree at {root:#x}")
    per = [model_span(ex, n["model"]) for n in nodes if n["model"]]
    if not per:
        raise ValueError(f"tree at {root:#x} has no models")
    lo = min(p["min"] for p in per)
    hi = max(p["max"] for p in per)
    return {"root": f"0x{root:08X}", "nodes": len(nodes), "models": len(per),
            "min": lo, "max": hi, "span": hi - lo, "allocation_safe": False,
            "referenced_bytes": sum(p["referenced_bytes"] for p in per), "per_model": per}


# ------------------------------------------------------------------ CLI

def main(argv=None) -> int:
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(description="Sonic Adventure (DC) occupied ranges, canonical comparison and geometry no-op")
    ap.add_argument("gdi")
    ap.add_argument("--char", default="sonic")
    ap.add_argument("--out", help="write the span JSON here")
    a = ap.parse_args(argv)
    from . import sa1_chars as S
    disc = __import__("gbox.gdrom", fromlist=["GDRom"]).GDRom(a.gdi)
    ex, root, src = S.locate(disc, a.char)
    span = data_span(ex, root)
    nodes = ex.tree(root) or []
    # Canonical comparison and genuine no-op are different checks.
    ok = all(roundtrip(ex, n["model"])[2] for n in nodes if n["model"])
    noop = all(patch_points(ex, n['model'], model_data(ex, n['model'])['points']) == ex.d
               for n in nodes if n['model'])
    import json, hashlib
    span['source_sha256'] = hashlib.sha256(ex.d).hexdigest()
    span['noop_all_models_byte_identical'] = noop
    span["source"] = src
    span["roundtrip_all_models_semantically_equal"] = bool(ok)
    text = json.dumps(span, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    print(text)
    return 0 if ok and noop else 1


if __name__ == "__main__":
    raise SystemExit(main())
