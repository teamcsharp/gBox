"""Zelda RAM tables for gbox/zelda_tool.py: per game, items (name -> how to give it), equip buttons, hearts, rupees.

Addresses are the console's own (SNES $7Exxxx WRAM, GB $Cxxx-$Dxxx, NES $0000-$07FF, GBA 0x02/0x03xxxxxx, N64 0x80xxxxxx);
zelda_tool.Mem translates them for cores without a libretro memory map. Item spec keys:
  k   kind: "set" byte a = v (have: byte >= v, or == v with ex=True) | "cnt" counter a (n bytes, bcd, default d)
            | "or" byte a |= m | "slot" item id v lives in one of the game's inventory slots (LA / Oracles)
            | "inv2" Minish Cap 2-bit inventory entry for item id v | "oot"/"mm" handled by the N64 code
  also  more specs applied with it (ammo, levels).   menu  ALttP Y-menu index.   id  value an equip slot holds.
Sources per game are in the comments; every address marked (live) was read back on the Spark with the item on screen.
"""

def S(a, v, **kw):
    return {"k": "set", "a": a, "v": v, **kw}


def N(a, d, n=1, bcd=False, **kw):
    return {"k": "cnt", "a": a, "d": d, "n": n, "bcd": bcd, **kw}


def O(a, m, **kw):
    return {"k": "or", "a": a, "m": m, **kw}


def SL(v, *also, **kw):
    return {"k": "slot", "v": v, "also": list(also), **kw}


def I2(v, *also, **kw):
    return {"k": "inv2", "v": v, "also": list(also), **kw}


# ---------------------------------------------------------------------------------------------------------------------
# A Link to the Past (SNES, USA/EU). SRAM mirror $7EF340.. (Data Crystal RAM map, zelda3 disassembly, libretro .cht);
# Y item = $7E0202 (menu index 1-20). Verified live (Spark, snes9x): hookshot give + Y equip, HUD after menu close.
_Z3 = 0x7EF300
ALTTP_ITEMS = {
    "bow": S(_Z3 + 0x40, 2, menu=1, also=[N(_Z3 + 0x77, 30)]), "silver arrows": S(_Z3 + 0x40, 4, menu=1, also=[N(_Z3 + 0x77, 30)]),
    "boomerang": S(_Z3 + 0x41, 1, menu=2), "magic boomerang": S(_Z3 + 0x41, 2, menu=2),
    "hookshot": S(_Z3 + 0x42, 1, menu=3), "bombs": N(_Z3 + 0x43, 10, menu=4),
    "mushroom": S(_Z3 + 0x44, 1, ex=True, menu=5), "magic powder": S(_Z3 + 0x44, 2, ex=True, menu=5),
    "fire rod": S(_Z3 + 0x45, 1, menu=6), "ice rod": S(_Z3 + 0x46, 1, menu=7), "bombos medallion": S(_Z3 + 0x47, 1, menu=8),
    "ether medallion": S(_Z3 + 0x48, 1, menu=9), "quake medallion": S(_Z3 + 0x49, 1, menu=10), "lamp": S(_Z3 + 0x4A, 1, menu=11),
    "magic hammer": S(_Z3 + 0x4B, 1, menu=12), "shovel": S(_Z3 + 0x4C, 1, ex=True, menu=13), "flute": S(_Z3 + 0x4C, 3, ex=True, menu=13),
    "bug catching net": S(_Z3 + 0x4D, 1, menu=14), "book of mudora": S(_Z3 + 0x4E, 1, menu=15),
    "bottle": {"k": "fn", "fn": "alttp_bottle", "v": 2, "menu": 16},
    "red potion": {"k": "fn", "fn": "alttp_bottle", "v": 3, "menu": 16}, "green potion": {"k": "fn", "fn": "alttp_bottle", "v": 4, "menu": 16},
    "blue potion": {"k": "fn", "fn": "alttp_bottle", "v": 5, "menu": 16}, "fairy": {"k": "fn", "fn": "alttp_bottle", "v": 6, "menu": 16},
    "bee": {"k": "fn", "fn": "alttp_bottle", "v": 7, "menu": 16}, "good bee": {"k": "fn", "fn": "alttp_bottle", "v": 8, "menu": 16},
    "cane of somaria": S(_Z3 + 0x50, 1, menu=17), "cane of byrna": S(_Z3 + 0x51, 1, menu=18), "magic cape": S(_Z3 + 0x52, 1, menu=19),
    "magic mirror": S(_Z3 + 0x53, 2, menu=20),
    "power glove": S(_Z3 + 0x54, 1), "titans mitt": S(_Z3 + 0x54, 2), "pegasus boots": S(_Z3 + 0x55, 1, also=[O(_Z3 + 0x79, 0x04)]),
    "zoras flippers": S(_Z3 + 0x56, 1, also=[O(_Z3 + 0x79, 0x02)]), "moon pearl": S(_Z3 + 0x57, 1),
    "fighters sword": S(_Z3 + 0x59, 1), "master sword": S(_Z3 + 0x59, 2), "tempered sword": S(_Z3 + 0x59, 3), "golden sword": S(_Z3 + 0x59, 4),
    "fighters shield": S(_Z3 + 0x5A, 1), "fire shield": S(_Z3 + 0x5A, 2), "mirror shield": S(_Z3 + 0x5A, 3),
    "green mail": S(_Z3 + 0x5B, 0, ex=True), "blue mail": S(_Z3 + 0x5B, 1, ex=True), "red mail": S(_Z3 + 0x5B, 2, ex=True),
    "arrows": N(_Z3 + 0x77, 30), "half magic": S(_Z3 + 0x7B, 1), "magic": N(_Z3 + 0x6E, 0x80),
    "bomb upgrade": N(_Z3 + 0x70, 7), "arrow upgrade": N(_Z3 + 0x71, 7),
    "all pendants": O(_Z3 + 0x74, 0x07), "all crystals": O(_Z3 + 0x7A, 0x7F),
}
_Z3_SOLID = {0x01, 0x02, 0x03, 0x26, 0x43}            # dungeon tile attributes that block (zelda3 tile_detect.c StandardCollision)


def _alttp_noclip(m, on):
    """Dungeons: blank the solid tile attributes in the room's attribute table ($7F2000-$7F3FFF, rebuilt per room) so
    pits/water/stairs keep working. Overworld (attributes come from ROM): the retail debug flag $7E037F
    (zelda3 cheatWalkThroughWalls) - every tile acts as floor there."""
    if not on:
        m.poke(0x7E037F, b"\x00")
        return
    if m.u8(0x7E001B):                                      # indoors
        if m.u8(0x7E037F):
            m.poke(0x7E037F, b"\x00")
        tbl = m.rd(0x7F2000, 0x2000)
        if any(b in _Z3_SOLID for b in tbl):
            m.poke(0x7F2000, bytes(0 if b in _Z3_SOLID else b for b in tbl), tbl)
    elif m.u8(0x7E037F) != 1:
        m.poke(0x7E037F, b"\x01")


ALTTP = dict(
    name="A Link to the Past", platforms=("snes",), match=r"link to the past", exclude=r"four swords",
    ready=(0x7E0010, (0x07, 0x09, 0x0B, 0x0E)),           # main module: dungeon / overworld / special overworld / menu
    items=ALTTP_ITEMS,
    aliases={"sword": "fighters sword", "shield": "fighters shield", "hammer": "magic hammer", "net": "bug catching net",
             "book": "book of mudora", "mirror": "magic mirror", "cape": "magic cape", "gloves": "power glove", "glove": "power glove",
             "titans mitts": "titans mitt", "boots": "pegasus boots", "flippers": "zoras flippers", "pearl": "moon pearl",
             "bombos": "bombos medallion", "ether": "ether medallion", "quake": "quake medallion", "somaria": "cane of somaria",
             "byrna": "cane of byrna", "powder": "magic powder", "silver bow": "silver arrows", "red boomerang": "magic boomerang",
             "blue boomerang": "boomerang", "ocarina": "flute", "lantern": "lamp", "tunic": "blue mail", "armor": "blue mail",
             "blue tunic": "blue mail", "red tunic": "red mail", "potion": "red potion", "empty bottle": "bottle",
             "pendants": "all pendants", "crystals": "all crystals", "red shield": "fire shield"},
    equip={"y": ("menu", 0x7E0202)}, default_button="y",
    refresh=("start", "start"),                            # the Y box on the HUD redraws when the menu closes
    refresh_when=(0x7E0010, (0x07, 0x09)),                 # only from plain gameplay (module 07/09, submodule $11 == 0)
    all=["bow", "silver arrows", "magic boomerang", "hookshot", "bombs", "magic powder", "fire rod", "ice rod", "bombos medallion",
         "ether medallion", "quake medallion", "lamp", "magic hammer", "flute", "bug catching net", "book of mudora", "bottle",
         "red potion", "green potion", "fairy", "cane of somaria", "cane of byrna", "magic cape", "magic mirror", "titans mitt",
         "pegasus boots", "zoras flippers", "moon pearl", "golden sword", "mirror shield", "red mail", "half magic", "magic",
         "bomb upgrade", "arrow upgrade"],
    max_counts={"bombs": 50, "arrows": 70},
    unrestrict=dict(give=["moon pearl", "pegasus boots", "zoras flippers", "titans mitt"],
                    writes=[O(_Z3 + 0x79, 0xFE)],          # $7EF379 abilities: read/talk/lift/pull/dash/swim (cheat 'all abilities' 6F)
                    note="no Bunny form in the Dark World (Moon Pearl), dash, swim, lift anything"),
    hearts=dict(max=(_Z3 + 0x6C, 8), cur=(_Z3 + 0x6D, 8), cap=20),
    rupees=dict(addr=(_Z3 + 0x60, _Z3 + 0x62), fmt="u16le", cap=999),
    noclip=[("tick", _alttp_noclip)],
    noclip_note="dungeons: walls/blocks/doors only; overworld: the game's debug walk-through-walls flag (water and pits act as floor there)",
)

# ---------------------------------------------------------------------------------------------------------------------
# Link's Awakening (GB) / DX (GBC): zladx disassembly src/constants/memory/wram.asm + libretro GameShark codes; same WRAM
# on GB and DX and all revisions. B = $DB00, A = $DB01, subscreen $DB02-$DB0B. Counts are BCD.
LA_ITEMS = {
    "sword": SL(0x01, S(0xDB4E, 1)), "l2 sword": SL(0x01, S(0xDB4E, 2)), "bombs": SL(0x02, N(0xDB4D, 0x30, bcd=True)),
    "power bracelet": SL(0x03, S(0xDB43, 1)), "l2 power bracelet": SL(0x03, S(0xDB43, 2)),
    "shield": SL(0x04, S(0xDB44, 1)), "mirror shield": SL(0x04, S(0xDB44, 2)), "bow": SL(0x05, N(0xDB45, 0x30, bcd=True)),
    "hookshot": SL(0x06), "magic rod": SL(0x07), "pegasus boots": SL(0x08), "ocarina": SL(0x09, O(0xDB49, 0x07)),
    "rocs feather": SL(0x0A), "shovel": SL(0x0B), "magic powder": SL(0x0C, N(0xDB4C, 0x20, bcd=True)), "boomerang": SL(0x0D),
    "flippers": S(0xDB0C, 1), "secret medicine": S(0xDB0D, 1), "tail key": S(0xDB11, 1), "angler key": S(0xDB12, 1),
    "face key": S(0xDB13, 1), "bird key": S(0xDB14, 1), "slime key": S(0xDB15, 6, ex=True), "golden leaves": N(0xDB15, 5),
    "toadstool": S(0xDB4B, 1), "seashells": N(0xDB0F, 0x20, bcd=True), "arrows": N(0xDB45, 0x30, bcd=True),
    "all songs": O(0xDB49, 0x07), "all instruments": {"k": "fn", "fn": "la_instruments"},
    "red tunic": S(0xDC0F, 1, ex=True, dx=True), "blue tunic": S(0xDC0F, 2, ex=True, dx=True), "green tunic": S(0xDC0F, 0, ex=True, dx=True),
    **{n: S(0xDB0E, v, ex=True, also=[S(0xDB7F, 0, ex=True)]) for v, n in enumerate(
        ["yoshi doll", "ribbon", "dog food", "bananas", "stick", "honeycomb", "pineapple", "hibiscus", "letter", "broom",
         "fishing hook", "mermaid necklace", "mermaid scale", "magnifying lens"], 1)},
}
LA = dict(
    name="Link's Awakening", platforms=("gb", "gbc"), match=r"link'?s awakening|yume o miru shima",
    ready=(0xDB95, (0x0B, 0x0C)),                          # wGameplayType: world / inventory subscreen
    items=LA_ITEMS, slots=tuple(range(0xDB00, 0xDB0C)), store=tuple(range(0xDB02, 0xDB0C)),
    aliases={"magic wand": "magic rod", "fire rod": "magic rod", "rod": "magic rod", "feather": "rocs feather", "boots": "pegasus boots",
             "bracelet": "power bracelet", "power glove": "l2 power bracelet", "gloves": "l2 power bracelet", "flute": "ocarina",
             "powder": "magic powder", "medicine": "secret medicine", "potion": "secret medicine", "bow and arrow": "bow",
             "level 2 sword": "l2 sword", "master sword": "l2 sword", "shells": "seashells", "leaves": "golden leaves",
             "necklace": "mermaid necklace", "scale": "mermaid scale", "lens": "magnifying lens", "mushroom": "toadstool",
             "instruments": "all instruments", "songs": "all songs"},
    equip={"b": ("slot", 0xDB00), "a": ("slot", 0xDB01)}, default_button="b",
    all=["l2 sword", "bombs", "l2 power bracelet", "mirror shield", "bow", "hookshot", "magic rod", "pegasus boots", "ocarina",
         "rocs feather", "shovel", "magic powder", "flippers", "secret medicine", "tail key", "angler key", "face key",
         "bird key", "toadstool", "all songs"],
    max_counts={"bombs": 60, "bow": 60, "arrows": 60, "magic powder": 40},     # decimal; stored BCD
    max_writes=[S(0xDB76, 0x40), S(0xDB77, 0x60), S(0xDB78, 0x60)],   # wMaxMagicPowder / wMaxBombs / wMaxArrows (BCD)
    unrestrict=dict(give=["flippers", "l2 power bracelet", "pegasus boots", "rocs feather"],
                    note="LA has no item restrictions besides the equipment that opens paths: swim, lift, dash, jump"),
    hearts=dict(max=(0xDB5B, 1), cur=(0xDB5A, 8), cap=14, bump=0xDB93),      # wMaxHearts (count) / wHealth (8 per heart)
    rupees=dict(addr=(0xDB5D,), fmt="bcd_la", cap=999, bump=0xDB90),
    noclip=[("hold", 0xC10A, "10", "00")],            # libretro GameShark "Walk Thru Walls" 01100AC1 (same WRAM on GB/DX/revs)
    noclip_note="Link walks through walls (and into neighbouring rooms); pits still work",
)

# ---------------------------------------------------------------------------------------------------------------------
# The Minish Cap (GBA, USA): zeldaret/tmc include/save.h + linker.ld: gSave = 0x02002A40, Stats at +0xA8,
# inventory 2 bits per item id at gSave+0xF2 (0x02002B32), equipped A/B = 0x02002AF4/5 (item ids 1..0x1F), health 8/heart.
_MC = 0x02002AE8
MC_ITEMS = {
    "smiths sword": I2(0x01), "white sword": I2(0x02), "white sword 3": I2(0x03), "white sword 4": I2(0x04), "four sword": I2(0x06),
    "bombs": I2(0x07, N(_MC + 0x04, 10)), "remote bombs": I2(0x08, N(_MC + 0x04, 10)), "bow": I2(0x09, N(_MC + 0x05, 30)),
    "light arrows": I2(0x0A, N(_MC + 0x05, 30)), "boomerang": I2(0x0B), "magic boomerang": I2(0x0C), "shield": I2(0x0D),
    "mirror shield": I2(0x0E), "lantern": I2(0x0F), "gust jar": I2(0x11), "cane of pacci": I2(0x12), "mole mitts": I2(0x13),
    "rocs cape": I2(0x14), "pegasus boots": I2(0x15), "ocarina of wind": I2(0x17),
    "bottle": {"k": "fn", "fn": "mc_bottle", "v": 0x20}, "red potion": {"k": "fn", "fn": "mc_bottle", "v": 0x24},
    "blue potion": {"k": "fn", "fn": "mc_bottle", "v": 0x25}, "fairy": {"k": "fn", "fn": "mc_bottle", "v": 0x28},
    "milk": {"k": "fn", "fn": "mc_bottle", "v": 0x22}, "mineral water": {"k": "fn", "fn": "mc_bottle", "v": 0x27},
    "grip ring": I2(0x44), "power bracelets": I2(0x45), "flippers": I2(0x46), "kinstone bag": I2(0x67),
    "big wallet": S(_MC + 0x00, 3), "big bomb bag": S(_MC + 0x06, 3), "big quiver": S(_MC + 0x07, 3),
    "arrows": N(_MC + 0x05, 30), "shells": N(_MC + 0x1A, 100, n=2),
    "all scrolls": {"k": "raw", "a": 0x02002B44, "data": "5555"},
}
MC = dict(
    name="The Minish Cap", platforms=("gba",), match=r"minish cap|fushigi no boushi",
    ready=(0x03001002, (0x02,)),                           # gMain.task == TASK_GAME
    items=MC_ITEMS, inv2=0x02002B32,
    aliases={"sword": "smiths sword", "white sword 2": "white sword", "jar": "gust jar", "cane": "cane of pacci", "pacci": "cane of pacci",
             "mitts": "mole mitts", "cape": "rocs cape", "feather": "rocs cape", "boots": "pegasus boots", "ocarina": "ocarina of wind",
             "flute": "ocarina of wind", "bracelet": "power bracelets", "power bracelet": "power bracelets", "wallet": "big wallet",
             "bomb bag": "big bomb bag", "quiver": "big quiver", "light arrow": "light arrows", "magic bow": "light arrows",
             "lamp": "lantern", "kinstones": "kinstone bag", "seashells": "shells", "scrolls": "all scrolls", "sword skills": "all scrolls"},
    equip={"a": ("id", 0x02002AF4), "b": ("id", 0x02002AF5)}, default_button="b",
    all=["four sword", "remote bombs", "bombs", "light arrows", "magic boomerang", "mirror shield", "lantern", "gust jar",
         "cane of pacci", "mole mitts", "rocs cape", "pegasus boots", "ocarina of wind", "bottle", "red potion", "fairy",
         "grip ring", "power bracelets", "flippers", "kinstone bag", "big wallet", "big bomb bag", "big quiver", "all scrolls"],
    max_counts={"bombs": 99, "remote bombs": 99, "bow": 99, "light arrows": 99, "arrows": 99},
    unrestrict=dict(give=["grip ring", "power bracelets", "flippers", "pegasus boots", "rocs cape", "mole mitts"],
                    note="Minish Cap has no item restrictions besides the gear that opens paths (climb, lift, swim, dash, jump, dig)"),
    hearts=dict(max=(_MC + 0x03, 8), cur=(_MC + 0x02, 8), cap=20),
    rupees=dict(addr=(_MC + 0x18,), fmt="u16le", cap=999, wallet=_MC + 0x00),
    # tmc include/map.h MapLayer.collisionData (+0x2004, 0x1000 bytes) of gMapBottom 0x02025EB0 / gMapTop 0x0200B650:
    # 0 = no collision; reloaded per room, so it's held. Pits/water/ledges use actTiles (separate) and keep working.
    noclip=[("zero", 0x02027EB4, 0x1000), ("zero", 0x0200D654, 0x1000)],
    noclip_note="walls come back on the next room load after switching off",
)


def TF(t):
    return {"k": "tf", "v": t}


# ---------------------------------------------------------------------------------------------------------------------
# The Legend of Zelda (NES / FDS; the GBA Classic NES Series keeps NES RAM at 0x03007000): aldonunez/zelda1-disassembly
# Variables.inc (Items = $0657.., SelectedItemSlot $0656), Data Crystal, libretro AR codes. The B box redraws every frame.
def _z1_noclip(m, on):
    """$034A ObjectFirstUnwalkableTile (zelda1-disassembly Variables.inc; reset per room to $89 overworld / $78 dungeon)."""
    want = 0xFF if on else (0x89 if m.u8(0x10) == 0 else 0x78)
    if m.u8(0x34A) != want:
        m.poke(0x34A, bytes([want]))


Z1_ITEMS = {
    "wooden sword": S(0x657, 1), "white sword": S(0x657, 2), "magical sword": S(0x657, 3),
    "bombs": N(0x658, 8, menu=1), "wooden arrow": S(0x659, 1, menu=2), "silver arrow": S(0x659, 2, menu=2),
    "bow": S(0x65A, 1, menu=2, also=[S(0x659, 1, up=True)]), "blue candle": S(0x65B, 1, menu=4), "red candle": S(0x65B, 2, menu=4),
    "recorder": S(0x65C, 1, menu=5), "food": S(0x65D, 1, menu=6), "blue potion": S(0x65E, 1, menu=7),
    "red potion": S(0x65E, 2, menu=7), "magic rod": S(0x65F, 1, menu=8), "raft": S(0x660, 1), "book of magic": S(0x661, 1),
    "blue ring": S(0x662, 1), "red ring": S(0x662, 2), "stepladder": S(0x663, 1), "magic key": S(0x664, 1),
    "power bracelet": S(0x665, 1), "letter": S(0x666, 1, menu=7), "boomerang": S(0x674, 1, menu=0),
    "magical boomerang": S(0x675, 1, menu=0), "magic shield": S(0x676, 1), "keys": N(0x66E, 5),
    "bomb upgrade": S(0x67C, 0x10), "triforce": O(0x671, 0xFF), "all maps": O(0x668, 0xFF), "all compasses": O(0x667, 0xFF),
}
Z1 = dict(
    name="The Legend of Zelda", platforms=("nes", "fds"), match=r"^(the )?legend of zelda(, the)?( \(|$)|zelda no densetsu - the hyrule|zelda i - the legend",
    ready=(0x0012, (0x05, 0x09, 0x0A, 0x0B, 0x0C)),       # GameMode: play / cellar / cave
    items=Z1_ITEMS,
    aliases={"sword": "wooden sword", "wood sword": "wooden sword", "master sword": "magical sword", "magic sword": "magical sword",
             "arrows": "wooden arrow", "silver arrows": "silver arrow", "candle": "blue candle", "whistle": "recorder",
             "flute": "recorder", "ocarina": "recorder", "bait": "food", "meat": "food", "potion": "blue potion", "wand": "magic rod",
             "rod": "magic rod", "book": "book of magic", "ring": "blue ring", "ladder": "stepladder", "bracelet": "power bracelet",
             "magic boomerang": "magical boomerang", "shield": "magic shield", "key": "keys", "bomb bag": "bomb upgrade"},
    equip={"b": ("menu", 0x0656)}, default_button="b",
    all=["magical sword", "bomb upgrade", "bombs", "silver arrow", "bow", "red candle", "recorder", "food", "red potion",
         "magic rod", "raft", "book of magic", "red ring", "stepladder", "magic key", "power bracelet", "boomerang",
         "magical boomerang", "magic shield"],
    max_counts={"bombs": 16, "keys": 9},
    unrestrict=dict(give=["stepladder", "raft", "power bracelet", "magic key"],
                    note="Zelda 1 has no item restrictions; ladder, raft, bracelet and magic key open every path"),
    hearts=dict(fmt="z1", cap=16), rupees=dict(addr=(0x066D,), fmt="nes", cap=255),
    noclip=[("tick", _z1_noclip)], noclip_note="Link (and enemies) ignore blocking tiles, incl. water; room bounds/locked doors stay",
)
Z1_GBA = {**Z1, "platforms": ("gba",), "match": r"classic nes.*legend of zelda", "base": 0x03007000}

# Zelda II - The Adventure of Link (NES; GBA Classic NES at 0x03007000): Data Crystal RAM map + z2disassembly ram-map.
Z2_ITEMS = {
    **{n: S(a, 1) for a, n in enumerate(["shield spell", "jump spell", "life spell", "fairy spell", "fire spell", "reflect spell",
                                        "spell spell", "thunder spell"], 0x77B)},
    **{n: S(a, 1) for a, n in enumerate(["candle", "glove", "raft", "boots", "flute", "cross", "hammer", "magic key"], 0x785)},
    "downward thrust": O(0x796, 0x10), "upward thrust": O(0x796, 0x04), "keys": N(0x793, 5),
    "attack level 8": S(0x777, 8), "magic level 8": S(0x778, 8), "life level 8": S(0x779, 8),
    "magic containers": {"k": "fn", "fn": "z2_magic"}, "lives": N(0x700, 5),
}
Z2 = dict(
    name="Zelda II: The Adventure of Link", platforms=("nes",), match=r"zelda (ii|2)\b.*adventure of link|^zelda ii - the adventure",
    exclude=r"part [23]|journey|inertia|shadow of night|\bmq\b|outlands",
    ready=(0x0736, (0x05, 0x0B)),                         # game mode: overworld main / side-view main ($076C is 1 on file select too)
    items=Z2_ITEMS,
    aliases={"shield": "shield spell", "jump": "jump spell", "life": "life spell", "fairy": "fairy spell", "fire": "fire spell",
             "reflect": "reflect spell", "spell": "spell spell", "thunder": "thunder spell", "power glove": "glove",
             "handy glove": "glove", "key": "magic key", "down thrust": "downward thrust", "up thrust": "upward thrust",
             "max attack": "attack level 8", "max magic": "magic level 8", "max life": "life level 8", "magic": "magic containers"},
    equip={}, equip_note="Zelda II has no item buttons: items work as soon as Link owns them; spells are cast from the pause menu",
    all=[*(f"{s} spell" for s in ("shield", "jump", "life", "fairy", "fire", "reflect", "spell", "thunder")),
         "candle", "glove", "raft", "boots", "flute", "cross", "hammer", "magic key", "downward thrust", "upward thrust",
         "magic containers"],
    unrestrict=dict(give=["downward thrust", "upward thrust", "jump spell", "fairy spell", "boots", "raft", "hammer", "flute"],
                    note="Zelda II has no item restrictions; this gives the moves/items that open every path"),
    hearts=dict(fmt="z2", cap=8),
    noclip=[("emu", "AAOETYZA"), ("emu", "AIXOYGEY+EOOOGLEY")],   # Game Genie (ROM) codes from the libretro .cht
    noclip_note="overworld + side-view walls via the emulator's Game Genie engine",
)
Z2_GBA = {**Z2, "platforms": ("gba",), "match": r"classic nes.*zelda ii", "exclude": None, "base": 0x03007000}


# ---------------------------------------------------------------------------------------------------------------------
# Oracle of Seasons / Ages (GBC, USA): Stewmath/oracles-disasm include/wram.s + constants/common/treasure.s; libretro
# GameShark codes. Giving = put the treasure id in a free slot + set its wObtainedTreasureFlags bit + its level byte.
def _oracle(ages: bool):
    o = 8 if ages else 0
    B, A, STORE, FLAGS = 0xC680 + o, 0xC681 + o, 0xC682 + o, 0xC692 + o
    if ages:
        sword, shield, bombs, maxb, chus, satchel = 0xC6B2, 0xC6AF, 0xC6B0, 0xC6B1, 0xC6B3, 0xC6B4
        seeds, flute_icon, hp, maxhp, rupees, ess = 0xC6B9, 0xC6B5, 0xC6AA, 0xC6AB, 0xC6AD, 0xC6BF
    else:
        sword, shield, bombs, maxb, chus, satchel = 0xC6AC, 0xC6A9, 0xC6AA, 0xC6AB, 0xC6AD, 0xC6AE
        seeds, flute_icon, hp, maxhp, rupees, ess = 0xC6B5, 0xC6AF, 0xC6A2, 0xC6A3, 0xC6A5, 0xC6BB
    seed = {n: (0x20 + i, seeds + i) for i, n in enumerate(["ember seeds", "scent seeds", "pegasus seeds", "gale seeds", "mystery seeds"])}
    it = {
        "wooden sword": SL(0x05, S(sword, 1, up=True)), "noble sword": SL(0x05, S(sword, 2)), "master sword": SL(0x05, S(sword, 3)),
        "wooden shield": SL(0x01, S(shield, 1, up=True)), "iron shield": SL(0x01, S(shield, 2)), "mirror shield": SL(0x01, S(shield, 3)),
        "bombs": SL(0x03, N(bombs, 0x10, bcd=True)), "bombchus": SL(0x0D, N(chus, 0x20, bcd=True)), "biggoron sword": SL(0x0C),
        "seed satchel": SL(0x19, S(satchel, 1, up=True), TF(0x20), N(seeds, 0x20, bcd=True)),
        "shovel": SL(0x15), "rocs feather": SL(0x17), "flippers": TF(0x2E), "all essences": O(ess, 0xFF),
        "bomb bag upgrade": S(maxb, 0x99), "satchel upgrade": S(satchel, 3),
        **{f"{c} flute": SL(0x0E, S(0xC610, v), S(flute_icon, i)) for i, (c, v) in
           enumerate([("ricky", 0x0B), ("dimitri", 0x0C), ("moosh", 0x0D)], 1)},
        **{n: {"k": "tf", "v": t, "also": [N(a, 0x20, bcd=True)]} for n, (t, a) in seed.items()},
    }
    if ages:
        it.update({"cane of somaria": SL(0x04), "switch hook": SL(0x0A, S(0xC6B6, 1, up=True)), "long hook": SL(0x0A, S(0xC6B6, 2)),
                   "seed shooter": SL(0x0F, TF(0x20), N(seeds, 0x20, bcd=True)),
                   "harp of ages": SL(0x11, TF(0x25), TF(0x26), TF(0x27), S(0xC6B7, 3)),
                   "power bracelet": SL(0x16, S(0xC6B8, 1, up=True)), "power glove": SL(0x16, S(0xC6B8, 2)),
                   "mermaid suit": TF(0x4A)})
        aliases = {"hook": "switch hook", "harp": "harp of ages", "cane": "cane of somaria", "shooter": "seed shooter",
                   "bracelet": "power bracelet", "glove": "power glove", "long shot": "long hook", "longshot": "long hook"}
        all_ = ["master sword", "mirror shield", "bombs", "bombchus", "biggoron sword", "seed satchel", "shovel", "rocs feather",
                "flippers", "cane of somaria", "long hook", "seed shooter", "harp of ages", "power glove", "mermaid suit",
                "ricky flute", *seed, "satchel upgrade", "bomb bag upgrade"]
        unres = ["flippers", "mermaid suit", "power glove", "rocs feather", "long hook", "harp of ages"]
    else:
        it.update({"boomerang": SL(0x06, S(0xC6B1, 1, up=True)), "magic boomerang": SL(0x06, S(0xC6B1, 2)),
                   "rod of seasons": SL(0x07, O(0xC6B0, 0x8F)), "magnetic gloves": SL(0x08),
                   "slingshot": SL(0x13, S(0xC6B3, 1, up=True), TF(0x20), N(seeds, 0x20, bcd=True)),
                   "hyper slingshot": SL(0x13, S(0xC6B3, 2), TF(0x20), N(seeds, 0x20, bcd=True)),
                   "power bracelet": SL(0x16), "rocs cape": SL(0x17, S(0xC6B4, 2)), "fools ore": SL(0x1E)})
        it["rocs feather"] = SL(0x17, S(0xC6B4, 1, up=True))
        aliases = {"rod": "rod of seasons", "magnet gloves": "magnetic gloves", "magnet glove": "magnetic gloves",
                   "bracelet": "power bracelet", "cape": "rocs cape"}
        all_ = ["master sword", "mirror shield", "bombs", "bombchus", "biggoron sword", "seed satchel", "shovel", "rocs cape",
                "flippers", "magic boomerang", "rod of seasons", "magnetic gloves", "hyper slingshot", "power bracelet",
                "ricky flute", *seed, "satchel upgrade", "bomb bag upgrade"]
        unres = ["flippers", "power bracelet", "rocs cape", "rod of seasons", "magnetic gloves"]
    sig = b"Z21216-0" if ages else b"Z11216-0"

    def ready(m, g):
        if m.rd(0xC5B2, 8) != sig:
            raise RuntimeError(f"no {g['name']} save loaded yet - load a file first")

    return dict(
        name="Oracle of Ages" if ages else "Oracle of Seasons", platforms=("gbc", "gb"),
        match=r"oracle of ages|jikuu no shou" if ages else r"oracle of seasons|daichi no shou",
        ready=(0xC2EE, (0x02,)), ready_fn=ready, items=it, slots=tuple(range(B, STORE + 16)), store=tuple(range(STORE, STORE + 16)),
        tflags=FLAGS, hud_refresh=(0xCBE9 if ages else 0xCBEA, 0x1F),
        aliases={"sword": "wooden sword", "shield": "wooden shield", "satchel": "seed satchel", "feather": "rocs feather",
                 "flute": "ricky flute", "seeds": "ember seeds", "essences": "all essences", "biggoron": "biggoron sword",
                 "chus": "bombchus", **aliases},
        equip={"b": ("slot", B), "a": ("slot", A)}, default_button="b",
        all=all_, max_counts={"bombs": 99, "bombchus": 99, **{n: 99 for n in seed}},
        max_writes=[S(satchel, 3), S(maxb, 0x99)],
        unrestrict=dict(give=unres, note="the Oracles have no item restrictions; this gives the gear that opens every path"),
        hearts=dict(max=(maxhp, 4), cur=(hp, 4), cap=16), rupees=dict(addr=(rupees,), fmt="bcd2", cap=999),
        noclip=[("zero", 0xCE00, 0xC0)],              # wRoomCollisions: the current room's solidity map, rebuilt per room
    )


OOS, OOA = _oracle(False), _oracle(True)

GAMES = {"alttp": ALTTP, "la": LA, "mc": MC, "z1": Z1, "z1_gba": Z1_GBA, "z2": Z2, "z2_gba": Z2_GBA, "oos": OOS, "ooa": OOA}


# ---------------------------------------------------------------------------------------------------------------------
# The Wind Waker (GameCube, USA GZLE01): zeldaret/tww include/d/d_save.h + config/GZLE01/symbols.txt
# (g_dComIfG_gameInfo = 0x803C4C08 = mSavedata.mPlayer), cross-checked with Dolphin's GZLE01.ini AR codes. Big-endian.
_WW = 0x803C4C08
_WW_ITEMS, _WW_GET = _WW + 0x3C, _WW + 0x51          # mItems[21] (slot -> item id), get-item flag byte per slot


def _ww_slot(slot, iid, *also, bit=1, **kw):
    return S(_WW_ITEMS + slot, iid, ex=True, slot=slot, also=[O(_WW_GET + slot, bit), *also], **kw)


WW_ITEMS = {
    "telescope": _ww_slot(0, 0x20), "sail": _ww_slot(1, 0x78), "wind waker": _ww_slot(2, 0x22),
    "grappling hook": _ww_slot(3, 0x25), "spoils bag": _ww_slot(4, 0x24), "boomerang": _ww_slot(5, 0x2D),
    "deku leaf": _ww_slot(6, 0x34), "tingle tuner": _ww_slot(7, 0x21), "picto box": _ww_slot(8, 0x23),
    "deluxe picto box": _ww_slot(8, 0x26, bit=3), "iron boots": _ww_slot(9, 0x29), "magic armor": _ww_slot(10, 0x2A),
    "bait bag": _ww_slot(11, 0x2C),
    "bow": _ww_slot(12, 0x27, N(_WW + 0x69, 30), S(_WW + 0x6F, 30, up=True)),
    "fire and ice arrows": _ww_slot(12, 0x35, N(_WW + 0x69, 30), S(_WW + 0x6F, 30, up=True), bit=3),
    "light arrows": _ww_slot(12, 0x36, N(_WW + 0x69, 30), S(_WW + 0x6F, 30, up=True), bit=7),
    "bombs": _ww_slot(13, 0x31, N(_WW + 0x6A, 30), S(_WW + 0x70, 30, up=True)),
    "bottle": _ww_slot(14, 0x50), "delivery bag": _ww_slot(18, 0x30), "hookshot": _ww_slot(19, 0x2F),
    "skull hammer": _ww_slot(20, 0x33),
    "heros sword": S(_WW + 0x0E, 0x38, ex=True, also=[O(_WW + 0xB4, 0x01)]),
    "master sword": S(_WW + 0x0E, 0x3E, ex=True, also=[O(_WW + 0xB4, 0x08)]),
    "heros shield": S(_WW + 0x0F, 0x3B, ex=True, also=[O(_WW + 0xB5, 0x01)]),
    "mirror shield": S(_WW + 0x0F, 0x3C, ex=True, also=[O(_WW + 0xB5, 0x02)]),
    "power bracelets": S(_WW + 0x10, 0x28, ex=True, also=[O(_WW + 0xB6, 0x01)]),
    "magic": S(_WW + 0x13, 0x20, also=[S(_WW + 0x14, 0x20)]), "big wallet": S(_WW + 0x12, 2),
    "arrows": N(_WW + 0x69, 30), "all songs": O(_WW + 0xBD, 0x3F), "triforce": O(_WW + 0xBE, 0xFF),
    "pearls": O(_WW + 0xBF, 0x07),
}


def _ww_ready(m, g):
    if m.rd(0x80000000, 6) != b"GZLE01":
        raise RuntimeError("not The Wind Waker (USA, GZLE01)")
    if not 0x80000000 <= int.from_bytes(m.rd(0x803CA754, 4), "big") < 0x81800000:
        raise RuntimeError("no Link on screen yet - load a save file first")


WW = dict(
    name="The Wind Waker", platforms=("gamecube",), match=r"wind waker", ready_fn=_ww_ready, items=WW_ITEMS,
    aliases={"sword": "heros sword", "shield": "heros shield", "hammer": "skull hammer", "hook": "grappling hook",
             "grapple": "grappling hook", "leaf": "deku leaf", "boots": "iron boots", "camera": "picto box",
             "fire arrows": "fire and ice arrows", "ice arrows": "fire and ice arrows", "baton": "wind waker",
             "bracelets": "power bracelets", "wallet": "big wallet", "songs": "all songs", "empty bottle": "bottle"},
    # X/Y/Z hold the INVENTORY SLOT; the HUD draws dComIfG_play's item-id cache (play+... 0x803CA7DB..)
    equip={"x": ("slotidx", (_WW + 0x09, 0x803CA7DB)), "y": ("slotidx", (_WW + 0x0A, 0x803CA7DC)),
           "z": ("slotidx", (_WW + 0x0B, 0x803CA7DD))}, default_button="y",
    all=["telescope", "sail", "wind waker", "grappling hook", "spoils bag", "boomerang", "deku leaf", "tingle tuner",
         "deluxe picto box", "iron boots", "magic armor", "bait bag", "light arrows", "bombs", "bottle", "delivery bag",
         "hookshot", "skull hammer", "master sword", "mirror shield", "power bracelets", "magic", "big wallet", "all songs"],
    max_counts={"bombs": 99, "bow": 99, "light arrows": 99, "arrows": 99},
    max_writes=[S(_WW + 0x6F, 99), S(_WW + 0x70, 99)],
    unrestrict=dict(give=["iron boots", "deku leaf", "power bracelets", "grappling hook", "hookshot"],
                    note="The Wind Waker has no item restrictions; this gives the gear that opens every path"),
    hearts=dict(max=(_WW + 0x00, 4), cur=(_WW + 0x02, 4), cap=20, n=2, add=(0x803CA764, 0x803CA77E)),
    rupees=dict(addr=(_WW + 0x04,), fmt="u16be", cap=5000, wallet=_WW + 0x12, wallet_max=2, add=0x803CA768),
)
GAMES["ww"] = WW
