"""Bounded loader probe for Twin Snakes disc 1: proves the loader addresses pinned in docs/twin_snakes.md lie inside
the linked shared/mgso.rel image (not main.dol) and shows the loader-registration table (ext letter -> loader).

Usage: python3 -m gbox.ts_loader_probe <disc.iso>
"""
from __future__ import annotations

import hashlib
import struct
import sys

from . import gcdisc

# claimed in docs/twin_snakes.md
CLAIMED = {"kms_loader": 0x806B66B4, "tri_loader": 0x806AE21C, "tex_lookup": 0x806AE880, "resource_key": 0x806C0470,
           "loader_registration": 0x806C0524}


def locate(secs, addr):
    """-> (section index, offset in section, executable) or None."""
    for i, s in enumerate(secs):
        if s and s[0] <= addr < s[0] + s[1]:
            return i, addr - s[0], s[2]
    return None


def probe(iso_path) -> dict:
    d = gcdisc.GCDisc(iso_path)
    rel = d.read("shared/mgso.rel")
    secs = gcdisc.rel_sections(rel)
    img = gcdisc.rel_link(rel)
    base = gcdisc.REL_BASE
    out = {"rel_sha256": hashlib.sha256(rel).hexdigest(), "rel_size": len(rel),
           "sections": [None if not s else {"i": i, "addr": hex(s[0]), "size": s[1], "exec": s[2]}
                        for i, s in enumerate(secs)], "claimed": {}}
    for name, a in CLAIMED.items():
        loc = locate(secs, a)
        e = {"addr": hex(a), "section": loc[0] if loc else None, "exec": loc[2] if loc else None,
             "in_rel_image": bool(loc) and a - base < len(img) and secs[loc[0]][0] >= base}
        if loc and e["in_rel_image"]:
            e["words"] = [f"{struct.unpack_from('>I', img, a - base + 4 * k)[0]:08x}" for k in range(4)]
        out["claimed"][name] = e
    # registration table: pointers into the executable section near 0x806c0524 (hypothesis: ext letter -> loader fn)
    ptrs = {}
    lo, hi = base, base + len(img)
    for off in range(0x806C0524 - base, 0x806C0524 - base + 0x100, 4):
        v = struct.unpack_from(">I", img, off)[0]
        for name, a in CLAIMED.items():
            if v == a:
                ptrs[name] = hex(base + off)
    out["pointer_refs_to_claimed_near_registration"] = ptrs
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(probe(sys.argv[1]), indent=1))
