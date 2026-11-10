"""Writer round-trip on a COPY of the owned Crazy Taxi 2 (USA) GD-ROM (#1666). Skipped without the owned GDI."""
import hashlib
from pathlib import Path

import pytest

from gbox import crazy_taxi2 as c2, crazy_taxi2_swap as W
from gbox.gdrom import GDRom, patch_gdi

GDI = Path.home() / "gBox_alt/gbox-cache/dc/b5dfa0c44de0ba90/disc.gdi"
EXE_SHA = "8057a8e37636ad78b1fc70ee590bd314686546b13ffe100623d86b572aec53c1"
pytestmark = pytest.mark.skipif(not GDI.exists(), reason="owned USA GDI not present")


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def test_noop_roundtrip_and_axel_into_slash(tmp_path):
    d = GDRom(str(GDI))
    assert _sha(d.read("1ST_READ.BIN")) == EXE_SHA
    before = {n: _sha(d.read(n)) for n in d.files}
    names = W.driver_file_names(["PP2A"])
    # no-op: the original bytes written back leave the data track bit-identical
    img = patch_gdi(GDI, tmp_path, "noop", {n: d.read(n) for n in names})
    assert _sha(Path(str(tmp_path / "noop.track03.bin")).read_bytes()) == _sha(Path(GDI.parent / "disc03.bin").read_bytes())
    b = GDRom(str(img))
    assert [n for n in before if _sha(b.read(n)) != before[n]] == []
    # changed donor: Axel's own rigged model written into the Slash (PP2A) slot, both detail levels
    exe = d.read("1ST_READ.BIN")
    src = {"1ST_READ.BIN": exe}
    for k in ("PP1A", "PP2A"):
        for s in ("", "H"):
            src[f"POL{k}{s}.BIN"], src[f"TEX{k}{s}.BIN"] = d.read(f"POL{k}{s}.BIN"), d.read(f"TEX{k}{s}.BIN")
    a = c2.assemble(src["POLPP1AH.BIN"], src["TEXPP1AH.BIN"], c2.player_tables(exe, "PP1A", True))
    glb = c2.write_glb(tmp_path / "axel.glb", a, "axel")
    changed, _ = W.write_drivers(src, glb, dict(c2.ROLES), ["PP2A"])
    assert set(changed) == {"1ST_READ.BIN", "POLPP2A.BIN", "POLPP2AH.BIN", "TEXPP2A.BIN", "TEXPP2AH.BIN"}
    b2 = GDRom(str(patch_gdi(GDI, tmp_path, "axel_in_slash", changed)))
    assert {n for n in before if _sha(b2.read(n)) != before[n]} == set(changed)
    assert all(b2.read(n) == v for n, v in changed.items())
    rb = W.readback({**src, **changed}, ["PP2A"])
    assert rb["PP2A"]["parts"] == 15 and rb["PP2AH"]["triangles"] > 500
