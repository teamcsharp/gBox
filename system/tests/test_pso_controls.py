"""PSO catalog metadata, native spawn records, and platform/mutation boundaries."""
import struct
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import pso_api, pso_controls, psoitems
from gbox import pso_mods_tool as T
from gbox.config import Config
from gbox.registry import Unsupported
from test_pso_mods import FakeDC


def test_class_rares_use_attributes_and_star_values_not_names():
    rows = [
        {"code": "000100", "name": "ALL CAPS COMMON", "cat": "Weapons", "stars": 1, "usability_flags": 255},
        {"code": "000101", "name": "Hunter rare", "cat": "Weapons", "stars": 10, "usability_flags": 0x49},
        {"code": "000102", "name": "Best hunter", "cat": "Weapons", "stars": 12, "usability_flags": 0x49},
        {"code": "000103", "name": "Ranger rare", "cat": "Weapons", "stars": 12, "usability_flags": 0x4A},
    ]
    assert [r["code"] for r in psoitems.rare_pool(rows, "HUmar")] == ["000102"]
    assert [r["code"] for r in psoitems.rare_pool(rows, "HUmar", False)] == ["000101", "000102"]
    assert [r["code"] for r in psoitems.rare_pool(rows, "RAmar")] == ["000103"]
    with pytest.raises(ValueError):
        psoitems.rare_pool(rows, "guess")
    with pytest.raises(ValueError):
        psoitems.rare_pool(rows, "FOnewearl")


def test_enemy_defaults_validate_pool_and_preserve_other_preferences(tmp_path):
    app=FastAPI();pso_api.routes(app,Config(data_dir=tmp_path),lambda:'operator');c=TestClient(app)
    assert c.post('/api/pso/preferences',json={'enemy_drops':True}).status_code==422
    assert c.post('/api/pso/preferences',json={'enemy_codes':['invalid']}).status_code==422
    assert c.post('/api/pso/preferences',json={'enemy_codes':['000100']*2}).status_code==422
    good=c.post('/api/pso/preferences',json={'enemy_drops':True,'enemy_codes':['010122','000100'],'walk_through':True}).json()
    assert good['enemy_codes']==['010122','000100'] and good['equip_any'] is True
    assert c.post('/api/pso/preferences',json={'equip_any':False}).json()['walk_through'] is True
    assert c.get('/api/pso/preferences').json()['enemy_drops'] is True


def test_gc_capability_never_reads_dreamcast_addresses():
    def forbidden(*args):
        raise AssertionError("DC address read on GameCube")
    r = pso_controls.capabilities({"platform": "gamecube", "title": "Phantasy Star Online Episode I & II"}, forbidden)
    assert r["version"] == "gc" and not r["supported"]
    assert not any(r["features"].values())


def test_capabilities_require_code_fingerprint_and_guard_saved_class():
    ad = FakeDC()
    game = {"platform": "dreamcast", "title": "Phantasy Star Online Ver. 2"}
    ptr = 0x8CFD0000
    ad.put(T.CHAR_PTR, struct.pack("<I", ptr))
    ad.put(ptr + 0x424, bytes.fromhex("64b005a2"))
    ad.put(ptr + 0x3A1, b"\x04")
    assert pso_controls.capabilities(game, ad.read_memory)["character_class"] == "RAcast"
    ad.put(ptr + 0x424, b"xxxx")
    assert pso_controls.capabilities(game, ad.read_memory)["character_class"] is None
    ad.put(T.PATCHES["equip_any"][0], b"xx")
    assert not pso_controls.capabilities(game, ad.read_memory)["supported"]


def test_floor_records_use_selected_spread_and_each_weapons_own_max_grind():
    ad = FakeDC()
    p = 0x8CFA0000
    ad.put(p + 0x3C, struct.pack("<3f", 100, 8, 200))
    ad.put(p + 0x2C, struct.pack("<H", 3))
    ad.put(T.FLOOR_NOW, b"\x02")
    m = T.PSO(ad.read_memory, ad.write_memory)
    captured = []
    def run(calls):
        for fn, addr, _ in calls:
            assert fn == T.F_FLOOR_CREATE
            captured.append(ad.read_memory(addr, 36))
        return [1] * len(calls)
    m.call = run
    assert m.floor_spawn(["000100", "001000"], radius=50, item_id0=T.ID_BASE,
                         grinds={"000100": 35, "001000": 9}) == [1, 1]
    assert struct.unpack_from("<ff", captured[0], 4) == (100, 250)
    assert struct.unpack_from("<ff", captured[1], 4) == (100, 150)
    assert captured[0][16:20] == bytes.fromhex("00010023")
    assert captured[1][16:20] == bytes.fromhex("00100009")
    assert struct.unpack_from("<I", captured[1], 28)[0] == T.ID_BASE + 1


def test_tool_floor_rares_randomizes_exact_count_and_keeps_class(monkeypatch):
    from gbox.tools import SESSIONS
    ad = FakeDC()
    monkeypatch.setitem(SESSIONS, "fixture", (ad, {"platform": "dreamcast"}))
    monkeypatch.setattr(T, "_catalog_rows", lambda ctx: [
        {"code": "000100", "cat": "Weapons", "stars": 12, "usability_flags": 0x49, "max_grind": 9},
        {"code": "000200", "cat": "Weapons", "stars": 12, "usability_flags": 0x4A, "max_grind": 99}])
    seen = []
    monkeypatch.setattr(T.PSO, "floor_spawn", lambda self, codes, **kw: seen.append((codes, kw)) or [1] * len(codes))
    monkeypatch.setattr(T.PSO, "floor_items", lambda self: [(seen[0][1]["item_id0"] + i, c) for i, c in enumerate(seen[0][0])])
    r = T.pso_mods(T.ModsIn(session_id="fixture", op="floor_rares", count=17,
                          character_class="HUmar", max_grind=True, radius=60), None)["result"]
    assert r["spawned"] == 17
    assert r["codes"] == ["000100"] * 17
    assert seen[0][1]["radius"] == 60 and seen[0][1]["grinds"] == {"000100": 9}
    assert r["verified"] is True


def test_unknown_item_cannot_install_dispatcher(monkeypatch):
    from gbox.tools import SESSIONS
    ad = FakeDC()
    monkeypatch.setitem(SESSIONS, "fixture", (ad, {"platform": "dreamcast"}))
    monkeypatch.setattr(T, "_catalog_rows", lambda ctx: [])
    with pytest.raises(ValueError, match="item codes"):
        T.pso_mods(T.ModsIn(session_id="fixture", op="floor_spawn", code="ffffff"), None)
    assert struct.unpack("<I", ad.read_memory(T.VT_UPDATE, 4))[0] == T.ORIG_UPDATE


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0, 101])
def test_invalid_spread_rejected_before_memory(value):
    with pytest.raises(ValueError):
        T.ModsIn(session_id="fixture", radius=value)


def test_persistent_defaults_and_catalog_version_validation(tmp_path):
    app = FastAPI()
    cfg = Config(data_dir=tmp_path)
    pso_api.routes(app, cfg, lambda: "fixture")
    client = TestClient(app)
    assert client.get("/api/pso/preferences").json() == pso_controls.DEFAULTS
    assert client.post("/api/pso/preferences", json={"equip_any": False}).json()['equip_any'] is False
    assert client.post('/api/pso/preferences',json={'permanent_scape':True,'legendary':True}).json()==pso_controls.DEFAULTS|{'equip_any':False,'permanent_scape':True,'legendary':True}
    assert client.post('/api/pso/preferences',json={'equip_any':True}).json()['permanent_scape'] is True
    client.post('/api/pso/preferences',json={'equip_any':False})
    assert client.get("/api/pso/preferences").json()["equip_any"] is False
    assert client.get("/api/pso/items?version=../../api_token").status_code == 422
    assert client.get("/api/pso/items?version=gc").status_code == 404
    app2 = FastAPI()
    pso_api.routes(app2, cfg, lambda: "fixture")
    assert TestClient(app2).get("/api/pso/preferences").json()["equip_any"] is False


def test_catalog_rejects_corrupt_relocation_bounds():
    p = bytearray(500)
    struct.pack_into("<I", p, len(p) - 16, 0)
    struct.pack_into("<II", p, len(p) - 32, len(p) - 1, 100)
    # Deliberately malformed preamble must fail rather than exposing data as an item name.
    with pytest.raises((ValueError, StopIteration, struct.error)):
        psoitems.catalog(p, b"Saber\0" + b"\0" * 40)


@pytest.mark.parametrize("fetch_ok", [True, False])
def test_boot_defaults_only_write_after_preference_and_revision_checks(monkeypatch, fetch_ok):
    import time
    from gbox.tools import SESSIONS
    ad = FakeDC(player=0)
    game = {"platform": "dreamcast", "title": "Phantasy Star Online Ver. 2 (USA)"}
    monkeypatch.setitem(SESSIONS, "boot-fixture", (ad, game))
    class Thread:
        def __init__(self, target, **kw): self.target = target
        def start(self): self.target()
    monkeypatch.setattr(pso_controls.threading, "Thread", Thread)
    monkeypatch.setattr(time, "sleep", lambda n: SESSIONS.pop("boot-fixture", None))
    def prefs(ctx):
        if not fetch_ok: raise ConnectionError("unreachable")
        return {"equip_any": True}
    monkeypatch.setattr(pso_controls, "preferences", prefs)
    r = pso_controls.on_launch("boot-fixture", ad, game, SimpleNamespace())
    assert T.PSO(ad.read_memory, ad.write_memory).patch_state("equip_any") == ("on" if fetch_ok else "off")
    assert r["state"] == ("applied" if fetch_ok else "waiting")


def test_owned_disc_catalogs_when_provided():
    import os
    from pathlib import Path
    if not os.environ.get("GBOX_PSO_OWNED_METADATA"):
        pytest.skip("owned PMT/text files are not bundled")
    base = Path(os.environ["GBOX_PSO_OWNED_METADATA"])
    for version, expected in (("dcv2", 545), ("gc", 1257)):
        rows = psoitems.catalog((base / (version + ".pmt")).read_bytes(),
                                (base / (version + ".text")).read_bytes(),
                                "<" if version == "dcv2" else ">", int(version == "dcv2"))
        assert len(rows) == expected
        saber = next(i for i in rows if i["code"] == "000100")
        assert saber["name"] == "Saber" and not saber["rare"] and saber["atp_required"] == 30
        assert any(i["code"].startswith("0088") for i in rows)
        assert next(i for i in rows if i["code"] == "001000")["name"] == "OROTIAGITO"
        assert all(i["schema"] == 2 and 0 <= i["stars"] <= 12 for i in rows)
        for c in list(psoitems.CLASSES)[:9 if version == "dcv2" else 12]:
            pool = psoitems.rare_pool(rows, c)
            assert pool and all(c in i["classes"] for i in pool)
