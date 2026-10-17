"""Stranglehold PS3 writer (#1410): donor retarget + SPU re-encode + appended SkeletalMesh export + chunk rebuild on a
synthetic package (tests/stranglehold_synth.py), PS3TOC.txt sizes, slots and the writer registrations."""
import numpy as np
import pytest

import stranglehold_synth as S
from gbox import stranglehold_inventory as I
from gbox import stranglehold_models as M
from gbox import stranglehold_swap as W


@pytest.fixture(scope="module")
def swapped(tmp_path_factory):
    from gbox.sm64_swap import load_rig
    d = tmp_path_factory.mktemp("sh")
    glb, roles = S.donor_glb(d / "donor.glb")
    raw = S.package()
    out, rep = W.swap_package(raw, load_rig(glb, roles), None, "donor")
    return raw, out, rep, d


def test_appended_export_and_untouched_offsets(swapped):
    raw, out, rep, _d = swapped
    assert len(out) % W.PAD == 0 and rep["readback_triangles"][0] > 0
    s0, s1 = I.read_summary(raw[:4096]), I.read_summary(out[:4096])
    assert len(s0["chunks"]) == len(s1["chunks"]) and s1["chunks"][0]["uoff"] == s0["chunks"][0]["uoff"]
    _a, da = M.load_package(raw)
    _b, db = M.load_package(out)
    pa, pb = M.Package(da), M.Package(db)
    assert pa.names == pb.names and len(pa.exports) == len(pb.exports)
    mi = pa.find("SkeletalMesh")[0]
    ti = pa.find("Texture2D")[0]
    assert pb.exports[mi - 1]["offset"] >= len(da)                    # appended past the old logical end
    assert pb.exports[ti - 1]["offset"] == pa.exports[ti - 1]["offset"]  # everything else stays put
    assert pb.blob(ti) != pa.blob(ti) and len(pb.blob(ti)) == len(pa.blob(ti))


def test_written_mesh_reads_back_as_the_donor(swapped):
    _raw, out, rep, d = swapped
    p = d / "out.xxx"
    p.write_bytes(out)
    r = M.extract_package(p, d / "after.glb")
    assert r["stats"]["triangles"] == rep["readback_triangles"][0] > 0
    assert set(r["roles"]) == set(M.ROLE_BONES) and r["stats"]["bones"] == len(S.BONES)
    _s, data = M.load_package(out)
    pkg = M.Package(data)
    img = M.texture_rgba(pkg, pkg.find("Texture2D")[0])
    assert img[..., 1].mean() > img[..., 0].mean()                    # the donor's green atlas, not the red stock
    mesh = r["mesh"]
    joints = np.concatenate([sg["joints"][:, 0] for sg in mesh["groups"][0]])
    pos = np.concatenate([sg["pos"] for sg in mesh["groups"][0]])
    head = [b["name"] for b in mesh["bones"]].index("Head")
    assert pos[joints == head][:, 1].mean() < pos[:, 1].mean()        # head-weighted vertices are up (-Y in mesh space)


def test_identity_rewrite_keeps_every_export():
    raw = S.package()
    out = W.rewrite_package(raw, {})
    _a, da = M.load_package(raw)
    _b, db = M.load_package(out)
    assert da == db


def test_toc_update():
    toc = ("1703936 0 0 ..\\StrangleholdGame\\CookedPS3\\char_tequila.xxx 0\r\n"
           "1867776 0 0 ..\\StrangleholdGame\\CookedPS3\\char_tequila_MP.xxx 0\r\n")
    new = W.update_toc(toc, {"char_tequila.xxx": 720896})
    assert new.splitlines()[0].startswith("720896 0 0 ") and new.splitlines()[1].startswith("1867776 ")
    assert new.count("\r\n") == 2


def test_slots():
    assert W.is_slot("player") and W.is_slot("enemy:gk_assault_1") and not W.is_slot("driver:axel")
    assert len(W.packages_for("player")) == 10 and "char_tequila_MP" in W.packages_for("tequila")
    assert W.packages_for("tequila:suit") == ["char_tequila_suit", "char_tequila_suit_MP"]
    assert W.packages_for("enemy:gk_assault_1") == ["char_GK_Assault_1_MP"]
    assert len(W.packages_for("enemies")) == 22
    assert W.packages_for("model:damonZakarov_MP") == ["char_damonZakarov_MP"]
    with pytest.raises(ValueError):
        W.packages_for("enemy:nobody")
    slots = W.cast_slots()
    assert slots[0]["slot"] == "player" and any(s["slot"] == "enemies" for s in slots)


def test_registrations():
    from gbox import cast_swap as CS, char_coverage as CC, replacement_readiness as RR
    g = {"title": "John Woo Presents Stranglehold", "platform": "ps3", "game_id": M.GAME_ID}
    w = CC.writer_for(g)
    assert w and w["routed"] is True
    assert CS.STRATEGIES["gbox.stranglehold_swap"][0] == "pairs" and "gbox.stranglehold_swap" in CS.BUILDERS
    assert RR.spec_for("gbox.stranglehold_swap")["tex"] == 1024


def test_build_changes_writes_package_and_toc(tmp_path):
    from gbox.sm64_swap import load_rig
    glb, roles = S.donor_glb(tmp_path / "donor.glb")
    (tmp_path / "char_tequila.xxx").write_bytes(S.package())
    toc = "1703936 0 0 ..\\StrangleholdGame\\CookedPS3\\char_tequila.xxx 0\r\n5 0 0 ..\\x.bin 0\r\n"
    changes, rep = W.build_changes(tmp_path, toc, {"char_tequila": (load_rig(glb, roles), None, "donor", "donor")})
    assert rep["char_tequila"]["status"] == "built"
    out = changes[f"{W.COOKED}/char_tequila.xxx"]["bytes"]
    new_toc = changes[W.TOC]["bytes"].decode("latin1")
    assert new_toc.startswith(f"{len(out)} 0 0 ") and new_toc.count("\r\n") == 2
