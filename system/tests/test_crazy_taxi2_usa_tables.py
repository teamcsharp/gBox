"""Crazy Taxi 2 (USA) DC build: 1ST_READ.BIN slot/texture tables through the published reader.

The owned USA build is a different executable from the QuickSwap2 CDI build (69f7bd24..) but the same
modelpack layout; origin/main's gbox.crazy_taxi2 KNOWN_TABLES carries its table addresses. These tests pin
that mapping and, when the owned 1ST_READ.BIN is present, decode it and check the tables are consistent.
"""
import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox import crazy_taxi2 as c2

USA_SHA = "8057a8e37636ad78b1fc70ee590bd314686546b13ffe100623d86b572aec53c1"      # 1ST_READ.BIN of the owned USA CHD (MK-51136 V1.004)
CDI_SHA = "69f7bd24cc82752d0b4995290e91b2e0de8eeda7efefadd4bd227ec6ba2b9042"      # 1ST_READ.BIN of the QuickSwap2 CDI build
EXE = Path("/home/ehm_eckx/ct2_usa/analysis/1ST_READ_usa.bin")
EXE_SIZE = 1452148


def test_usa_build_is_known():
    """The owned USA 1ST_READ.BIN is registered with its slot/texture table addresses."""
    assert USA_SHA in c2.KNOWN_TABLES, "USA 1ST_READ.BIN not in KNOWN_TABLES"
    t = c2.KNOWN_TABLES[USA_SHA]
    assert set(t) == {"normal", "high"}
    assert t["normal"] != c2.KNOWN_TABLES[CDI_SHA]["normal"], "USA and CDI builds must differ"
    for detail, (slots, count, tex, buf) in t.items():
        for va in (slots, count, tex, buf):
            off = va - c2.EXE_BASE
            assert 0 <= off < EXE_SIZE, f"{detail} table {va:#x} outside the executable"


def test_usa_code_hash_still_resolves():
    """A patched 1ST_READ (tables rewritten by a writer) still resolves to the USA build."""
    assert c2.CODE_SHA256["4c66db6a568b72cf01dc66c2321dbb4e702ba5a0be2657c70d4d7d4035026ccb"] == USA_SHA


def test_usa_executable_decodes():
    """The owned 1ST_READ.BIN decodes into slot + texture tables for every driver."""
    if not EXE.exists():
        print("owned USA 1ST_READ.BIN not present; skipping the byte-level decode")
        return
    exe = EXE.read_bytes()
    assert hashlib.sha256(exe).hexdigest() == USA_SHA, "owned 1ST_READ.BIN is a different build"
    for key in c2.PLAYER_KEYS:
        t = c2.player_tables(exe, key, high=False)
        assert t, f"no tables for {key}"
        va = t.get("slot_table_va")
        if va:
            off = va - c2.EXE_BASE
            assert 0 <= off < len(exe) - 4
            count = t.get("slot_count")
            if count:
                vals = [struct.unpack_from("<I", exe, off + 4 * i)[0] for i in range(int(count))]
                assert len(vals) == int(count)
    # the name table of the owned executable holds every driver model file
    data = exe
    for key in c2.PLAYER_KEYS:
        for name in (f"pol{key}.bin", f"tex{key}.bin", f"pol{key}H.bin", f"tex{key}H.bin"):
            assert data.find(name.encode()) >= 0, f"{name} not in the USA 1ST_READ.BIN"


def test_driver_mapping_is_axel_pp1a():
    """PP1A is Axel and PP2A is Slash (checked on the decoded models); PP2A=Axel is a known bad claim."""
    assert c2.DRIVERS["PP1A"] == "Axel"
    assert c2.DRIVERS["PP2A"] == "Slash"
    assert c2.SLUGS["PP1A"] == "axel"


GDI_CANDIDATES = [Path.home() / "gBox_alt/gbox-cache/dc/b5dfa0c44de0ba90/disc.gdi",
                  Path.home() / "gbox-cache/dc/b5dfa0c44de0ba90/disc.gdi"]


def test_usa_disc_assembles_every_driver():
    """When the owned GDI is present, every driver (normal + H) assembles into a posed textured mesh."""
    gdi = next((p for p in GDI_CANDIDATES if p.exists()), None)
    if gdi is None:
        print("owned USA GDI not present; skipping the disc walk")
        return
    disc = c2.open_disc(gdi)
    assert hashlib.sha256(disc.read("1ST_READ.BIN")).hexdigest() == USA_SHA
    for key in c2.PLAYER_KEYS:
        for high in (False, True):
            f = c2.driver_files(disc, key, high)
            a = c2.assemble(f["pol"], f["tex"], f["tables"])
            tris = sum(len(p["tris"]) for p in a["parts"])
            assert a["parts"] and tris > 200, (key, high, tris)
            assert a["textures"], (key, high)
