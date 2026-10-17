"""The Matrix: Path of Neo (USA, PS2 SLUS-21273): ``.dcn_11`` character model reader (geometry stage).

Path of Neo keeps every character as a type-3 chunk ``<model>.dcn_11`` inside each level package
``levels\\<level>.lvl_3`` (``gbox.pon_inventory``). Recovered from the owned disc (no community notes cover it):

* file: ``u32 sections end - 0x40, u32, u32, u32 texture data start`` + 0x30 bytes, then tagged sections from 0x40,
  each ``char tag[8], u32 size (incl. this 16-byte head), u32 version, ...``: ``_HEADER_``, ``PATCHOBJ`` (model name,
  part records ``head`` / ``handL`` / ``handR`` / ``legs`` ...), ``SKINMESH``, ``A_DMAPAK``, ``REFS____``
  (relocation list); texture data after the sections. Offsets inside the file are relative to 0x40.
* ``A_DMAPAK`` holds PS2 DMA chains: ``ref`` tags (id 3) whose VIF code is ``UNPACK V4-32`` of the same qword count,
  each pointing at one vertex batch. A batch is a header qword ``{u32 vertices, u32 3, u32 0, u32 GIF NLOOP | EOP}``
  then ``vertices`` x 2 qwords:

  - qword A: ``s32 x, y, z`` (16.16 fixed point, +Y up, model units) and ``f32 matrix address * 4096``
    (VU memory address of the vertex's joint matrix; -4096 = none / previous);
  - qword B: ``f32 u, f32 v, f32 weight 0, f32 weight 1`` whose low 16 bits carry VU addresses: u -> the output
    slot address, v -> a second output slot (0 = none), the weights -> joint matrix addresses.

  The batch's output is one GS triangle strip of ``NLOOP`` vertices, 3 qwords per vertex from VU address 12: each
  source vertex is scattered into one or two strip slots. A strip triangle that touches an unwritten slot or repeats
  a vertex is not drawn (strip restarts).

Verified on the owned disc: every batch lies inside the file, its qword count is ``1 + 2 * vertices``, its slots are
inside ``NLOOP``; whole meshes look like the characters (Agent Smith LP, Neo; A-pose, head / hands / coat present).
Not decoded yet: ``PATCHOBJ`` / ``SKINMESH`` beyond the part names, the skeleton, skin weights to joint indices and
the textures, so this stage exports static geometry (OBJ) and does not register a collection reader or a writer.

    python -m gbox.pon_models <PoN.chd | PoN.iso> <out_dir> [level] [model ...]
"""
from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path

import numpy as np

BASE = 0x40                     # file offsets in sections / DMA tags are relative to the end of the 0x40 head
SLOT0, SLOT_QW = 12, 3          # VU output buffer: first strip vertex address, qwords per output vertex
UNPACK_V4_32 = 0x6c
TAGS = ("_HEADER_", "PATCHOBJ", "SKINMESH", "A_DMAPAK", "REFS____")


class FormatError(ValueError):
    pass


def sections(d: bytes) -> dict[str, tuple[int, int]]:
    """Tagged sections from 0x40: tag -> (file offset, size). Bounds-checked; A_DMAPAK is required."""
    if len(d) < BASE + 16:
        raise FormatError("shorter than the .dcn_11 head")
    end = struct.unpack_from("<I", d)[0] + BASE
    if not BASE < end <= len(d):
        raise FormatError(f"sections end 0x{end:x} outside the file (0x{len(d):x})")
    out, o = {}, BASE
    while o < end:
        if o + 16 > end:
            raise FormatError(f"section head at 0x{o:x} runs past the sections end")
        tag = d[o:o + 8].decode("latin-1")
        size = struct.unpack_from("<I", d, o + 8)[0]
        if not re.fullmatch(r"[A-Z_]{8}", tag) or size < 16 or o + size > end:
            raise FormatError(f"bad section {tag!r} at 0x{o:x} (size 0x{size:x})")
        out[tag] = (o, size)
        o += size
    if "A_DMAPAK" not in out:
        raise FormatError("no A_DMAPAK section")
    return out


def model_name(d: bytes, secs: dict | None = None) -> str:
    secs = secs or sections(d)
    o, _ = secs.get("PATCHOBJ", (None, 0))
    if o is None:
        return ""
    return d[o + 0x14:o + 0x24].split(b"\0")[0].split(b".")[0].decode("latin-1")   # char[16]: ".dcn_11" may be cut


def parts(d: bytes, secs: dict | None = None) -> list[str]:
    """Part names of the PATCHOBJ records (``head``, ``handL``, ``handR``, ``legs`` ...): 0x40-byte records listed by
    ``u32 count`` + offsets at PATCHOBJ+0x58 / +0x60."""
    secs = secs or sections(d)
    o, size = secs.get("PATCHOBJ", (None, 0))
    if o is None or size < 0x64:
        return []
    count = struct.unpack_from("<I", d, o + 0x58)[0]
    if not 0 < count < 64 or o + 0x60 + 4 * count > o + size:
        return []
    out = []
    for i in range(count):
        p = BASE + struct.unpack_from("<I", d, o + 0x60 + 4 * i)[0]
        if not o < p < o + size:
            return []
        out.append(d[p:p + 8].split(b"\0")[0].decode("latin-1"))
    return out


def batches(d: bytes, secs: dict | None = None) -> list[dict]:
    """Every vertex batch the A_DMAPAK chains reference (``ref`` + ``UNPACK V4-32``), once each, in chain order."""
    secs = secs or sections(d)
    o, size = secs["A_DMAPAK"]
    out, seen = [], set()
    for p in range(o + 16, o + size - 15, 16):
        tag, addr, _, vif = struct.unpack_from("<4I", d, p)
        qwc = tag & 0xffff
        if (tag >> 28) & 7 != 3 or (vif >> 24) & 0x7f != UNPACK_V4_32 or (vif >> 16) & 0xff != qwc & 0xff or qwc < 3:
            continue
        a = BASE + addr
        if a in seen:
            continue
        if a + 16 * qwc > len(d):
            raise FormatError(f"batch at 0x{a:x} (+{qwc} qw) outside the file")
        n, three, _, gif = struct.unpack_from("<4I", d, a)
        if three != 3 or qwc != 1 + 2 * n:
            continue                                   # another unpack (matrices, constants): not a vertex batch
        seen.add(a)
        out.append({"offset": a, "qwc": qwc, "vertices": n, "nloop": gif & 0x7fff, "eop": bool(gif & 0x8000)})
    if not out:
        raise FormatError("A_DMAPAK references no vertex batch")
    return out


def decode_batch(d: bytes, b: dict) -> dict:
    n = b["vertices"]
    raw = np.frombuffer(d, dtype="<u4", count=8 * n, offset=b["offset"] + 16).reshape(n, 8)
    f = raw.view("<f4")
    pos = raw[:, :3].view("<i4").astype(np.float64) / 65536.0
    uv = (raw[:, 4:6] & 0xffff0000).view("<f4").astype(np.float64)
    slots = [-1] * b["nloop"]
    for i in range(n):
        for a in (int(raw[i, 4] & 0xffff), int(raw[i, 5] & 0xffff)):
            if not a:
                continue
            s, r = divmod(a - SLOT0, SLOT_QW)
            if r or not 0 <= s < b["nloop"]:
                raise FormatError(f"batch 0x{b['offset']:x} vertex {i}: output address {a} outside the strip")
            slots[s] = i
    tris = []
    for s in range(b["nloop"] - 2):
        t = slots[s:s + 3]
        if -1 in t or len(set(t)) < 3:
            continue
        tris.append((t[1], t[0], t[2]) if s & 1 else tuple(t))
    return {"pos": pos, "uv": uv, "matrix": np.rint(f[:, 3] / 4096.0).astype(int), "tris": tris,
            "unwritten": slots.count(-1)}


def mesh(d: bytes) -> dict:
    """The whole model: positions (n, 3, model units, +Y up), UVs (n, 2), triangles (m, 3), per-batch counts."""
    secs = sections(d)
    P, UV, T, base, info = [], [], [], 0, []
    for b in batches(d, secs):
        m = decode_batch(d, b)
        P.append(m["pos"])
        UV.append(m["uv"])
        T.extend((a + base, c + base, e + base) for a, c, e in m["tris"])
        base += b["vertices"]
        info.append({"vertices": b["vertices"], "nloop": b["nloop"], "triangles": len(m["tris"]),
                     "unwritten": m["unwritten"]})
    pos = np.concatenate(P)
    return {"name": model_name(d, secs), "parts": parts(d, secs), "positions": pos, "uvs": np.concatenate(UV),
            "triangles": np.array(T, dtype=np.int64).reshape(-1, 3), "batches": info,
            "height": float(pos[:, 1].max() - pos[:, 1].min())}


def summary(d: bytes) -> dict:
    m = mesh(d)
    lo, hi = m["positions"].min(0), m["positions"].max(0)
    return {"name": m["name"], "parts": m["parts"], "batches": len(m["batches"]), "vertices": len(m["positions"]),
            "triangles": len(m["triangles"]), "height": round(m["height"], 1),
            "bbox": [[round(float(x), 1) for x in lo], [round(float(x), 1) for x in hi]]}


def to_obj(d: bytes, path) -> dict:
    m = mesh(d)
    lines = [f"# {m['name']} (Path of Neo .dcn_11, gbox.pon_models), model units"]
    lines += [f"v {x:.4f} {y:.4f} {z:.4f}" for x, y, z in m["positions"]]
    lines += [f"vt {u:.5f} {1.0 - v:.5f}" for u, v in m["uvs"]]
    lines += [f"f {a + 1}/{a + 1} {b + 1}/{b + 1} {c + 1}/{c + 1}" for a, b, c in m["triangles"]]
    Path(path).write_text("\n".join(lines) + "\n")
    return summary(d)


def level_model_files(dfu, level: str) -> dict[str, bytes]:
    """model name -> .dcn_11 bytes for every type-3 character chunk of one level package."""
    from . import pon_inventory as inv
    pkg = dfu.read(inv.LEVEL_FMT.format(level))
    p = inv.parse_package(pkg)
    return {c["model"]: pkg[c["offset"]:c["offset"] + c["size"]] for c in p["chunks"] if c.get("model")}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[-1].strip())
        return 2
    from .etm_inventory import open_disc
    from .shiny_dfu import Dfu
    from . import pon_inventory as inv
    disc, out = open_disc(argv[0]), Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    dfu = Dfu(disc, variant="pon")
    lv = [argv[2]] if len(argv) > 2 else [r["level"] for r in inv.levels(dfu)]
    want = set(argv[3:])
    report, done = {}, set()
    for level in lv:
        for name, data in level_model_files(dfu, level).items():
            if name in done or (want and name not in want):
                continue
            done.add(name)
            try:
                report[name] = to_obj(data, out / f"{name}.obj") | {"level": level}
            except FormatError as e:
                report[name] = {"level": level, "error": str(e)}
    (out / "pon_models.json").write_text(json.dumps(report, indent=1))
    bad = [k for k, v in report.items() if "error" in v]
    print(f"{len(report)} models, {len(bad)} failed{': ' + ', '.join(bad) if bad else ''} -> {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
