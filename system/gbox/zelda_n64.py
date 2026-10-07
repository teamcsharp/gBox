"""N64 Zeldas for the `zelda` tool. Ocarina of Time reuses gbox/oot.py (NTSC v1.2 SaveContext, word-swapped RDRAM
access through zelda_tool.Mem -> oot._rd/_wr); Majora's Mask uses the zeldaret/mm SaveContext (NTSC-U)."""
from . import oot
from .zelda_games import N, O, S
from .zelda_tool import GAMES

SV = oot.SAVE
IT, AM = SV + oot.S_ITEMS, SV + oot.S_AMMO
EQ = SV + oot.S_EQUIPS                     # u16 BE: boots<<12 | tunic<<8 | shield<<4 | sword  (byte EQ = boots|tunic)
INV = SV + oot.S_INV_EQUIP                 # u16 BE owned bits: boots 12-14, tunics 8-10, shields 4-6, swords 0-3


def _oot_items():
    it = {}
    for name, (iid, slot) in oot.ITEMS.items():
        also = [N(AM + slot, oot.AMMO[name])] if name in oot.AMMO else []
        it[name] = S(IT + slot, iid, ex=True, slot=slot, also=also, c=True)
    for name, iid, slot in (("fire arrow", 0x04, 4), ("ice arrow", 0x0C, 10), ("light arrow", 0x12, 16)):
        it[name]["also"] = [S(IT + 3, 0x03, ex=True), N(AM + 3, 30)]          # arrows need the bow
    it["bombchu"]["also"] = [N(AM + 8, 20)]
    # gear: owned bit (in INV) + equipped nibble; swords also set the B button item
    gear = [("kokiri sword", 1, 0, 1, 0x3B), ("master sword", 2, 0, 2, 0x3C), ("biggoron sword", 4, 0, 3, 0x3D),
            ("deku shield", 0x10, 4, 1, None), ("hylian shield", 0x20, 4, 2, None), ("mirror shield", 0x40, 4, 3, None),
            ("kokiri tunic", 0x100, 8, 1, None), ("goron tunic", 0x200, 8, 2, None), ("zora tunic", 0x400, 8, 3, None),
            ("kokiri boots", 0x1000, 12, 1, None), ("iron boots", 0x2000, 12, 2, None), ("hover boots", 0x4000, 12, 3, None)]
    for name, bit, shift, val, bitem in gear:
        a = INV + (0 if bit >= 0x100 else 1)
        it[name] = O(a, bit >> 8 if bit >= 0x100 else bit, gear=(shift, val, bitem), bitem=bitem)
    bottles = {"bottle": 0x14, "red potion": 0x15, "green potion": 0x16, "blue potion": 0x17, "fairy": 0x18, "fish": 0x19,
               "lon lon milk": 0x1A, "rutos letter": 0x1B, "blue fire": 0x1C, "bug": 0x1D, "big poe": 0x1E, "poe": 0x20}
    for name, iid in bottles.items():
        it[name] = {"k": "fn", "fn": "n64_bottle", "v": iid, "c": True}
    child = {"weird egg": 0x21, "chicken": 0x22, "zeldas letter": 0x23, "keaton mask": 0x24, "skull mask": 0x25,
             "spooky mask": 0x26, "bunny hood": 0x27, "goron mask": 0x28, "zora mask": 0x29, "gerudo mask": 0x2A, "mask of truth": 0x2B}
    adult = {"pocket egg": 0x2D, "pocket cucco": 0x2E, "cojiro": 0x2F, "odd mushroom": 0x30, "odd potion": 0x31,
             "poachers saw": 0x32, "broken goron sword": 0x33, "prescription": 0x34, "eyeball frog": 0x35, "eye drops": 0x36,
             "claim check": 0x37}
    for name, iid in child.items():
        it[name] = S(IT + 22, iid, ex=True, slot=22, c=True)
    for name, iid in adult.items():
        it[name] = S(IT + 23, iid, ex=True, slot=23, c=True)
    for name, b in oot.QUEST.items():
        it[name] = O(SV + oot.S_QUEST + 3 - b // 8, 1 << (b % 8))
    songs = ["minuet of forest", "bolero of fire", "serenade of water", "requiem of spirit", "nocturne of shadow", "prelude of light",
             "zeldas lullaby", "eponas song", "sarias song", "suns song", "song of time", "song of storms"]
    for i, name in enumerate(songs):
        b = 6 + i
        it[name] = O(SV + oot.S_QUEST + 3 - b // 8, 1 << (b % 8))
    it["all songs"] = {"k": "fn", "fn": "oot_bits", "bits": [6 + i for i in range(12)]}
    it["all medallions"] = {"k": "fn", "fn": "oot_bits", "bits": list(range(6)) + [18, 19, 20]}
    it["full inventory"] = {"k": "fn", "fn": "oot_full"}
    it["magic"] = {"k": "fn", "fn": "oot_magic"}
    it["giants wallet"] = O(SV + 0xA2, 0x20)                    # upgrades u32 BE at +0xA0: wallet = bits 12-13
    return it


def _bottle(m, g, sp, op, count):
    """Bottle slots (OoT 18-21, MM 0x12-0x17); 0xFF = no bottle."""
    base, first = g["bottle_slots"]
    n = g.get("bottle_count", 4)
    slots = m.rd(base, n)
    if op == "have":
        return sp["v"] in slots
    if op == "remove":
        for i, x in enumerate(slots):
            if x == sp["v"]:
                m.wr(base + i, b"\xff")
        return
    if sp["v"] in slots:
        return
    i = next((i for i, x in enumerate(slots) if x == 0xFF), None)
    if i is None:
        i = next((i for i, x in enumerate(slots) if x == g["empty_bottle"]), 0)
    m.wr(base + i, bytes([sp["v"]]))


def _oot_bits(m, g, sp, op, count):
    q = int.from_bytes(m.rd(SV + oot.S_QUEST, 4), "big")
    mask = sum(1 << b for b in sp["bits"])
    if op == "have":
        return q & mask == mask
    m.wr(SV + oot.S_QUEST, ((q | mask) if op == "give" else (q & ~mask)).to_bytes(4, "big"))


def _oot_full(m, g, sp, op, count):
    if op == "have":
        return False
    if op == "give":
        before = m.rd(IT, 24)
        r = oot.full_inventory(m.ad)                             # oot.py: every item, upgrades, all gear, 20 hearts, 500 rupees
        m.log.append({"addr": hex(IT), "before": before.hex(), "after": m.rd(IT, 24).hex()})
        return r


def _oot_magic(m, g, sp, op, count):
    if op == "have":
        return bool(m.u8(SV + 0x3A))
    m.wr(SV + 0x32, b"\x02")                                     # magicLevel 2 (double)
    m.wr(SV + 0x3A, b"\x01"); m.wr(SV + 0x3C, b"\x01")          # isMagicAcquired, isDoubleMagicAcquired
    m.wr(SV + 0x33, b"\x60")                                     # magic (full double bar)


def _oot_ready(m, g):
    oot.check(m.ad)


# Use any item at any age (OoT). zeldaret/oot ovl_kaleido_scope (z_kaleido_scope.c): gSlotAgeReqs[24], gEquipAgeReqs[4][4],
# gItemAgeReqs[86] back to back (0 adult, 1 child, 9 both). The pause-menu overlay is only in RAM while paused (it shares
# its area with the player overlay), so: find the tables by content while paused and fill them with 9. C-button and gear
# writes (equip) skip the age check altogether - the HUD greys buttons by scene, not by age (z_parameter.c).
OOT_AGE_SIG = bytes.fromhex(
    "010909000009010909000009010901000009090909090001" "00010000090109000009000009090000"
    "0109090000090109090900000009010901000009090909090909090909090909"
    "0901010101010101010101010100000000000000000000000000000100000109"
    "0009000009000001010100000009090901000009090900")
BUTTON_STATUS = SV + 0x13E2                               # u8[5] B, C-left, C-down, C-right, A: 0 enabled / 0xFF disabled


def _oot_any_age(m, g, count):
    out = {}
    m.poke(BUTTON_STATUS, bytes(5))                        # un-grey every button right now (scene limits come back on change)
    sig = OOT_AGE_SIG[:40]
    found = None
    for lo in range(0x801C0000, 0x80400000, 0x40000):      # the kaleido area lives in the play-state heap
        blk = m.rd(lo, 0x40000 + 0x80)
        i = blk.find(sig)
        if i >= 0:
            found = lo + i
            break
    if found is None:
        out.update(any_age=False, buttons_enabled=True,
                   note="C buttons / gear equipped with this tool work at any age now. To also equip anything from the "
                        "pause menu, open the pause menu and run unrestrict again (the age tables only exist while paused).")
        return out
    m.wr(found, b"\x09" * len(OOT_AGE_SIG))
    out.update(any_age=True, tables_at=hex(found), buttons_enabled=True,
               note="pause-menu age checks lifted for this pause (the menu reloads them each time it opens: run again "
                    "after re-opening); C buttons / gear set by this tool work at any age.")
    return out


OOT = dict(
    name="Ocarina of Time", platforms=("n64",), match=r"ocarina of time|toki no ocarina", exclude=r"master quest|ura",
    items=_oot_items(), ready_fn=_oot_ready,
    aliases={"sword": "kokiri sword", "shield": "deku shield", "fairy bow": "bow", "heros bow": "bow", "arrows": "bow",
             "hammer": "megaton hammer", "lens": "lens of truth", "beans": "magic beans", "chus": "bombchu", "bombchus": "bombchu",
             "ocarina": "ocarina of time", "din": "dins fire", "farore": "farores wind", "nayru": "nayrus love",
             "fire arrows": "fire arrow", "ice arrows": "ice arrow", "light arrows": "light arrow", "long shot": "longshot",
             "biggoron": "biggoron sword", "big goron sword": "biggoron sword", "red tunic": "goron tunic", "blue tunic": "zora tunic",
             "milk": "lon lon milk", "letter": "zeldas letter", "ruto letter": "rutos letter", "empty bottle": "bottle",
             "potion": "red potion", "songs": "all songs", "medallions": "all medallions", "wallet": "giants wallet",
             "stick": "deku stick", "nut": "deku nut", "deku sticks": "deku stick", "deku nuts": "deku nut"},
    equip={"b": ("oot_b", SV + 0x68), "c-left": ("oot_c", 1), "c-down": ("oot_c", 2), "c-right": ("oot_c", 3)},
    default_button="c-left", gear_addr=EQ, cbtn=SV + oot.S_BUTTONS, cslot=SV + oot.S_CSLOTS, bottle_slots=(IT + 18, 18),
    empty_bottle=0x14,
    all=["full inventory", "magic", "all songs"],
    unrestrict=dict(fn=_oot_any_age),
    hearts=dict(max=(SV + 0x2E, 16), cur=(SV + 0x30, 16), cap=20, n=2),
    rupees=dict(addr=(SV + 0x34,), fmt="u16be", cap=500, wallet_or=(SV + 0xA2, 0x20)),
    c_note="the C-button icon is drawn on the next area load or pause/unpause",
    # libretro "Walk Though Walls (Hold A)" (USA Rev 2) made unconditional: the X/Z-axis wall pre-checks in
    # Math3D_TriChkPointParaXImpl/ZImpl (jal Math3D_CirSquareVsTriSquare) -> li v0,0. Floors (ParaY) untouched.
    noclip=[("patch", 0x800A77BC, "0c0295a8", "24020000"), ("patch", 0x800A7E50, "0c0295a8", "24020000")],
    noclip_note="walls off for Link and every other actor (floors kept); camera/hookshot also pass walls", jit_flush=True,
)
GAMES["oot"] = OOT

# ---------------------------------------------------------------------------------------------------------------------
# Majora's Mask NTSC-U: zeldaret/mm include/z64save.h + tools/disasm/n64-us/variables.txt (gSaveContext 0x801EF670,
# gPlayerFormItemRestrictions 0x801C2410 [5][0x72]); item/mask slots cross-checked with the libretro MM (USA) .cht.
MS = 0x801EF670
MIT, MAM = MS + 0x70, MS + 0xA0                      # items[48] (masks from slot 0x18), ammo[24] by slot
MBTN, MCSL = MS + 0x4C, MS + 0x5C                    # buttonItems[4 forms][B, C-left, C-down, C-right], cButtonSlots same
MEQ = MS + 0x6C                                      # equipment u16: sword bits 0-3, shield bits 4-7


def _mm_items():
    it = {}
    plain = {"ocarina of time": 0x00, "bow": 0x01, "fire arrow": 0x02, "ice arrow": 0x03, "light arrow": 0x04, "bombs": 0x06,
             "bombchu": 0x07, "deku stick": 0x08, "deku nut": 0x09, "magic beans": 0x0A, "powder keg": 0x0C,
             "pictograph box": 0x0D, "lens of truth": 0x0E, "hookshot": 0x0F, "great fairys sword": 0x10}
    ammo = {"bow": 30, "bombs": 20, "bombchu": 20, "deku stick": 10, "deku nut": 20, "magic beans": 10, "powder keg": 1}
    for name, iid in plain.items():
        also = [N(MAM + iid, ammo[name])] if name in ammo else []
        if name.endswith("arrow"):
            also = [S(MIT + 1, 0x01, ex=True), N(MAM + 1, 30)]
        it[name] = S(MIT + iid, iid, ex=True, slot=iid, also=also, c=True)
    masks = {"postman hat": (0x3E, 0x18), "all night mask": (0x38, 0x19), "blast mask": (0x47, 0x1A), "stone mask": (0x45, 0x1B),
             "great fairy mask": (0x40, 0x1C), "deku mask": (0x32, 0x1D), "keaton mask": (0x3A, 0x1E), "bremen mask": (0x46, 0x1F),
             "bunny hood": (0x39, 0x20), "don geros mask": (0x42, 0x21), "mask of scents": (0x48, 0x22), "goron mask": (0x33, 0x23),
             "romanis mask": (0x3C, 0x24), "circus leaders mask": (0x3D, 0x25), "kafeis mask": (0x37, 0x26),
             "couples mask": (0x3F, 0x27), "mask of truth": (0x36, 0x28), "zora mask": (0x34, 0x29), "kamaros mask": (0x43, 0x2A),
             "gibdo mask": (0x41, 0x2B), "garos mask": (0x3B, 0x2C), "captains hat": (0x44, 0x2D), "giants mask": (0x49, 0x2E),
             "fierce deity mask": (0x35, 0x2F)}
    for name, (iid, slot) in masks.items():
        it[name] = S(MIT + slot, iid, ex=True, slot=slot, c=True)
    bottles = {"bottle": 0x12, "red potion": 0x13, "green potion": 0x14, "blue potion": 0x15, "fairy": 0x16, "deku princess": 0x17,
               "milk": 0x18, "fish": 0x1A, "bug": 0x1B, "blue fire": 0x1C, "poe": 0x1D, "big poe": 0x1E, "spring water": 0x1F,
               "hot spring water": 0x20, "zora egg": 0x21, "gold dust": 0x22, "magic mushroom": 0x23, "seahorse": 0x24,
               "chateau romani": 0x25}
    for name, iid in bottles.items():
        it[name] = {"k": "fn", "fn": "n64_bottle", "v": iid, "c": True}
    for name, sh, v, bitem in (("kokiri sword", 0, 1, 0x4D), ("razor sword", 0, 2, 0x4E), ("gilded sword", 0, 3, 0x4F),
                               ("heros shield", 4, 1, None), ("mirror shield", 4, 2, None)):
        it[name] = {"k": "nib", "a": MEQ, "sh": sh, "v": v, "bitem": bitem,
                    "also": [S(MBTN, bitem, ex=True)] if bitem else []}
    it["magic"] = {"k": "fn", "fn": "mm_magic"}
    it["giants wallet"] = O(MS + 0xBA, 0x20)                     # upgrades u32 BE at +0xB8: wallet bits 12-13
    it["big quiver"] = O(MS + 0xBB, 0x03)                        # quiver bits 0-2
    it["biggest bomb bag"] = O(MS + 0xBB, 0x18)                  # bomb bag bits 3-5
    it["double defense"] = S(MS + 0x42, 1)
    return it


def _mm_magic(m, g, sp, op, count):
    if op == "have":
        return bool(m.u8(MS + 0x40))
    m.wr(MS + 0x38, b"\x02"); m.wr(MS + 0x40, b"\x01"); m.wr(MS + 0x41, b"\x01"); m.wr(MS + 0x39, b"\x60")


def _mm_ready(m, g):
    if m.rd(MS + 0x24, 6) != b"ZELDA3":
        raise RuntimeError("no Majora's Mask (USA) save loaded yet - load a file first")


def _mm_any_form(m, g, count):
    m.wr(0x801C2410, b"\x01" * (5 * 0x72))                     # gPlayerFormItemRestrictions[5][114]: every form, every item
    m.poke(MS + 0x3F18, bytes(5))                               # buttonStatus: un-grey B/C/A now (the game recomputes it)
    return {"any_form": True, "note": "every form (Deku/Goron/Zora/Fierce Deity/Human) may use and equip every item until "
            "the game is reset; some items look or act odd on forms that have no animation for them"}


MM = dict(
    name="Majora's Mask", platforms=("n64",), match=r"majora|mujura", items=_mm_items(), ready_fn=_mm_ready,
    aliases={"ocarina": "ocarina of time", "sword": "kokiri sword", "shield": "heros shield", "heros bow": "bow",
             "arrows": "bow", "fire arrows": "fire arrow", "ice arrows": "ice arrow", "light arrows": "light arrow",
             "keg": "powder keg", "camera": "pictograph box", "picto box": "pictograph box", "lens": "lens of truth",
             "great fairy sword": "great fairys sword", "fierce deity": "fierce deity mask", "deku": "deku mask",
             "goron": "goron mask", "zora": "zora mask", "bunny ears": "bunny hood", "giant mask": "giants mask",
             "empty bottle": "bottle", "potion": "red potion", "wallet": "giants wallet", "quiver": "big quiver",
             "bomb bag": "biggest bomb bag", "stick": "deku stick", "nut": "deku nut", "beans": "magic beans", "chus": "bombchu"},
    equip={"b": ("oot_b", MBTN), "c-left": ("oot_c", 1), "c-down": ("oot_c", 2), "c-right": ("oot_c", 3)},
    default_button="c-left", cbtn=MBTN, cslot=MCSL + 1, bottle_slots=(MIT + 0x12, 0x12), bottle_count=6, empty_bottle=0x12,
    all=["ocarina of time", "bow", "fire arrow", "ice arrow", "light arrow", "bombs", "bombchu", "deku stick", "deku nut",
         "magic beans", "powder keg", "pictograph box", "lens of truth", "hookshot", "great fairys sword", "postman hat",
         "all night mask", "blast mask", "stone mask", "great fairy mask", "deku mask", "keaton mask", "bremen mask",
         "bunny hood", "don geros mask", "mask of scents", "goron mask", "romanis mask", "circus leaders mask", "kafeis mask",
         "couples mask", "mask of truth", "zora mask", "kamaros mask", "gibdo mask", "garos mask", "captains hat", "giants mask",
         "fierce deity mask", "bottle", "red potion", "fairy", "milk", "gilded sword", "mirror shield", "magic",
         "giants wallet", "big quiver", "biggest bomb bag"],
    max_counts={"bow": 50, "bombs": 40, "bombchu": 40, "deku stick": 30, "deku nut": 40},
    unrestrict=dict(fn=_mm_any_form),
    hearts=dict(max=(MS + 0x34, 16), cur=(MS + 0x36, 16), cap=20, n=2),
    rupees=dict(addr=(MS + 0x3A,), fmt="u16be", cap=500, wallet_or=(MS + 0xBA, 0x20)),
    c_note="the C-button icon is drawn on the next area load or pause/unpause",
    # same patch as OoT, MM US (zeldaret/mm functions.txt): the jal to Math3D_CirSquareVsTriSquareYZ / XY inside
    # Math3D_TriChkPointParaXImpl (0x8017C540) / ParaZImpl (0x8017CB7C) -> li v0,0
    noclip=[("scan", 0x8017C540, 0x8017C808, "0c05e874", "24020000"), ("scan", 0x8017CB7C, 0x8017CEA8, "0c05e827", "24020000")],
    noclip_note="walls off for Link and every other actor (floors kept); camera/hookshot also pass walls", jit_flush=True,
)
GAMES["mm"] = MM

FNS = {"n64_bottle": _bottle, "oot_bits": _oot_bits, "oot_full": _oot_full, "oot_magic": _oot_magic, "mm_magic": _mm_magic}
