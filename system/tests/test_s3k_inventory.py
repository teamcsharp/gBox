import hashlib
import json
from pathlib import Path

import pytest

from gbox import s3k_inventory as inv

SRC = inv.DEFAULT_SRC
pytestmark = pytest.mark.skipif(not SRC.exists(), reason="owned S3K zip not mounted")


def test_manifest_identity_and_tables():
    m = inv.build_manifest(SRC)
    s = m["source"]
    assert s["size"] == 4194304 and len(s["sha256"]) == 64
    assert s["sha256"] == "fba0677fde9f76df93f3e98d6310d8af68b9847bde16e253d73cd4dd8134ed23"
    assert s["sha1"] == "cfbf98c36c776677290a872547ac47c53d2761d6"
    assert m["game"] == "s3k" and m["layout"] == "s3k"
    c = m["characters"]
    assert set(c) == {"sonic", "tails", "knuckles"}
    assert c["sonic"]["art_bank_switch_frame"] == 0xDA and c["tails"]["art_bank_switch_frame"] == 0xD1
    assert c["knuckles"]["art_extra"] is None and c["tails"]["tails_overlay"]
    for ch in c.values():
        assert ch["dplc_frames"] == ch["mapping_frames"] == 251
        assert 0 < ch["max_art_tile_index"] < 0x2000
    json.dumps(m, default=str)
