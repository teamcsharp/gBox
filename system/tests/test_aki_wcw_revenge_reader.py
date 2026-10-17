"""WCW/nWo Revenge (Europe) analysis + reader probes (#1317).

Ghidra confirmation (USA NW2E build; reused project ~/gbox-cache/aki_re/ghidra/projrv.gpr, RDRAM image
rv_ram4.bin, decompile rv_ram.c, MIPS:BE:32 base 0x80000000) locates the loader/model functions:
  * FUN_800034a0 loads the AkiFileTable: malloc(0x77a8) into PTR_DAT_800482e0, reads 0xce2752, then walks
    0x1de9 entries with first-file base 0xdac50 and a 0x77a4-byte sizes buffer (the writer's patch sites).
  * FUN_8000bdd0 reads one slot's parts: slot code (DAT_8006a2a4) >> 6 & 0x7c -> set table PTR_DAT_80031998,
    costume lists PTR_PTR_800360f0, body table PTR_DAT_800317f0, part map 0x80031088, costume slot
    DAT_8007dfbc. The profile's body-table read (lui at,0x8003 / lw v0,0x17f0(at)) sits inside it.
  * FUN_8000bc78 allocates costume-variant records (0x17-sized records at DAT_8007c438; the profile's
    "costume sets" lui/lw pair at 0x8000be94 sits inside it).
  * FUN_8000c000 assembles the body rig (the profile's second "costume sets" pair at 0x8000c264 sits inside it).
The PAL (NW2P) build is not a uniform byte shift of the USA code, but every writer patch site was matched
with immediates masked (gbox.aki_wcw_inventory.derive_profile): each PAL site lies at USA site - 0xE0 and
holds the same instruction modulo the immediate/offset field. The tests below pin that correspondence and
then decode one EU wrestler (Sting) with aki_wcw.extract, checking the part ids against the USA build.
"""
import json
import struct
from pathlib import Path

import pytest

from gbox import aki_wcw as W
from gbox import n64_rom

ROMS = Path("/mnt/gbox/hyperspin/Arcade/collections/Nintendo 64/roms")
EU_ZIP = ROMS / "Europe/WCW-nWo Revenge (Europe).zip"
US_ZIP = ROMS / "USA/WCW-nWo Revenge (USA).zip"

# PAL patch site -> (USA address inside the named Ghidra function, what the function does there)
LOADER_SITES = [
    (0x800033E0, 0x800034C0, "FUN_800034a0", "file-table load: malloc(0x77a8), read from 0xce2752, 0x1de9 entries"),
    (0x8000BE00, 0x8000BEE0, "FUN_8000bdd0", "slot parts read: body table PTR_DAT_800317f0"),
    (0x8000BDB4, 0x8000BE94, "FUN_8000bc78", "costume-set lookup: PTR_PTR_800360f0"),
    (0x8000C184, 0x8000C264, "FUN_8000c000", "costume-set lookup: PTR_PTR_800360f0"),
]


def _ins(rom: bytes, ram: int) -> int:
    return struct.unpack_from(">I", rom, W.Rom.r2r(ram))[0]


def _mask(i: int) -> int:
    """Opcode + registers only: drop a jal's target or an instruction's immediate/offset field."""
    return i & 0xFC000000 if (i >> 26) == 0x03 else i & 0xFFFF0000


@pytest.mark.skipif(not (EU_ZIP.exists() and US_ZIP.exists()), reason="owned Revenge ROMs not mounted")
def test_pal_loader_sites_track_usa_ghidra_functions():
    """Each NW2P loader site = the USA site analysed in Ghidra (projrv), minus 0xE0, same instruction.

    The Ghidra functions above were decompiled from the USA RDRAM image; the PAL site must hold the same
    instruction (immediate masked) so the writer's patch sites really sit inside the same loader paths.
    """
    eu, us = n64_rom.read(EU_ZIP), n64_rom.read(US_ZIP)
    for pal, usa, func, why in LOADER_SITES:
        assert _mask(_ins(eu, pal)) == _mask(_ins(us, usa)), (hex(pal), func, why)
    for ram, _exp, kind in W.PROFILES[("NW2P", 0)]["patch"]:
        assert _mask(_ins(eu, ram)) == _mask(_ins(us, ram + 0xE0)), kind


@pytest.mark.skipif(not EU_ZIP.exists(), reason="owned EU Revenge ROM not mounted")
def test_pal_reader_decodes_sting_from_owned_rom(tmp_path):
    """Decode one EU wrestler (Sting) through the NW2P profile: 92-wrestler roster, rigged glTF out."""
    eu = n64_rom.read(EU_ZIP)
    ros = W.roster(eu)
    assert len(ros) == 92
    sting = next(w for w in ros if w["name"] == "Sting")
    parts = W.rest_parts(W.Rom(eu), sting)
    assert len([k for k in parts if isinstance(k, int)]) >= 17          # 17 body parts + face/head-back
    out = tmp_path / "sting.gltf"
    r = W.extract(eu, sting, out, "Sting")
    assert out.is_file() and out.stat().st_size > 10_000
    assert r["triangles"] > 400 and len(r["roles"]) >= 15
    gl = json.loads(out.read_text())
    assert "Sting" in {m.get("name") for m in gl["meshes"]}          # glTF meshes carry the wrestler's name


@pytest.mark.skipif(not (EU_ZIP.exists() and US_ZIP.exists()), reason="owned Revenge ROMs not mounted")
def test_pal_costume_part_ids_equal_usa_for_sting():
    """Sting costume 0 resolves to the same model/texture/palette file ids in both builds."""
    eu, us = n64_rom.read(EU_ZIP), n64_rom.read(US_ZIP)
    eus = next(w for w in W.roster(eu) if w["name"] == "Sting")
    uss = next(w for w in W.roster(us) if w["name"] == "Sting")
    ek = {k: (v["mid"], v["tex"], v["pal"]) for k, v in W.rest_parts(W.Rom(eu), eus).items()
          if isinstance(k, int)}
    uk = {k: (v["mid"], v["tex"], v["pal"]) for k, v in W.rest_parts(W.Rom(us), uss).items()
          if isinstance(k, int)}
    assert ek == uk and len(ek) >= 17


def test_revenge_dedicated_roster_is_registered():
    """characters.DEDICATED 'revenge' no longer ships an empty roster (lambda: [])."""
    from gbox import characters
    reader = next(r for r in characters.DEDICATED if r[0] == "revenge")
    assert reader[1]("wcw-nwo revenge (europe)", "n64")
    roster = reader[2]()
    assert len(roster) == 92 and all(e["kind"] == "character" for e in roster)
    assert roster[0]["key"] == "0-1" and roster[0]["slug"] == "rv_0_1_sting"
    sting = next(e for e in roster if e["name"] == "Sting")
    assert sting["slug"].startswith("rv_")


@pytest.mark.skipif(not EU_ZIP.exists(), reason="owned EU Revenge ROM not mounted")
def test_static_revenge_roster_matches_owned_rom():
    """The static DEDICATED roster is a faithful snapshot of aki_wcw.roster() on the owned PAL build."""
    eu = n64_rom.read(EU_ZIP)
    rom_roster = {(w["group"], w["member"], w["name"]) for w in W.roster(eu)}
    assert {(g, m, n) for g, m, n in W.RV_NAMES} == rom_roster and len(W.RV_NAMES) == 92
    by_key = {e["key"]: e for e in W.revenge_roster()}
    for w in W.roster(eu):
        e = by_key[f"{w['group']}-{w['member']}"]
        assert e["name"] == w["name"] and e["slug"] == f"rv_{w['group']}_{w['member']}_{_slug(w['name'])}"


def _slug(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


@pytest.mark.skipif(not EU_ZIP.exists(), reason="owned EU Revenge ROM not mounted")
def test_collection_path_exports_editable_sting(tmp_path, monkeypatch):
    """The characters collect path (dedicated_entries -> extract_dedicated -> add -> verify_entry)
    exports rv_0_1_sting as a verified, rigged, editable glTF from the owned ROM, not just aki_wcw.extract."""
    from gbox import characters as C
    from gbox import tools

    # The collect job resolves the ROM through rom_path; point it at the owned EU zip on this node.
    monkeypatch.setattr(tools, "rom_path", lambda g, cfg: EU_ZIP)

    class Ctx:
        class config:
            cache = str(tmp_path / "cache")

        def progress(self, pct, msg):
            pass

    game = {"game_id": "061264c636cc284d", "title": "WCW-nWo Revenge (Europe)", "platform": "n64",
            "source_paths": [str(EU_ZIP)], "format": "n64", "profile_id": "061264c636cc284d"}
    root = tmp_path / "lib"
    root.mkdir()
    ros = C.dedicated_entries(Ctx().config, game, "revenge", W.revenge_roster)
    assert len(ros) == 92 and all(e["kind"] == "character" for e in ros)
    res = C.extract_dedicated(Ctx(), game, "rv_0_1_sting", root, ("revenge", ros))
    assert res["status"] == "extracted", res
    meta = C.get(root, "rv_0_1_sting")
    check = C.verify_entry(root, meta)
    assert check["ok"], check
    roles = meta["rig"]["roles"]
    assert len(roles) == 15 and set(roles) >= {"hip", "chest", "head", "l_foot", "r_foot"}
    model = root / "rv_0_1_sting" / meta["model"]
    assert model.is_file() and model.stat().st_size > 10_000
    rig = C.rig_from_gltf(model, roles)
    assert len(rig["joints"]) == 18 and len(rig["roles"]) == 15
    y = {r: rig["joints"][i][1] for r, i in rig["roles"].items()}
    assert y["l_foot"] < y["hip"] < y["head"] and y["r_foot"] < y["hip"]
