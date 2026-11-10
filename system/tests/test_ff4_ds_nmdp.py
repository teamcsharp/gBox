import hashlib, json, os, pathlib
import pytest
from gbox.formats.ff4_ds_nmdp import parse_nmdp, parse_dict

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "ff4_ds_nmdp_models.json").read_text())


def test_fixture_shape():
    assert len(FIX["models"]) == 58
    assert all(m["models"] and m["models"][0]["nodes"] >= 1 for m in FIX["models"].values())


def test_rejects_non_nmdp():
    with pytest.raises(ValueError):
        parse_nmdp(b"XXXX" + bytes(0x40))


@pytest.mark.skipif(not os.environ.get("FF4_DS_ROM"), reason="owned ROM path not provided")
def test_rom_models_match_fixture():
    from gbox.formats.nitro import NitroROM
    from gbox.formats.lz import lz10_decompress
    data = open(os.environ["FF4_DS_ROM"], "rb").read()
    assert hashlib.sha256(data).hexdigest() == FIX["source_sha256"]
    rom = NitroROM(data)
    for path, exp in FIX["models"].items():
        d = lz10_decompress(rom.raw(path))
        assert hashlib.sha256(d).hexdigest() == exp["decomp_sha256"]
        got = parse_nmdp(d)["models"]
        assert [(m["name"], len(m["nodes"]), len(m["materials"]), len(m["shapes"])) for m in got] == \
               [(m["name"], m["nodes"], m["materials"], m["shapes"]) for m in exp["models"]]
