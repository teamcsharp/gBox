"""Devil May Cry 2 (PS2, NTSC-U SLUS_204.84) owned-disc inventory.

Layout of the owned USA Disc 1 (chdman extractcd of the catalog CHD -> 2048-byte MODE1 ISO):

* ``SYSTEM.CNF`` boots ``cdrom0:\\SLUS_204.84;1`` (VER 1.03, NTSC); ``IOPRP255.IMG`` / ``MODULE.BIZ`` are IOP
  modules; ``0FLIST.DVD`` lists the three data archives.
* ``X_DATA.BIN``, ``Y_DATA.BIN`` and ``Z_DATA.BIN`` are standard CRI AFS archives ("AFS\\0", u32 count, then
  (u32 offset, u32 size) pairs).  The (offset, size) of each CRI filename directory is recorded, but the
  directory itself lies past the archive's ISO extent (it was cut at mastering), so entries are nameless.
  - X_DATA (3488 entries) is the game data: mostly ``MOMO`` packages.
  - Y_DATA (148 entries) is streamed audio (``0x80000020``-style headers).
  - Z_DATA (11 entries) is MPEG-2 program streams (FMV, ``00 00 01 BA``).
* ``MOMO`` package: "MOMO", u32 count, then count (u32 offset, u32 size) pairs relative to the package start.
  Packages nest (a child can itself be MOMO).
* Some X_DATA entries are compressed: a 2-byte flag then a literal-first LZ stream, so the original magic
  appears at +2.  Verified on the owned disc: the flag's HIGH byte is the container type (``0x00`` = MOMO,
  ``0x04`` = TIM2) and its LOW byte is a mode/level (MOMO ``{0x00,0x02,0x04,0x06,0x08,0x20,0x24,0x8c}``,
  TIM2 ``{0x00,0x40,0x41}``).  The stream opens with a literal run that reproduces the container header
  ("MOMO" + count + leading table entries, or the TIM2 header) and then switches to back-references; the
  back-ref word encoding is still analysis-stage work (see ``compressed_entry_probe``).
* Model children start ``<b0> <b1> <b2> 01`` followed by u32 part count and u32 byte size (<= child size), then
  16-byte part records (u16 kind, u16 count, u32 offset, 0, 0).  Texture banks start u32 n followed by n
  u32 0x21 type words; textures are ``TIM2``.
* Mesh children (``b1 == 0x22``) verified on the owned disc: the u32 at +4 is NOT a reliable part-record
  count (X:108/0 declares 57 but holds 7 records), so ``mesh_parts`` walks 16-byte records
  (u16 kind, u16 count, u32 offset, u16 flags, u16 z2) until one fails sanity checks; the 0xCDCD padding
  after the last record terminates most tables.  Kinds seen: 1/3/4/5 = float arrays (kind 3/4 carry the
  (1, 0x10) quad flags), 2 = u16 arrays.  Every verified mesh child ends with a 0x280-byte trailer beyond
  the declared size.  Part payloads are plain float/u16 blocks; the EE code (SLUS_204.84) wraps them into
  VIF uploads, so the VIF tag construction lives in the executable, not in the file.

Nothing here writes to the disc; ``inventory`` only reads the extracted image.
"""
from __future__ import annotations

import collections
import hashlib
import json
import struct
from pathlib import Path

SECTOR = 2048
SERIAL = "SLUS_204.84"
ARCHIVES = ("X_DATA.BIN", "Y_DATA.BIN", "Z_DATA.BIN")
GAME_IDS = {"01bb1fe7c84e8e79": "Devil May Cry 2 (USA) (Disc 1)"}


def afs_table(head: bytes, archive_size: int | None = None) -> dict:
    """Parse an AFS header (at least 8 + 8*count + 8 bytes). Returns offsets, sizes and the name-dir pair."""
    if len(head) < 8 or head[:4] != b"AFS\x00":
        raise ValueError(f"not an AFS archive (magic {head[:4]!r})")
    n = struct.unpack_from("<I", head, 4)[0]
    if len(head) < 8 + 8 * n:
        raise ValueError(f"AFS header truncated: {n} entries need {8 + 8 * n} bytes")
    tab = struct.unpack_from(f"<{2 * n}I", head, 8)
    offs, sizes = list(tab[0::2]), list(tab[1::2])
    for o, z in zip(offs, sizes):
        if archive_size is not None and o + z > archive_size:
            raise ValueError("AFS entry extends outside the archive")
    names = None
    if len(head) >= 16 + 8 * n:
        names = struct.unpack_from("<II", head, 8 + 8 * n)
        if names == (0, 0) and offs and offs[0] >= 8:
            names = None
    return {"count": n, "offsets": offs, "sizes": sizes, "name_dir": names}


def afs_name_dir(table: dict, pre_first: bytes | None = None) -> tuple[int, int] | None:
    """The CRI name directory pair: after the table, or in the 8 bytes before the first entry (CRI layout)."""
    nd = table.get("name_dir")
    if nd and nd[1] == 48 * table["count"]:
        return tuple(nd)
    if pre_first and len(pre_first) == 8:
        o, z = struct.unpack("<II", pre_first)
        if z == 48 * table["count"]:
            return (o, z)
    return None


def momo_children(b: bytes) -> list[tuple[int, int]]:
    """(offset, size) of each child of a MOMO package; raises ValueError on a bad table."""
    if b[:4] != b"MOMO":
        raise ValueError("not a MOMO package")
    n = struct.unpack_from("<I", b, 4)[0]
    if 8 + 8 * n > len(b):
        raise ValueError(f"MOMO table of {n} entries exceeds {len(b)} bytes")
    out = []
    for j in range(n):
        o, z = struct.unpack_from("<II", b, 8 + 8 * j)
        if z and o + z > len(b):
            raise ValueError(f"MOMO child {j} extends outside the package")
        out.append((o, z))
    return out


def model_header(b: bytes) -> dict | None:
    """Recognise a DMC2 model child: <b0> <b1> <b2> 01, u32 parts, u32 size, 16-byte part records."""
    if len(b) < 0x30 or b[3] != 1:
        return None
    parts, size = struct.unpack_from("<II", b, 4)
    if not (1 <= parts <= 512) or not (len(b) - 0x1000 <= size <= len(b)):
        return None
    return {"tag": b[:4].hex(), "parts": parts, "size": size}


def texbank_header(b: bytes) -> dict | None:
    if len(b) < 8:
        return None
    n = struct.unpack_from("<I", b, 0)[0]
    if not (1 <= n <= 64) or len(b) < 4 + 4 * n:
        return None
    if all(struct.unpack_from("<I", b, 4 + 4 * k)[0] == 0x21 for k in range(n)):
        return {"textures": n}
    return None


def classify(b: bytes) -> str:
    if not b:
        return "empty"
    m = b[:4]
    if m == b"MOMO":
        return "momo"
    if m == b"TIM2":
        return "tim2"
    if m == b"HITS":
        return "hits"
    if m == b"ipum":
        return "ipum"
    if m == b"\x00\x00\x01\xba":
        return "mpeg_ps"
    if b[2:6] in (b"MOMO", b"TIM2"):
        return "compressed_" + b[2:6].decode().lower()
    mh = model_header(b)
    if mh:
        # b1 == 0x22: the mesh family (57-262 parts, 150-210 KB, repeated across stage packages). Other headed
        # records (01 01 01 01, 01 12 01 01, ...) share the count/size header but hold float tracks; they are
        # motion/collision candidates until the analysis stage maps their loaders.
        return "mesh" if b[1] == 0x22 else "rec01"
    if texbank_header(b):
        return "texbank"
    if m[0] == 0x80 and m[1] == 0 and len(b) > 0x10000:
        return "stream_audio"
    return "unknown"


def walk_package(b: bytes, path: str, out: list, depth: int = 0):
    """Append (path, kind, size, sha256, extra) for a package and its MOMO children, recursively."""
    kind = classify(b)
    rec = {"path": path, "kind": kind, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()}
    if kind in ("mesh", "rec01"):
        rec["model"] = model_header(b)
    elif kind == "texbank":
        rec["texbank"] = texbank_header(b)
    out.append(rec)
    if kind == "momo" and depth < 4:
        try:
            kids = momo_children(b)
        except ValueError as e:
            rec["error"] = str(e)
            return
        rec["children"] = len(kids)
        for j, (o, z) in enumerate(kids):
            if z:
                walk_package(b[o:o + z], f"{path}/{j}", out, depth + 1)


def character_candidates(uniq: dict, models: list, min_copies: int = 20) -> list[dict]:
    """Unique meshes repeated in >= min_copies stage packages: playable/recurring-character candidates.

    Names are NOT assigned here; the analysis stage must tie each to the SLUS_204.84 loader tables."""
    by = {m["sha256"]: m for m in models}
    out = [{"sha256": k, "first": v[0], "copies": len(v), "parts": by[k]["model"]["parts"],
            "size": by[k]["size"], "tag": by[k]["model"]["tag"]} for k, v in uniq.items() if len(v) >= min_copies]
    return sorted(out, key=lambda c: (-c["copies"], c["first"]))


# --- mesh part-record / VIF probe --------------------------------------------------------------
# Verified against the six recurring mesh candidates on the owned disc (X:108/0, 108/10, 1157/0,
# 1157/10, 2036/0, 836/10): every one has len(child) - declared_size == 0x280.  Part payloads are
# plain float/u16 blocks; the EE wraps them into VIF uploads at runtime (analysis-stage target in
# SLUS_204.84), so the file itself carries no VIF tags.

MESH_KINDS = (1, 2, 3, 4, 5)      # 1/3/4/5: float arrays; 2: u16 arrays
QUAD_FLAGS = (1, 0x10)             # kinds 3 and 4 carry these flags on every verified mesh
MESH_TRAILER = 0x280               # bytes after the declared size on every verified mesh child
MAX_PARTS = 4096


def mesh_parts(b: bytes) -> tuple[dict, list[dict]]:
    """Parse a DMC2 mesh child (b1 == 0x22): 12-byte header then 16-byte part records.

    The u32 at +4 is not a reliable record count (X:108/0 declares 57 but holds 7 records), so
    records are walked until one fails the kind/offset sanity checks; 0xCDCD padding terminates
    most tables.  Each record: u16 kind, u16 count, u32 offset, u16 flags, u16 z2.  Offsets are
    child-absolute and payloads must end inside the declared size."""
    if len(b) < 12 or b[1] != 0x22 or b[3] != 1:
        raise ValueError(f"not a DMC2 mesh child (tag {b[:4].hex()})")
    declared_parts, size = struct.unpack_from("<II", b, 4)
    if size > len(b):
        raise ValueError(f"declared size {size} exceeds child size {len(b)}")
    header = {"tag": b[:4].hex(), "declared_parts": declared_parts, "size": size,
              "trailer": len(b) - size}
    parts = []
    for j in range(min(declared_parts, MAX_PARTS)):
        off = 12 + 16 * j
        if off + 16 > len(b):
            break
        kind, count = struct.unpack_from("<HH", b, off)
        p_off = struct.unpack_from("<I", b, off + 4)[0]
        flags, z2 = struct.unpack_from("<HH", b, off + 8)
        elsz = 2 if kind == 2 else 4
        if kind not in MESH_KINDS or p_off < 12 or p_off + count * elsz > size:
            break
        parts.append({"kind": kind, "count": count, "offset": p_off, "flags": flags,
                      "z2": z2, "elements": elsz})
    return header, parts


def mesh_probe(b: bytes) -> dict:
    """Structural probe of a mesh child: header, parsed part records and float sanity.

    The probe is the analysis-stage format check: it validates the part-record table against the
    declared size and reports how much of the payload region the records cover, so a reader can be
    built on the same arithmetic once the ELF consumer (VIF upload construction) is mapped."""
    header, parts = mesh_parts(b)
    floats = u16s = quads = nans = 0
    max_end = 0
    for p in parts:
        o, c = p["offset"], p["count"]
        max_end = max(max_end, o + p["elements"] * c)
        if p["kind"] == 2:
            u16s += c
            continue
        floats += c
        if p["kind"] in (3, 4):
            quads += c
        if c:
            n = min(c, 64)
            vals = struct.unpack_from(f"<{n}f", b, o)
            nans += sum(1 for v in vals if v != v)
    return {**header, "records": len(parts), "floats": floats, "u16s": u16s,
            "quads": quads, "max_end": max_end,
            "coverage": max_end / header["size"] if header["size"] else 0.0,
            "nan_count": nans,
            "quad_flagged": [p for p in parts if p["kind"] in (3, 4) and
                             (p["flags"], p["z2"]) == QUAD_FLAGS]}


# --- compressed entry probe --------------------------------------------------------------
# Verified on the owned disc.  Compressed X_DATA entries put their container magic at +2:
# ``00 00 'MOMO'`` / ``41 04 'TIM2'``.  The 2-byte flag's high byte selects the type
# (0x00 MOMO, 0x04 TIM2) and the low byte is a mode; the stream is a literal-first LZ.  The
# literal run reproduces the container header before the first back-reference.  The AFS
# loader that feeds these buffers is the CRI ADXT library in SLUS_204.84 (ADXT_EntryAfs
# FUN_00131aa8, ADXT_StartAfs FUN_00139968, read FUN_00131260, AFS index globals 0x548220 /
# 0x548340); the LZ back-ref decoder itself is the remaining analysis gap.

MOMO_FLAGS = (0x00, 0x02, 0x04, 0x06, 0x08, 0x20, 0x24, 0x8c)
TIM2_FLAGS = (0x00, 0x40, 0x41)
COMPRESSED_TYPE = {b"MOMO": "momo", b"TIM2": "tim2"}


def compressed_entry_probe(b: bytes) -> dict:
    """Characterise a compressed X_DATA entry (container magic at +2).

    Pins the 2-byte flag, its type/mode bytes and the length of the literal header run so a
    candidate back-ref decoder can be validated against X:105/106 (MOMO) and X:2631 (TIM2).
    """
    if len(b) < 10 or b[2:6] not in COMPRESSED_TYPE:
        raise ValueError(f"not a compressed DMC2 entry (magic at +2 = {b[2:6]!r})")
    flag = struct.unpack_from("<H", b, 0)[0]
    typ = COMPRESSED_TYPE[b[2:6]]
    out = {"flag": flag, "flag_hi": flag >> 8, "flag_lo": flag & 0xff,
           "type": typ, "magic": b[2:6].decode(), "size": len(b)}
    out["literal_prefix"] = _momo_literal_prefix(b, 2) if typ == "momo" else _tim2_literal_prefix(b, 2)
    return out


def _momo_literal_prefix(b: bytes, off: int) -> int:
    """Bytes from ``off`` that parse as a contiguous MOMO header ("MOMO" + count + table entries).

    Walks (u32 offset, u32 size) pairs until one fails sanity: offsets are package-relative
    and grow with each child, so a valid literal entry has a positive size and a strictly
    increasing offset that stays under a generous decompression bound (64x the compressed
    size); anything larger is the compressed stream resuming.  Returns the total literal byte
    count including the magic.
    """
    if b[off:off + 4] != b"MOMO":
        return 0
    n = struct.unpack_from("<I", b, off + 4)[0]
    if not (1 <= n <= 512):
        return 0
    run, prev_end, bound = 8, 0, len(b) * 64
    for j in range(n):
        if off + run + 8 > len(b):
            break
        o, s = struct.unpack_from("<II", b, off + run)
        if o <= 0 or s <= 0 or o > bound or (j and o < prev_end):
            break
        prev_end = o + s
        run += 8
    return run


def _tim2_literal_prefix(b: bytes, off: int) -> int:
    """Bytes from ``off`` forming the literal TIM2 header prefix ("TIM2" v4 + format/count)."""
    if b[off:off + 4] != b"TIM2" or b[off + 4] != 4:
        return 0
    return 8  # conservative: magic + version + format + u16 picture_count


def inventory(iso: Path, deep: bool = True) -> dict:
    """Read-only inventory of the extracted disc image."""
    from .gta_rw import iso_files
    iso = Path(iso)
    with iso.open("rb") as f:
        files = iso_files(f)
        disc = {}
        for name, (lba, size) in sorted(files.items()):
            f.seek(lba * SECTOR)
            h, left = hashlib.sha256(), size
            while left:
                c = f.read(min(left, 1 << 24))
                if not c:
                    raise ValueError(f"{name} truncated in {iso}")
                h.update(c)
                left -= len(c)
            disc[name] = {"lba": lba, "size": size, "sha256": h.hexdigest()}
        cnf = files.get("SYSTEM.CNF")
        boot = None
        if cnf:
            f.seek(cnf[0] * SECTOR)
            txt = f.read(cnf[1]).decode("ascii", "replace")
            for line in txt.splitlines():
                if line.upper().startswith("BOOT2"):
                    boot = line.split("\\", 1)[-1].split(";")[0].strip()
        archives, entries = {}, []
        for an in ARCHIVES:
            if an not in files:
                continue
            lba, size = files[an]
            base = lba * SECTOR
            f.seek(base)
            n = struct.unpack("<I", f.read(8)[4:])[0]
            f.seek(base)
            tab = afs_table(f.read(16 + 8 * n), size)
            f.seek(base + tab["offsets"][0] - 8)
            nd = afs_name_dir(tab, f.read(8))
            kinds = collections.Counter()
            for i, (o, z) in enumerate(zip(tab["offsets"], tab["sizes"])):
                if not z:
                    kinds["empty"] += 1
                    continue
                if an == "X_DATA.BIN" and deep:
                    f.seek(base + o)
                    rows: list = []
                    walk_package(f.read(z), f"{an}:{i}", rows)
                    kinds[rows[0]["kind"]] += 1
                    entries.extend(rows)
                else:
                    f.seek(base + o)
                    kinds[classify(f.read(16 if an != "Y_DATA.BIN" else 0x10001)[:0x10001])] += 1
            archives[an] = {"entries": n, "kinds": dict(kinds), "name_dir": list(nd) if nd else None,
                            "name_dir_on_disc": bool(nd and nd[0] + nd[1] <= size)}
    models = [e for e in entries if e["kind"] == "mesh"]
    uniq = {}
    for e in models:
        uniq.setdefault(e["sha256"], []).append(e["path"])
    tex = sum(1 for e in entries if e["kind"] == "tim2")
    return {"serial": boot, "disc": disc, "archives": archives,
            "x_kinds": dict(collections.Counter(e["kind"] for e in entries)),
            "models": len(models), "unique_models": len(uniq), "tim2_textures": tex,
            "character_candidates": character_candidates(uniq, models),
            "model_packages": sorted({e["path"].split("/")[0] for e in models},
                                     key=lambda p: int(p.split(":")[1])),
            "unique_model_index": [{"sha256": k, "parts": next(m["model"]["parts"] for m in models
                                                               if m["sha256"] == k), "paths": v[:8], "copies": len(v)}
                                   for k, v in sorted(uniq.items(), key=lambda kv: kv[1][0])],
            "entries": entries}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="DMC2 PS2 disc inventory (read-only)")
    ap.add_argument("iso")
    ap.add_argument("--out", help="write the full manifest JSON here")
    a = ap.parse_args(argv)
    inv = inventory(Path(a.iso))
    if a.out:
        Path(a.out).write_text(json.dumps(inv, indent=1))
    summary = {k: v for k, v in inv.items() if k not in ("entries", "unique_model_index")}
    summary["model_packages"] = len(inv["model_packages"])
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
