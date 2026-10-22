"""Bounded RE6 (Xbox 360, MT Framework) format probe for the analysis stage.

Validates the existing ARC / Mod reader+writer against an owned ISO: pulls one hero model arc,
parses the .mod, checks header/offset consistency, no-op serialize roundtrip, a changed-bone
roundtrip and an ARC rebuild roundtrip. Emits JSON with hashes so the evidence is reproducible.

    python -m gbox.re6_probe "<Resident Evil 6.iso>" [--arc /nativeXenon/arc/X360/uPl00LeonUsa.arc]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys

from gbox import re6
from gbox.re6_models import HEADER, Mod

DEFAULT_ARC = "/nativeXenon/arc/X360/uPl00LeonUsa.arc"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def header_check(data: bytes) -> dict:
    """Decode the raw 0x40 header and check every offset is in-range, ordered and 4-aligned."""
    h = struct.unpack_from(HEADER, data)
    names = ("magic", "version", "nbones", "nprims", "nmats", "nverts", "nindices", "ntris", "vbsize", "ntex",
             "ngroups", "o_bones", "o_groups", "o_mats", "o_meshes", "o_vb", "o_ib", "o_end")
    f = dict(zip(names, h))
    offs = [f[k] for k in ("o_bones", "o_groups", "o_mats", "o_meshes", "o_vb", "o_ib", "o_end")]
    ok = (all(0 < o <= len(data) for o in offs) and offs == sorted(offs)
          and f["o_vb"] + f["vbsize"] <= f["o_ib"] and f["o_ib"] + 2 * f["nindices"] <= len(data)
          and f["ntris"] * 3 == f["nindices"])
    f["magic"] = f["magic"].decode("latin-1")
    f["version"] = hex(f["version"])
    f["offsets_consistent"] = bool(ok)
    return f


def probe_mod(data: bytes) -> dict:
    m = Mod(data)
    hc = header_check(data)
    noop = m.serialize()
    m2 = Mod(noop)
    changed = Mod(data)
    changed.local[4][3][1] += 1.0                         # +1.0 Y on bone 4 (row-vector translation row)
    ch = changed.serialize()
    cm = Mod(ch)
    return {
        "mod_bytes": len(data), "mod_sha256": sha(data), "header": hc,
        "bones": len(m.bones), "prims": len(m.prims), "verts": int(m.nv), "indices": int(m.ni), "tris": int(m.ntri),
        "materials": len(m.mat_hashes),
        "noop_roundtrip": {"bytes": len(noop), "sha256": sha(noop), "byte_identical": noop == data,
                           "reparse_counts_equal": (len(m2.bones), len(m2.prims), int(m2.ni)) ==
                                                   (len(m.bones), len(m.prims), int(m.ni)),
                           "vb_identical": m2.vb == m.vb, "ib_identical": bool((m2.ib == m.ib).all())},
        "changed_bone": {"sha256": sha(ch), "bone": 4, "dy": 1.0,
                         "applied": abs(float(cm.local[4][3][1]) - float(m.local[4][3][1]) - 1.0) < 1e-5,
                         "others_unchanged": bool((cm.local[[i for i in range(len(m.bones)) if i != 4]] ==
                                                   m.local[[i for i in range(len(m.bones)) if i != 4]]).all())},
    }


def probe_arc(arc_bytes: bytes) -> dict:
    arc = re6.Arc(arc_bytes)
    mods = [e for e in arc.entries if e["ext"] == "mod"]
    if not mods:
        raise ValueError("arc has no .mod entry")
    e = mods[0]
    data = arc.get(e)
    out = {"arc_bytes": len(arc_bytes), "arc_sha256": sha(arc_bytes), "arc_version": arc.version,
           "entries": len(arc.entries), "entry_exts": sorted({x["ext"] for x in arc.entries}),
           "mod_entry": e["name"], "mod": probe_mod(data)}
    arc.put(e["name"], "mod", data)                       # recompress same bytes, rebuild, re-read
    rebuilt = arc.build()
    back = re6.Arc(rebuilt)
    out["arc_rebuild"] = {"bytes": len(rebuilt), "sha256": sha(rebuilt), "entries": len(back.entries),
                          "mod_roundtrip_identical": back.get(back.find(e["name"], "mod")) == data}
    return out


def probe_iso(iso: str, arc_path: str = DEFAULT_ARC) -> dict:
    x = re6.XDVD(iso)
    try:
        res = probe_arc(x.read(arc_path))
    finally:
        x.close()
    res["arc_path"] = arc_path
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("iso")
    ap.add_argument("--arc", default=DEFAULT_ARC)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    r = probe_iso(a.iso, a.arc)
    s = json.dumps(r, indent=1)
    if a.out:
        open(a.out, "w").write(s)
    print(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
