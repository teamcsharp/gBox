"""gbox.crazy_taxi2_usa_inventory: Crazy Taxi 2 (USA) DC inventory (request #1666, game b5dfa0c44de0ba90).

Unit tests use synthetic file lists / fake discs. The owned-disc test reads the unpacked hyperspin CHD
(GBOX_CT2_USA_GDI, else <home>/gbox-cache/dc/b5dfa0c44de0ba90/disc.gdi) and skips without it."""
import hashlib
import os
from pathlib import Path

import pytest

from gbox import crazy_taxi2 as c2
from gbox import crazy_taxi2_usa_inventory as inv

GDI = os.environ.get("GBOX_CT2_USA_GDI", str(Path.home() / "gbox-cache/dc/b5dfa0c44de0ba90/disc.gdi"))
FIRST_READ_SHA = "8057a8e37636ad78b1fc70ee590bd314686546b13ffe100623d86b572aec53c1"


def test_driver_set_pairs_models_textures_and_high_detail():
    files = {"POLPP1A.BIN": 0, "POLPP1AH.BIN": 0, "TEXPP1A.BIN": 0, "TEXPP1AH.BIN": 0,
             "POLPP2D.BIN": 0, "POLPPL0.BIN": 0, "POLPPTST.BIN": 0}
    d = inv.driver_set(files)
    assert sorted(d) == ["1A", "2D"]
    assert d["1A"] == {"driver": "Axel", "model": "POLPP1A.BIN", "texture": "TEXPP1A.BIN",
                       "high_model": "POLPP1AH.BIN", "high_texture": "TEXPP1AH.BIN"}
    assert d["2D"] == {"driver": "Hot-D", "model": "POLPP2D.BIN", "texture": None}


def test_model_regex_covers_banks_but_not_other_bins():
    for n in ("POLPP2AH.BIN", "TEXPC1A1.BIN", "POLPSG0.BIN", "POLPPL0.BIN", "POLPPTST.BIN", "TEXDC0A.BIN",
              "POLDC3.BIN"):
        assert inv.MODEL_RE.match(n), n
    for n in ("1ST_READ.BIN", "SPRPLYR.BIN", "OBJDC1.BIN", "LANDDC1.AFS"):
        assert not inv.MODEL_RE.match(n), n


def test_compare_known_flags_a_different_executable():
    hashes = dict(c2.FILES_SHA256)
    assert inv.compare_known(hashes)["same_build"]
    hashes["1ST_READ.BIN"] = "0" * 64
    r = inv.compare_known(hashes)
    assert r["different"] == ["1ST_READ.BIN"] and not r["same_build"] and "POLPP2A.BIN" in r["identical"]
    del hashes["POLDC0.BIN"]
    assert inv.compare_known(hashes)["missing"] == ["POLDC0.BIN"]


class _Disc:
    def __init__(self, blobs):
        self.blobs = blobs
        self.files = {n: (i, len(b)) for i, (n, b) in enumerate(blobs.items())}

    def read(self, n):
        return self.blobs[n]


def test_compare_disc_counts_identical_changed_and_missing_banks():
    a, b = b"model-a", b"model-b"
    man = {"models": [{"file": "POLPP1A.BIN", "sha256": hashlib.sha256(a).hexdigest()},
                      {"file": "TEXPP1A.BIN", "sha256": hashlib.sha256(a).hexdigest()},
                      {"file": "POLPP2A.BIN", "sha256": hashlib.sha256(a).hexdigest()}],
           "first_read": {"sha256": hashlib.sha256(b"exe").hexdigest()}}
    other = _Disc({"POLPP1A.BIN": a, "TEXPP1A.BIN": b, "1ST_READ.BIN": b"exe2"})
    r = inv.compare_disc(man, other)
    assert r["identical"] == 1 and r["different"] == ["TEXPP1A.BIN"] and r["missing"] == ["POLPP2A.BIN"]
    assert not r["first_read_identical"] and r["other_first_read"]["bytes"] == 4


def _exists(p) -> bool:
    try:
        return Path(p).is_file()
    except OSError:
        return False


@pytest.mark.skipif(not _exists(GDI), reason="owned Crazy Taxi 2 (USA) GDI not unpacked on this node")
def test_owned_usa_disc_inventory():
    man = inv.build(GDI, hash_tracks=False)
    assert man["ip"]["product"] == "MK-51136" and man["ip"]["version"] == "V1.004" and man["ip"]["area"] == "U"
    assert man["first_read"]["sha256"] == FIRST_READ_SHA
    assert man["pol_files"] == man["pol_walked"] == 35 and not man["walk_failures"]
    assert man["triangles"] == 103625
    assert len(man["drivers"]) == 8 and all(r["model"] and r["texture"] and r["high_model"]
                                            for r in man["drivers"].values())
    k = man["vs_cdi_build_45e9455ca5487e7d"]
    assert k["different"] == ["1ST_READ.BIN"] and len(k["identical"]) == 5
