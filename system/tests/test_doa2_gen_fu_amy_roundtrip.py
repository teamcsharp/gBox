"""Request #1167: the pick-whip actor is Gen Fu, so the Amy donor must replace
every actual Gen Fu costume through the native DOA2 writer.

The unit checks pin the explicit fighter route (the generic player slot stays
refused).  The disc check rebuilds GEN00-GEN05 from the owned disc cache,
re-decodes every rebuilt CHR, proves that only Gen Fu resources changed (the
executable and all other files stay byte-identical) and that the source tracks
keep their hashes.  It skips without GBOX_DOA2_LE_GDI / GBOX_DOA2_DONOR_DIR.
"""
import hashlib
import json
import os
import re
from pathlib import Path

import pytest

from gbox import doa2_swap

GEN_COSTUMES = [("GEN", f"{c:02d}") for c in range(6)]
GEN_FILES = ({f"DOA2/GEN{c:02d}.{e}" for c in range(6) for e in ("CHR", "BIN", "SUP", "APV")}
             | {f"DOA2/GEN_A{c:02d}.ACS" for c in range(6)})
GDI = os.environ.get("GBOX_DOA2_LE_GDI", "")
DONOR = os.environ.get("GBOX_DOA2_DONOR_DIR", "")
needs_disc = pytest.mark.skipif(not (GDI and Path(GDI).is_file() and DONOR and Path(DONOR, "meta.json").is_file()),
                                reason="owned DOA2 LE disc cache or donor library entry not available")


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 24), b""):
            h.update(block)
    return h.hexdigest()


def test_gen_fu_names_resolve_to_family_and_every_costume():
    assert doa2_swap.fighter_slot("Gen Fu") == ("GEN", None)
    assert doa2_swap.fighter_slot("Gen Fu:03") == ("GEN", "03")


@pytest.mark.parametrize("slot", ["", "player", "default"])
def test_unresolved_pick_slot_is_still_refused(slot):
    with pytest.raises(ValueError):
        doa2_swap.fighter_slot(slot)


@needs_disc
def test_gen_fu_all_costume_build_round_trip(tmp_path):
    from gbox import doa2_geometry, doa2_lab
    from gbox.gdrom import GDRom
    gdi = Path(GDI)
    before = {p.name: _sha(p) for p in sorted(gdi.parent.iterdir()) if p.is_file()}
    source = GDRom(str(gdi))
    assert doa2_lab.selected_costumes(source.files, "GEN", "all") == GEN_COSTUMES

    doa2_swap.build_fighter(str(gdi), Path(DONOR), tmp_path, "Gen Fu", "all")
    meta = json.loads((tmp_path / ".gbox-mod.json").read_text(encoding="utf-8"))
    assert meta["name"] == "doa2_gen_" + json.loads(Path(DONOR, "meta.json").read_text(encoding="utf-8"))["slug"]
    assert meta["gameplay_verified"] is False
    assert meta["writer_sha256"] == doa2_swap.writer_fingerprint()

    rebuilt = GDRom(str(tmp_path / meta["image"]))
    assert set(rebuilt.files) == set(source.files)
    changed = {f for f in source.files if source.read(f) != rebuilt.read(f)}
    assert changed <= GEN_FILES, sorted(changed - GEN_FILES)
    assert {f"DOA2/GEN{c:02d}.{e}" for c in range(6) for e in ("CHR", "BIN", "SUP")} <= changed
    assert "1ST_READ.BIN" not in changed
    assert set(meta["files"]) == changed

    for _, costume in GEN_COSTUMES:
        name = f"DOA2/GEN{costume}.CHR"
        decoded = doa2_geometry.decode_chr(rebuilt.read(name))
        assert len(decoded["models"]) == len(doa2_geometry.decode_chr(source.read(name))["models"])
    report = (tmp_path / "build-report.json").read_text(encoding="utf-8")
    assert len(re.findall(r'"triangles":\s*1384\b', report)) >= len(GEN_COSTUMES)

    assert {p.name: _sha(p) for p in sorted(gdi.parent.iterdir()) if p.is_file()} == before
