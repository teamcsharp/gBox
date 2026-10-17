"""Exact-build inventory for NFL Blitz 2001 (USA), Dreamcast (game b0d6166c71562f78).

Reads the unpacked GD-ROM (``disc.gdi`` made by ``chdman extractcd`` from the owned HyperSpin
CHD) read-only and writes a JSON manifest: source/track hashes, IP.BIN identity, the 1ST_READ.BIN
hash and the character asset names it references, and the parsed layout of the player body
models (``*.SBM``), the head/stadium model banks (``*.MDL``) and the animation bank
(``GENSEQ.ANI``), each with its LBA room (the bound for a same-size native writer).

    python -m gbox.blitz2001_inventory disc.gdi --chd OWNED.chd --out manifest.json

Build: T-9712N V1.001 (2000-08-14), area U, Midway. The fingerprint reported "engine unknown":
this is Midway's own Blitz engine (arcade lineage), not Ninja/NaomiLib, so no NJCM/PVM model
containers exist. Player models are single skinned meshes::

    SBM  u32 version, u32 n_verts, u32 n_strip_records, u32 n_parts, u32 vert_off, u32 strip_off,
         4*u32 0, u32 bone_off, 5*u32 0                     (0x40-byte header)
         vert_off:  n_verts * float4 (x, y, z, 1.0)
         strip_off: n_strip_records * 16 B (PVR-style records: u16 0xE000/0xF000 = vertex /
                    end-of-strip, u16 vertex index * 16, u32 colour, float u, float v; group
                    header records interleave)
         bone_off:  15 * {u32 bone (bit31 = last), u32 count, u32 list_off, u32 0}, then a u16
                    vertex list (n_verts entries) that list_off indexes, relative to bone_off

``PLAYERS/PLAYERM/PLAYERB.SBM`` are the small/medium/big body types (same topology: 564 verts,
15 bones); ``HELMET.SBM`` (bone table) and ``FOOTBALL.SBM`` (version 0, rigid) share the layout.
``GENSEQ.ANI`` holds the shared 15-limb animation sequences: a table of 16-byte entries
``{u32 flag, u32 n_frames, u32 n_limbs, u32 offset}`` (entry 0's flag word is the file tag);
a sequence is either packed (180-byte header + 72 B/frame) or raw (252 B/frame = 15 limbs *
16 B + 12 B root); the flag word does NOT select between them (size does).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

GAME_ID = "b0d6166c71562f78"
TITLE = "NFL Blitz 2001 (USA)"
PRODUCT = "T9712N"
VERSION = "V1.001"
CATALOG = {"library": "hyperspin", "rel_path": "collections/Sega Dreamcast/roms/NFL Blitz 2001 (USA).chd"}
# owned HyperSpin CHD v4 (zlib, 5 tracks); every stage reuses this source identity
SOURCE_SHA256 = "0a9c4312a9035aafd5de44fbfb92bad5ef8b96ffbd6bd43122ad72fb58e860eb"
SECTOR = 2048
BONES = 15
BODY_TYPES = {"PLAYERS.SBM": "small", "PLAYERM.SBM": "medium", "PLAYERB.SBM": "big"}
ANI_TAG = 0x385515A5
ANI_PACKED_HEAD, ANI_PACKED_FRAME, ANI_RAW_FRAME = 180, 72, 252


def sha256_file(path: str | Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def parse_ip(sector: bytes) -> dict:
    """Dreamcast IP.BIN meta block (first 0x100 bytes of the high-density data track)."""
    if sector[:16] != b"SEGA SEGAKATANA ":
        raise ValueError("No Dreamcast IP.BIN at the start of the high-density area")
    f = lambda a, b: sector[a:b].decode("latin-1").strip()  # noqa: E731
    return {"hardware": f(0x00, 0x10), "maker": f(0x10, 0x20), "device": f(0x20, 0x30),
            "area": f(0x30, 0x38), "peripherals": f(0x38, 0x40), "product": f(0x40, 0x4A),
            "version": f(0x4A, 0x50), "date": f(0x50, 0x60), "boot": f(0x60, 0x70),
            "company": f(0x70, 0x80), "title": f(0x80, 0x100)}


def file_room(files: dict[str, tuple[int, int]]) -> dict[str, int]:
    """Bytes each file may occupy without moving another file: up to the next file's LBA."""
    order = sorted(files.items(), key=lambda kv: (kv[1][0], kv[0]))
    room = {}
    for i, (name, (lba, size)) in enumerate(order):
        own = (size + SECTOR - 1) // SECTOR * SECTOR
        nxt = next((l for _, (l, _s) in order[i + 1:] if l > lba), None)
        room[name] = max(own, (nxt - lba) * SECTOR) if nxt is not None else own
    return room


def sbm(data: bytes) -> dict:
    """Parse and validate a Blitz ``.SBM`` skinned body model; raises ValueError on inconsistency."""
    if len(data) < 0x40:
        raise ValueError("SBM too short")
    h = struct.unpack_from("<16I", data, 0)
    ver, nv, ns, nparts, voff, soff, boff = h[0], h[1], h[2], h[3], h[4], h[5], h[10]
    if ver not in (0, 1) or voff != 0x40 or soff != voff + 16 * nv:
        raise ValueError(f"SBM header {h[:6]}")
    send = soff + 16 * ns
    if send > len(data):
        raise ValueError("SBM strip records past EOF")
    ws = [struct.unpack_from("<f", data, voff + 16 * i + 12)[0] for i in range(nv)]
    if any(w != 1.0 for w in ws):
        raise ValueError("SBM vertex w != 1.0")
    recs = [struct.unpack_from("<HHI", data, soff + 16 * i) for i in range(ns)]
    verts = [r for r in recs if r[0] in (0xE000, 0xF000)]
    if any(r[1] % 16 or r[1] // 16 >= nv for r in verts):
        raise ValueError("SBM strip vertex index out of range")
    out = {"version": ver, "verts": nv, "strip_records": ns, "parts": nparts,
           "vert_off": voff, "strip_off": soff, "strip_vertices": len(verts),
           "strips": sum(1 for r in verts if r[0] == 0xF000), "bones": None}
    if not boff:
        if send != len(data):
            raise ValueError("rigid SBM has trailing bytes")
        return out
    nb, rem = divmod(len(data) - boff - 2 * nv, 16)
    if boff != send or rem or not 0 < nb <= BONES:
        raise ValueError(f"SBM bone table at {boff:#x} does not end the file")
    bones, last = [], None
    for i in range(nb):
        b, n, lo, z = struct.unpack_from("<4I", data, boff + 16 * i)
        if z or lo % 2 or lo < 16 * nb or boff + lo + 2 * n > len(data):
            raise ValueError(f"SBM bone record {i} out of range")
        if b & 0x80000000:
            last = i
        bones.append({"bone": b & 0x7FFFFFFF, "count": n, "first": (lo - 16 * nb) // 2})
    ids = sorted(b["bone"] for b in bones)
    if last != nb - 1 or len(set(ids)) != nb or ids[-1] >= BONES or nb == BONES and ids != list(range(BONES)):
        raise ValueError("SBM bone ids are not unique limbs 0..14 ending in the last flag")
    runs = sorted((b["first"], b["count"]) for b in bones if b["count"])
    if any(a + n > c for (a, n), (c, _) in zip(runs, runs[1:])) or sum(n for _, n in runs) > nv:
        raise ValueError("SBM bone vertex runs overlap")
    out["bones"] = bones
    out["skinned_verts"] = sum(n for _, n in runs)
    return out


def mdl(data: bytes) -> dict:
    """Header of a ``.MDL`` model bank: u32 count, u32 0, then count * 36-byte records
    {u32 flags (0x200), n_verts, n_strip, n_tex, vert_ptr, strip_ptr, 0, end_ptr, 0}.

    The pointers are offsets saved from a runtime layout: entry i's float4 vertex block starts at
    ``vert_ptr + 8 + 4*i`` on disc for the head bank and most stadium parts (``w_ok`` counts the
    vertices whose w is 1.0 at that base). The exact relocation rule is left to the analysis stage
    (the MDL loader in 1ST_READ); this only checks that every block stays inside the file.
    """
    count, z = struct.unpack_from("<2I", data, 0)
    if not count or z or 8 + 36 * count > len(data):
        raise ValueError(f"MDL header {count}/{z}")
    ents = []
    for i in range(count):
        fl, nv, ns, nt, vo, so, z1, x, z2 = struct.unpack_from("<9I", data, 8 + 36 * i)
        if z1 or z2 or vo + 16 * nv > so or so + 16 * ns > x or x > len(data) + 64:
            raise ValueError(f"MDL entry {i} out of range")
        base = vo + 8 + 4 * i
        w_ok = sum(1 for k in range(nv) if base + 16 * k + 16 <= len(data)
                   and struct.unpack_from("<f", data, base + 16 * k + 12)[0] == 1.0)
        ents.append({"index": i, "flags": fl, "verts": nv, "strip_records": ns, "textures": nt,
                     "vert_ptr": vo, "strip_ptr": so, "end_ptr": x, "w_ok": w_ok})
    return {"count": count, "entries": ents, "verts": sum(e["verts"] for e in ents),
            "w_ok": sum(e["w_ok"] for e in ents)}


def genseq(data: bytes) -> dict:
    """Parse ``GENSEQ.ANI``: sequence table and per-sequence sizes, validated to tile the file."""
    tag = struct.unpack_from("<I", data, 0)[0]
    if tag != ANI_TAG:
        raise ValueError(f"GENSEQ tag {tag:#x}")
    first = struct.unpack_from("<I", data, 12)[0]
    if first % 16:
        raise ValueError("GENSEQ table not 16-byte aligned")
    seqs = []
    for i in range(first // 16):
        fl, nf, nl, off = struct.unpack_from("<4I", data, 16 * i)
        seqs.append({"index": i, "flag": None if i == 0 else fl, "frames": nf, "limbs": nl,
                     "offset": off})
    for i, s in enumerate(seqs):
        end = seqs[i + 1]["offset"] if i + 1 < len(seqs) else len(data)
        size = end - s["offset"]
        packed, raw = ANI_PACKED_HEAD + ANI_PACKED_FRAME * s["frames"], ANI_RAW_FRAME * s["frames"]
        if s["limbs"] != BONES:
            raise ValueError(f"sequence {i}: {s['limbs']} limbs")
        last = i + 1 == len(seqs)                     # the file pads its last sequence to 8 bytes
        if packed <= size <= packed + 7 * last:
            s["packed"] = True
        elif raw <= size <= raw + 7 * last:
            s["packed"] = False
        else:
            raise ValueError(f"sequence {i}: {size} B fits neither packed nor raw frames")
        s["size"] = size
    return {"sequences": len(seqs), "packed": sum(s["packed"] for s in seqs),
            "raw": sum(not s["packed"] for s in seqs), "frames": sum(s["frames"] for s in seqs),
            "table": seqs}


def exe_refs(exe: bytes) -> dict:
    """Character-asset names referenced by 1ST_READ (case-insensitive string scan)."""
    pick = lambda pat: sorted({m.group().decode().upper() for m in re.finditer(pat, exe, re.I)})  # noqa: E731
    return {"sbm": pick(rb"[a-z0-9_]+\.sbm"), "mdl": pick(rb"[a-z0-9_]+\.mdl"),
            "ani": pick(rb"[a-z0-9_]+\.ani"),
            "uniform_textures": pick(rb"[a-z0-9_]*(unif|torso|armhnd)[a-z0-9_]*\.(pvr|wms)")}


def league(data: bytes) -> dict:
    """LEAGUE.DB header counts (u16 teams, u16 players) and the decoded name strings."""
    teams, players = struct.unpack_from("<2H", data, 0)
    names = [m.group().decode() for m in re.finditer(rb"[A-Z][A-Za-z.' -]{1,}", data)]
    return {"teams_field": teams, "players_field": players, "name_strings": len(names)}


def build(gdi: str | Path, chd: str | Path | None = None) -> dict:
    from .gdrom import GDRom
    g = GDRom(gdi)
    files = g.files
    ip = parse_ip(g.sector(45000))
    if ip["product"].replace("-", "") != PRODUCT or ip["version"] != VERSION:
        raise ValueError(f"not the inventoried build: {ip['product']} {ip['version']}")
    room = file_room(files)
    gdi = Path(gdi)
    tracks = [{"file": t[2].name, "lba": t[0], "sha256": sha256_file(t[2])} for t in g.tracks]
    exe = g.read("1ST_READ.BIN")
    ent = lambda n, extra: {"name": n, "lba": files[n][0], "size": files[n][1], "room": room[n],  # noqa: E731
                            "sha256": hashlib.sha256(g.read(n)).hexdigest(), **extra}
    bodies = [ent(n, {"kind": "body", "body_type": BODY_TYPES.get(n), **sbm(g.read(n))})
              for n in sorted(files) if n.endswith(".SBM") and files[n][1]]
    mdls = [ent(n, {"kind": "head_bank" if n == "MDL_HEAD.MDL" else "stadium", **mdl(g.read(n))})
            for n in sorted(files) if n.endswith(".MDL") and files[n][1]]
    ani = ent("GENSEQ.ANI", genseq(g.read("GENSEQ.ANI")))
    ext = collections.Counter(n.rsplit(".", 1)[-1] for n in files)
    pvr = sorted(n for n in files if n.endswith(".PVR"))
    return {
        "game_id": GAME_ID, "title": TITLE, "platform": "dreamcast", "catalog": CATALOG,
        "source": {"sha256": sha256_file(chd) if chd else SOURCE_SHA256, "expected": SOURCE_SHA256,
                   "kind": "chd", "tracks": tracks},
        "ip": ip, "engine": "Midway Blitz (arcade lineage); no Ninja/NJCM, no NaomiLib",
        "first_read": {"sha256": hashlib.sha256(exe).hexdigest(), "size": len(exe),
                       "lba": files["1ST_READ.BIN"][0], "refs": exe_refs(exe)},
        "filesystem": {"files": len(files), "bytes": sum(s for _, s in files.values()),
                       "by_extension": dict(ext.most_common()), "flat_root": all("/" not in n for n in files)},
        "characters": {
            "bodies": bodies, "models": mdls, "animations": ani,
            "uniform_textures": [n for n in pvr if re.search(r"UNIF|TORSO|ARMHND|PANT|NUM", n)],
            "helmet_textures": [n for n in pvr if re.search(r"HLM[LR]\.PVR$", n)],
            "team_packs": sorted(n for n in files if re.fullmatch(r"TB[A-Z_]{3}[AH]00\.PAK", n)),
            "league": league(g.read("LEAGUE.DB")),
            "playerdummy": {n: files[n][1] for n in files if n == "PLAYERS.MDL"},
        },
        "launch": {"prerequisites": "Dreamcast BIOS (dc_boot.bin/dc_flash.bin) for Flycast; GDI from chdman",
                   "boot": ip["boot"]},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("--chd")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    m = build(a.gdi, a.chd)
    txt = json.dumps(m, indent=1)
    if a.out:
        Path(a.out).write_text(txt)
    else:
        sys.stdout.write(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
