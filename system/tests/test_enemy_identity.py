"""Who each enemy is (gbox/mercs/enemy_identity.py), its portrait (gbox/mercs/enemy_portraits.py), the identity routes
(gbox/tactical_map.py) and the names / tiers the tactical frames carry (operator 2026-11-10: "identify what enemy is
who in the game and have the bot prioritize dispatching boss level foes and dangerous opponents ... profile pictures
of the enemies with names in the live map ... a sidebar with listings and details on each and every enemy type")."""
import io
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from gbox import tactical_map as TM
from gbox.mercs import enemy_identity as EI
from gbox.mercs import enemy_kinds as K
from gbox.mercs import enemy_portraits as EP
from gbox.mercs import tactical as T

RE5, RE6, RE4 = EI.RE5, EI.RE6, EI.RE4


# --- the table ---------------------------------------------------------------------------------------------------------
def test_every_entry_is_complete_short_and_sourced():
    for title in (RE5, RE6, RE4):
        rows = EI.listing(title)
        assert rows, title
        for e in rows:
            assert e["tier"] in EI.TIERS and e["level"] in EI.LEVELS, e["cls"]
            assert e["confirmed"] == (e["level"] in ("verified", "matched"))
            assert e["name"] and e["danger"] and e["weak_point"] and e["tactics"], e["cls"]
            assert K.valid_class(e["cls"]), e["cls"]                 # every key is a safe file / URL name
            assert len(e["danger"]) <= 160 and all(len(t) <= 160 for t in e["tactics"]), e["cls"]   # ours, short
            assert all(s.startswith("https://") for s in e["sources"]), e["cls"]
            if e["level"] != "unconfirmed":
                assert e["evidence"], e["cls"]                       # how it was mapped is always said
    assert len(EI.listing(RE5)) >= 18 and len(EI.listing(RE6)) >= 30 and len(EI.listing(RE4)) >= 10
    assert [e["tier"] for e in EI.listing(RE5)][0] == "boss"         # bosses lead the listing


def test_the_re5_mapping_agrees_with_the_set_lists_and_the_guide():
    # docs/research/re5-enemy-cast.md: The Mercenaries' set-list counts per class; the guide's heavies per stage
    census = {"Public Assembly": {"uEm20": 3}, "The Mines": {"uEm34": 3}, "Village": {"uEm24": 4},
              "Ancient Ruins": {"uEm24": 5}, "Missile Area": {"uEm23": 3}, "Ship Deck": {"uEm22": 7},
              "Prison": {"uEm26": 3, "uEm20": 2}}
    for stage, classes in census.items():
        info = EI.stage_info(RE5, stage)
        for cls, n in classes.items():
            assert sum(h["cls"] == cls for h in info["heavies"]) == n, (stage, cls)
            assert EI.identity(RE5, cls)["tier"] == "boss"
    assert EI.name(RE5, "uEm20") == "Executioner Majini" and EI.name(RE5, "uEm22") == "Chainsaw Majini"
    assert EI.name(RE5, "uEm11") != EI.name(RE5, "uEm10")             # the two Majini classes read apart
    assert EI.tier(RE5, "uEm62") == "harmless" and EI.weight(RE5, "uEm62") == 0.0


def test_variants_by_maximum_health_and_unknown_classes_by_health():
    assert EI.resolve(RE5, {"class": "uEm22", "hp_max": 7000})["name"] == "Chainsaw Majini (red)"
    assert EI.resolve(RE5, {"class": "uEm22", "hp_max": 15000})["name"] == "Chainsaw Majini (blue)"
    assert EI.resolve(RE5, {"class": "uEm20", "hp_max": 15000})["name"] == "Executioner Majini (Prison)"
    torch = EI.resolve(RE5, {"class": "uEm12", "hp_max": 1500})
    assert torch["name"] == "Torch Majini" and torch["tier"] == "dangerous"
    plain = EI.resolve(RE5, {"class": "uEm12", "hp_max": 700})
    assert plain["name"] == "Wetlands Majini" and plain["tier"] == "normal" and plain["known"]
    odd = EI.resolve(RE6, {"class": "uEm9999", "hp_max": 3500})
    assert odd == {"cls": "uEm9999", "name": "uEm9999", "tier": "boss", "weight": 3.0, "level": "unconfirmed",
                   "confirmed": False, "known": False, "tier_source": "health"}
    assert EI.resolve(RE6, {"class": "uEm9999"})["tier"] == "normal"
    assert EI.tier(RE6, "uEm9999") is None and EI.weight(RE6, "uEm9999") == EI.UNKNOWN_WEIGHT


def test_weights_rank_boss_over_dangerous_over_normal():
    w = EI.TIER_WEIGHT
    assert w["boss"] > w["dangerous"] > w["normal"] > w["harmless"] == 0.0
    assert EI.weight(RE5, "uEm20") > EI.weight(RE5, "uEm32") > EI.weight(RE5, "uEm10")
    assert EI.weight(RE6, "uEm4300") == w["boss"] and EI.weight(RE6, "uEm5200") == w["normal"]
    assert set(EI.CALL_SITES) == {RE5, RE6, RE4, "shared"}


def test_re4_identities_come_from_the_type_byte_and_health():
    # the set lists (etc/omake01.esl, omake02.esl): each stage's (type, health) rows, measured 2026-11-10
    esl = {"Village": [(3, 1400), (4, 1800), (11, 1700), (12, 1500), (11, 6500), (12, 6500), (0, 1000), (1, 1000)],
           "Castle": [(7, 800), (9, 900), (9, 2200), (10, 2500), (13, 3000)],
           "Base": [(2, 2000), (2, 3000), (14, 400), (21, 1000)],
           "Waterworld": [(14, 400), (18, 1000), (22, 3500), (22, 5000)]}
    for stage, rows in esl.items():
        for etype, hp in rows:
            key = EI.re4_key(etype, hp)
            assert key in EI.TABLE[RE4] and etype in EI.RE4_STAGE_TYPES[stage], (stage, etype, hp, key)
    unit = {"class": 0xAE7050, "type": 11, "hp_max": 6500, "hp": 6500, "id": 30}      # what re4_switch's census reads
    who = EI.resolve(RE4, unit)
    assert who["cls"] == "salvador" and who["name"] == "Dr. Salvador" and who["tier"] == "boss"
    assert EI.resolve(RE4, {"class": 0xAE7050, "type": 11, "hp_max": 1400})["cls"] == "ganado"
    assert EI.resolve(RE4, {"type": 22, "hp_max": 3500})["name"] == "Super Salvador"
    assert EI.resolve(RE4, {"type": 2, "hp_max": 2000})["cls"] == "jj"
    assert EI.resolve("G4BE08", {"class_id": "em16.0b.hp6500"})["cls"] == "salvador"    # the GameCube's keys
    assert EI.resolve(RE4, {"type": 99, "hp_max": 2500})["tier"] == "boss"              # unknown type: by health


def test_aliases_and_the_stage_table():
    assert EI.identity("BLUS30491", "uEm20")["name"] == "Executioner Majini"
    assert EI.stage_info(RE5, "s400")["stage"] == EI.stage_info(RE5, "Public_Assembly")["stage"] == "Public Assembly"
    nxt = EI.next_heavy(RE5, "Public Assembly", 18)
    assert nxt["cls"] == "uEm20" and nxt["kills"] == 20 and nxt["in_kills"] == 2 and nxt["where"] == "SW fence"
    assert EI.next_heavy(RE5, "Public Assembly", 71) is None
    assert EI.next_heavy(RE5, "Ship Deck", 0)["kills"] == 0
    assert EI.next_heavy(RE6, "Urban Chaos", 3) is None and EI.stage_info(RE5, "nowhere") is None
    assert EI.RULES[RE5]["combo_window_s"] == 10.0


def test_enemy_kinds_names_only_what_is_confirmed():
    assert K.name(RE5, "uEm20") == "Executioner Majini" and K.name(RE5, "uEm11") == "Majini (female)"
    assert K.name(RE6, "uEm3200") == "uEm3200"                        # Napad is not confirmed yet: its class
    assert K.name(RE6, "uEm1000") == "J'avo"


# --- the frames ---------------------------------------------------------------------------------------------------------
def _snap(enemies):
    return {"player": {"pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000}, "enemies": enemies}


def test_every_title_publishes_cls_name_and_tier():
    f = T.Tracker(RE4, "mm").frame(_snap([
        {"slot": 0, "ptr": 0x10, "class": 0xAE7050, "type": 11, "hp": 6500, "hp_max": 6500, "pos": (1000.0, 0, 0)},
        {"slot": 1, "ptr": 0x20, "class": 0xAE7050, "type": 3, "hp": 1400, "hp_max": 1400, "pos": (2000.0, 0, 0)}]),
        {}, "playing", now=1.0)
    rows = {r["id"]: r for r in f["enemies"]}
    assert (rows[0]["cls"], rows[0]["name"], rows[0]["tier"]) == ("salvador", "Dr. Salvador", "boss")
    assert (rows[1]["cls"], rows[1]["name"], rows[1]["tier"]) == ("ganado", "Ganado (villager)", "normal")
    assert list(f["kinds"]) == ["salvador", "ganado"]
    f6 = T.Tracker(RE6).frame(_snap([{"slot": 0, "ptr": 0x30, "class": "uEm4300", "hp": 900, "hp_max": 900,
                                      "pos": (300.0, 0, 0)}]), {}, "playing", now=1.0)
    row = f6["enemies"][0]
    assert row["name"] == "Ubistvo?" and row["tier"] == "boss" and row["level"] == "unconfirmed"   # "?": not confirmed
    assert f6["kinds"]["uEm4300"]["name"] == "Ubistvo?"


def test_the_portrait_hint_uses_the_frames_key():
    from types import SimpleNamespace
    bot = SimpleNamespace(_aimctx={"target": 0x10, "where": "chest", "dist": 400.0, "class": 0xAE7050}, plan=lambda: {})
    f = T.Tracker(RE4, "mm").frame(_snap([{"slot": 0, "ptr": 0x10, "class": 0xAE7050, "type": 22, "hp": 3500,
                                           "hp_max": 3500, "pos": (400.0, 0, 0)}]), T.take_plan(bot), "playing", now=1.0)
    assert f["portrait"] == {"class": "super_salvador", "dist": 400}   # RE4's live crop is kept per identity


# --- the portraits ------------------------------------------------------------------------------------------------------
def _quad(color):
    import numpy as np
    pos = np.array([[-50, 0, 0], [50, 0, 0], [50, 180, 0], [-50, 180, 0]], float)
    uvs = np.array([[0, 1], [1, 1], [1, 0], [0, 0]], float)
    tex = np.zeros((4, 4, 3), np.uint8)
    tex[:] = color
    return [(pos, None, uvs, np.array([[0, 1, 2], [0, 2, 3]]), tex)]


def test_a_model_is_drawn_cropped_and_kept(tmp_path):
    im, drawn = EP.draw(_quad((200, 30, 30)), size=200)
    assert drawn == 2 and im.size == (200, 200)
    px = im.getpixel((100, 100))
    assert px[0] > 80 and px[1] < 60                                  # the albedo, shaded
    pic = EP.crop_portrait(im)
    assert pic.size == (EP.PORTRAIT_PX, EP.PORTRAIT_PX)
    store = EP.Store(tmp_path)
    buf = io.BytesIO()
    pic.save(buf, "PNG")
    path = store.put(RE5, "uEm20", buf.getvalue(), {"source": "model", "model": "m", "triangles": 2})
    assert path == tmp_path / RE5 / "uEm20.png" and store.index(RE5)["uEm20"]["source"] == "model"
    assert store.path("../x", "uEm20") is None and store.path(RE5, "../e") is None
    with pytest.raises(EP.PortraitError):
        EP.crop_portrait(Image.new("RGB", (64, 64), EP.BACKGROUND))


ORIGINAL = Path(r"C:\_tools\gBox\.scratch-merc-recovery\variety\classes2\uEm62.arc")


@pytest.mark.skipif(not ORIGINAL.is_file(), reason="the owned RE5 uEm62.arc is not on this machine")
def test_an_owned_re5_archive_renders_its_own_model():
    png, info = EP.render_class(RE5, ORIGINAL.read_bytes(), "uEm62")
    assert info["model"].endswith("em6200") and info["triangles"] >= EP.MIN_TRIANGLES and info["textured"] >= 1
    assert Image.open(io.BytesIO(png)).size == (EP.PORTRAIT_PX, EP.PORTRAIT_PX)


# --- the routes ---------------------------------------------------------------------------------------------------------
def _png(color=(10, 200, 10)):
    out = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(out, "PNG")
    return out.getvalue()


def test_the_identity_routes_list_every_type_and_serve_its_portrait(tmp_path):
    models, crops = tmp_path / "enemy_portraits", tmp_path / "portraits"
    EP.Store(models).put(RE5, "uEm20", _png(), {"source": "model", "model": "pawn\\em\\em20\\model\\em2000"})
    (crops / RE5).mkdir(parents=True)
    Image.new("RGB", (8, 8)).save(crops / RE5 / "uEm22.jpg", "JPEG")
    (crops / RE5 / "index.json").write_text(json.dumps({"uEm22": {"name": "x", "at": 1, "dist": 350}}))
    app = FastAPI()
    TM.install(app, lambda: "agent", portraits_root=crops, model_portraits_root=models)
    c = TestClient(app)
    out = c.get(f"/api/mercs/enemies/{RE5}").json()
    assert out["title"] == RE5 and out["tiers"]["boss"] == 3.0 and out["rules"]["combo_window_s"] == 10.0
    by = {e["cls"]: e for e in out["enemies"]}
    assert by["uEm20"]["portrait"] == f"/api/mercs/enemies/{RE5}/uEm20.png" and by["uEm20"]["portrait_source"] == "model"
    assert by["uEm22"]["portrait_source"] == "frame" and "portrait" not in by["uEm10"]
    assert by["uEm20"]["weight"] == 3.0 and by["uEm20"]["tactics"]
    assert any(s["stage"] == "Ship Deck" for s in out["stages"])
    r = c.get(f"/api/mercs/enemies/{RE5}/uEm20.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    r = c.get(f"/api/mercs/enemies/{RE5}/uEm22.png")                  # no render: the live crop
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert c.get(f"/api/mercs/enemies/{RE5}/uEm10.png").status_code == 404
    assert c.get(f"/api/mercs/enemies/BLUS30491/uEm20.png").status_code == 200       # the PS3 reads RE5's table
    assert c.get("/api/mercs/enemies/..%2Fx").status_code in (404, 422)
    assert c.get(f"/api/mercs/enemies/{RE5}/..%2Fx.png").status_code == 404
    assert c.get(f"/api/mercs/enemies/{RE4}").json()["enemies"][0]["tier"] == "boss"
