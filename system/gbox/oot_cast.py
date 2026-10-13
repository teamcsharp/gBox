"""Zelda: Ocarina of Time (N64): the cast catalogue and the ROM facts a whole-cast build needs ("replace the entire
cast in OoT", `characters op=cast_swap target_game=oot source=<game>`).

CAST lists every character slot gBox offers: the object file (gObjectTable id), the skeleton inside it (offset, decomp
name, Flex vs Normal SkelAnime, Standard / LOD / Skin limbs) and the actors that draw it. Names and offsets come from
the zeldaret/oot decompilation (assets/xml/objects/*.xml, include/tables/actor_table.h, object_table.h) - read as
documentation only; every fact is re-derived from the operator's ROM by `snapshot()` (`python -m gbox.oot_cast ROM
--write` refreshes gbox/oot_cast.json): the actor profile's objectId, the skeleton header at the offset (limb count, LOD
spacing, the Flex dListCount), the actor overlay's references to it, the humanoid limb roles the retarget uses (or why
there are none), the bytes the old model frees, and every scene room that loads the object.

Object space (z_scene.c Object_InitContext): every room's objects, gameplay_keep, the scene's sub-keep and Link's object
share one ~1000 KB buffer, allocated in list order. A cast build grows many objects of one scene at once (Kokiri
Forest: object_km1, object_kw1 + object_fa, object_sa, object_md and Link), so growth is shared out per room
(growth_plan) from what the scene / room object lists leave free in this ROM, and checked again after the build
(space_report). Nothing here launches or writes anything; gbox.oot_swap.build_cast does the writing.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

from . import oot_writer as OW

SNAPSHOT = Path(__file__).with_name("oot_cast.json")
SPACE = 1000 * 1024                       # Object_InitContext: the default object space
SPACE_SCENES = {0x4F: 1150 * 1024, 0x17: 1050 * 1024, 0x44: 1050 * 1024, 0x19: 1050 * 1024}   # Ganon, Twinrova, sages, Ganondorf
RESERVE = 0x3000                          # head room kept free in every room after a cast build
LINK_OBJECTS = {"child": OW.OBJECT_LINK_CHILD, "adult": OW.OBJECT_LINK_BOY}
GROWTH_CAP = {"link": 0xA000, "npc": 0x9000}   # = gbox.oot_swap.GROWTH: the most one object may grow
DL_OPS = {0x01, 0xD7, 0xD9, 0xDA, 0xDE, 0xE2, 0xE3, 0xE7, 0xFA, 0xFB, 0xFC, 0xFD}

# include/tables/scene_table.h order (retail: 0x00 - 0x64)
SCENES = [
    "Deku Tree", "Dodongo's Cavern", "Jabu-Jabu's Belly", "Forest Temple", "Fire Temple", "Water Temple",
    "Spirit Temple", "Shadow Temple", "Bottom of the Well", "Ice Cavern", "Ganon's Tower", "Gerudo Training Ground",
    "Thieves' Hideout", "Inside Ganon's Castle", "Ganon's Tower (collapse, inside)", "Ganon's Castle (collapse)",
    "Treasure Chest Shop", "Gohma's lair", "King Dodongo's lair", "Barinade's lair", "Phantom Ganon's lair",
    "Volvagia's lair", "Morpha's lair", "Twinrova's lair", "Bongo Bongo's lair", "Ganondorf's lair",
    "Ganon's Tower (collapse, outside)", "Market Entrance (day)", "Market Entrance (night)", "Market Entrance (ruins)",
    "Back Alley (day)", "Back Alley (night)", "Market (day)", "Market (night)", "Market (ruins)",
    "Temple of Time exterior (day)", "Temple of Time exterior (night)", "Temple of Time exterior (ruins)",
    "Know-It-All Brothers' House", "Twins' House", "Mido's House", "Saria's House", "Kakariko guest house",
    "Back Alley house", "Bazaar", "Kokiri Shop", "Goron Shop", "Zora Shop", "Kakariko Potion Shop",
    "Market Potion Shop", "Bombchu Shop", "Happy Mask Shop", "Link's House", "Dog Lady's House", "Stable",
    "Impa's House", "Lakeside Laboratory", "Carpenters' Tent", "Gravekeeper's Hut", "Great Fairy (magic)",
    "Fairy Fountain", "Great Fairy (spells)", "Grottos", "Redead grave", "Fairy Fountain grave", "Royal Family's Tomb",
    "Shooting Gallery", "Temple of Time", "Chamber of the Sages", "Castle courtyard guards (day)",
    "Castle courtyard guards (night)", "Cutscene map", "Windmill and Dampe's grave", "Fishing Pond",
    "Castle courtyard (Zelda)", "Bombchu Bowling Alley", "Lon Lon Ranch buildings", "Market guard house",
    "Granny's Potion Shop", "Ganon's arena", "House of Skulltula", "Hyrule Field", "Kakariko Village", "Graveyard",
    "Zora's River", "Kokiri Forest", "Sacred Forest Meadow", "Lake Hylia", "Zora's Domain", "Zora's Fountain",
    "Gerudo Valley", "Lost Woods", "Desert Colossus", "Gerudo's Fortress", "Haunted Wasteland", "Hyrule Castle",
    "Death Mountain Trail", "Death Mountain Crater", "Goron City", "Lon Lon Ranch", "Outside Ganon's Castle"]


def _s(slot, name, kind, actors, obj, skel, skel_name, typ="flex", limbs="standard", **kw):
    return {"slot": slot, "name": name, "kind": kind, "actors": list(actors), "object": obj, "skel": skel,
            "skel_name": skel_name, "type": typ, "limb_type": limbs, **kw}


# slot -> object / skeleton / actors. kind: player, npc, sage, enemy, boss. size: body size relative to an adult Hylian
# (the cast swap's by_role mapping deals the tallest donors to the biggest slots).
CAST = [
    {"slot": "player", "name": "Link (adult and child)", "kind": "player", "actors": ["Player"],
     "object": "object_link_boy", "objects_also": ["object_link_child"], "skel": 0x377F4, "skel_name": "gLinkAdultSkel",
     "type": "flex", "limb_type": "lod", "size": 1.0,
     "note": "both ages (object_link_child skeleton 0x2CF6C); hands, waist and first-person tables in code follow"},
    # Kokiri Forest
    _s("kokiri_boy", "Kokiri boys (Know-It-All Brothers, shopkeeper)", "npc", ["En_Ko"], "object_km1", 0xF0,
       "gKm1Skel", size=0.55, group=("En_Ko", "object_km1"),
       note="every Kokiri boy shares object_km1 (En_Ko draws head, body and legs from it)"),
    _s("kokiri_girl", "Kokiri girls and Fado", "npc", ["En_Ko"], "object_kw1", 0xF0, "gKw1Skel", size=0.55,
       group=("En_Ko", "object_kw1"), objects_also=["object_fa"],
       note="every Kokiri girl shares object_kw1; Fado has object_fa's head on it (written too)"),
    _s("saria", "Saria", "sage", ["En_Sa", "Demo_Sa"], "object_sa", 0xB1A0, "gSariaSkel", size=0.55),
    _s("mido", "Mido", "npc", ["En_Md"], "object_md", 0x7FB8, "gMidoSkel", size=0.6),
    # Hyrule Castle / Market / Kakariko
    _s("zelda_child", "Princess Zelda (child, castle courtyard)", "npc", ["En_Zl4"], "object_zl4", 0xE038,
       "gChildZeldaSkel", size=0.6),
    _s("zelda_child_escape", "Princess Zelda (child, escape and ocarina cutscenes)", "npc", ["En_Zl1"], "object_zl1",
       0xF5D8, "gChildZelda1Skel", size=0.6),
    _s("zelda_adult", "Princess Zelda (adult)", "sage", ["En_Zl2", "En_Zl3"], "object_zl2", 0x10D70, "gZelda2Skel",
       size=1.0),
    _s("sheik", "Sheik", "npc", ["En_Xc"], "object_xc", 0x13510, "gSheikSkel", size=1.0),
    _s("impa", "Impa", "sage", ["Demo_Im"], "object_im", 0xF788, "gImpaSkel", size=1.35),
    _s("hyrule_soldier", "Hyrule soldiers and castle guards", "npc",
       ["En_Heishi1", "En_Heishi2", "En_Heishi3", "En_Heishi4"], "object_sd", 0xBAC8, "gEnHeishiSkel", typ="normal",
       size=1.05),
    _s("dampe", "Dampe the gravekeeper (and his ghost)", "npc", ["En_Tk", "En_Po_Relay"], "object_tk", 0xBE40,
       "gDampeSkel", size=0.8),
    _s("happy_mask_salesman", "Happy Mask Salesman", "npc", ["En_Ossan"], "object_os", 0x4658,
       "gHappyMaskSalesmanSkel", size=1.0),
    _s("running_man", "Running Man", "npc", ["En_Mm", "En_Mm2"], "object_mm", 0x5E18, "gRunningManSkel", size=1.0),
    _s("cucco_lady", "Anju, the Cucco Lady", "npc", ["En_Niw_Lady"], "object_ane", 0xF0, "gCuccoLadySkel", size=0.95),
    _s("cucco_girl", "Market girl chasing the cucco", "npc", ["En_Niw_Girl"], "object_gr", 0x9948, "gNiwGirlSkel",
       size=0.6),
    _s("windmill_man", "Guru-Guru, the windmill man", "npc", ["En_Fu"], "object_fu", 0x6C90, "gWindmillManSkel",
       size=1.0),
    _s("roof_man", "The man on the Kakariko roof", "npc", ["En_Ani"], "object_ani", 0xF0, "gRoofManSkel", size=1.0),
    _s("graveyard_kid", "Graveyard kid", "npc", ["En_Cs"], "object_cs", 0x8540, "gGraveyardKidSkel", size=0.55),
    _s("carpenter_boss", "Mutoh, the carpenter boss", "npc", ["En_Toryo"], "object_toryo", 0x7150,
       "object_toryo_Skel_007150", size=1.0),
    _s("carpenters", "The carpenters (Gerudo Fortress, Kakariko)", "npc", ["En_Daiku", "En_Daiku_Kakariko"],
       "object_daiku", 0x7958, "object_daiku_Skel_007958", size=1.0),
    _s("carpenter_son", "Carpenter's son (Lost Woods)", "npc", ["En_Hs", "En_Hs2"], "object_hs", 0x6260,
       "gCarpenterSonSkel", size=1.0),
    _s("shooting_gallery_man", "Shooting gallery owner", "npc", ["En_Syateki_Man"], "object_ossan", 0x9B38,
       "gObjectOssanSkel", size=1.0),
    _s("bombchu_bowling_girl", "Bombchu Bowling Alley girl", "npc", ["En_Bom_Bowl_Man"], "object_bg", 0x6EB0,
       "gBowlingGirlSkel", size=0.95),
    _s("poe_collector", "Poe Collector", "npc", ["En_Gb"], "object_ps", 0xC220, "gPoeSellerSkel", size=1.0),
    _s("scientist", "Lake Hylia scientist", "npc", ["En_Mk"], "object_mk", 0x5DF0, "object_mk_Skel_005DF0", size=0.9),
    _s("carpet_merchant", "Carpet merchant (Haunted Wasteland)", "npc", ["En_Js"], "object_js", 0x5EA0,
       "gCarpetMerchantSkel", size=1.0),
    _s("bean_salesman", "Magic bean salesman", "npc", ["En_Ms"], "object_ms", 0x3DC0, "gBeanSalesmanSkel", size=1.0),
    _s("fishing_pond_owner", "Fishing pond owner", "npc", ["Fishing"], "object_fish", 0x85F8, "gFishingOwnerSkel",
       size=1.0),
    _s("great_fairy", "Great Fairy", "npc", ["Bg_Dy_Yoseizo"], "object_dy_obj", 0x1C450, "gGreatFairySkel", size=1.6),
    # Lon Lon Ranch
    _s("malon_child", "Malon (child)", "npc", ["En_Ma1"], "object_ma1", 0x8460, "gMalonChildSkel", size=0.6),
    _s("malon_adult", "Malon (adult)", "npc", ["En_Ma2", "En_Ma3"], "object_ma2", 0x8D90, "gMalonAdultSkel", size=0.95),
    _s("talon", "Talon", "npc", ["En_Ta"], "object_ta", 0xB7B8, "gTalonSkel", size=1.1),
    _s("ingo", "Ingo", "npc", ["En_In"], "object_in", 0x13B88, "gIngoSkel", size=1.1),
    # Gorons / Zoras / Gerudo / sages
    _s("darunia", "Darunia", "sage", ["En_Du", "Demo_Du"], "object_du", 0x122A8, "gDaruniaSkel", size=1.5),
    _s("goron", "Gorons (Goron City, Biggoron, Link the Goron)", "npc", ["En_Go", "En_Go2", "Demo_Go"],
       "object_oF1d_map", 0xFEF0, "gGoronSkel", size=1.4, note="every Goron shares object_oF1d_map, so all of them change"),
    _s("zora", "Zoras", "npc", ["En_Zo", "En_Diving_Game"], "object_zo", 0xBFA8, "gZoraSkel", size=1.1),
    _s("king_zora", "King Zora", "npc", ["En_Kz"], "object_kz", 0x86D0, "gKzSkel", size=1.6),
    _s("ruto_child", "Princess Ruto (child)", "npc", ["En_Ru1"], "object_ru1", 0x12700, "gRutoChildSkel", size=0.6),
    _s("ruto_adult", "Princess Ruto (adult, sage)", "sage", ["En_Ru2"], "object_ru2", 0xC700, "gAdultRutoSkel",
       size=1.0),
    _s("nabooru", "Nabooru", "sage", ["En_Nb"], "object_nb", 0x181C8, "gNabooruSkel", size=1.05),
    _s("rauru", "Rauru", "sage", ["En_Rl"], "object_rl", 0x7B38, "object_rl_Skel_007B38", size=1.0),
    _s("gerudo_guard", "Gerudo guards (purple)", "npc", ["En_Ge2"], "object_gla", 0x8968, "gGerudoPurpleSkel",
       size=1.0),
    _s("gerudo_white", "Gerudo (white, fortress and training ground)", "npc", ["En_Ge1"], "object_ge1", 0x330,
       "gGerudoWhiteSkel", size=1.0),
    _s("koume", "Koume (Twinrova sister)", "npc", ["En_Tr"], "object_tr", 0x11688, "gKoumeSkel", size=0.8),
    _s("kotake", "Kotake (Twinrova sister)", "npc", ["En_Tr"], "object_tr", 0xC530, "gKotakeSkel", size=0.8),
    _s("skull_kid", "Skull Kid", "npc", ["En_Skj"], "object_skj", 0x5F40, "gSkullKidSkel", size=0.55),
    _s("kaepora_gaebora", "Kaepora Gaebora (perched)", "npc", ["En_Owl"], "object_owl", 0x100B0, "gOwlPerchingSkel",
       size=1.2),
    # enemies
    _s("stalfos", "Stalfos", "enemy", ["En_Test"], "object_sk2", 0x7C28, "gStalfosSkel", typ="normal", size=1.2),
    _s("stalchild", "Stalchild", "enemy", ["En_Skb"], "object_skb", 0x41F8, "gStalchildSkel", typ="normal", size=0.6),
    _s("moblin_spear", "Moblin (spear)", "enemy", ["En_Mb"], "object_mb", 0x8F38, "gEnMbSpearSkel", size=1.5),
    _s("moblin_club", "Moblin (club, Sacred Forest Meadow)", "enemy", ["En_Mb"], "object_mb", 0x14190,
       "gEnMbClubSkel", size=1.8),
    _s("iron_knuckle", "Iron Knuckle", "enemy", ["En_Ik", "Demo_Ik"], "object_ik", 0x1E178, "gIronKnuckleSkel",
       size=1.6, note="the defeat skeleton (0x205C0) keeps the old armour"),
    _s("lizalfos", "Lizalfos", "enemy", ["En_Zf"], "object_zf", 0x104B8, "gLizalfosSkel", typ="normal", size=1.2),
    _s("dinolfos", "Dinolfos", "enemy", ["En_Zf"], "object_zf", 0x6690, "gDinolfosSkel", typ="normal", size=1.3),
    _s("wolfos", "Wolfos", "enemy", ["En_Wf"], "object_wf", 0x9690, "gWolfosGraySkel", size=1.1),
    _s("white_wolfos", "White Wolfos", "enemy", ["En_Wf"], "object_wf", 0x3BC0, "gWolfosWhiteSkel", size=1.1),
    _s("redead", "ReDead", "enemy", ["En_Rd"], "object_rd", 0xE778, "gRedeadSkel", size=1.1),
    _s("gibdo", "Gibdo", "enemy", ["En_Rd"], "object_rd", 0x3DD8, "gGibdoSkel", size=1.1),
    _s("gerudo_fighter", "Gerudo fighter (red)", "enemy", ["En_GeldB", "En_Ge3"], "object_geldb", 0xA458,
       "gGerudoRedSkel", size=1.0),
    _s("dark_link", "Dark Link", "enemy", ["En_Torch2"], "object_torch2", 0x4764, "gDarkLinkSkel", limbs="lod",
       size=1.0, roles="link"),
    _s("flare_dancer", "Flare Dancer", "enemy", ["En_Fd", "En_Fw"], "object_fw", 0x5810, "gFlareDancerSkel", size=1.2),
    _s("deku_scrub", "Deku Scrub (Mad Scrub)", "enemy", ["En_Dekunuts"], "object_dekunuts", 0x3268, "gDekuNutsSkel",
       typ="normal", size=0.5),
    _s("business_scrub", "Business Scrub", "npc", ["En_Dns", "En_Shopnuts"], "object_shopnuts", 0x41A8,
       "gBusinessScrubSkel", size=0.5),
    _s("skulltula", "Skulltula (and Gold Skulltula)", "enemy", ["En_St", "En_Sw"], "object_st", 0x5298,
       "object_st_Skel_005298", typ="normal", size=0.8),
    _s("poe", "Poe", "enemy", ["En_Poh"], "object_poh", 0x50D0, "gPoeSkel", typ="normal", size=1.0),
    _s("poe_sisters", "Poe Sisters", "enemy", ["En_Po_Sisters"], "object_po_sisters", 0x65C8, "gPoeSistersSkel",
       typ="normal", size=1.1),
    _s("big_poe", "Big Poe (Hyrule Field)", "enemy", ["En_Po_Field"], "object_po_field", 0x6A30, "gPoeFieldSkel",
       typ="normal", size=1.2),
    _s("armos", "Armos", "enemy", ["En_Am"], "object_am", 0x5948, "gArmosSkel", typ="normal", size=1.2),
    _s("octorok", "Octorok", "enemy", ["En_Okuta"], "object_okuta", 0x3660, "gOctorokSkel", typ="normal", size=0.6),
    _s("keese", "Keese", "enemy", ["En_Firefly"], "object_firefly", 0x18B8, "gKeeseSkel", typ="normal", size=0.4),
    _s("tektite", "Tektite", "enemy", ["En_Tite"], "object_tite", 0x3A20, "object_tite_Skel_003A20", typ="normal",
       size=0.7),
    _s("peahat", "Peahat", "enemy", ["En_Peehat"], "object_peehat", 0x1C80, "gPeehatSkel", typ="normal", size=1.5),
    _s("dodongo", "Dodongo", "enemy", ["En_Dodongo"], "object_dodongo", 0x8318, "gDodongoSkel", typ="normal", size=1.3),
    _s("wallmaster", "Wallmaster and Floormaster", "enemy", ["En_Wallmas", "En_Floormas"], "object_wallmaster",
       0x8FB0, "gWallmasterSkel", size=1.0),
    _s("dead_hand", "Dead Hand", "enemy", ["En_Dh"], "object_dh", 0x7E88, "object_dh_Skel_007E88", size=1.4),
    _s("anubis", "Anubis", "enemy", ["En_Anubice"], "object_anubice", 0x3990, "gAnubiceSkel", typ="normal", size=1.1),
    _s("guay", "Guay", "enemy", ["En_Crow"], "object_crow", 0x10C0, "gGuaySkel", size=0.4),
    _s("deku_baba", "Deku Baba (head)", "enemy", ["En_Dekubaba", "En_Karebaba"], "object_dekubaba", 0x2A40,
       "gDekubabaHeadSkel", typ="normal", size=0.6),
    # bosses
    _s("ganondorf", "Ganondorf", "boss", ["Boss_Ganon"], "object_ganon", 0x100E8, "gGanondorfSkel", size=1.4),
    _s("ganon", "Ganon", "boss", ["Boss_Ganon2"], "object_ganon2", 0x24570, "gGanonSkel", size=3.0),
    _s("phantom_ganon", "Phantom Ganon", "boss", ["Boss_Ganondrof"], "object_gnd", 0xC710, "gPhantomGanonSkel",
       typ="normal", size=1.4),
    _s("twinrova", "Twinrova (merged)", "boss", ["Boss_Tw"], "object_tw", 0x30C20, "gTwinrovaSkel", size=1.2),
    _s("king_dodongo", "King Dodongo", "boss", ["Boss_Dodongo"], "object_kingdodongo", 0x19F10,
       "object_kingdodongo_Skel_01B310", typ="normal", size=3.0),
    _s("bongo_bongo_head", "Bongo Bongo (head)", "boss", ["Boss_Sst"], "object_sst", 0x16840, "gBongoHeadSkel",
       size=2.5),
    # not replaceable by an object rebuild (kept in the catalogue so the reason is on record)
    {"slot": "epona", "name": "Epona", "kind": "npc", "actors": ["En_Horse"], "object": "object_horse", "skel": 0x9D74,
     "skel_name": "gEponaSkel", "type": "normal", "limb_type": "skin", "size": 2.0,
     "refuse": "Epona is a skinned skeleton (SkinLimbs: vertices blended between limbs every frame by Skin_Draw); "
               "gBox's OoT writer only rebuilds Standard / LOD limb display lists"},
    {"slot": "navi", "name": "Navi", "kind": "npc", "actors": ["En_Elf"], "object": "gameplay_keep", "skel": None,
     "skel_name": "gFairySkel", "type": "normal", "limb_type": "standard", "size": 0.2,
     "refuse": "Navi (En_Elf) is drawn from gameplay_keep, the object every actor and Link share: rebuilding it is "
               "not a per-character change; the overlay (characters op=overlay) can still draw over her"},
    {"slot": "like_like", "name": "Like Like", "kind": "enemy", "actors": ["En_Rr"], "object": "object_rr",
     "skel": None, "skel_name": None, "type": None, "limb_type": None, "size": 1.2,
     "refuse": "Like Like has no skeleton (En_Rr builds its body from display lists and matrices in code)"},
    {"slot": "hylian_townsfolk", "name": "Market and Kakariko townsfolk (En_Hy)", "kind": "npc", "actors": ["En_Hy"],
     "object": "object_aob", "skel": 0xF0, "skel_name": "gHylianWoman1Skel", "type": "flex", "limb_type": "standard",
     "size": 1.0,
     "refuse": "En_Hy draws a head from one object on a body from another, per townsperson type (object_aob, ahg, "
               "boj, bba, bji, cne, cob + object_os_anime): the per-type head / body table isn't catalogued yet"},
]
# creatures: paired wings / legs / leaves read as arms by the limb-tree guess -> the donor rides the body whole
CREATURES = {"kaepora_gaebora", "skulltula", "octorok", "keese", "tektite", "peahat", "dodongo", "wallmaster",
             "dead_hand", "guay", "deku_baba", "king_dodongo", "bongo_bongo_head", "deku_scrub"}
# objects whose actors animate them from a shared animation object (the pose for the fit comes from there)
ANIM_OBJECTS = {"zelda_adult": ["object_zl2_anime1", "object_zl2_anime2"], "cucco_lady": ["object_os_anime"],
                "roof_man": ["object_os_anime"]}
for _c in CAST:
    if _c["slot"] in CREATURES:
        _c["shape"] = "creature"
    if _c["slot"] in ANIM_OBJECTS:
        _c["anim"] = ANIM_OBJECTS[_c["slot"]]
BY_SLOT = {c["slot"]: c for c in CAST}


def names() -> dict:
    return json.loads((Path(__file__).with_name("oot_names.json")).read_text())


def object_id(name: str) -> int | None:
    n = (name or "").lower()
    objs = names()["objects"]
    return next((int(k, 16) for k, v in reversed(list(objs.items())) if v.lower() == n), None)


def actor_id(name: str) -> int | None:
    return next((int(k, 16) for k, v in names()["actors"].items() if v == name), None)


# ---------------------------------------------------------------- the snapshot (facts measured on the owned ROM)

def load_snapshot() -> dict:
    try:
        return json.loads(SNAPSHOT.read_text())
    except (OSError, ValueError):
        return {}


def cast_slots(game: dict | None = None) -> list[dict]:
    """The cast menu / whole-cast swap rows: every catalogued slot; slots the writer can't rebuild are status
    not_working with the reason (the cast swap skips them and says why)."""
    snap = load_snapshot().get("slots", {})
    out = []
    for c in CAST:
        m = snap.get(c["slot"], {}).get("mapping") or {}
        mode = m.get("mode")
        row = {"slot": c["slot"], "name": c["name"], "kind": c["kind"], "size": c.get("size", 1.0),
               "object": c["object"], "skeleton": c.get("skel_name"), "writer": "gbox.oot_swap",
               **({"mode": mode} if mode else {}), **({"note": c["note"]} if c.get("note") else {})}
        if c.get("refuse") or (snap and c["slot"] in snap and not mode):
            row |= {"status": "not_working", "reason": c.get("refuse") or m.get("reason") or "no mapping on record"}
        out.append(row)
    return out


# ---------------------------------------------------------------- skeleton facts

def skeleton_facts(obj: bytes, off: int) -> dict:
    """Header at `off`: limb count, LOD limb spacing, limbs with a display list, and whether it is a
    FlexSkeletonHeader (the byte after the 8-byte SkeletonHeader = the number of limbs that draw, then 3 pad bytes)."""
    sk = OW.skeleton(obj, off)
    drawn = sum(1 for lb in sk["limbs"] if any(lb["dls"]))
    flex = off + 12 <= len(obj) and 0 < obj[off + 8] <= sk["count"] and abs(obj[off + 8] - drawn) <= 1 and \
        obj[off + 9:off + 12] == b"\0\0\0"                # (LOD skeletons count a far-only list too)
    return {"offset": off, "limbs": sk["count"], "lod": sk["lod"], "limbs_with_dl": drawn,
            "type": "flex" if flex else "normal", "table": sk["table"]}


# ---------------------------------------------------------------- what an actor's code points into its object

def overlay_refs(rom: OW.Rom, actor: int) -> set[int]:
    """Segment-6 addresses the actor's overlay names: data words (tables of lists / textures / animations) and
    lui/addiu pairs in its code (gSPDisplayList(..., gXxxDL), SkelAnime_Init(..., &gXxxSkel))."""
    from . import oot_analysis as A
    from .oot_swap import actor_overlay, actor_table
    cache = rom.__dict__.setdefault("_ovl_refs", {})
    if actor in cache:
        return cache[actor]
    try:
        actor_table(rom)
        ov = actor_overlay(rom, actor)
    except (StopIteration, struct.error, IndexError, KeyError):
        ov = None
    refs = set()
    if ov:
        refs = OW.seg6_words(ov) | {t for _a, t in A.hilo_refs(ov, 0, 0x06000000, 0x07000000)}
    cache[actor] = refs
    return refs


def actor_objects(rom: OW.Rom) -> dict[int, list[str]]:
    """object id -> the actors whose profile (ActorProfile.objectId) names it."""
    from .oot_swap import actor_object
    out: dict[int, list[str]] = {}
    for k, v in names()["actors"].items():
        try:
            oid = actor_object(rom, int(k, 16))
        except (StopIteration, struct.error, IndexError, KeyError):
            oid = None
        if oid is not None and oid > 0:
            out.setdefault(oid, []).append(v)
    return out


# ---------------------------------------------------------------- textures (the bytes besides lists and vertices)

def texture_ranges(obj: bytes, dls, segs: dict | None = None) -> list[tuple[int, int]]:
    """Object offsets [start, end) of every texture and palette the lists load from segment 6 (G_SETTIMG followed by
    G_LOADBLOCK / G_LOADTILE / G_LOADTLUT)."""
    out = []
    for d in dls:
        if not d or d >> 24 != 6:
            continue
        st = OW.run_dl({**(segs or {}), 6: obj}, d)
        timg = None
        for _a, w0, w1 in st["cmds"]:
            c = w0 >> 24
            if c == 0xFD:
                timg = (w1, (w0 >> 19) & 3, (w0 & 0xFFF) + 1)
            elif timg and timg[0] >> 24 == 6:
                a, siz, width = timg[0] & 0xFFFFFF, timg[1], timg[2]
                bits = (4, 8, 16, 32)[siz]
                if c == 0xF3:                              # LoadBlock: lrs + 1 texels of the SETTIMG size
                    n = (((w1 >> 12) & 0xFFF) + 1) * bits // 8
                elif c == 0xF4:                            # LoadTile: rows up to lrt of the image width
                    lrt = (w1 & 0xFFF) >> 2
                    n = (lrt + 1) * width * bits // 8
                elif c == 0xF0:                            # LoadTLUT: count + 1 16-bit entries
                    n = (((w1 >> 14) & 0x3FF) + 1) * 2
                else:
                    continue
                if 0 < n and a + n <= len(obj):
                    out.append((a, a + n))
    return out


def _subtract(rs, minus):
    out = []
    for a, b in OW._merge(rs):
        cur = [(a, b)]
        for ka, kb in minus:
            nxt = []
            for x, y in cur:
                if kb <= x or ka >= y:
                    nxt.append((x, y))
                else:
                    if ka > x:
                        nxt.append((x, ka))
                    if kb < y:
                        nxt.append((kb, y))
            cur = nxt
        out += cur
    return out


def other_skeleton_dls(obj: bytes, off: int) -> list[int]:
    """Limb lists of every OTHER skeleton in the object (Koume / Kotake, Lizalfos / Dinolfos share one): kept."""
    from .oot_swap import find_skeletons
    out = []
    for o in find_skeletons(obj):
        if o != off:
            out += [d for lb in OW.skeleton(obj, o)["limbs"] for d in lb["dls"] if d]
    return out


def npc_regions(rom: OW.Rom, oid: int, off: int, actor_ids=(), textures: bool = True, extra_kept=()) -> dict:
    """The bytes a single-object NPC's new model may overwrite: its limb lists, their vertices and (textures=True) the
    textures / palettes only those lists load - minus anything another skeleton's lists, a list the actors' code names,
    or an address the code holds uses. -> {"regions": [(start, end)], "lists": bytes, "textures": bytes, "kept_lists":
    [...], "refs": n}."""
    obj = rom.object(oid)
    sk = OW.skeleton(obj, off)
    keep = {4: rom.object(OW.OBJECT_GAMEPLAY_KEEP)}
    body = sorted({d for lb in sk["limbs"] for d in lb["dls"] if d})
    refs = set()
    for a in actor_ids:
        refs |= overlay_refs(rom, a)
    refs = {r for r in refs if (r & 0xFFFFFF) < len(obj)} | set(extra_kept)
    others = other_skeleton_dls(obj, off)
    kept = sorted({w for w in refs if w % 8 == 0 and obj[w & 0xFFFFFF] in DL_OPS and w not in body} | set(others))
    starts = set(body) | {a for d in body for a, _n in OW.run_dl({**keep, 6: obj}, d).get("vtx", [])}
    base = OW.reclaimable(obj, body, kept, refs & starts, keep)
    out = list(base)
    tex_bytes = 0
    if textures:
        tb = texture_ranges(obj, body, keep)
        tk = texture_ranges(obj, kept, keep)
        named = [(a, b) for a, b in OW._merge(tb) if any(a <= (r & 0xFFFFFF) < b for r in refs)]
        free = []
        for a, b in _subtract(tb, OW._merge(tk) + named):
            a, b = (a + 15) & ~15, b & ~15
            if b - a >= 0x100:
                free.append((a, b))
        tex_bytes = sum(b - a for a, b in free)
        out = OW._merge(out + free)
        out = [(a, b) for a, b in out if b - a >= 0x100]
    out = sorted((tuple(r) for r in out), key=lambda r: r[0] - r[1])
    return {"regions": out, "lists": sum(b - a for a, b in base), "textures": tex_bytes,
            "kept_lists": [k for k in kept if k not in others], "refs": len(refs)}


def alt_body_dls(rom: OW.Rom, oid: int, off: int, kept_lists, segs: dict | None = None) -> list[tuple[int, int]]:
    """Lists the actor's code draws in place of a limb's own (an open mouth, a turned head, a hand holding something):
    drawn with the body's materials, so after the swap they would show the OLD character. -> [(list offset, limb)]: each
    is branched to that limb's new list. A list counts when most of its triangles use the body's materials; its limb is
    the one whose list shares the most of them."""
    obj = rom.object(oid)
    sk = OW.skeleton(obj, off)
    keep = {**(segs or {}), 4: rom.object(OW.OBJECT_GAMEPLAY_KEEP), 6: obj}
    per_limb = {}
    for i, lb in enumerate(sk["limbs"]):
        mats = set()
        for d in lb["dls"]:
            if d:
                OW.run_dl(keep, d, lambda st, ix, here, w, m=mats: m.add(OW.material(st)[0]))
        if mats:
            per_limb[i] = mats
    body = set().union(*per_limb.values()) if per_limb else set()
    out = []
    for d in kept_lists:
        tris = []
        OW.run_dl(keep, d, lambda st, ix, here, w: tris.append(OW.material(st)[0]))
        if not tris:
            continue
        on = [m for m in tris if m in body]
        if len(on) < 0.5 * len(tris) or all(m is None for m in on):
            continue
        mine = set(on) - {None}
        limb = max(per_limb, key=lambda i: (len(per_limb[i] & mine), -i))
        if per_limb[limb] & mine:
            out.append((d & 0xFFFFFF, limb))
    return out


# ---------------------------------------------------------------- scenes, rooms, object space

def scene_table(rom: OW.Rom) -> tuple[int, int] | None:
    """gSceneTable in `code`: 0x14-byte entries {sceneFile vromStart, vromEnd, titleFile..}; -> (offset, count)."""
    if "_scene_table" not in rom.__dict__:
        code = getattr(rom, "_orig_code", None) or rom.file(rom.v["code"])
        pairs = {(e[0], e[1]) for e in rom.dma}
        hit = None
        for o in range(0, len(code) - 0x14 * 100, 4):
            if struct.unpack_from(">II", code, o) in pairs and \
                    all(struct.unpack_from(">II", code, o + 0x14 * k) in pairs for k in range(100)):
                n = 0
                while o + 0x14 * (n + 1) <= len(code) and struct.unpack_from(">II", code, o + 0x14 * n) in pairs:
                    n += 1
                hit = (o, n)
                break
        rom._scene_table = hit
    return rom._scene_table


def _commands(data: bytes, off: int) -> list[tuple[int, int, int]]:
    out = []
    while off + 8 <= len(data) and len(out) < 64:
        c, d1, _p, d2 = struct.unpack_from(">BBHI", data, off)
        out.append((c, d1, d2))
        if c == 0x14:
            break
        off += 8
    return out


def _headers(data: bytes) -> list:
    """[main header commands, alternate layer 1, 2, ... (None = not set)] of a scene or room file."""
    main = _commands(data, 0)
    hs = [main]
    for c, _d1, d2 in main:
        if c == 0x18:
            o = d2 & 0xFFFFFF
            for k in range(20):
                if o + 4 * k + 4 > len(data):
                    break
                p = struct.unpack_from(">I", data, o + 4 * k)[0]
                if p == 0:
                    hs.append(None)
                elif p >> 24 in (2, 3) and (p & 0xFFFFFF) + 8 <= len(data):
                    hs.append(_commands(data, p & 0xFFFFFF))
                else:
                    break
    return hs


def contexts(rom: OW.Rom) -> list[dict]:
    """Every (scene, layer, room) the game can be in, with the objects in object space there and the bytes left:
    {scene, name, layer, room, age, objects [ids, Link's included], free}. Layers 0/1 are child day/night, 2/3 adult,
    4+ cutscenes (either age: both Link objects counted)."""
    if "_contexts" in rom.__dict__:
        return rom._contexts
    st = scene_table(rom)
    out = []
    if st is None:
        rom._contexts = out
        return out
    code = getattr(rom, "_orig_code", None) or rom.file(rom.v["code"])
    sizes: dict[int, int] = {}

    def size(oid):
        if oid not in sizes:
            try:
                sizes[oid] = (len(rom.object(oid)) + 15) & ~15
            except (StopIteration, struct.error, IndexError):
                sizes[oid] = 0
        return sizes[oid]
    base0 = size(OW.OBJECT_GAMEPLAY_KEEP)
    for si in range(st[1]):
        vs, _ve = struct.unpack_from(">II", code, st[0] + 0x14 * si)
        try:
            sc = rom.file(rom.index_of_vrom(vs))
        except StopIteration:
            continue
        hs = _headers(sc)
        rooms_cache: dict[int, list] = {}
        for li, h in enumerate(hs):
            if h is None:
                continue
            rl = next(((d1, d2) for c, d1, d2 in h if c == 0x04), None)
            keep = next((d2 & 0xFFFF for c, _d1, d2 in h if c == 0x07), 0)
            if not rl:
                continue
            age = "child" if li in (0, 1) else "adult" if li in (2, 3) else "either"
            links = [LINK_OBJECTS[age]] if age != "either" else list(LINK_OBJECTS.values())
            space = SPACE if (si == 0x4F and li == 4) else SPACE_SCENES.get(si, SPACE)
            for r in range(rl[0]):
                o = (rl[1] & 0xFFFFFF) + 8 * r
                if o + 8 > len(sc):
                    break
                rvs, _rve = struct.unpack_from(">II", sc, o)
                if rvs not in rooms_cache:
                    try:
                        rd = rom.file(rom.index_of_vrom(rvs))
                        rooms_cache[rvs] = [rd, _headers(rd)]
                    except StopIteration:
                        rooms_cache[rvs] = None
                if not rooms_cache[rvs]:
                    continue
                rd, rhs = rooms_cache[rvs]
                rh = rhs[li] if li < len(rhs) and rhs[li] is not None else rhs[0]
                ol = next(((d1, d2) for c, d1, d2 in rh if c == 0x0B), (0, 0))
                ids = list(struct.unpack_from(f">{ol[0]}h", rd, ol[1] & 0xFFFFFF)) if ol[0] and \
                    (ol[1] & 0xFFFFFF) + 2 * ol[0] <= len(rd) else []
                used = base0 + (size(keep) if keep else 0) + max(size(x) for x in links) + sum(size(i) for i in ids)
                out.append({"scene": si, "name": SCENES[si] if si < len(SCENES) else f"scene {si:#x}", "layer": li,
                            "room": r, "age": age, "objects": ids + links, "free": space - used})
    rom._contexts = out
    return out


def where(rom: OW.Rom, oid: int) -> list[str]:
    """Scene names whose rooms load the object."""
    seen = []
    for c in contexts(rom):
        if oid in c["objects"] and c["name"] not in seen and oid not in LINK_OBJECTS.values():
            seen.append(c["name"])
    return seen


def growth_plan(rom: OW.Rom, caps: dict[int, int], reserve: int = RESERVE, cutscenes: bool = False) -> dict:
    """caps {object id: the most it may grow} -> {"allow": {object id: bytes}, "tight": [rooms that cut an
    allowance]}. Every room's objects together may grow by what its object list leaves free minus `reserve`; where
    the caps don't fit, the room's objects are cut in proportion (repeated until every room fits). Gameplay layers
    (child / adult, day / night) always count; cutscene layers (4+: the ending's Lon Lon Ranch and Chamber of the Sages
    shots load a dozen characters into ~20 KB) only with cutscenes=True - otherwise space_report lists the ones the
    build overfills."""
    # max-min fair ("water filling"): every object grows by the same amount until a room is full or it reaches its
    # cap; the objects of a full room stop there, the rest keep growing
    allow = {o: 0.0 for o in caps}
    ctx = [(sorted({o for o in c["objects"] if o in caps}), max(0, c["free"] - reserve), c) for c in contexts(rom)
           if any(o in caps for o in c["objects"]) and (cutscenes or c["layer"] < 4)]
    frozen = {o for o, cap in caps.items() if cap <= 0}
    tight = {}
    while len(frozen) < len(caps):
        active = [o for o in caps if o not in frozen]
        step = min(caps[o] - allow[o] for o in active)
        for objs, room, _c in ctx:
            n = sum(1 for o in objs if o not in frozen)
            if n:
                step = min(step, (room - sum(allow[o] for o in objs)) / n)
        step = max(step, 0.0)
        for o in active:
            allow[o] += step
        for o in active:
            if caps[o] - allow[o] < 1:
                frozen.add(o)
        for objs, room, c in ctx:
            if any(o not in frozen for o in objs) and room - sum(allow[o] for o in objs) < 1:
                frozen.update(objs)
                tight[(c["name"], c["layer"], c["room"])] = room
    return {"allow": {o: int(a) & ~0xF for o, a in allow.items()},
            "tight": [{"scene": n, "layer": l, "room": r, "free_kb": room // 1024}
                      for (n, l, r), room in sorted(tight.items())]}


def space_report(rom: OW.Rom, growth: dict[int, int]) -> list[dict]:
    """Rooms where the grown objects no longer fit the object space: [{scene, layer, room, over (bytes), cutscene}]."""
    out = []
    for c in contexts(rom):
        g = sum(growth.get(o, 0) for o in set(c["objects"]))
        if g and g > c["free"]:
            out.append({"scene": c["name"], "layer": c["layer"], "room": c["room"], "over": g - c["free"],
                        "cutscene": c["layer"] >= 4})
    return out


# ---------------------------------------------------------------- slot -> what to write

def slot_spec(rom: OW.Rom, slot: str) -> dict:
    """A catalogue slot on this ROM -> {"kind": "link", ...} | {"kind": "npc", object, skel, actors, actor_ids, group,
    regions, branch_dls, ...}. Raises ValueError with the reason for a slot that can't be rebuilt."""
    c = BY_SLOT.get(slot)
    if c is None:
        raise LookupError(f"no OoT cast slot {slot!r}; slots: {', '.join(BY_SLOT)}")
    if c.get("refuse"):
        raise ValueError(c["refuse"])
    if c["kind"] == "player":
        return {"kind": "link", "ages": ("adult", "child"), "name": "Link", "slot": slot}
    oid = object_id(c["object"])
    if oid is None:
        raise ValueError(f"{c['object']} isn't in this ROM's object table")
    obj = rom.object(oid)
    if c["skel"] + 8 > len(obj):
        raise ValueError(f"{c['object']} ({len(obj):#x} bytes) has no skeleton at {c['skel']:#x} in this ROM")
    try:
        f = skeleton_facts(obj, c["skel"])
    except struct.error as e:
        raise ValueError(f"{c['object']}: no skeleton header at {c['skel']:#x} ({e})") from None
    if f["limbs"] < 2 or f["limbs_with_dl"] < 1:
        raise ValueError(f"{c['object']}: the header at {c['skel']:#x} isn't a drawable skeleton")
    aids = [a for a in (actor_id(n) for n in c["actors"]) if a is not None]
    spec = {"kind": "npc", "slot": slot, "name": c["name"], "actor": c["actors"][0], "actor_id": aids[0] if aids else None,
            "actor_ids": aids, "object": oid, "skel": c["skel"], "frame": None, "facts": f,
            "roles_hint": c.get("roles"), "shape": c.get("shape", "humanoid")}
    anims = [a for a in (object_id(n) for n in c.get("anim", [])) if a is not None]
    group = {"objects": [oid], "skels": [(oid, c["skel"])], "skel": (oid, c["skel"]), "anim_objects": anims}
    mine_heads = []
    if c.get("group"):                                    # En_Ko: the head list the actor swaps in, Fado's head object
        from .oot_swap import GROUPS
        g = GROUPS[(c["group"][0], oid)]
        mine_heads = [(o, off) for o, off in g["head_dls"] if o == oid]
        group |= {"head_limb": g["head_limb"], "head_dls": mine_heads, "anim_objects": list(g["anim_objects"]),
                  "extra_heads": [(o, off) for o, off in g["head_dls"] if o != oid], "note": g.get("note", "")}
    r = npc_regions(rom, oid, c["skel"], aids, extra_kept=[0x06000000 | off for _o, off in mine_heads])
    heads = {off for _o, off in mine_heads}
    alts = [(o, limb) for o, limb in alt_body_dls(rom, oid, c["skel"], r["kept_lists"]) if o not in heads]
    group["branch_dls"] = [(oid, o, limb) for o, limb in alts]
    spec |= {"group": group, "regions": r["regions"], "reclaim": {k: r[k] for k in ("lists", "textures")},
             "objects": [oid] + [o for o, _off in group.get("extra_heads", [])]}
    return spec


def check_object(obj: bytes, off: int, segs: dict | None = None) -> list[str]:
    """A rebuilt object read back: every limb list of the skeleton at `off` must lie in the object, end, and load
    vertices / textures / sub-lists only from inside it. -> problems (empty = fine)."""
    sk = OW.skeleton(obj, off)
    out = []
    for i, lb in enumerate(sk["limbs"]):
        for d in lb["dls"]:
            if not d:
                continue
            if d >> 24 != 6 or (d & 0xFFFFFF) + 8 > len(obj):
                out.append(f"limb {i}: list {d:#010x} outside the object ({len(obj):#x} bytes)")
                continue
            st = OW.run_dl({**(segs or {}), 6: obj}, d)
            for _a, w0, w1 in st["cmds"]:
                if w0 >> 24 in (0x01, 0xDE, 0xFD) and w1 >> 24 == 6 and (w1 & 0xFFFFFF) >= len(obj):
                    out.append(f"limb {i}: {w0 >> 24:#04x} reads {w1:#010x} past the object's end")
            if not st["cmds"] or st["cmds"][-1][1] >> 24 not in (0xDF, 0xDE):
                out.append(f"limb {i}: list {d:#010x} runs off the object without an end")
    return out[:20]


# ---------------------------------------------------------------- the snapshot

def snapshot(rom: OW.Rom, mapping: bool = True) -> dict:
    """Every catalogue slot measured on this ROM, plus the scan of every actor -> object -> skeleton."""
    import hashlib
    from . import oot_swap as SW
    N = names()
    slots = {}
    for c in CAST:
        row = {"object": c["object"], "skeleton": c.get("skel_name")}
        try:
            spec = slot_spec(rom, c["slot"])
        except (ValueError, LookupError) as e:
            row["mapping"] = {"mode": None, "reason": str(e)}
            slots[c["slot"]] = row
            continue
        if spec["kind"] == "link":
            row |= {"object_id": OW.OBJECT_LINK_BOY, "mapping": {"mode": "retarget", "roles": "LINK_ROLES"}}
            slots[c["slot"]] = row
            continue
        oid = spec["object"]
        row |= {"object_id": oid, "dma_index": rom.object_index(oid), "object_bytes": len(rom.object(oid)),
                "skeleton_facts": {k: v for k, v in spec["facts"].items() if k != "table"},
                "type_matches_decomp": spec["facts"]["type"] == c["type"],
                "actors": {n: {"id": actor_id(n), "names_skeleton": (0x06000000 | spec["skel"]) in
                               overlay_refs(rom, actor_id(n)) if actor_id(n) is not None else False}
                           for n in c["actors"]},
                "reclaim": spec.get("reclaim"), "branch_dls": len(spec["group"].get("branch_dls", [])),
                "scenes": where(rom, oid)}
        if mapping:
            try:
                t = SW.slot_target(rom, spec)
                row["mapping"] = {"mode": t["mode"], "roles": {r: int(j) for r, j in t["roles"].items()},
                                  "pose": t.get("pose"), "height": round(float(t["height"]), 1)}
            except ValueError as e:
                row["mapping"] = {"mode": None, "reason": str(e)}
        slots[c["slot"]] = row
    scan = {}
    for oid, actors in sorted(actor_objects(rom).items()):
        if oid <= 3:
            continue
        try:
            obj = rom.object(oid)
        except (StopIteration, struct.error, IndexError):
            continue
        sks = SW.find_skeletons(obj)
        if sks:
            scan[N["objects"].get(hex(oid), hex(oid))] = {
                "id": oid, "actors": actors, "bytes": len(obj),
                "skeletons": [{k: v for k, v in skeleton_facts(obj, o).items() if k != "table"} for o in sks]}
    return {"rom": {"version": rom.version, "md5": hashlib.md5(rom.data).hexdigest()}, "slots": slots,
            "scan": scan, "scenes": len(SCENES), "scene_table": scene_table(rom)}


def main(argv=None) -> int:
    import argparse
    from . import n64_rom
    ap = argparse.ArgumentParser(description="OoT cast catalogue measured on a ROM")
    ap.add_argument("rom")
    ap.add_argument("--write", action="store_true", help=f"refresh {SNAPSHOT.name}")
    ap.add_argument("--no-mapping", action="store_true")
    a = ap.parse_args(argv)
    rom = OW.Rom(n64_rom.read(a.rom))
    snap = snapshot(rom, not a.no_mapping)
    text = json.dumps(snap, indent=1, default=str)
    if a.write:
        SNAPSHOT.write_text(text + "\n")
    for s, r in snap["slots"].items():
        m = r.get("mapping") or {}
        print(f"{s:22} {r['object']:18} {m.get('mode') or 'REFUSED':8} "
              f"{(r.get('skeleton_facts') or {}).get('limbs', ''):>3} {m.get('reason', '')[:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
