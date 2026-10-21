"""Killer7 (GameCube, GK7E08 / GK7E08 Disc 2) owned-source inventory.

The owned build is a Dolphin ``.gcz`` disc image.  Its model data is HAL
sysdolphin (HSD): every ``3Ddata/Model/Chara/<CODE>/<CODE>_M##.dat`` parses as a
valid HSD archive (0x20 header: file size, data size, #relocations, #roots,
#references; a relocation table, a root table and a string table).  Scene roots
are ``scene_data``, ``scene_camera``, ``castsShadows``, ``SdExpInfo`` plus named
toon-ramp surface shaders (Killer7's cel look).  This module is the step-one
"assimilation fingerprint -> verified inventory" deliverable: it enumerates the
disc, groups the character roster and proves the HSD claim against real files.

It reuses the shared readers (``gbox.gcdisc.GCDisc``, ``gbox.gcz.GCZ`` and the
HSD header/root parser in ``gbox.melee_models``) — it does NOT reimplement a
model decoder, and it never writes to the source image.
"""
from __future__ import annotations

import os
import struct
from collections import Counter, defaultdict

# Disc 2 of Killer7 (USA), the ticket's owned source.
GAME_ID = "GK7E08"
TITLE = "Killer7 Disk2"

# Character model root on the disc.
CHARA_ROOT = "3Ddata/Model/Chara"


def is_hsd(data: bytes) -> bool:
    """True when `data` is a plausible HSD archive: a 0x20 header whose first
    u32 equals the file length and whose data size is non-zero and fits inside
    the file."""
    if len(data) < 0x20:
        return False
    fs, ds, nr, nroot, nref = struct.unpack_from(">5I", data, 0)
    return fs == len(data) and 0 < ds < fs and 0x20 + ds + 4 * nr <= fs


def hsd_roots(data: bytes) -> list[str]:
    """Root-object names of an HSD archive (empty list if it does not parse)."""
    if not is_hsd(data):
        return []
    from .melee_models import HSD
    try:
        return sorted(HSD(data).roots)
    except Exception:
        return []


def classify_variant(code: str, stem: str) -> str:
    """Map a Chara file stem to its variant kind: ``M`` (main model),
    ``B`` (B), ``R`` (R) or ``other``.

    Stems are matched case-insensitively against the directory code because the
    disc mixes cases (``Cyo`` dir -> ``CYO_M00.dat``, ``Gal`` -> ``GAL_M00.dat``).
    """
    up = stem.upper()
    cu = code.upper()
    if up == cu or (up.startswith(cu + "_M") and up[len(cu) + 2:len(cu) + 3].isdigit()):
        return "M"
    if up.startswith(cu + "_B"):
        return "B"
    if up.startswith(cu + "_R"):
        return "R"
    return "other"


def chara_roster(files: dict[str, tuple[int, int]] | list[str]) -> dict[str, dict]:
    """Group ``3Ddata/Model/Chara/<CODE>/*`` into a per-character roster.

    `files` is either the GCDisc ``.files`` mapping {path: (offset, size)} or a
    list of paths.  Returns {CODE: {variants: {M/B/R/other: n}, total: n,
    model_variants: sorted set of M indices}}.
    """
    paths = list(files.keys()) if isinstance(files, dict) else list(files)
    codes: dict[str, dict] = {}
    for p in paths:
        parts = p.split("/")
        if len(parts) < 5 or parts[0:3] != ["3Ddata", "Model", "Chara"]:
            continue
        code, fn = parts[3], parts[4]
        stem = fn.rsplit(".", 1)[0]
        e = codes.setdefault(code, {"variants": Counter(), "total": 0,
                                    "model_variants": set()})
        kind = classify_variant(code, stem)
        e["variants"][kind] += 1
        e["total"] += 1
        if kind == "M":
            m = re_match_model_index(stem, code)
            if m is not None:
                e["model_variants"].add(m)
    for e in codes.values():
        e["model_variants"] = sorted(e["model_variants"])
        e["variants"] = dict(e["variants"])
    return codes


def re_match_model_index(stem: str, code: str) -> int | None:
    """``DAN_M00`` -> 0, ``CYO_M04`` -> 4; None when the stem is not ``<CODE>_M<digits>``."""
    up = stem.upper()
    cu = code.upper()
    pref = cu + "_M"
    if not up.startswith(pref):
        return None
    tail = up[len(pref):]
    if not tail.isdigit():
        return None
    return int(tail)


def _ext_hist(files: dict[str, tuple[int, int]]) -> Counter:
    c = Counter()
    for p in files:
        c[os.path.splitext(p)[1].lower() or "(none)"] += 1
    return c


def inventory(src: str, verify_hsd_sample: bool = True) -> dict:
    """Open the owned ``.gcz`` read-only and return the full inventory.

    ``verify_hsd_sample`` reads and HSD-parses the first character model to prove
    the engine claim (small extra disc I/O).
    """
    from .gcdisc import GCDisc
    d = GCDisc(src)
    files = d.files
    roster = chara_roster(files)
    hsd_proof = None
    if verify_hsd_sample and roster:
        sample = None
        for code in sorted(roster):
            p = f"{CHARA_ROOT}/{code}/{code}_M00.dat"
            if p in files:
                sample = p
                break
        if sample is not None:
            hsd_proof = {"file": sample, "roots": hsd_roots(d.read(sample))}
    return {
        "source": src,
        "game_id": d.game_id,
        "title": d.title,
        "num_files": len(files),
        "extensions": dict(_ext_hist(files)),
        "top_dirs": {p.split("/")[0] for p in files},
        "chara_codes": len(roster),
        "chara_roster": roster,
        "hsd_proof": hsd_proof,
    }


def summary(inv: dict) -> str:
    """One-paragraph human summary of an inventory dict."""
    n = inv["num_files"]
    cc = inv["chara_codes"]
    tm = sum(r["variants"].get("M", 0) for r in inv["chara_roster"].values())
    lines = [
        f"{inv['title']} ({inv['game_id']}): {n} files, {cc} character codes, "
        f"{tm} main-model files (M##).",
        f"HSD engine proof: {inv.get('hsd_proof')}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("src", help="Killer7 Disc 2 .gcz (read-only)")
    ap.add_argument("--no-verify", action="store_true")
    a = ap.parse_args()
    print(summary(inventory(a.src, verify_hsd_sample=not a.no_verify)))
