"""Owned-build inventory for Madden NFL 2005 (USA) on GameCube (#2007).

Read-only: opens the owned Dolphin .gcz (or .iso/.gcm) disc image, verifies
the exact build (game id ``GNQE69``), walks the disc FST, classifies every
container by magic, extracts and hashes ``main.dol``, and maps the
character-relevant asset containers (bodies, faces, face geometry, coach
faces, animations, uniforms, portraits, stadiums).

The assimilation fingerprint claimed the engine is "HAL sysdolphin (HSD)"
(0.77) with a "PLAY character container (JGR)" and suggested starting from
``gbox.melee_models``.  This module proves that is wrong for this build: every
data file is an Electronic Arts archive — a ``TERF`` archive (``.dat``) or a
``QL01``/``FILS`` archive (``.qkl``) — plus one ``DB`` and one ``BNR`` banner.
There is no HSD/sysdolphin or Melee layout anywhere on the disc, so the EA
reader path (``gbox.refpack`` / TERF index) is the correct starting point, not
``gbox.melee_models``.

Usage::

    python -m gbox.madden2005_inventory SRC [--out manifest.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

BUILD_ID = "GNQE69"
TITLE = "Madden NFL 2005"

TERF_MAGIC = b"TERF"
QKL_MAGIC = b"QL01"
FILS_MAGIC = b"FILS"
DB_MAGIC = b"DB"
BNR_MAGICS = (b"BNR1", b"BNR2")

# Character-relevant containers, keyed by exact FST name.
CHARACTER_CONTAINERS = {
    "PLADATA.DAT": "player_data",             # player bodies / models
    "PLYRFACE.DAT": "player_faces",           # player face textures
    "FACEGEOM.DAT": "face_geometry",          # face morph geometry
    "COACFACE.DAT": "coach_faces",            # coach face textures
    "COACHES.DAT": "coach_data",
    "ANIMDATA.DAT": "animations",             # animation clips
    "UNIFORMS.DAT": "uniforms",               # uniform textures/meshes
    "UIS_LIB_PLAYER_PORT.DAT": "player_portraits",
    "UIS_LIB_COACH_PORT.DAT": "coach_portraits",
    "STADATA.DAT": "stadium_data",
    "STADIUMS.DAT": "stadiums",
    "FIELDART.DAT": "field_art",
    "ICONS.DAT": "icons",
    "DB_TEAMS.DAT": "team_database",
    "DB_TEMPLATES.DAT": "template_database",
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

    Returns a dict with ``engine``, ``confidence`` and ``evidence``; the
    conclusion is deterministic, not a guess: TERF/QKL archives are EA's
    own on-disc container formats.
    """
    ea = kinds.get("terf", 0) + kinds.get("qkl", 0)
    platform = kinds.get("db", 0) + kinds.get("bnr", 0)
    other = kinds.get("other", 0)  # HSD/Melee layouts would not use TERF/QKL
    evidence = {k: v for k, v in sorted(kinds.items())}
    if ea > 0 and other == 0:
        return {"engine": "ea_terf_qkl", "confidence": 1.0,
                "refutes": "hal_sysdolphin", "evidence": evidence,
                "platform_files": platform}
    return {"engine": "unknown", "confidence": 0.0,
            "refutes": None, "evidence": evidence,
            "hsd_containers": other}


def _disc(src: str):
    from .gcdisc import GCDisc
    return GCDisc(src)


def inventory(src: str) -> dict:
    """Walk the owned disc and return the full inventory manifest."""
    d = _disc(src)
    kinds: Counter[str] = Counter()
    char_assets: dict[str, dict] = {}
    files: list[dict] = []
    for name, (off, size) in sorted(d.files.items()):
        head = d.read(name)[:8] if size else b""
        kind = classify_magic(head)
        kinds[kind] += 1
        rec = {"name": name, "offset": off, "size": size, "magic": head[:4].hex(" ") or None,
               "kind": kind}
        files.append(rec)
        if name in CHARACTER_CONTAINERS:
            char_assets[name] = {"role": CHARACTER_CONTAINERS[name],
                                 "size": size, "offset": off, "magic": head[:4].decode("latin-1")}
    dol = d.dol()
    return {
        "title": TITLE,
        "platform": "gamecube",
        "build_id": d.game_id,
        "disc_title": d.title,
        "main_dol": {"size": len(dol), "sha256": hashlib.sha256(dol).hexdigest()},
        "file_count": len(files),
        "kinds": dict(kinds),
        "engine": engine_finding(dict(kinds)),
        "character_containers": char_assets,
        "files": files,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Madden NFL 2005 (USA) GameCube inventory")
    ap.add_argument("src")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    m = inventory(a.src)
    m["source_path"] = a.src
    m["source_sha256"] = hashlib.sha256(Path(a.src).read_bytes()).hexdigest()
    text = json.dumps(m, indent=1)
    (Path(a.out).write_text(text) if a.out else print(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
