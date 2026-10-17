"""Owned-build inventory for GoldenEye - Rogue Agent (USA) (Disc 1) on GameCube.

    python -m gbox.rogue_agent_inventory GCZ [--out manifest.json]

EA EAGL engine (the "Bond" lineage: Agent Under Fire -> Nightfire -> Rogue Agent).
The owned source is a Dolphin ``.gcz`` disc image (game id ``GOYE69``).  The disc's
``/`` filesystem (FST) holds three ELF executables -- ``GE2RDVD.ELF`` is the game,
``LOADRDVD.ELF`` / ``STUBRDVD.ELF`` are the loader shim -- and the data tree:

  * ``DATA/SHARED/UI/...``: 172 ``.big`` files.  Each is an EA RefPack (QFS, magic
    ``0x10FB``) stream that decompresses to a ``BIGF`` archive (see ``parse_bigf``).
  * ``DATA/1/1_NN/...``: 45 ``.viv`` archives (magic ``0xC0FB``), one set per level
    (``comp.viv`` / ``level.viv`` / ``mvd.viv``).  ``level.viv`` carries the geometry
    (``*.msh`` meshes, ``*.gsh`` shader geometry), ``comp.viv`` the per-level character
    databases (``*_C_cN.cdb``) and art (``*_Art_cN.cpt``/``.rtc`` textures),
    ``mvd.viv`` the motion-video data (``*.mvd``).
  * ``DATA/SHARED/MOVIES/`` (``.vp6``), ``DATA/SHARED/LANG/Eng/`` (``.loc``),
    ``DATA/1/1_NN/SOUND/`` (``.abk``/``.ast``/``.bnk``/``.bus``/``.mus``/``.mpf``/
    ``.ubr``) are audio/streaming/movie data.

BIGF layout (measured on every UI archive; offsets/sizes are big-endian, the total
size field is little-endian)::

    "BIGF" u32 total_size(LE) u32 count u32 extra
    count x { u32 offset(BE, absolute) u32 size(BE) cstring name }   # names NOT padded

The ``.viv`` header is ``u16 magic=0xC0FB`` then a per-file directory of null-terminated
names interleaved with 6-byte records.  ``viv_names`` enumerates the member names; the
exact meaning of the 6-byte records (compressed vs uncompressed offset/size) is
analysis-stage work against ``GE2RDVD.ELF``'s VIV loader.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections import Counter
from pathlib import Path

from . import refpack
from .gcdisc import GCDisc

GAME_ID = "a224c4dd390169cb"
SOURCE_SHA256 = "bb739812f55c1c0baf86f7a9a5b86496a677873d92edf849af3688b4f3cc9432"
MAIN_ELF = "GE2RDVD.ELF"

BIGF_MAGIC = b"BIGF"
VIV_MAGIC = b"\xC0\xFB"
# member extensions that name the per-level art / character data (inventory signal)
MODEL_EXT = {"msh", "gsh", "lfc", "mvd", "cpt", "rtc", "cdb", "stf", "gfn"}


def parse_bigf(buf: bytes, base: int = 0) -> tuple[int, list[tuple[str, int, int]]]:
    """(extra, [(name, absolute offset, size)]) for a BIGF archive at buf[base]."""
    if buf[base:base + 4] != BIGF_MAGIC or base + 16 > len(buf):
        raise ValueError(f"no BIGF at {base:#x}")
    total = struct.unpack_from("<I", buf, base + 4)[0]     # little-endian, not used as a bound
    count = struct.unpack_from(">I", buf, base + 8)[0]
    extra = struct.unpack_from(">I", buf, base + 12)[0]
    p, out = base + 16, []
    for _ in range(count):
        if p + 8 > len(buf):
            raise ValueError("BIGF directory truncated")
        off, size = struct.unpack_from(">II", buf, p)
        p += 8
        e = buf.find(b"\0", p)
        if e < 0:
            raise ValueError("BIGF member name unterminated")
        name = buf[p:e].decode("latin-1")
        p = e + 1
        if base + off + size > len(buf):
            raise ValueError(f"BIGF member {name!r} overruns the archive ({off:#x}+{size:#x})")
        out.append((name, base + off, size))
    return extra, out


def _member_blob(buf: bytes, name: str, off: int, size: int) -> dict:
    blob = buf[off:off + size]
    row = {"name": name, "offset": off, "size": size}
    if refpack.is_refpack(blob):
        data, used = refpack.decompress_ex(blob)
        row.update(refpack=True, unpacked=len(data), slack=size - used,
                   sha256=hashlib.sha256(data).hexdigest())
    else:
        row.update(refpack=False, unpacked=size, sha256=hashlib.sha256(blob).hexdigest())
    return row


def viv_header(buf: bytes) -> dict:
    """The 12-byte .viv header: magic, the two unknown u32/u16 fields, and count at +6."""
    if buf[:2] != VIV_MAGIC:
        raise ValueError("not a VIV archive")
    f02, f06, f08 = struct.unpack_from(">IHI", buf, 2)
    return {"magic": "c0fb", "field_02": f02, "count_06": f06, "field_08": f08}


def viv_entries(buf: bytes) -> list[tuple[str, int, int]]:
    """The .viv directory: {cstring name, u32 off, u16 size} records, walked from +12 until the
    name no longer parses as a printable dotted member name.  ``off``/``size`` semantics (compressed
    vs uncompressed) are unresolved -- see the module docstring / analysis stage."""
    out, p = [], 12
    n = len(buf)
    while p < n:
        e = buf.find(b"\0", p)
        if e < 0 or e + 7 > n:
            break
        name = buf[p:e].decode("latin-1", "replace")
        if (not name or "." not in name
                or not all(c.isalnum() or c in "._/-" for c in name)):
            break
        off, size = struct.unpack_from(">IH", buf, e + 1)
        out.append((name, off, size))
        p = e + 7
    return out


def inventory(gcz: Path | str) -> dict:
    d = GCDisc(str(gcz))
    files = d.files
    exts = Counter()
    for p in files:
        exts[p.rsplit(".", 1)[-1].lower() if "." in p else ""] += 1

    elfs = {}
    for elf in ("GE2RDVD.ELF", "LOADRDVD.ELF", "STUBRDVD.ELF"):
        if elf in files:
            data = d.read(elf)
            elfs[elf] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    big_rows = []
    for p in sorted(files):
        if not p.lower().endswith(".big"):
            continue
        raw = d.read(p)
        if refpack.is_refpack(raw):
            try:
                data, _used = refpack.decompress_ex(raw)
            except ValueError as e:
                big_rows.append({"archive": p, "error": f"refpack: {e}"})
                continue
        else:                       # stub.big is a raw BIGF with no RefPack wrapper
            data = raw
        try:
            extra, members = parse_bigf(data)
        except ValueError as e:
            big_rows.append({"archive": p, "error": f"bigf: {e}"})
            continue
        rows = [_member_blob(data, nm, off, sz) for nm, off, sz in members]
        big_rows.append({"archive": p, "header_extra": extra, "members": len(rows),
                         "refpack_wrapped": refpack.is_refpack(raw),
                         "unpacked": len(data), "members_rows": rows})

    viv_rows = []
    for p in sorted(files):
        if not p.lower().endswith(".viv"):
            continue
        raw = d.read(p)
        try:
            hdr = viv_header(raw)
            entries = viv_entries(raw)
        except ValueError as e:
            viv_rows.append({"archive": p, "error": str(e)})
            continue
        viv_rows.append({"archive": p, "size": len(raw), **hdr, "members": len(entries),
                         "member_names": [n for n, _o, _s in entries]})

    n_big = len(big_rows)
    n_viv = len(viv_rows)
    n_refpack_members = sum(1 for r in big_rows for m in r.get("members_rows", []) if m.get("refpack"))
    all_members = [m for r in big_rows for m in r.get("members_rows", [])]
    member_exts = Counter(m["name"].rsplit(".", 1)[-1].lower() if "." in m["name"] else ""
                          for m in all_members)
    viv_member_exts = Counter(n.rsplit(".", 1)[-1].lower() if "." in n else ""
                              for r in viv_rows for n in r.get("member_names", []))

    return {
        "game_id": GAME_ID,
        "title": d.title,
        "disc_game_id": d.game_id,
        "platform": "gamecube",
        "engine": "EA EAGL (BIG/RefPack + VIV)",
        "source": {"path": str(gcz), "sha256": SOURCE_SHA256, "fst_files": len(files)},
        "executables": elfs,
        "launch": {"main_elf": MAIN_ELF, "byte_order": "big-endian (PPC); BIGF total-size field is little-endian"},
        "layout": {
            "fst_ext_counts": dict(sorted(exts.items())),
            "big_archives": n_big, "viv_archives": n_viv,
            "big_are_refpack": all("error" not in r or r["error"].startswith("refpack") for r in big_rows),
        },
        "bigf": {
            "archives": n_big,
            "total_members": len(all_members),
            "refpack_members": n_refpack_members,
            "member_ext_counts": dict(sorted(member_exts.items())),
        },
        "viv": {
            "archives": n_viv,
            "member_ext_counts": dict(sorted(viv_member_exts.items())),
            "archives_rows": viv_rows,
        },
        "open": [
            "decode the .viv 6-byte member records (offset/size semantics) via GE2RDVD.ELF's VIV loader",
            "locate the character model format inside level.viv (*.msh) and comp.viv (*_C_cN.cdb / *_Art_cN.cpt)",
            "map the character roster from the .cdb / .msh members",
        ],
        "big_archives": big_rows,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("gcz")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    m = inventory(a.gcz)
    txt = json.dumps(m, indent=1)
    if a.out:
        Path(a.out).write_text(txt)
    print(f"GOYE69 inventory: {m['layout']['fst_ext_counts']}")
    print(f"big {m['bigf']['archives']} archives / {m['bigf']['total_members']} members "
          f"({m['bigf']['refpack_members']} refpack)")
    print(f"viv {m['viv']['archives']} archives; member exts {m['viv']['member_ext_counts']}")
    print(f"executables: { {k: v['sha256'][:12] for k, v in m['executables'].items()} }")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
