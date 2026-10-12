"""Source inventory for Dead or Alive 5 Ultimate: Arcade (Sega RingEdge 2, TeknoParrot).

The catalog entry (``collections/Teknoparrot/roms/DOA5.txt``, 57 bytes) is only a
placeholder that reads "DOA 5 Ultimate v2.6 (2.06) including all dlc (RingEdge 2)".
The owned build is the loose game directory ``collections/Teknoparrot/roms/DOA5``
that TeknoParrot's ``DOA5`` profile launches (``DOA5A.exe``, SegaJvs, 32-bit).

Assets are loose KT-engine files::

    character/<NAME>/costume/COS_NNN/<NAME>_COS_NNN.{tmc,tmcl,misc}
    character/<NAME>/equipment/{FACE,HAIR_NNN,CMN_FACE,...}/<NAME>_<PART>.{tmc,tmcl,mpm}
    character/<NAME>/animation/{INGAME,SELECT}/<NAME>_<SET>[_N].{mpm,sktm}
    character/<NAME>/{rtm,rte,tag_motion}/<GROUP>/<NAME>_<GROUP>.mpm
    character/<NAME>/camera/*.cam, <name>[_N|_non_encrypt].bin, <name>.phyd

``.tmc``/``.tmcl`` use KT chunked zlib (:func:`kt_decompress`).  A decompressed
``.tmc`` is a KT container (:func:`parse_container`) whose children are the model
chunks (MdlGeo, TTDM, VtxLay, ...); ``.mpm`` (``char_dat``) and ``.misc``
(``texch``) are uncompressed KT containers.

``python -m gbox.doa5a_inventory ROOT --out manifest.json [--listing find.tsv]``
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
import time
import zlib
from collections import Counter, defaultdict

SCHEMA = "gbox.doa5a_inventory/1"
CHUNK = 0x4000            # decoded bytes per KT zlib record
ZFLAG = 0x8000            # record holds a zlib stream (else stored bytes)
KT_VERSION = 0x01010000
EXE = "DOA5A.exe"
EXE_ORIG = "DOA5A.exe.orig"
DEEP_PARTS = ("COS_001", "FACE", "HAIR_001")   # bounded per-character deep parse


# --------------------------------------------------------------------------- codec

def kt_decode(data: bytes) -> tuple[bytes, int, dict]:
    """Decode KT chunked zlib.  Returns (raw, consumed_bytes, stats).

    Layout: ``u32 total``; then records ``{u32 w; data[w & 0x7fff]; pad to 4}``.
    ``w & 0x8000`` marks a complete zlib stream, otherwise the bytes are stored;
    a zero word is 4 bytes of filler.
    Every record expands to at most 0x4000 bytes; the decoded length must equal
    ``total`` exactly.
    """
    if len(data) < 4:
        raise ValueError("KT stream shorter than its size field")
    total = struct.unpack_from("<I", data, 0)[0]
    pos, out = 4, bytearray()
    stats = {"records": 0, "zlib": 0, "stored": 0, "fill": 0}
    while len(out) < total:
        if pos + 4 > len(data):
            raise ValueError(f"KT stream truncated at {pos:#x}")
        w = struct.unpack_from("<I", data, pos)[0]
        if w == 0:                      # zero word: 4-byte filler between records
            stats["fill"] += 1
            pos += 4
            continue
        if w >> 16:
            raise ValueError(f"unknown KT record word {w:#x} at {pos:#x}")
        n = w & 0x7FFF
        blob = data[pos + 4:pos + 4 + n]
        if len(blob) != n or n == 0:
            raise ValueError(f"bad KT record length {n:#x} at {pos:#x}")
        if w & ZFLAG:
            d = zlib.decompressobj()
            piece = d.decompress(blob)
            if not d.eof or d.unused_data:
                raise ValueError(f"KT zlib record at {pos:#x} is not one whole stream")
            stats["zlib"] += 1
        else:
            piece = blob
            stats["stored"] += 1
        if len(piece) > CHUNK:
            raise ValueError(f"KT record at {pos:#x} expands past {CHUNK:#x}")
        out += piece
        stats["records"] += 1
        pos = (pos + 4 + n + 3) & ~3
    if len(out) != total:
        raise ValueError(f"KT stream decoded {len(out):#x} bytes, header says {total:#x}")
    return bytes(out), min(pos, len(data)), stats


def kt_decompress(data: bytes) -> bytes:
    return kt_decode(data)[0]


def kt_compress(raw: bytes, level: int = 9) -> bytes:
    """Encode ``raw`` in the same record format (decoder-equivalent, not byte-identical)."""
    out = bytearray(struct.pack("<I", len(raw)))
    for i in range(0, len(raw), CHUNK):
        piece = raw[i:i + CHUNK]
        z = zlib.compress(piece, level)
        if len(z) < len(piece) and len(z) <= 0x7FFF:
            out += struct.pack("<I", len(z) | ZFLAG) + z
        else:
            out += struct.pack("<I", len(piece)) + piece
        out += b"\0" * (-len(out) % 4)
    return bytes(out)


# ----------------------------------------------------------------------- container

def _tag(b: bytes) -> str | None:
    t = b.split(b"\0", 1)[0]
    if not t or len(t) > 8 or not all(33 <= c < 127 for c in t):
        return None
    return t.decode("ascii")


def parse_container(buf: bytes, base: int = 0) -> dict:
    """Parse a KT container header at ``base``.

    ``magic[8]; u32 version; u32 header_size; u32 size; u32 count; u32 valid;
    u32 ?; u32 offset_table; u32 size_table; u32 ?; u32 ?`` (0x30 bytes); chunk
    offsets are u32 relative to ``base`` (0 = empty slot).
    """
    if len(buf) < base + 0x30:
        raise ValueError("buffer shorter than a KT container header")
    magic = _tag(buf[base:base + 8])
    if magic is None:
        raise ValueError(f"no KT container magic at {base:#x}")
    ver, hsize, size, count, valid, _r, otab, stab = struct.unpack_from("<8I", buf, base + 8)
    if ver != KT_VERSION:
        raise ValueError(f"{magic}: unexpected KT version {ver:#x}")
    if count > 0x10000 or size < hsize or base + size > len(buf):
        raise ValueError(f"{magic}: size/count out of range")
    if otab + 4 * count > size:
        raise ValueError(f"{magic}: offset table outside container")
    offsets = list(struct.unpack_from(f"<{count}I", buf, base + otab))
    sizes = None
    if stab:
        if stab + 4 * count > size:
            raise ValueError(f"{magic}: size table outside container")
        sizes = list(struct.unpack_from(f"<{count}I", buf, base + stab))
    if any(o and (o < hsize or o >= size) for o in offsets):
        raise ValueError(f"{magic}: chunk offset outside container")
    return {"magic": magic, "header_size": hsize, "size": size, "count": count,
            "valid": valid, "offsets": offsets, "sizes": sizes}


def container_children(buf: bytes, base: int = 0) -> list[dict]:
    head = parse_container(buf, base)
    kids = []
    for i, off in enumerate(head["offsets"]):
        if not off:
            continue
        kid = {"index": i, "offset": off, "tag": None, "count": None}
        try:
            sub = parse_container(buf, base + off)
            kid.update(tag=sub["magic"], count=sub["count"], size=sub["size"])
        except ValueError:
            pass
        kids.append(kid)
    return kids


def tmc_summary(raw: bytes) -> dict:
    head = parse_container(raw)
    if head["magic"] != "TMC":
        raise ValueError(f"expected TMC, found {head['magic']}")
    ident = raw[0x50:0x60].split(b"\0", 1)[0]
    kids = container_children(raw)
    return {"chunks": [[k["tag"], k["count"]] for k in kids],
            "chunk_count": head["count"], "valid": head["valid"],
            "tmc_id": ident.decode("ascii") if ident.isascii() and ident.isalnum() else None}


# -------------------------------------------------------------------------- source

def pe_info(exe: bytes) -> dict:
    if exe[:2] != b"MZ":
        raise ValueError("not an MZ executable")
    pe = struct.unpack_from("<I", exe, 0x3C)[0]
    if exe[pe:pe + 4] != b"PE\0\0":
        raise ValueError("missing PE signature")
    machine, nsec, stamp = struct.unpack_from("<HHI", exe, pe + 4)
    optsz = struct.unpack_from("<H", exe, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", exe, opt)[0]
    image_base = struct.unpack_from("<I", exe, opt + 28)[0] if magic == 0x10B else \
        struct.unpack_from("<Q", exe, opt + 24)[0]
    secs = []
    for i in range(nsec):
        s = opt + optsz + 40 * i
        name = exe[s:s + 8].split(b"\0", 1)[0].decode("latin1")
        vsize, va, rsize, rptr = struct.unpack_from("<4I", exe, s + 8)
        secs.append({"name": name, "va": va, "vsize": vsize, "raw": rptr, "rsize": rsize})
    return {"machine": hex(machine), "pe32": magic == 0x10B, "timestamp": stamp,
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp)),
            "image_base": hex(image_base), "sections": secs}


def file_to_va(pe: dict, off: int) -> str | None:
    for s in pe["sections"]:
        if s["raw"] <= off < s["raw"] + s["rsize"]:
            return hex(int(pe["image_base"], 16) + s["va"] + off - s["raw"])
    return None


def diff_ranges(a: bytes, b: bytes, gap: int = 16, limit: int = 64) -> dict:
    if len(a) != len(b):
        return {"same_size": False, "size_a": len(a), "size_b": len(b)}
    ranges, n = [], 0
    for i in range(len(a)):
        if a[i] != b[i]:
            n += 1
            if ranges and i - ranges[-1][1] <= gap:
                ranges[-1][1] = i + 1
            else:
                ranges.append([i, i + 1])
    return {"same_size": True, "differing_bytes": n, "range_count": len(ranges),
            "ranges": [[s, e - s] for s, e in ranges[:limit]]}


ASSET_STR = re.compile(rb"[A-Za-z0-9_%./\\:-]{3,80}\.(?:tmcl?|mpm|sktm|phyd|misc|cam|bin)\b")


def exe_strings(exe: bytes, limit: int = 60) -> list[str]:
    seen = []
    for m in ASSET_STR.finditer(exe):
        s = m.group(0).decode("latin1")
        if s not in seen:
            seen.append(s)
        if len(seen) >= limit:
            break
    return seen


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def read_ini(text: str) -> dict:
    out, sec = {}, None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            sec = line[1:-1]
            out[sec] = {}
        elif "=" in line and sec is not None:
            k, v = line.split("=", 1)
            out[sec][k.strip()] = v.strip()
    return out


# ------------------------------------------------------------------------- listing

def load_listing(path: str) -> list[tuple[str, int, str]]:
    """Read ``find -printf '%y\\t%s\\t%T@\\t%p\\n'`` output: (type, size, relpath)."""
    rows = []
    with open(path, encoding="utf-8", errors="surrogateescape") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t", 3)
            if len(parts) != 4:
                continue
            rel = parts[3][2:] if parts[3].startswith("./") else parts[3]
            if rel in (".", ""):
                continue
            rows.append((parts[0], int(parts[1]), rel))
    return rows


def walk(root: str) -> list[tuple[str, int, str]]:
    rows = []
    for dp, dns, fns in os.walk(root):
        for d in dns:
            rows.append(("d", 0, os.path.relpath(os.path.join(dp, d), root)))
        for fn in fns:
            p = os.path.join(dp, fn)
            rows.append(("f", os.path.getsize(p), os.path.relpath(p, root)))
    return rows


def classify_character_files(rows) -> dict:
    chars: dict = defaultdict(lambda: {"costumes": defaultdict(dict), "equipment": defaultdict(dict),
                                       "animation": defaultdict(dict), "motion": Counter(),
                                       "motion_bytes": 0, "camera": [], "bins": {}, "phyd": {},
                                       "other": []})
    for kind, size, rel in rows:
        parts = rel.replace("\\", "/").split("/")
        if len(parts) < 3 or parts[0] != "character":
            continue
        name = parts[1]
        if kind != "f":
            chars[name]   # register the directory
            continue
        c = chars[name]
        fn = parts[-1]
        ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
        if len(parts) == 3:
            (c["bins"] if ext == "bin" else c["phyd"] if ext == "phyd" else {})[fn] = size
            if ext not in ("bin", "phyd"):
                c["other"].append(rel)
        elif parts[2] == "costume" and len(parts) == 5:
            c["costumes"][parts[3]][ext] = size
        elif parts[2] == "equipment" and len(parts) == 5:
            c["equipment"][parts[3]][fn] = size
        elif parts[2] == "animation" and len(parts) == 5:
            c["animation"][parts[3]][fn] = size
        elif parts[2] in ("rtm", "rte", "tag_motion"):
            c["motion"][parts[2]] += 1
            c["motion_bytes"] += size
        elif parts[2] == "camera":
            c["camera"].append(fn)
        else:
            c["other"].append(rel)
    out = {}
    for name in sorted(chars):
        c = chars[name]
        out[name] = {"costumes": {k: dict(v) for k, v in sorted(c["costumes"].items())},
                     "equipment": {k: dict(v) for k, v in sorted(c["equipment"].items())},
                     "animation": {k: dict(v) for k, v in sorted(c["animation"].items())},
                     "motion_files": dict(c["motion"]), "motion_bytes": c["motion_bytes"],
                     "camera": sorted(c["camera"]), "bins": dict(sorted(c["bins"].items())),
                     "phyd": c["phyd"], "other": c["other"][:20]}
    return out


def totals(rows) -> dict:
    by_ext, top = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    files = nbytes = dirs = 0
    for kind, size, rel in rows:
        if kind == "d":
            dirs += 1
            continue
        files += 1
        nbytes += size
        fn = rel.replace("\\", "/").rsplit("/", 1)[-1]
        ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
        by_ext[ext][0] += 1
        by_ext[ext][1] += size
        t = rel.replace("\\", "/").split("/", 1)[0] if "/" in rel.replace("\\", "/") else "."
        top[t][0] += 1
        top[t][1] += size
    return {"files": files, "dirs": dirs, "bytes": nbytes,
            "by_ext": dict(sorted(by_ext.items(), key=lambda kv: -kv[1][1])),
            "top_dirs": dict(sorted(top.items()))}


# ----------------------------------------------------------------------- inventory

def deep_parse(root: str, rel: str) -> dict:
    p = os.path.join(root, rel)
    data = open(p, "rb").read()
    rec = {"path": rel, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    try:
        raw, used, st = kt_decode(data)
        rec.update(raw_size=len(raw), trailing=data[used:].hex()[:32], **st)
        rec.update(tmc_summary(raw))
    except ValueError as e:
        rec["error"] = str(e)
    tmcl = p[:-4] + ".tmcl"
    if os.path.exists(tmcl):
        with open(tmcl, "rb") as f:
            head = f.read(4)
        rec["tmcl_raw_size"] = struct.unpack("<I", head)[0] if len(head) == 4 else None
    return rec


def build_inventory(root: str, rows=None, deep_parts=DEEP_PARTS, profile: dict | None = None,
                    log=None) -> dict:
    rows = rows if rows is not None else walk(root)
    man = {"schema": SCHEMA, "root": root, "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "errors": []}
    src = {}
    exe = open(os.path.join(root, EXE), "rb").read()
    src["exe"] = {"path": EXE, "size": len(exe), "sha256": hashlib.sha256(exe).hexdigest(),
                  "pe": pe_info(exe), "asset_strings": exe_strings(exe)}
    orig_p = os.path.join(root, EXE_ORIG)
    if os.path.exists(orig_p):
        orig = open(orig_p, "rb").read()
        src["exe_orig"] = {"path": EXE_ORIG, "size": len(orig), "sha256": hashlib.sha256(orig).hexdigest(),
                           "pe": pe_info(orig)}
        d = diff_ranges(orig, exe)
        for r in d.get("ranges", []):
            r.append(file_to_va(src["exe"]["pe"], r[0]))
        src["patch_vs_orig"] = d
    man["source"] = src
    launch: dict = {"teknoparrot_profile": profile or {}}
    for fn in ("teknoparrot.ini", "game.bat", "steam_appid.txt"):
        p = os.path.join(root, fn)
        if os.path.exists(p):
            text = open(p, "rb").read().decode("latin1")
            launch[fn] = read_ini(text) if fn.endswith(".ini") else text.strip()
    launch["runtime_dlls"] = sorted(r[2] for r in rows if r[0] == "f" and "/" not in r[2]
                                    and r[2].lower().endswith((".dll", ".exe")))
    man["launch"] = launch
    man["totals"] = totals(rows)
    chars = classify_character_files(rows)
    man["characters"] = chars
    roster = []
    deep = []
    for name, c in chars.items():
        tmc_parts = {k: v for k, v in c["costumes"].items() if "tmc" in v}
        roster.append({"name": name, "costumes": len(tmc_parts),
                       "costume_ids": sorted(tmc_parts),
                       "hair": sorted(k for k in c["equipment"] if k.startswith("HAIR")),
                       "face": sorted(k for k in c["equipment"] if "FACE" in k),
                       "animation_sets": sorted(c["animation"]),
                       "motion_files": sum(c["motion_files"].values())})
        for part in deep_parts:
            sub = "costume" if part.startswith("COS_") else "equipment"
            rel = f"character/{name}/{sub}/{part}/{name}_{part}.tmc"
            if any(r[2] == rel for r in rows):
                try:
                    deep.append(deep_parse(root, rel))
                except OSError as e:
                    man["errors"].append(f"{rel}: {e}")
                if log:
                    log(f"parsed {rel}")
    man["roster"] = roster
    man["deep_tmc"] = deep
    man["summary"] = {
        "characters": len(roster),
        "costume_models": sum(r["costumes"] for r in roster),
        "hair_models": sum(len(r["hair"]) for r in roster),
        "deep_tmc_parsed": len(deep),
        "deep_tmc_ok": sum(1 for d in deep if "error" not in d),
        "chunk_tags": sorted({t for d in deep for t, _ in d.get("chunks", []) if t}),
    }
    return man


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DOA5 Ultimate Arcade source inventory")
    ap.add_argument("root")
    ap.add_argument("--out", required=True)
    ap.add_argument("--listing", help="find -printf '%%y\\t%%s\\t%%T@\\t%%p\\n' output for ROOT")
    ap.add_argument("--profile", help="JSON file with the TeknoParrot profile fields")
    a = ap.parse_args(argv)
    rows = load_listing(a.listing) if a.listing else None
    prof = json.load(open(a.profile)) if a.profile else None
    man = build_inventory(a.root, rows, profile=prof, log=lambda s: print(s, file=sys.stderr, flush=True))
    with open(a.out, "w") as f:
        json.dump(man, f, indent=1, sort_keys=False)
    print(json.dumps(man["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
