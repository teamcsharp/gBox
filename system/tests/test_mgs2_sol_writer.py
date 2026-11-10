"""Writer tests for the OWNED MGS2 Sons of Liberty build (SLUS-201.44): the Substance model writer is routed
onto this STAGE.DAT-only disc and a real donor (Revolver Ocelot) is written into the soldier_tanker slot."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gbox import mgs2_inventory as inv
from gbox import mgs2_models as M
from gbox import mgs2_sol as sol
from gbox import mgs2_swap as S

ISO = sol.source_path()
need_iso = pytest.mark.skipif(not Path(ISO).exists(), reason="owned SLUS-201.44 ISO not mounted")


def test_sol_build_constants():
    assert inv.SOL_ELF == "SLUS_201.44"
    assert inv.SOL_ELF_SHA256 == sol.ELF_SHA256


@need_iso
def test_owned_disc_is_a_supported_build_without_stage2():
    d = inv.Disc(str(ISO))
    ident = inv.identify(d)
    assert ident["sol_build"] and ident["supported_build"] and not ident["exact_build"]
    assert inv.disc_stage_files(d) == ("MGS2/STAGE.DAT",)
    idx = M.Index(d)
    assert list(idx.archives) == ["MGS2/STAGE.DAT"]
    assert len(idx.stages_with(inv.T_KMS, 0x613791)) == 52


@need_iso
def test_donor_fits_soldier_tanker_slot_dry_run(tmp_path):
    idx = M.Index(inv.Disc(str(ISO)))
    glb = tmp_path / "ocelot.glb"
    M.extract_model(idx, 0x9BA944, glb, "ocelot")
    fn, st = M.best_stage(idx, 0x9BA944)
    kk = M.parse_kms(idx.read(fn, st, inv.T_KMS, 0x9BA944))
    roles = M.roles_of(kk["parents"], kk["world"])
    rr = {r: M.bone_name(i, roles) for r, i in roles.items()}
    rep = S.build_disc(ISO, None, [dict(slot="soldier_tanker", model=str(glb), roles=rr, name="Ocelot")])
    models = rep["reports"][0]["models"]
    main = [m for m in models if m["model"] == "613791"]
    built = [m for m in main if m["status"] == "built"]
    failed = [m for m in main if m["status"] == "failed"]
    assert len(built) == 51 and all(m["size"] <= m["cap"] and m["triangles"] == 1049 for m in built)
    # one stage pack (d036p03) has no free 8-bit page region for the donor atlas: reported, left untouched
    assert [m["stage"] for m in failed] == ["MGS2/STAGE.DAT:d036p03"]
    assert "no free 8-bit page region" in failed[0]["reason"]
    assert rep["image"] is None


def test_sol_game_id_routes_to_writer():
    """The ordinary replacement request (characters op=use/match) must reach mgs2_swap for the Sons of Liberty game id."""
    from gbox import char_coverage as CC, mgs2_inventory as inv, mgs2_swap as S
    assert inv.SOL_GAME_ID == "3fc2fad561187055" and inv.SOL_GAME_ID in S.GAME_IDS and inv.GAME_ID in S.GAME_IDS
    w = CC.writer_for({"game_id": inv.SOL_GAME_ID, "title": "Metal Gear Solid 2 - Sons of Liberty (USA)", "platform": "ps2"})
    assert w and w["writer"] == "gbox.mgs2_swap" and w["routed"] is True
    assert "soldiers" in w["slots"] and S.is_slot("soldier_tanker")
