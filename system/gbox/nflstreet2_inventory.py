"""Owned-build inventory for NFL Street 2 (USA) on GameCube (request #2028).

Read-only: opens the owned Dolphin ``.gcz`` disc image, verifies the exact
build (game id ``GN7E69``), walks the disc FST, classifies every container by
magic, extracts and hashes ``main.dol``, maps the character-relevant asset
containers and identifies one concrete native target model asset.

The assimilation fingerprint attached to the ticket claimed the engine is
"HAL sysdolphin (HSD)" (0.75), nearest SoulCalibur (Dreamcast) / Resident
Evil 4 (GameCube), starting from ``gbox.melee_models``.  This module refutes
that at the container level: every data file is an Electronic Arts archive - a
``TERF`` archive (``.dat``) or a ``QL01`` archive (``.qkl``) - plus one ``DB``
and one ``BNR1`` banner, and the native model assets are EA3 (``.ea3``) models
inside ``objmodel.dat``.  The conclusion identifies the outer archive families
and the model container only; the inner mesh format still needs loader
analysis (analysis stage), so this module is a manifest, not a reader.

Usage::

    python3 -m gbox.nflstreet2_inventory SRC [--out manifest.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from collections import Counter
from pathlib import Path

BUILD_ID = "GN7E69"
TITLE = "NFL STREET 2"

TERF_MAGIC = b"TERF"
QKL_MAGIC = b"QL01"
DB_MAGIC = b"DB"
BNR_MAGICS = (b"BNR1", b"BNR2")

TERF_HEADER_SIZE = 0x800
EA3_RE = re.compile(rb"[A-Za-z0-9_][A-Za-z0-9_.\-]{2,}\.ea3")

# Character-relevant containers, keyed by exact FST name.
CHARACTER_CONTAINERS = {
    "plamodel.dat": "player_models",
    "platex.dat": "player_textures",
    "plaface.dat": "player_face_textures",
    "plahair.dat": "player_hair",
    "plarosterhair.dat": "player_roster_hair",
    "plahat.dat": "player_hats",
    "plajewel.dat": "player_jewelry",
    "plaglass.dat": "player_glasses",
    "pladyncl.dat": "player_dynamic_cloth",
    "objmodel.dat": "object_models",
    "objdefs.dat": "object_definitions",
    "animdata.dat": "animations",
    "statmod.dat": "stat_models",
    "envrnmt.dat": "environments",
    "fieldsfx.dat": "field_fx",
    "crowddat.dat": "crowd_data",
    "chatdata.dat": "chat_data",
    "ambstrm.dat": "ambient_streams",
    "ambbank.dat": "ambient_banks",
    "ambsys.dat": "ambient_system",
    "db_teams.dat": "team_database",
    "loaddata.dat": "load_data",
    "tutspch.dat": "tutorial_speech",
    "igdata.dat": "in_game_data",
    "template.dat": "templates",
    "moviedat.dat": "movies",
    "pathfind.dat": "pathfinding",
}


def classify_magic(head: bytes) -> str:
    """Classify a container by its leading magic bytes."""
    if head[:4] == TERF_MAGIC:
        return "terf"
    if head[:4] == QKL_MAGIC:
        return "qkl"
    if head[:2] == DB_MAGIC:
        return "db"
    if head[:4] in BNR_MAGICS:
        return "bnr"
    return "other"


def engine_finding(kinds: dict[str, int]) -> dict:
    """Derive the engine conclusion from the container-magic census.

    Identifies the outer archive families only; it does not prove the inner
    mesh format or exclude a format nested inside an archive.
    """
    ea = kinds.get("terf", 0) + kinds.get("qkl", 0)
    other = kinds.get("other", 0)
    evidence = {k: v for k, v in sorted(kinds.items())}
    if ea > 0 and other == 0:
        return {"engine": "ea_terf_qkl", "confidence": 1.0,
                "refutes": "HAL sysdolphin (HSD) - no HSD/Melee container layout in this build",
                "scope": "outer containers only", "evidence": evidence}
    return {"engine": "unknown", "confidence": 0.0, "refutes": None,
            "evidence": evidence, "unclassified_containers": other}


def terf_header(blob: bytes) -> dict:
    """The 0x800-byte EA ``TERF`` archive header of a ``.dat`` member.

    ``header_size`` is the u32 at 0x04, ``version`` the bytes at 0x08..0x0B
    (02 02 01 06 on this build), ``subchunk`` the magic of the member's own
    directory chunk at 0x800 (``DIR1`` for a plain directory, ``HSH1`` for a
    hashed one) and ``entry_count`` the u16 at 0x0E.
    """
    if blob[:4] != TERF_MAGIC:
        raise ValueError("not a TERF archive: " + repr(blob[:4]))
    return {
        "magic": "TERF",
        "header_size": struct.unpack_from(">I", blob, 0x04)[0],
        "version": list(blob[0x08:0x0C]),
        "subchunk": blob[TERF_HEADER_SIZE:TERF_HEADER_SIZE + 4].decode("latin-1"),
        "subchunk_offset": TERF_HEADER_SIZE,
        "entry_count": struct.unpack_from(">H", blob, 0x0E)[0],
    }


def ea3_models(blob: bytes) -> list[dict]:
    """Native EA3 model assets named inside a ``.dat`` member.

    Returns [{"name", "offset"}] with the offset of the name inside the member.
    """
    return [{"name": m.group().decode("latin-1"), "offset": m.start()}
            for m in EA3_RE.finditer(blob)]


def _disc(src: str):
    from .gcdisc import GCDisc
    return GCDisc(src)


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(src: str) -> dict:
    """Walk the owned disc and return the full inventory manifest."""
    d = _disc(src)
    try:
        if d.game_id != BUILD_ID:
            raise ValueError(f"Expected {BUILD_ID}, got {d.game_id}")
        kinds: Counter[str] = Counter()
        files: list[dict] = []
        for name, (off, size) in sorted(d.files.items()):
            head = d._r(off, min(size, 8)) if size else b""
            kind = classify_magic(head)
            kinds[kind] += 1
            files.append({"name": name, "offset": off, "size": size, "kind": kind,
                          "magic": head[:4].hex(" ") or None})
        dol = d.dol()
        assets: dict[str, dict] = {}
        for name, role in CHARACTER_CONTAINERS.items():
            if name in d.files:
                off, size = d.files[name]
                assets[name] = {"role": role, "offset": off, "size": size}
        target = None
        if "objmodel.dat" in d.files:
            blob = d.read("objmodel.dat")
            models = ea3_models(blob)
            if models:
                base = d.files["objmodel.dat"][0]
                first = models[0]
                target = {
                    "name": first["name"],
                    "member": "objmodel.dat",
                    "format": "ea3",
                    "name_offset": first["offset"],
                    "disc_offset": base + first["offset"],
                    "member_offset": base,
                    "skeleton_chunk_offsets": [m.start() for m in re.finditer(b"SKL1", blob)][:4],
                    "terf": terf_header(blob),
                    "model_count": len(models),
                }
        return {
            "source_path": str(src),
            "source_sha256": sha256_file(src),
            "title": TITLE,
            "platform": "gamecube",
            "build_id": d.game_id,
            "disc_title": d.title,
            "byte_order": "big-endian (PowerPC 750/Gekko, GameCube native)",
            "main_dol": {"size": len(dol), "sha256": hashlib.sha256(dol).hexdigest()},
            "file_count": len(files),
            "kinds": dict(kinds),
            "engine": engine_finding(dict(kinds)),
            "character_containers": assets,
            "native_target_asset": target,
            "files": files,
        }
    finally:
        d.f.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="NFL Street 2 (USA) GameCube inventory")
    ap.add_argument("src")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    m = inventory(a.src)
    m["source_path"] = a.src
    text = json.dumps(m, indent=1)
    if a.out:
        Path(a.out).write_text(text)
        print("wrote", a.out)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
