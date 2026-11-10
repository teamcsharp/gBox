import os
import struct
import pytest
from gbox.truecrime_inventory import ngc_head, sha256_file, inventory

ROM = "/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/True Crime - Streets of LA (USA).gcz"


def test_ngc_head_not_auf_chunk():
    b = struct.pack(">8I", 9, 0x60000, 0x5c, 0x40030, 0x60, 3, 0x960, 0x1000a) + bytes(64)
    h = ngc_head(b)
    assert h["words"][0] == 9 and not h["auf_chunk_header"]


def test_short():
    with pytest.raises(ValueError):
        ngc_head(b"\0" * 8)


@pytest.mark.skipif(not os.path.exists(ROM), reason="owned ROM absent")
def test_owned_build():
    inv = inventory(ROM)
    assert inv["game_id"] == "GTLE52" and inv["files"] == 4075
    assert inv["dol_sha256"] == "55461d07b48b88f0509f2eeab85e3279cd8150672f33137a9d43553d0343a978"
    assert inv["counts"]["Char:ngc"] == 127 and len(inv["char_ngc"]) == 127
    assert sha256_file(ROM) == "aae3c402ced1e9ea8d46dd416547b126844f34519c7ed35a4f5472b28d25b064"
