from pathlib import Path

import pytest

from gbox import tetris_plus_saturn as T

BIN = Path("/home/ehm_eckx/.hermes/cache/scratch/tp/tp.bin")
needs = pytest.mark.skipif(not BIN.exists(), reason="extracted disc not on this node")


def test_static_manifest():
    assert len(T.ISO_FILES) == 33
    assert T.ISO_FILES["0MAIN.BIN"] == {"lba": 24, "size": 121064}
    assert T.inventory()["status"] == "research_only"


@needs
def test_disc_matches_manifest():
    assert T.sha256_file(str(BIN)) == T.RAW_BIN_SHA256
    with open(BIN, "rb") as f:
        assert T.parse_iso(f) == T.ISO_FILES
        h = T.ip_header(f)
    assert h["product"] == "T-5704H" and h["version"] == "V1.001"
