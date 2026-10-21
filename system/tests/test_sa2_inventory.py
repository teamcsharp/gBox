import os
import struct
from pathlib import Path

import pytest

from gbox import sa2_inventory as inv

GDI = Path(os.environ.get("GBOX_SA2_GDI", Path.home() / "gBox_alt/gbox-cache/dc/d95ed7ed1e40552a/disc.gdi"))
EXE_SHA = "6919ed8bc96782d041be41ba86f90bf86d99632b8b7787391969721bc0991736"


def test_motion_table_reads_id_nodes_offset_until_minus_one():
    data = struct.pack("<hhI", 87, 62, 0x20) + struct.pack("<hhI", 88, 3, 0x24) + struct.pack("<hhI", -1, 0, 0)
    data += bytes(0x30 - len(data))
    assert inv.motion_table(data) == {87: (62, 0x20), 88: (3, 0x24)}


def test_id_table_rejects_out_of_file_pointer_and_missing_terminator():
    with pytest.raises(ValueError, match="outside"):
        inv.id_table(struct.pack("<iI", 0, 0x1000) + struct.pack("<iI", -1, 0), "<iI")
    with pytest.raises(ValueError, match="terminator"):
        inv.id_table(struct.pack("<iI", 0, 0), "<iI")


def test_model_key_family_maps_variants_to_the_base_motion_owner():
    assert inv.model_key_family("SONIC") == ("SONIC", None)
    assert inv.model_key_family("HSONIC") == ("SONIC", "H")
    assert inv.model_key_family("PSOSHADOW") == ("TERIOS", "PSO")
    assert inv.model_key_family("XSHADOW") == ("TERIOS", "X")
    assert inv.model_key_family("BKNUCK") == ("KNUCK", "B")
    assert inv.model_key_family("TWALK1") == ("TWALK", None)
    assert inv.model_key_family("BWALK") == ("BWALK", None)       # unknown: left alone, no motion claimed


def test_classify():
    assert inv.classify("SONIC2/SONICMDL.PRS") == "character_model"
    assert inv.classify("SONIC2/PLCOMMTN.PRS") == "character_motion"
    assert inv.classify("SONIC2/EVENT/E0000TEXLIST.PRS") == "event"
    assert inv.classify("1ST_READ.BIN") == "executable"
    assert inv.classify("SONIC2/SONICTEX.PRS") == "prs"


@pytest.mark.skipif(not GDI.exists(), reason="owned SA2 USA disc not unpacked on this node")
def test_owned_build_inventory():
    m = inv.inventory(GDI)
    assert m["ip"]["product"] == "MK-51117" and m["ip"]["version"] == "V1.008" and m["build_matches_writer"]
    assert m["executable"]["sha256"] == EXE_SHA and m["executable"]["size"] == 1578116
    assert m["file_count"] == 2572 and m["kinds"]["character_model"] == 34
    s = m["models"]["SONIC"]
    assert s["model"]["full_model_id"] == 0 and s["model"]["nodes"] == 62 and s["model"]["tris"] == 1369
    assert s["textures"]["count"] == 11 and s["motion"]["matches_model"]
    assert m["motion_files"]["SONIC"]["count"] == 34
    # every playable humanoid except Eggman shares Sonic's 62-node tree, so its motions drive the donor slot
    humanoids = ["TERIOS", "MILES", "KNUCK", "ROUGE", "AMY", "METALSONIC", "TICAL", "CHAOS0", "SSONIC", "SSHADOW"]
    assert all(m["models"][k]["model"]["nodes"] == 62 and m["models"][k]["motion"]["matches_model"] for k in humanoids)
    assert m["models"]["EGG"]["model"]["nodes"] == 46
