"""gbox.crazy_taxi2_rdc_inventory (request #1878, game e3f480866acf7465).

Unit tests use a fake disc. The owned-disc test reads the RDC CDI (GBOX_CT2_RDC_CDI, else the scratch copy) and
skips without it."""
import hashlib
import os
from pathlib import Path

import pytest

from gbox import crazy_taxi2 as c2
from gbox import crazy_taxi2_rdc_inventory as inv

CDI = os.environ.get("GBOX_CT2_RDC_CDI", str(Path.home() / ".hermes/cache/scratch/ct2_rdc/ct2_rdc.cdi"))
FIRST_READ_SHA = "53b20b163d0df493c4507bf132bba20f8bc07bdd88722b61f9d4a78fdc816264"


class _Disc:
    def __init__(self, blobs):
        self.blobs = blobs
        self.files = {n: (i, len(b)) for i, (n, b) in enumerate(blobs.items())}

    def read(self, n):
        return self.blobs[n]


def test_build_hashes_banks_and_flags_failed_walk():
    disc = _Disc({"1ST_READ.BIN": b"exe", "TEXPP1A.BIN": b"tex", "POLPP1A.BIN": b"not a pol", "OTHER.BIN": b"x"})
    man = inv.build(disc, source="x.cdi", source_bytes=1)
    assert man["game_id"] == "e3f480866acf7465"
    assert man["first_read"]["sha256"] == hashlib.sha256(b"exe").hexdigest()
    assert [m["file"] for m in man["models"]] == ["POLPP1A.BIN", "TEXPP1A.BIN"]
    assert man["pol_files"] == 1 and man["pol_walked"] == 0 and man["walk_failures"]
    assert man["vs_pinned_cdi_build"]["different"] == ["1ST_READ.BIN", "POLPP1A.BIN"] and not man["vs_pinned_cdi_build"]["same_build"]
    assert man["drivers"]["1A"]["driver"] == "Axel"


def _exists(p) -> bool:
    try:
        return Path(p).is_file()
    except OSError:
        return False


@pytest.mark.skipif(not _exists(CDI), reason="owned Crazy Taxi 2 RDC CDI not available on this node")
def test_owned_rdc_disc_inventory():
    from gbox.gdrom import CDIRom
    man = inv.build(CDIRom(CDI))
    assert man["first_read"]["sha256"] == FIRST_READ_SHA != c2.FILES_SHA256["1ST_READ.BIN"]
    assert man["first_read"]["known_build_tables"]["normal"][0] == 202587720
    assert man["pol_files"] == man["pol_walked"] == 35 and not man["walk_failures"]
    assert man["triangles"] == 103625
    assert len(man["drivers"]) == 8
    k = man["vs_pinned_cdi_build"]
    assert k["different"] == ["1ST_READ.BIN"] and len(k["identical"]) == 5
