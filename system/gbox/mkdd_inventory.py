"""Mario Kart: Double Dash!! (GameCube, USA GM4E01) disc inventory.

Resolves the owned build, verifies the platform label against the disc header, hashes the main
executable, and enumerates the character model / texture / animation inventory.  Read-only on the
source image; the source_sha256 is recorded, never recomputed.

The top-level container is the GameCube FST (gbox.gcdisc).  Almost every payload is a Nintendo RARC
archive (79 .arc files, 78 raw + ``AudioRes/Seqs/JaiSeqs.arc`` which is Yaz0-wrapped).  Inside the
RARC members are the J3D v2 asset formats, big-endian on GameCube:

  - ``*.bmd``  binary model  (magic ``J3D2bmd3``); the playable character bodies are the
               ``<char>/driver.bmd`` (+ ``driver_200.bmd`` low-detail) files under ``MRAM.arc``'s
               ``driver/`` directory, and the karts are ``{char}_k_{body,arm,tire_l,tire_r,shock}.bmd``.
  - ``*.bti``  texture        (header: u8 format, u8 alpha, u16 w, u16 h, ...)
  - ``*.bca``  joint/character animation; ``*.bck`` bone animation; ``*.btk`` texture-SRT animation;
               ``*.btp`` texture-pattern (face/expression) animation; ``*.brk`` register animation;
               ``*.bpk`` palette animation; ``*.blo`` layout.
  - ``*.ikp``  IK parameter   (one per driver); ``*.set`` kart/character setup (one per driver);
               ``*.snp``/``*.blk``/``*.bls`` particle/shadow data; ``*.bco``/``*.bol`` course data.

The 20-character roster is keyed by the 4-char directory codes under ``MRAM.arc/driver/`` (see
``CHARACTERS``).  A 21st ``extra``/``u_extra_car`` slot exists but is not a playable character.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from .gcdisc import GCDisc

# driver directory code -> display name.  "dkjr" is Diddy Kong (his internal DK-Jr. name);
# "bosspakkun"/"kingteresa" are the boss characters Petey Piranha / King Boo.
CHARACTERS = {
    "mario": "Mario", "luigi": "Luigi", "peach": "Peach", "daisy": "Daisy",
    "yoshi": "Yoshi", "catherine": "Birdo", "kinopio": "Toad", "kinopico": "Toadette",
    "nokonoko": "Koopa Troopa", "patapata": "Paratroopa", "dk": "Donkey Kong",
    "dkjr": "Diddy Kong", "wario": "Wario", "waluigi": "Waluigi", "koopa": "Bowser",
    "koopajr": "Bowser Jr.", "babymario": "Baby Mario", "babyluigi": "Baby Luigi",
    "bosspakkun": "Petey Piranha", "kingteresa": "King Boo",
}

# MRAM.arc "kart" directory codes -> driver directory code (kart part naming differs from
# the driver directory naming for a few characters).
KART_TO_DRIVER = {
    "baby": "babymario", "bblui": "babyluigi", "noko": "nokonoko", "pata": "patapata",
    "diddy": "dkjr", "jr": "koopajr", "kpio": "kinopio", "kpico": "kinopico",
    "mario": "mario", "luigi": "luigi", "peach": "peach", "daisy": "daisy",
    "yoshi": "yoshi", "cathy": "catherine", "walui": "waluigi", "wario": "wario",
    "dk": "dk", "koopa": "koopa", "pakku": "bosspakkun", "teres": "kingteresa",
}

MODEL_MAGIC = b"J3D2bmd3"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- RARC

class RARCError(Exception):
    pass


def rarc_nodes(b: bytes) -> list[dict]:
    """The RARC node table (directory nodes in pre-order; files live in the file table)."""
    if b[:4] != b"RARC":
        raise RARCError(f"not a RARC archive (magic {b[:4]!r})")
    nnodes, node_off, nfiles, file_off, str_size, str_off = struct.unpack_from(">6I", b, 0x20)
    strings = b[0x20 + str_off:0x20 + str_off + str_size]
    out = []
    for i in range(nnodes):
        o = 0x20 + node_off + 16 * i
        typ = b[o:o + 4].decode("latin-1")
        name_off, _hash, nchild, first = struct.unpack_from(">IHHI", b, o + 4)
        end = strings.find(b"\0", name_off)
        out.append({"type": typ, "name": strings[name_off:end].decode("latin-1"),
                    "nchild": nchild, "first": first})
    return out


def rarc_files(b: bytes) -> list[dict]:
    """The RARC file-entry table (flat, in pre-order): {name, type, offset, size}."""
    if b[:4] != b"RARC":
        raise RARCError(f"not a RARC archive (magic {b[:4]!r})")
    _nnodes, _no, nfiles, file_off, str_size, str_off = struct.unpack_from(">6I", b, 0x20)
    data_off = struct.unpack_from(">I", b, 0x0C)[0]
    strings = b[0x20 + str_off:0x20 + str_off + str_size]
    base = 0x20 + data_off
    out = []
    for i in range(nfiles):
        o = 0x20 + file_off + 20 * i
        _fid, _hash, ftype = struct.unpack_from(">HHB", b, o)
        name_off = struct.unpack(">I", b"\0" + b[o + 5:o + 8])[0]
        end = strings.find(b"\0", name_off)
        doff, dsize, _reserved = struct.unpack_from(">III", b, o + 8)
        out.append({"name": strings[name_off:end].decode("latin-1"), "type": ftype,
                    "offset": base + doff, "size": dsize})
    return out


def rarc_walk(b: bytes) -> list[tuple[str, int, int]]:
    """[(full path, offset into the archive, size)] for every real file in a RARC.

    Directories are rebuilt from the node tree: node i's child directories are the dir-marker
    entries inside its file-entry range [first, first+nchild), and each child's own files follow
    contiguously in pre-order.  ``.``/``..`` markers are skipped.
    """
    nodes = rarc_nodes(b)
    files = rarc_files(b)
    # subtree size of node i (pre-order: children sit immediately after the parent)
    size_cache: dict[int, int] = {}

    def subtree(i: int) -> int:
        if i in size_cache:
            return size_cache[i]
        n = nodes[i]
        kids = 0
        for j in range(n["first"], n["first"] + n["nchild"]):
            fe = files[j]
            if fe["type"] & 2 and fe["name"] not in (".", ".."):
                kids += 1
        total = 1
        child = i + 1
        for _ in range(kids):
            total += subtree(child)
            child += subtree(child)
        size_cache[i] = total
        return total

    out: list[tuple[str, int, int]] = []

    def walk(i: int, path: str) -> None:
        n = nodes[i]
        child = i + 1
        for j in range(n["first"], n["first"] + n["nchild"]):
            fe = files[j]
            if fe["type"] & 2:
                if fe["name"] in (".", ".."):
                    continue
                walk(child, path + fe["name"] + "/")
                child += subtree(child)
            elif fe["type"] & 1:
                out.append((path + fe["name"], fe["offset"], fe["size"]))

    walk(0, "")
    return out


# ---------------------------------------------------------------- disc inventory

def _dol_info(dol: bytes) -> dict:
    sizes = struct.unpack_from(">18I", dol, 0x90)
    text_off, text_addr = struct.unpack_from(">7I", dol, 0), struct.unpack_from(">7I", dol, 0x48)
    data_off, data_addr = struct.unpack_from(">11I", dol, 0x1C), struct.unpack_from(">11I", dol, 0x64)
    bss_addr, bss_size, entry = struct.unpack_from(">3I", dol, 0xD8)
    sections = []
    for offs, addrs, n in ((text_off, text_addr, 7), (data_off, data_addr, 11)):
        for i in range(n):
            if sizes[i]:
                sections.append({"kind": "text" if n == 7 else "data",
                                 "offset": offs[i], "address": addrs[i], "size": sizes[i]})
    return {"size": len(dol), "entry": entry, "bss": {"address": bss_addr, "size": bss_size},
            "sections": sections}


def _read_head(path) -> bytes:
    """First 0x100 bytes of a GameCube disc, transparently through the GCZ layer when compressed."""
    p = str(path)
    if p.lower().endswith(".gcz"):
        from .gcz import GCZ
        with GCZ(p) as g:
            return g.read(0, 0x100)
    with open(p, "rb") as f:
        return f.read(0x100)


def inventory(path, source_sha256: str | None = None, source_path: str | None = None) -> dict:
    """Walk a GameCube disc (ISO/GCM/GCZ) and enumerate the MKDD character/texture/animation set."""
    header = _read_head(path)
    if len(header) < 0x100:
        raise ValueError("not a GameCube disc: file too short")
    game_id = header[:6].decode("ascii", "replace")
    magic = header[0x1C:0x20].hex()
    if game_id[0] not in "GD" or magic != "c2339f3d":
        raise ValueError(f"not a GameCube disc: id={game_id} magic={magic}")
    disc = GCDisc(path)

    dol = disc.dol()
    executables = [{"name": "main.dol", "sha256": _sha(dol), "dol": _dol_info(dol)}]

    # walk every .arc (RARC), decompressing the Yaz0-wrapped one
    rarc_counts: dict[str, int] = {}
    inner: list[dict] = []                       # every RARC member, with its archive
    driver_dirs: dict[str, list[dict]] = {}       # driver dir code -> [model/anim records]
    kart_parts: dict[str, list[dict]] = {}
    for arc_name, (_off, _size) in sorted(disc.files.items()):
        if not arc_name.lower().endswith(".arc"):
            continue
        data = disc.read(arc_name)
        if data[:4] == b"Yaz0":
            from .formats.lz import yaz0_decompress
            data = yaz0_decompress(data)
        if data[:4] != b"RARC":
            rarc_counts["skipped"] = rarc_counts.get("skipped", 0) + 1
            continue
        rarc_counts["parsed"] = rarc_counts.get("parsed", 0) + 1
        for fpath, off, size in rarc_walk(data):
            rec = {"name": fpath, "size": size, "sha256": _sha(data[off:off + size])}
            inner.append({"archive": arc_name, **rec})
            _index_char(rec, driver_dirs, kart_parts)

    # per-character kart parts -> driver
    characters = {}
    for code in sorted(set(list(driver_dirs) + list(kart_parts))):
        characters[code] = {
            "name": CHARACTERS.get(code, code),
            "driver": sorted([r for r in driver_dirs.get(code, []) if r["name"].endswith("driver.bmd")],
                             key=lambda r: r["name"]),
            "animations": sorted([r for r in driver_dirs.get(code, [])
                                  if not r["name"].endswith("driver.bmd")], key=lambda r: r["name"]),
            "kart": sorted(kart_parts.get(code, []), key=lambda r: r["name"]),
        }

    kinds: dict[str, list] = {}
    for rec in inner:
        ext = rec["name"].rsplit(".", 1)[-1].lower() if "." in rec["name"].rsplit("/", 1)[-1] else ""
        kind = {"bmd": "model", "bti": "texture", "bca": "animation", "bck": "animation",
                "btk": "animation", "btp": "animation", "brk": "animation", "bpk": "animation",
                "blo": "layout", "ikp": "rig", "set": "config", "snp": "particle",
                "blk": "shadow", "bls": "shadow", "bco": "course", "bol": "course"}.get(ext, "other")
        kinds.setdefault(kind, []).append(rec)

    totals = {k: len(v) for k, v in sorted(kinds.items())}

    return {
        "game_id": game_id,
        "title": disc.title,
        "platform": "gamecube",
        "region": "USA",
        "source_sha256": source_sha256,
        "source_path": source_path,
        "disc_magic": magic,
        "fst_file_count": len(disc.files),
        "executables": executables,
        "rarc": rarc_counts,
        "rarc_member_count": len(inner),
        "characters": {k: characters[k] for k in sorted(characters)},
        "assets": kinds,
        "totals_by_kind": totals,
        "launch": {"core": "dolphin", "notes": "GC disc boots under Dolphin/RetroArch-dolphin; "
                                                 "agent tests use 2% audio"},
        "notes": [
            "models are J3D v2 BMD (magic 'J3D2bmd3'), big-endian; textures BTI; animations "
            "BCA/BCK/BTK/BTP/BRK/BPK",
            "the playable driver body is <char>/driver.bmd (+ driver_200.bmd low detail) under "
            "MRAM.arc/driver/; kart parts are {char}_k_{body,arm,tire_l,tire_r,shock}.bmd",
            "AudioRes/Seqs/JaiSeqs.arc is Yaz0-wrapped; every other .arc is raw RARC",
        ],
    }


def _index_char(rec: dict, driver_dirs: dict, kart_parts: dict) -> None:
    """Route one RARC member to a driver or kart bucket when it belongs to one."""
    name = rec["name"]
    if "/" not in name:
        return
    if name.startswith("driver/"):
        parts = name.split("/")
        if len(parts) >= 3 and parts[1] in CHARACTERS:
            driver_dirs.setdefault(parts[1], []).append(rec)
        return
    if name.startswith("kart/"):
        # {code}_all/{code}_k_*.bmd ; map the kart code back to the driver code
        base = name.rsplit("/", 1)[-1]
        for kart_code, drv in KART_TO_DRIVER.items():
            if base.startswith(kart_code + "_k_"):
                kart_parts.setdefault(drv, []).append(rec)
                break
        return


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="GameCube ISO/GCM/GCZ")
    ap.add_argument("--source-sha256", default=None)
    ap.add_argument("--source-path", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    m = inventory(args.src, source_sha256=args.source_sha256, source_path=args.source_path)
    Path(args.out).write_text(json.dumps(m, indent=2))
    print(json.dumps({k: v for k, v in m.items() if k != "assets"}, indent=2))


if __name__ == "__main__":
    main()
