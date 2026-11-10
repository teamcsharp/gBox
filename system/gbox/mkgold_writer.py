"""Mortal Kombat Gold (Dreamcast) GEO writer: re-encode and replace mesh records of a 0.1v GEO, then fit it back on the disc.

Layout facts (see mkgold_inventory / mkgold_geo): a GEO is 0x20 header, `count` 32-byte records {u16 flags, u16 n, u32 rel,
24 bytes}, then the data blocks; record data sits at (record address + 4 + rel) unless flags & 0x80 (inline sprite).
`rebuild_geo` keeps every block it is not asked to replace byte for byte, re-lays the blocks in their original order and
recomputes `rel` and the header size, so with no replacements the output equals the input (the no-op roundtrip).

    python -m gbox.mkgold_writer DISC.gdi --roundtrip                          # all GEOs, byte-identical or fail
    python -m gbox.mkgold_writer DISC.gdi --donor SZ_GEO --target KL_GEO --out DIR   # donor character in KL's slot
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

from .mkgold_inventory import HEADER, MAGIC, RECORD, SPRITE, container, geo_records, img_pages

STRIP = VERTEX = 32


def encode_strip(parity: int, normals, positions, st) -> bytes:
    """One strip: 32-byte header {0, parity, nverts, 24 zero} + 32-byte vertices {normal, position, s, t}."""
    out = [struct.pack("<IHH24x", 0, parity, len(positions))]
    for n, p, t in zip(normals, positions, st):
        out.append(struct.pack("<8f", *n, *p, *t))
    return b"".join(out)


def encode_part(strips: list[dict]) -> bytes:
    """Inverse of mkgold_geo.part_strips."""
    return b"".join(encode_strip(s["parity"], s["normals"], s["positions"], s["st"]) for s in strips)


def blocks(geo: bytes) -> tuple[bytes, list[tuple[int, int]]]:
    """(gap between the record table and the first block, [(offset, length)] of the distinct data blocks in order)."""
    recs = geo_records(geo)
    offs = sorted({r["offset"] for r in recs if "offset" in r})
    table_end = HEADER + len(recs) * RECORD
    size = len(geo)
    spans = [(o, (offs[i + 1] if i + 1 < len(offs) else size) - o) for i, o in enumerate(offs)]
    return geo[table_end:offs[0]] if offs else geo[table_end:], spans


def rebuild_geo(geo: bytes, replace: dict[int, bytes] | None = None, n_strips: dict[int, int] | None = None) -> bytes:
    """Re-lay `geo`, swapping the data block of record i for replace[i] (its strip count becomes n_strips[i]).
    Records that shared one block keep sharing it; replacing one of them is refused."""
    replace, n_strips = replace or {}, n_strips or {}
    recs = geo_records(geo)
    size, count = container(geo)
    if not recs:
        return geo
    gap, spans = blocks(geo)
    owners: dict[int, list[int]] = {}
    for r in recs:
        if "offset" in r:
            owners.setdefault(r["offset"], []).append(r["index"])
    for i in replace:
        if i >= len(recs) or "offset" not in recs[i]:
            raise ValueError(f"record {i} has no data block to replace")
        if len(owners[recs[i]["offset"]]) > 1:
            raise ValueError(f"record {i} shares its block with {owners[recs[i]['offset']]}")
    table_end = HEADER + count * RECORD
    new_off, body = {}, bytearray(gap)
    for o, ln in spans:
        new_off[o] = table_end + len(body)
        i = owners[o][0]
        body += replace[i] if i in replace else geo[o:o + ln]
    out = bytearray(geo[:table_end])
    for r in recs:
        at = HEADER + r["index"] * RECORD
        if "offset" in r:
            struct.pack_into("<I", out, at + 4, new_off[r["offset"]] - (at + 4))
        if r["index"] in n_strips:
            struct.pack_into("<H", out, at + 2, n_strips[r["index"]])
    out += body
    struct.pack_into("<I", out, 4, len(out))
    return bytes(out)


def roundtrip(read, names) -> dict:
    """No-op roundtrip of every GEO: {files, identical, differing: [...]} (mesh records are also re-encoded)."""
    from .mkgold_geo import part_strips
    out = {"files": 0, "identical": 0, "records_reencoded": 0, "differing": []}
    for nm in names:
        geo = read(nm)
        out["files"] += 1
        ok = rebuild_geo(geo) == geo
        recs = geo_records(geo)
        for r in recs:
            if r["flags"] & SPRITE or "offset" not in r:
                continue
            try:
                strips = part_strips(geo, r)
            except ValueError:
                continue                          # stage/shared GEOs with another strip header are left as bytes
            enc = encode_part(strips)
            ok &= geo[r["offset"]:r["offset"] + len(enc)] == enc
            out["records_reencoded"] += 1
        if ok:
            out["identical"] += 1
        else:
            out["differing"].append(nm)
    return out


def swap_check(target_geo: bytes, target_img: bytes, donor_geo: bytes, donor_img: bytes) -> list[str]:
    """Reasons a donor GEO/IMG pair cannot stand in for the target's files (empty list: compatible). Skeleton node
    tables live in 1ST_READ and address parts by record index, so the donor must supply every part the target's
    skeleton uses, and its texture page must have the page size the target's UVs were authored for."""
    problems = []
    t, d = geo_records(target_geo), geo_records(donor_geo)
    if len(d) < len(t):
        problems.append(f"donor has {len(d)} records, target skeleton may use {len(t)}")
    tm = {r["index"] for r in t if "offset" in r}
    dm = {r["index"] for r in d if "offset" in r}
    if tm - dm:
        problems.append(f"donor lacks mesh records {sorted(tm - dm)}")
    tp = [(p["width"], p["height"]) for p in img_pages(target_img)]
    dp = [(p["width"], p["height"]) for p in img_pages(donor_img)]
    if tp[:1] != dp[:1]:
        problems.append(f"page size {dp[:1]} != {tp[:1]}")
    return problems


def patch_disc(src_gdi, out_dir, name: str, files: dict[str, bytes]) -> Path:
    """Write `files` in place on a copy of the GDI: each must fit its old sectors plus the free ones before the next
    file. MK Gold's directory sectors are in the first high-density track (LBA 45000) while the files are in the last
    one, which gdrom.patch_gdi cannot do, so both tracks are copied and patched (extent kept, size updated, EDC/ECC
    recomputed); every other track is hard-linked. The source disc is never touched."""
    import os
    import shutil
    from .gdrom import GDRom, mode1_sector
    src_gdi, out_dir = Path(src_gdi), Path(out_dir)
    disc = GDRom(src_gdi)
    order = sorted(l for l, _s in disc.files.values())
    tracks = sorted(disc.tracks)

    def track_of(lba):
        return max((t for t in tracks if t[0] <= lba), key=lambda t: t[0])
    plan = []
    for key, data in files.items():
        if key not in disc.files:
            raise ValueError(f"{key} is not on this disc")
        lba, size = disc.files[key]
        nxt = next((l for l in order if l > lba), None)
        room = ((nxt - lba) if nxt else (size + 2047) // 2048) * 2048
        if len(data) > room:
            raise ValueError(f"{key}: {len(data)} bytes exceed the {room} in place at LBA {lba}")
        plan.append((key, lba, data))
    name = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    out_dir.mkdir(parents=True, exist_ok=True)
    touched = {track_of(l)[2] for _k, l, _d in plan} | {track_of(disc.records[k][0])[2] for k, _l, _d in plan}
    lines = [ln for ln in src_gdi.read_text().splitlines() if ln.strip()]
    new_lines, dst_of = [lines[0]], {}
    for ln in lines[1:]:
        parts = ln.split()
        src = src_gdi.parent / parts[4].strip('"')
        dst = out_dir / f"{name}.track{int(parts[0]):02d}{src.suffix}"
        if dst.exists():
            dst.unlink()
        if src in touched:
            shutil.copyfile(src, dst)
        else:
            try:
                os.link(src, dst)
            except OSError:
                shutil.copyfile(src, dst)
        dst_of[src] = dst
        parts[4] = dst.name
        new_lines.append(" ".join(parts))

    def put(lba, data):
        start, ssz, path = track_of(lba)
        with open(dst_of[path], "r+b") as f:
            f.seek((lba - start) * ssz)
            if ssz == 2352:
                raw = f.read(2352)
                f.seek((lba - start) * ssz)
                f.write(mode1_sector(raw, data))
            else:
                f.write(data.ljust(2048, b"\0"))

    def get(lba):
        start, ssz, path = track_of(lba)
        with open(dst_of[path], "rb") as f:
            f.seek((lba - start) * ssz + (16 if ssz == 2352 else 0))
            return bytearray(f.read(2048))
    for key, lba, data in plan:
        for i in range(0, max(len(data), 1), 2048):
            put(lba + i // 2048, data[i:i + 2048])
        dlba, doff = disc.records[key]
        sec = get(dlba)
        sec[doff + 10:doff + 14] = struct.pack("<I", len(data))
        sec[doff + 14:doff + 18] = struct.pack(">I", len(data))
        put(dlba, bytes(sec))
    gdi = out_dir / f"{name}.gdi"
    gdi.write_text("\n".join(new_lines) + "\n")
    return gdi


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main(argv=None):
    import argparse
    from .gdrom import GDRom
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("--roundtrip", action="store_true")
    ap.add_argument("--target", default="KL_GEO")
    ap.add_argument("--donor")
    ap.add_argument("--out")
    ap.add_argument("--report")
    a = ap.parse_args(argv)
    g = GDRom(a.gdi)
    rep: dict = {}
    if a.roundtrip:
        rep["roundtrip"] = roundtrip(g.read, sorted(n for n in g.files if n.endswith(".GEO")))
    if a.donor:
        tg, dg = g.read(f"{a.target}.GEO"), g.read(f"{a.donor}.GEO")
        ti, di = g.read(f"{a.target}.IMG"), g.read(f"{a.donor}.IMG")
        rep["swap"] = {"target": a.target, "donor": a.donor, "problems": swap_check(tg, ti, dg, di),
                       "sizes": {"target_geo": len(tg), "donor_geo": len(dg), "target_img": len(ti), "donor_img": len(di)}}
        if a.out and not rep["swap"]["problems"]:
            files = {f"{a.target}.GEO": dg, f"{a.target}.IMG": di}
            gdi = patch_disc(a.gdi, a.out, f"mkgold_{a.donor}_in_{a.target}".lower(), files)
            rep["swap"]["gdi"] = str(gdi)
            m = GDRom(gdi)
            rep["swap"]["readback"] = {k: _sha(m.read(k)) == _sha(v) for k, v in files.items()}
    text = json.dumps(rep, indent=1)
    if a.report:
        Path(a.report).write_text(text)
    print(text)


if __name__ == "__main__":
    sys.exit(main())
