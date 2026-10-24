import os, struct, pytest
from gbox import vj2_inventory as v

ISO = "/mnt/gbox/quickswap2/Emulation/_emulation/GC ISO/Viewtiful Joe 2 (USA).nkit.iso"

@pytest.mark.skipif(not os.path.exists(ISO), reason="owned disc not mounted")
def test_owned_build_inventory():
    r = v.inventory(ISO)
    assert r["game_id"] == "G2VE08" and r["nkit"] and r["files"] == 102
    assert len(r["afs"]) == 10 and sum(r["afs"].values()) == 99
    assert set(r["characters"]) >= {"etc/pl00.dusgc", "etc/pl01.dusgc", "etc/pl04.dusgc", "etc/pl05.dusgc"}
    assert r["dol_sha256"] == "f22165762446109afbda5d84c03d7a5563f306d2801473ba5112b2d668895e6c"
