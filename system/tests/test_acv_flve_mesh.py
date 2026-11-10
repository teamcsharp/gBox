import os

import pytest

from gbox import acv_bnd3 as B
from gbox import acv_dcx as D
from gbox import acv_flve_mesh as M
from gbox import acv_inventory as acv

ISO_PATH = os.environ.get(
    "ACV_ISO",
    "/mnt/gbox/hyperspin/Arcade/collections/Microsoft XBOX 360/roms/Armored Core V.iso")


def test_strip_to_tris_restart_and_degenerate():
    assert M.strip_to_tris([0, 1, 2, 3, 0xFFFF, 4, 5, 6, 6], 0xFFFF) == [(0, 1, 2), (1, 3, 2), (4, 5, 6)]


def test_obj_format():
    m = {"meshes": [{"vertices": [(0, 0, 0), (1, 0, 0), (0, 1, 0)], "triangles": [(0, 1, 2)]}]}
    o = M.to_obj(m)
    assert o.count("\nv ") == 3 and "f 1 2 3" in o


@pytest.mark.skipif(not os.path.exists(ISO_PATH), reason="owned ISO absent")
def test_owned_iso_flve_mesh_sample():
    with open(ISO_PATH, "rb") as h:
        def rd(lba, n):
            h.seek(lba * 2048)
            return h.read(n)
        r, s = acv.xiso_root(rd)
        bp = {e["path"]: e for e in acv.parse_xiso_directory(rd, r, s)}
        b, d = bp["bind/dvdbnd5.bhd"], bp["bind/dvdbnd.bdt"]
        recs = acv.parse_bhd5_buckets(rd(b["lba"], b["size"]), d["size"])
        ok = tight = 0
        for x in sorted(recs, key=lambda x: x["offset"])[::40]:
            if x["size"] > 2 << 20:
                continue
            h.seek(d["lba"] * 2048 + x["offset"])
            raw = h.read(x["size"])
            if raw[:4] == b"DCX\0":
                raw = D.decompress_dcx(raw)
            if raw[:4] != b"BND3":
                continue
            try:
                t = B.parse_bnd3(raw)
            except ValueError:
                continue
            for en in t["entries"]:
                p = B.read_entry(raw, en)
                if p[:4] != b"FLVE":
                    continue
                try:
                    mdl = M.parse_flve_mesh(p)
                except ValueError:
                    continue
                hd = mdl["header"]
                nt = sum(len(m["triangles"]) for m in mdl["meshes"])
                ok += 1
                bb0, bb1 = hd["bbox_min"], hd["bbox_max"]
                vs = [v for m in mdl["meshes"] for v in m["vertices"]]
                if nt == hd["face_count"] and all(
                        bb0[i] - 1e-3 <= v[i] <= bb1[i] + 1e-3 for v in vs for i in range(3)):
                    tight += 1
        assert ok >= 20 and tight >= 5
