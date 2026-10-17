"""Dragon Ball Z: Budokai 2 (GameCube, GZ3E70, Dimps) -- owned-disc inventory for character work.

Catalog 8c47aa45fca5aed7 is a Dolphin GCZ on the HyperSpin GameCube mount.  The engine fingerprint
("CRI Middleware AFS/ADX/CPK, 0.97") is WRONG about the containers: this disc holds **no AFS or CPK
archive**.  The audio is CRI ADX1 (`.adx` + `.ack`) plus CRI ADX2 `.acb` banks; movies are CRI
Sofdec (`.sfd`).  Every character/stage/effect asset is a Dimps `#XXX`-magic chunk:

  #CCM  character material/part table   (bcgok.ccm 5.2 KB, u32 count = 77 parts)
  #CSK  character model + skeleton      (bcgok.csk 155 KB: the geometry lives here)
  #ACT  animation / action clips        (bcgok.act 344 KB; per-costume b00/b10/b20/s00..s23)
  #CFC  face/expression config          (us/bs/fix/<code>/<code>.cfc, 176 B)
  #CAD  animation data (stages)         (bg/<stage>/<stage>.cad)
  #CAS / #CDD  stage data               (bg/<stage>/)
  #CDW  world map                       (system/dworld/)
  #SPX  sprite/texture atlas            ("#SPX ver 0.01"; per-character bcgok.spx 61 KB)
  .st/.sd  stage + stage data (no magic)  (bg/<stage>/<stage>.st/.sd)
  .aco/.acm/.acc/.ack/.ace/.acp/.acl/.aei  Dimps action/effect chunks (magic varies)

Every `.ccm`/`.csk`/`.cfc`/`.cad`/`.act`/`.spx` file opens with a 4-byte `#` + 3-letter magic and a
big-endian u32 header (the second u32 is 0x10 for the section-table forms: `#CFC` count 10, `#CAD`
count 4, `#CCM` count 77).  `#CSK` differs: its header is `#CSK` + u32 0x20 + u32 0 + u32 3
(section count) + u32 0x538 + u32 0x20 + u32 0xd4 + u32 0x1f5e0 (data region), then a u32 offset
table at 0x20.  `#SPX` carries an ASCII version string.

Character identity: 41 playable characters live under `cdrom/cmn/bs/ch/bc<code>/`, each with
`.ccm` + `.csk` + `.spx` + `.act` and many `.acb`/`.aco`/`.acm` sidecars.  main.dol holds the roster
table: per-character records strided 0x4908 that embed `/CDROM/CMN/BS/CH/BC<CODE>/...` paths and the
display name (GOKOU, VEGETA, PICCOLO, RADITZ, RECOOM, FREEZA, ANDROID No.16, Mr.SATAN, GREAT SAIYAM,
TRUNKS S, BUU M, VIEDL, GOTENKS, ...) plus the fusion names (VEGITO, GOTAN, BUU-absorptions).

This module resolves the disc identity, hashes the source and main.dol, enumerates the roster, and
validates the `#XXX` chunk header family -- the verified plumbing the analysis/reader stages build on.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from collections import Counter
from pathlib import Path

GAME_IDS = {"8c47aa45fca5aed7": "Dragon Ball Z - Budokai 2 (USA)"}
DISC_ID = "GZ3E70"
CH_DIR = "cdrom/cmn/bs/ch"          # per-character model/texture/animation dirs
NAME_STRIDE = 0x4908                 # main.dol roster record stride
NAME_ANCHOR = b"GOKOU\x00"           # first roster name (Goku is always the first entry)
NAME_OFF = 0x44                      # display-name offset inside a roster record

# The `#XXX` chunk family observed on the disc (magic -> short label).
CHUNK_MAGICS = {
    b"#CCM": "character_material",
    b"#CSK": "character_model",
    b"#ACT": "animation",
    b"#CFC": "face_config",
    b"#CAD": "stage_anim",
    b"#CAS": "stage",
    b"#CDD": "stage",
    b"#CDW": "world_map",
    b"#SPX": "sprite_atlas",
}


def chunk_header(data: bytes) -> dict | None:
    """Parse the shared `#XXX` chunk header.  Returns None when the magic is unknown or truncated.

    The section-table form is ``#XXX + u32 count + u32 0x10 + u32 0`` followed by ``count`` u32
    offsets from 0x10.  `#CSK` and `#SPX` differ (see module docstring) so their first u32 is NOT a
    count; the returned dict keeps the raw words so callers can special-case them.
    """
    if len(data) < 12 or data[0] != 0x23:              # 0x23 = '#'
        return None
    magic = data[:4]
    label = CHUNK_MAGICS.get(magic)
    if label is None and not re.fullmatch(rb"#[A-Z]{3}", magic):
        return None
    word0, word1 = struct.unpack_from(">II", data, 4)
    return {"magic": magic.decode("latin-1"), "label": label or "unknown",
            "word0": word0, "word1": word1, "count": word0 if word1 == 0x10 else None}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def character_codes(disc) -> list[str]:
    """The 41 playable character codes (lowercase, ``bc`` prefix stripped), from their ``.ccm`` files."""
    codes = sorted({n.split("/")[4][2:] for n in disc.files
                    if n.startswith(CH_DIR + "/") and n.endswith(".ccm")})
    if not codes:
        raise ValueError("no character .ccm files under %s" % CH_DIR)
    return codes


def name_table(dol: bytes, codes: list[str]) -> list[dict]:
    """main.dol name table -> [{index, name, code}] in game order.

    Each 0x4908-byte record carries a display name at +0x44 and the character's ``BC<CODE>``
    sidecar paths.  This table is the story-mode (Dragon World) cast -- 13 base fighters plus the
    fusion/absorption forms -- NOT the full 41-slot select roster (that is the ``.ccm`` set).  It is
    anchored on the first name ``GOKOU`` (not on a path marker, which also appears earlier in the
    file-path table).  Fusion/absorption entries have a parenthesised name (``GOTAN (GOKOU)``,
    ``BUU (CELL)``, ...) and are recorded with ``code=None``; base entries get the ``BC`` prefix
    whose lowercase form is in the ``.ccm`` code set.
    """
    name_base = dol.find(NAME_ANCHOR)
    if name_base < 0:
        raise ValueError("roster anchor %r not found in main.dol" % NAME_ANCHOR)
    rec_base = name_base - NAME_OFF
    codeset = set(codes)
    out = []
    for k in range(128):
        rec = rec_base + k * NAME_STRIDE
        if rec + NAME_OFF + 32 > len(dol):
            break
        name = dol[rec + NAME_OFF:rec + NAME_OFF + 32].split(b"\0", 1)[0].decode("latin-1")
        if not name or not all(32 <= ord(c) < 127 for c in name):
            break
        code = None
        for m in re.finditer(rb"/CH/BC([A-Z0-9]{3,4})/", dol[rec:rec + NAME_STRIDE]):
            c = m.group(1).decode().lower()
            if c in codeset:
                code = c
                break
        if "(" in name:                     # fusion/absorption entry, not a base slot
            code = None
        out.append({"index": k, "name": name, "code": code})
    return out


def inventory(gcz, source_sha256: str | None = None) -> dict:
    """Disc identity, roster, chunk-family census and per-character file inventory (no geometry decode)."""
    from .gcdisc import GCDisc

    disc = GCDisc(str(gcz))
    if disc.game_id != DISC_ID:
        raise ValueError(f"{gcz}: disc id {disc.game_id}, expected {DISC_ID}")
    head = disc._r(0, 0x440)
    dol = disc.dol()
    codes = character_codes(disc)
    ros = name_table(dol, codes)

    exts, chunk_kinds = Counter(), Counter()
    chars = {c: {"files": {}} for c in codes}
    for name in sorted(disc.files):
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else "(none)"
        exts[ext] += 1
        if name.startswith(CH_DIR + "/"):
            code = name.split("/")[4][2:]
            if code in chars:
                chars[code]["files"][name.rsplit(".", 1)[-1].lower()] = disc.files[name][1]
        # census the chunk magics of the model/anim/effect containers (cheap 4-byte heads)
        if ext in ("ccm", "csk", "cfc", "cad", "cas", "cdd", "cdw", "act", "spx"):
            off, size = disc.files[name]
            h = chunk_header(disc._r(off, 0x10))
            chunk_kinds[(h["magic"] if h else ext)] += 1

    return {
        "game_id": next(iter(GAME_IDS)), "title": GAME_IDS[next(iter(GAME_IDS))],
        "platform": "gamecube", "source": str(gcz), "source_sha256": source_sha256,
        "image": {"disc_id": disc.game_id, "title": disc.title, "disc_number": head[6],
                  "version": head[7], "region_bi2": struct.unpack(">I", disc._r(0x458, 4))[0],
                  "apploader_date": disc._r(0x2440, 10).decode("ascii", "replace")},
        "main_dol": {"size": len(dol), "sha256": _sha(dol)},
        "fst_files": len(disc.files),
        "extensions": dict(exts),
        "chunk_magics": dict(chunk_kinds),
        "roster": ros,
        "name_table_note": "story-mode (Dragon World) cast: 13 base fighters + fusion/absorption forms; "
                           "the full 41-slot select roster is the `characters` set (.ccm codes)",
        "characters": {c: {"files": chars[c]["files"],
                           "total_bytes": sum(chars[c]["files"].values())} for c in sorted(chars)},
        "containers": "no AFS/CPK: Dimps '#XXX' chunks + CRI ADX1(.adx)/ADX2(.acb) audio + CRI Sofdec(.sfd) movies",
    }


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m gbox.budokai2_inventory", description=__doc__.split("\n")[0])
    ap.add_argument("gcz")
    ap.add_argument("--source-sha256")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    m = inventory(a.gcz, a.source_sha256)
    text = json.dumps(m, indent=1)
    if a.out:
        a.out.write_text(text)
    print(json.dumps({k: m[k] for k in ("image", "main_dol", "fst_files", "chunk_magics",
                                         "containers")}, indent=1))
    for r in m["roster"]:
        print(f"  {r['index']:3d}  {(r.get('code') or '?'):6s}  {r['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
