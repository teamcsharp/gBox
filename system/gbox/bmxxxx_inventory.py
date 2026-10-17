"""BMX XXX (USA, GameCube, GB3E51) -- owned-disc inventory for character-replacement work.

Z-Axis / Acclaim 2002.  Despite the HAL SysDolphin (HSD) engine fingerprint, the on-disc
assets are Z-Axis's own LITTLE-endian IFF container format, not Melee-style big-endian HSD
``.dat`` archives.  The disc FST carries ``default.dol``, the Z-Axis Library (``.zal``)
archives that hold every model/part/skeleton/animation, level ``.GEO/.TXR/.INS/.DAT`` files,
``.zsd`` audio banks, ``.h4m`` movies and ``.zsc/.zif`` scripts.

Container format (verified against every archive on the disc):

  ZAL  ``ZDIR <u32 dir_size>`` then the directory as sub-chunks (all little-endian):
         ``DIDF`` u32 count + u32 0, ``GRID`` count x u32 id/hash, ``DLEN`` count x u32
         (high nibble = flags, low 28 bits = byte length), ``OFST`` count x u32 (absolute
         file offset of each entry), optional ``NAME`` (NUL-separated names).  Entries are
         FORM records.

  FORM  ``<tag> <u32 size>`` chunks: FMDL (file model) -> MODL -> [TXRC texture banks,
         TGEO geometry, TGIN instances]; a FORM/ANIM entry holds DEFI animation data.
         TXRC carries a u32 texture count then TXRH headers with the texture names.
         TGEO carries a TGHD header + vertex/index data (geometry).

Character model set: a Create-a-Rider system -- a base skeleton (create/skeleton.zal, 5
bodies) plus modular parts (create/parts.zal, 278 FMDL clothing/hair/face/accessory parts)
and textures (create/textureA..D.zal), plus 45 assembled FMDL models in models.zal (riders,
bikes and props) and motion in motgame.zal.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path

GAME_IDS = {"a3c634315c086811": "BMX XXX (USA)"}
DISC_ID = "GB3E51"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- little-endian IFF / ZAL
def iff_chunks(data: bytes, off: int = 0, depth: int = 0) -> list[dict]:
    """Walk IFF ``<tag> <u32 le size>`` chunks from `off`. Returns [{tag, size, off, type}]."""
    out, o = [], off
    while o + 8 <= len(data):
        tag = data[o:o + 4].decode("latin-1")
        if not all(32 <= ord(c) < 127 for c in tag):
            break
        size = struct.unpack_from("<I", data, o + 4)[0]
        if size > len(data) - o - 8:
            break
        ftype = data[o + 8:o + 12].decode("latin-1") if size >= 4 else ""
        out.append({"tag": tag, "size": size, "off": o, "type": ftype})
        o += 8 + size
    return out


def zal_index(data: bytes) -> list[dict]:
    """Parse a ZAL directory -> one dict per entry {name, grid, flag, length, offset, type}."""
    if len(data) < 8 or data[:4] != b"ZDIR":
        raise ValueError("not a ZAL archive")
    dsize = struct.unpack_from("<I", data, 4)[0]
    end = 8 + dsize
    if end > len(data):
        raise ValueError("truncated ZAL directory")
    o = 8
    count = grid = dlen = ofst = names = None
    while o < end:
        if o + 8 > end:
            raise ValueError("truncated ZAL directory chunk")
        tag = data[o:o + 4].decode("latin-1")
        size = struct.unpack_from("<I", data, o + 4)[0]
        if o + 8 + size > end:
            raise ValueError("ZAL chunk exceeds directory")
        if tag in ("GRID", "DLEN", "OFST") and size % 4:
            raise ValueError("unaligned ZAL table")
        if tag == "DIDF" and size < 4:
            raise ValueError("truncated ZAL count")
        blob = data[o + 8:o + 8 + size]
        if tag == "DIDF":
            count = struct.unpack_from("<I", blob, 0)[0]
        elif tag == "GRID":
            grid = list(struct.unpack_from(f"<{size // 4}I", blob, 0))
        elif tag == "DLEN":
            dlen = list(struct.unpack_from(f"<{size // 4}I", blob, 0))
        elif tag == "OFST":
            ofst = list(struct.unpack_from(f"<{size // 4}I", blob, 0))
        elif tag == "NAME":
            names = [x.decode("latin-1") for x in blob.split(b"\0") if x]
        o += 8 + size
    if count is None or any(table is None or len(table) != count for table in (grid, dlen, ofst)):
        raise ValueError("missing or inconsistent ZAL directory tables")
    out = []
    for i in range(len(ofst)):
        eoff = ofst[i]
        elen = dlen[i] & 0x0FFFFFFF
        flag = dlen[i] >> 28
        if eoff < end or eoff + elen > len(data):
            raise ValueError("ZAL entry outside payload")
        etag = data[eoff:eoff + 4].decode("latin-1") if eoff + 4 <= len(data) else "?"
        etype = data[eoff + 8:eoff + 12].decode("latin-1") if eoff + 12 <= len(data) else "?"
        out.append({"name": names[i] if names and i < len(names) else "",
                    "grid": grid[i] if grid else 0, "flag": flag, "length": elen,
                    "offset": eoff, "tag": etag, "type": etype})
    return out


def model_summary(data: bytes) -> dict:
    """Summarize one FMDL model: texture count, geometry chunk count/size, instance count."""
    chunks = iff_chunks(data)
    if not chunks or chunks[0]["tag"] != "FMDL":
        return {"tag": chunks[0]["tag"] if chunks else "?", "type": chunks[0]["type"] if chunks else ""}
    # MODL sub-chunks sit inside FMDL's payload, and the real payloads sit inside MODL
    inner = iff_chunks(data, chunks[0]["off"] + 8)
    sub = inner
    if inner and inner[0]["tag"] == "MODL":
        sub = iff_chunks(data, inner[0]["off"] + 8)
    tc = sum(1 for c in sub if c["tag"] == "TXRC")
    tg = [c for c in sub if c["tag"] == "TGEO"]
    ti = [c for c in sub if c["tag"] == "TGIN"]
    return {"tag": "FMDL", "type": "MODL", "texture_banks": tc,
            "geometry_chunks": len(tg), "geometry_bytes": sum(c["size"] for c in tg),
            "instance_chunks": len(ti)}


# ---------------------------------------------------------------- inventory
def inventory(iso: Path, source: Path | None = None, source_sha256: str | None = None) -> dict:
    from .gcdisc import GCDisc

    disc = GCDisc(iso)
    if disc.game_id != DISC_ID:
        raise ValueError(f"{iso}: disc id {disc.game_id}, expected {DISC_ID}")
    head = disc._r(0, 0x440)
    region = struct.unpack(">I", disc._r(0x458, 4))[0]
    dol = disc.dol()
    entry = struct.unpack_from(">I", dol, 0xE0)[0]

    by_ext: Counter = Counter()
    zal_files: list[dict] = []
    level_files: list[dict] = []
    for name in sorted(disc.files):
        _, size = disc.files[name]
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        by_ext[ext] += 1
        if ext == "zal":
            raw = disc.read(name)
            try:
                entries = zal_index(raw)
                rows = []
                for e in entries:
                    row = {k: e[k] for k in ("name", "grid", "flag", "length", "tag", "type")}
                    if e["tag"] == "FMDL":
                        blob = raw[e["offset"]:e["offset"] + e["length"]]
                        row.update(model_summary(blob))
                    rows.append(row)
            except ValueError as err:
                rows = [{"error": str(err)}]
            zal_files.append({"path": name, "size": size, "sha256": _sha(raw), "entries": len(rows),
                              "list": rows})
        elif ext in ("dat", "geo", "ins", "txr", "zit"):
            level_files.append({"path": name, "size": size})

    return {
        "game_id": next(iter(GAME_IDS)), "title": GAME_IDS[next(iter(GAME_IDS))],
        "platform": "gamecube", "engine": "z-axis zal/iff (sysdolphin HSD runtime)",
        "source": str(source) if source else None, "source_sha256": source_sha256,
        "image": {"path": str(iso), "size": iso.stat().st_size, "disc_id": disc.game_id,
                  "title": disc.title, "disc_number": head[6], "version": head[7],
                  "region_bi2": region, "apploader_date": disc._r(0x2440, 10).decode("ascii", "replace")},
        "main_dol": {"name": "default.dol", "size": len(dol), "sha256": _sha(dol),
                     "entry": f"{entry:#x}"},
        "fst_files": len(disc.files),
        "extensions": dict(by_ext.most_common()),
        "fst_dirs": dict(Counter(n.split("/")[0] if "/" in n else "(root)" for n in disc.files)),
        "zal_archives": zal_files,
        "level_assets": level_files,
    }


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("iso", type=Path)
    ap.add_argument("--source", type=Path)
    ap.add_argument("--source-sha256")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    m = inventory(a.iso, a.source, a.source_sha256)
    text = json.dumps(m, indent=1)
    if a.out:
        a.out.write_text(text)
    print(json.dumps({k: m[k] for k in ("image", "main_dol", "fst_files", "extensions")}, indent=1))
    for z in m["zal_archives"]:
        kinds = Counter(e.get("tag", "?") for e in z["list"])
        print(f"  {z['path']}: {z['entries']} entries {dict(kinds)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
