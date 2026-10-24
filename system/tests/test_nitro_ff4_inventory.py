import hashlib, json, os, pathlib
import pytest
from gbox.formats import lz

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "ff4_ds_inventory.json").read_text())
SRC_SHA = "d878ac2792d9185d7e065294754d04bf82377d0853c1924b2358aac5cff6e94a"


def test_source_identity():
    assert FIX["source_sha256"] == SRC_SHA
    assert FIX["platform"] == "nds" and FIX["container"] == "NitroFS"
    assert FIX["game_code"] == "YF4E" and FIX["source_size"] == 134217728


def test_pc_models_and_textures_counted():
    ms = FIX["members"]
    models = [m for m in ms if m.get("decomp_magic") == "NMDP" and m.get("section_type") == 2]
    texs = [m for m in ms if m.get("decomp_magic") == "NMDP" and m.get("section_type") == 4]
    assert len(models) == 58 and len(texs) == 121
    assert all(m["header_ok"] and m["lz10_size"] == m["decomp_size"] for m in models + texs)
    assert all(m["path"].endswith(".nmdp.lz") for m in models)
    assert all(m["path"].endswith(".ntxp.lz") for m in texs)


def test_lz10_literal_fixture():
    payload = b"NMDP\x00\x10\x00\x00"
    blob = b"\x10" + len(payload).to_bytes(3, "little") + b"\x00" + payload[:8]
    assert lz.lz10_decompress(blob) == payload


@pytest.mark.skipif(not os.environ.get("FF4_DS_ROM"), reason="owned ROM path not provided")
def test_rom_roundtrip_matches_manifest():
    from gbox.formats.nitro import NitroROM
    rom = NitroROM(open(os.environ["FF4_DS_ROM"], "rb").read())
    for m in FIX["members"][:12]:
        raw = rom.raw(m["path"])
        assert hashlib.sha256(raw).hexdigest() == m["sha256"]
        if "decomp_sha256" in m:
            assert hashlib.sha256(lz.lz10_decompress(raw)).hexdigest() == m["decomp_sha256"]
