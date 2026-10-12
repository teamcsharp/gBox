"""Zelda: Ocarina of Time (N64 NTSC 1.0 / 1.1 / 1.2): make Link, or just his sword, bigger in the running game
(inbox #213 "make my sword three times bigger", #216 "make Link 2x bigger").

LINK (scale_link): the player actor is play->actorCtx.actorLists[ACTORCAT_PLAYER].head - PlayState +0x1C24 ActorContext,
+0x0C ActorListEntry actorLists[12] {s32 length; Actor* head}, ACTORCAT_PLAYER = 2, so the head sits at play + 0x1C44 -
and is accepted only when Actor.id == ACTOR_PLAYER (0) and Actor.category == 2. Actor.scale is the Vec3f at +0x50
(zeldaret/oot include/actor.h: home +0x08, params +0x1C, world +0x24, focus +0x38, lockOnArrowOffset +0x4C, scale +0x50,
next +0x124); Player_Init sets 0.01 (Actor_SetScale), so 2x bigger = 0.02 on all three axes. The PlayState / Actor /
ObjectContext layouts carry no per-revision conditionals (include/play_state.h, actor.h, object.h); only the gPlayState /
gSaveContext bases differ, and gbox.oot.layout resolves those per ROM.

SWORD (scale_sword): the mesh is in Link's object - object_link_boy (0x14) as adult, object_link_child (0x15) as child
(gLinkObjectIds) - found through play->objectCtx (PlayState +0x117A4: +0x08 numEntries, +0x0C ObjectEntry slots[19]
{s16 id; void* segment}, 0x44 each). The display lists that draw the equipped sword are known from z_player_lib.c
(sPlayerLeftHandSwordDLs, gPlayerLeftHandBgsDLs, and the sheath tables D_80125E78 / D_80125E88 / D_80125D28 / D_80125D88
indexed by shield); their offsets and vertex arrays are the decomp's assets/xml/objects/object_link_boy.xml /
object_link_child.xml (table DLS / VTX below). Each list is walked in the loaded object (F3DEX2, gbox.oot_writer.run_dl)
and a vertex belongs to the sword when a triangle drawn with one of the sword's textures uses it: in the hand lists the
hilt textures (SwordPommel 0xD0B8, SwordGuard 0xE438, SwordEmblem 0xEA38; child SwordJewel 0xA3F0 and the child's
MasterSword set) plus the blade, which is drawn with the reflective metal texture of gameplay_keep (segment 4, offset 0);
in the back (sheath) lists the hilt and sheath textures (Sheath 0xDC38, SheathBand 0xE838; child KokiriSwordSheath
0xA2F0) plus the sheath's untextured mouth, while the metal texture there is the Mirror Shield and stays. The hand, the
shields and the rest of the limb keep their vertices. Those rules were checked offline against the retail NTSC 1.0 and
1.2 ROMs (the two objects are byte-identical in both); the EXPECT column of DLS records what they found, and a live walk
that disagrees is refused before anything is written.

The sword is scaled about its end nearest the limb origin - the pommel for the sword in hand - so the hand keeps holding
the grip; s16 vertex coordinates are checked for overflow first (the result names the largest factor that fits), and the
original 16-byte Vtx records are kept in the session's hold so factor 1 restores them. The sword's reach follows:
sMeleeWeaponLengths (z_player_lib.c: {0, 4000 Master, 3000 Kokiri, 5500 Biggoron, 0 stick, 2500 hammer} f32, in `code`
at 0x800F7BB0 on 1.0 / 0x800F8200 on 1.2, found by content elsewhere) gets pommel + (length - pommel) * factor.

PERSISTENCE: Link is re-created on every scene change (scale back to 0.01) and his object is reloaded from ROM (vertices
back to the original), usually at another address, so a freeze_memory hold on a fixed address is wrong for both: it would
keep writing stale bytes into whatever the game allocates there next. Instead the session's hold thread (HOLDS, the same
pattern as gbox.oot_live.watch re-hooking statues after a room load) re-resolves Link and his object every HOLD_PERIOD and
re-applies only where it reads the game's own values (0.01 / the ROM's vertices), following age and equipment changes.
factor 1 restores and releases; the hold ends with the session.
"""
from __future__ import annotations

import struct
import threading
import time

from . import oot, oot_live
from . import oot_writer as OW

# ---------------------------------------------------------------- Link (the player actor)

ACTORCAT_PLAYER, ACTOR_PLAYER = 2, 0
A_ID, A_CATEGORY, A_SCALE, A_NEXT = 0x00, 0x02, 0x50, 0x124                     # include/actor.h
PLAYER_HEAD = oot_live.ACTOR_CTX + 0x0C + 8 * ACTORCAT_PLAYER + 4               # play + 0x1C44
LINK_SCALE = 0.01                                                               # Player_Init: Actor_SetScale(0.01f)
RDRAM = range(0x80000000, 0x80800000)
FACTOR_RANGE = (0.1, 64.0)


def player_actor(ad) -> int:
    """Link's actor: walk play->actorCtx.actorLists[ACTORCAT_PLAYER] and take the entry with id ACTOR_PLAYER and
    category ACTORCAT_PLAYER. 0 while there is no Link (title screen, scene load) or the list is not readable."""
    a = oot_live.u32(ad, oot.play(ad) + PLAYER_HEAD)
    for _ in range(4):
        if not a or a not in RDRAM:
            return 0
        aid, cat = struct.unpack(">hB", oot._rd(ad, a, 3))
        if aid == ACTOR_PLAYER and cat == ACTORCAT_PLAYER:
            return a
        a = oot_live.u32(ad, a + A_NEXT)
    return 0


def link_scale(ad) -> tuple[float, float, float] | None:
    pl = player_actor(ad)
    return struct.unpack(">3f", oot._rd(ad, pl + A_SCALE, 12)) if pl else None


def _check_factor(factor: float) -> float:
    factor = float(factor)
    if not FACTOR_RANGE[0] <= factor <= FACTOR_RANGE[1]:
        raise ValueError(f"factor {factor:g} is out of range {FACTOR_RANGE[0]:g}..{FACTOR_RANGE[1]:g}")
    return factor


def scale_link(ad, factor: float) -> dict:
    """Write 0.01 * factor to Link's Actor.scale (x, y, z) and read it back."""
    factor = _check_factor(factor)
    pl = player_actor(ad)
    if not pl:
        raise RuntimeError("no Link actor right now (title screen / scene loading) - try again in gameplay")
    oot._wr(ad, pl + A_SCALE, struct.pack(">3f", *[LINK_SCALE * factor] * 3))
    got = struct.unpack(">3f", oot._rd(ad, pl + A_SCALE, 12))
    return {"actor": hex(pl), "factor": factor, "scale": [round(v, 5) for v in got],
            "verified": all(abs(v - LINK_SCALE * factor) < 1e-6 for v in got)}


# ---------------------------------------------------------------- the sword in Link's object

OBJECT_LINK_BOY, OBJECT_LINK_CHILD = OW.OBJECT_LINK_BOY, OW.OBJECT_LINK_CHILD   # 0x14, 0x15 (gLinkObjectIds)
LINK_OBJECT = {"adult": OBJECT_LINK_BOY, "child": OBJECT_LINK_CHILD}
OBJECT_SIZE = {OBJECT_LINK_BOY: 0x37800, OBJECT_LINK_CHILD: 0x2CF80}            # dmadata vromEnd - vromStart (NTSC 1.0 = 1.2)
OBJECT_SLOTS, OBJECT_SLOT = 19, 0x44                                            # include/object.h ObjectContext / ObjectEntry
METAL_TEX = 0x04000000                     # gameplay_keep +0: the reflective metal texture (every blade, the Mirror Shield)
SWORDS = {1: "Kokiri Sword", 2: "Master Sword", 3: "Biggoron's Sword"}          # equips.equipment & 0xF (SaveContext +0x70)
# sword / sheath textures per object (object_link_boy.xml / object_link_child.xml offsets)
TEX = {"adult": {"sword": {0xD0B8, 0xE438, 0xEA38},                 # gLinkAdultSwordPommelTex, SwordGuardTex, SwordEmblemTex
                 "sheath": {0xDC38, 0xE838}},                       # gLinkAdultSheathTex, SheathBandTex
       "child": {"sword": {0xA3F0, 0xA5F0, 0xA6F0, 0xAAF0},         # SwordJewelTex, MasterSwordPommel / Guard / EmblemTex
                 "sheath": {0xA2F0}}}                               # gLinkChildKokiriSwordSheathTex

# Vertex arrays (name -> (offset, count)) of the sword display lists, from the decomp XMLs. A live walk whose vertices
# leave these ranges is not reading object_link_boy / _child and is refused.
VTX = {
    "gLinkAdultLeftHandHoldingMasterSwordNearVtx": (0x10EE8, 186), "gLinkAdultLeftHandHoldingMasterSwordFarVtx": (0x193B8, 113),
    "gLinkAdultLeftHandHoldingBgsNearVtx": (0x14448, 118), "gLinkAdultLeftHandHoldingBgsFarVtx": (0x1B0C8, 110),
    "gLinkAdultHandHoldingBrokenGiantsKnifeVtx": (0x14BA8, 93), "gLinkAdultHandHoldingBrokenGiantsKnifeFarVtx": (0x1BF08, 86),
    "gLinkAdultBrokenGiantsKnifeBladeVtx": (0x2B738, 48),
    "gLinkAdultMasterSwordAndSheathNearVtx": (0x12E68, 97), "gLinkAdultMasterSwordAndSheathFarVtx": (0x1A638, 48),
    "gLinkAdultHylianShieldSwordAndSheathNearVtx": (0xEFB8, 125), "gLinkAdultHylianShieldSwordAndSheathFarVtx": (0x18358, 55),
    "gLinkAdultMirrorShieldSwordAndSheathNearVtx1": (0xFAE8, 139), "gLinkAdultMirrorShieldSwordAndSheathNearVtx2": (0x204F8, 10),
    "gLinkAdultMirrorShieldSwordAndSheathFarVtx1": (0x188B8, 76), "gLinkAdultMirrorShieldSwordAndSheathFarVtx2": (0x20898, 10),
    "gLinkAdultSheathNearVtx": (0x15CD8, 26), "gLinkAdultSheathFarVtx": (0x1A938, 14),
    "gLinkAdultHylianShieldAndSheathNearVtx": (0xF788, 54), "gLinkAdultHylianShieldAndSheathFarVtx": (0x186C8, 31),
    "gLinkAdultMirrorShieldAndSheathNearVtx1": (0x10398, 68), "gLinkAdultMirrorShieldAndSheathNearVtx2": (0x20598, 10),
    "gLinkAdultMirrorShieldAndSheathFarVtx1": (0x18D78, 46), "gLinkAdultMirrorShieldAndSheathFarVtx2": (0x20938, 10),
    "gLinkChildLeftFistAndKokiriSwordNearVtx": (0xB1B0, 80), "gLinkChildLeftFistAndKokiriSwordFarVtx": (0x10E50, 81),
    "gLinkChildLeftHandHoldingMasterSwordVtx": (0xD4E0, 163),
    "gLinkChildSwordAndSheathNearVtx": (0xD1C0, 35), "gLinkChildSwordAndSheathFarVtx": (0x10B70, 31),
    "gLinkChildDekuShieldSwordAndSheathNearVtx": (0xCAA0, 67), "gLinkChildDekuShieldSwordAndSheathFarVtx": (0x10690, 47),
    "gLinkChildHylianShieldSwordAndSheathNearVtx": (0xC580, 51), "gLinkChildHylianShieldSwordAndSheathFarVtx": (0x10210, 44),
    "gLinkChildSheathNearVtx": (0xD3F0, 15), "gLinkChildSheathFarVtx": (0x10D60, 15),
    "gLinkChildDekuShieldAndSheathNearVtx": (0xCED0, 47), "gLinkChildDekuShieldAndSheathFarVtx": (0x10980, 31),
    "gLinkChildHylianShieldAndSheathNearVtx": (0xC8B0, 31), "gLinkChildHylianShieldAndSheathFarVtx": (0x104D0, 28),
}


# What the walk finds in the retail objects (NTSC 1.0 and 1.2 give the same): display list -> (sword vertices, other
# vertices, lo, hi of the sword's extent on its longest axis, always X). The pommel is the lo end in every list but the
# child's unused Master Sword grip, whose blade points to -X.
EXPECT = {
    "gLinkAdultLeftHandHoldingMasterSwordNearDL": (136, 50, -787, 3387), "gLinkAdultLeftHandHoldingMasterSwordFarDL": (77, 36, -814, 3387),
    "gLinkAdultLeftHandHoldingBgsNearDL": (68, 50, -1116, 5492), "gLinkAdultLeftHandHoldingBgsFarDL": (64, 46, -1116, 5492),
    "gLinkAdultHandHoldingBrokenGiantsKnifeDL": (51, 42, -1116, 1474), "gLinkAdultHandHoldingBrokenGiantsKnifeFarDL": (59, 27, -1116, 1474),
    "gLinkAdultBrokenGiantsKnifeBladeDL": (48, 0, -1847, 2265),
    "gLinkAdultMasterSwordAndSheathNearDL": (97, 0, -1502, 2700), "gLinkAdultMasterSwordAndSheathFarDL": (48, 0, -1502, 2700),
    "gLinkAdultHylianShieldSwordAndSheathNearDL": (97, 28, -1502, 2700), "gLinkAdultHylianShieldSwordAndSheathFarDL": (42, 13, -1502, 2700),
    "gLinkAdultMirrorShieldSwordAndSheathNearDL": (97, 52, -1502, 2700), "gLinkAdultMirrorShieldSwordAndSheathFarDL": (48, 38, -1502, 2700),
    "gLinkAdultSheathNearDL": (26, 0, -387, 2700), "gLinkAdultSheathFarDL": (14, 0, -380, 2700),
    "gLinkAdultHylianShieldAndSheathNearDL": (26, 28, -387, 2700), "gLinkAdultHylianShieldAndSheathFarDL": (18, 13, -380, 2700),
    "gLinkAdultMirrorShieldAndSheathNearDL": (26, 52, -387, 2700), "gLinkAdultMirrorShieldAndSheathFarDL": (18, 38, -380, 2700),
    "gLinkChildLeftFistAndKokiriSwordNearDL": (61, 19, -414, 1666), "gLinkChildLeftFistAndKokiriSwordFarDL": (62, 19, -411, 1666),
    "gLinkChildLeftHandHoldingMasterSwordDL": (136, 27, -3171, 828),
    "gLinkChildSwordAndSheathNearDL": (35, 0, -861, 1220), "gLinkChildSwordAndSheathFarDL": (31, 0, -859, 1220),
    "gLinkChildDekuShieldSwordAndSheathNearDL": (35, 32, -861, 1220), "gLinkChildDekuShieldSwordAndSheathFarDL": (31, 16, -859, 1220),
    "gLinkChildHylianShieldSwordAndSheathNearDL": (35, 16, -861, 1220), "gLinkChildHylianShieldSwordAndSheathFarDL": (31, 13, -859, 1220),
    "gLinkChildSheathNearDL": (15, 0, -155, 1220), "gLinkChildSheathFarDL": (15, 0, -155, 1220),
    "gLinkChildDekuShieldAndSheathNearDL": (15, 32, -155, 1220), "gLinkChildDekuShieldAndSheathFarDL": (15, 16, -155, 1220),
    "gLinkChildHylianShieldAndSheathNearDL": (15, 16, -155, 1220), "gLinkChildHylianShieldAndSheathFarDL": (15, 13, -155, 1220),
}


def _row(age, swords, role, name, dl, vtx, expect=None):
    """One display list that draws a sword. swords: equips values it is drawn for; role: 'hand' (the sword in Link's
    left hand; the hand's own triangles share the Vtx array) or 'back' (sword / sheath on his back, shields share);
    expect: (sword vertices, other vertices, axis extent lo, hi) the walk must find, EXPECT[name] by default."""
    return {"age": age, "swords": swords, "role": role, "name": name, "dl": dl, "vtx": vtx,
            "expect": EXPECT.get(name) if expect is None else expect}


# Which list the game draws (z_player_lib.c): hand = sPlayerLeftHandSwordDLs (adult Master Sword list also with the
# Kokiri Sword equipped, child Kokiri list also with the Master Sword) / gPlayerLeftHandBgsDLs (Biggoron's Sword and the
# Giant's Knife, broken knife included); back = D_80125E78 / D_80125D28 (sword sheathed, per shield) and D_80125E88 /
# D_80125D88 (sword drawn: the empty sheath, per shield). Adult shows the Master Sword's sheath whatever sword he holds.
DLS = [
    _row("adult", (1, 2), "hand", "gLinkAdultLeftHandHoldingMasterSwordNearDL", 0x21F78, ("gLinkAdultLeftHandHoldingMasterSwordNearVtx",)),
    _row("adult", (1, 2), "hand", "gLinkAdultLeftHandHoldingMasterSwordFarDL", 0x27078, ("gLinkAdultLeftHandHoldingMasterSwordFarVtx",)),
    _row("adult", (3,), "hand", "gLinkAdultLeftHandHoldingBgsNearDL", 0x238C8, ("gLinkAdultLeftHandHoldingBgsNearVtx",)),
    _row("adult", (3,), "hand", "gLinkAdultLeftHandHoldingBgsFarDL", 0x286B8, ("gLinkAdultLeftHandHoldingBgsFarVtx",)),
    _row("adult", (3,), "hand", "gLinkAdultHandHoldingBrokenGiantsKnifeDL", 0x23D50, ("gLinkAdultHandHoldingBrokenGiantsKnifeVtx",)),
    _row("adult", (3,), "hand", "gLinkAdultHandHoldingBrokenGiantsKnifeFarDL", 0x291E8, ("gLinkAdultHandHoldingBrokenGiantsKnifeFarVtx",)),
    _row("adult", (3,), "hand", "gLinkAdultBrokenGiantsKnifeBladeDL", 0x2BA38, ("gLinkAdultBrokenGiantsKnifeBladeVtx",)),
    _row("adult", (1, 2, 3), "back", "gLinkAdultMasterSwordAndSheathNearDL", 0x23160, ("gLinkAdultMasterSwordAndSheathNearVtx",)),
    _row("adult", (1, 2, 3), "back", "gLinkAdultMasterSwordAndSheathFarDL", 0x27F00, ("gLinkAdultMasterSwordAndSheathFarVtx",)),
    _row("adult", (1, 2, 3), "back", "gLinkAdultHylianShieldSwordAndSheathNearDL", 0x20A78, ("gLinkAdultHylianShieldSwordAndSheathNearVtx",)),
    _row("adult", (1, 2, 3), "back", "gLinkAdultHylianShieldSwordAndSheathFarDL", 0x25FB8, ("gLinkAdultHylianShieldSwordAndSheathFarVtx",)),
    _row("adult", (1, 2, 3), "back", "gLinkAdultMirrorShieldSwordAndSheathNearDL", 0x211B8,
         ("gLinkAdultMirrorShieldSwordAndSheathNearVtx1", "gLinkAdultMirrorShieldSwordAndSheathNearVtx2")),
    _row("adult", (1, 2, 3), "back", "gLinkAdultMirrorShieldSwordAndSheathFarDL", 0x264F0,
         ("gLinkAdultMirrorShieldSwordAndSheathFarVtx1", "gLinkAdultMirrorShieldSwordAndSheathFarVtx2")),
    _row("adult", (1, 2, 3), "back", "gLinkAdultSheathNearDL", 0x249D8, ("gLinkAdultSheathNearVtx",)),
    _row("adult", (1, 2, 3), "back", "gLinkAdultSheathFarDL", 0x28150, ("gLinkAdultSheathFarVtx",)),
    _row("adult", (1, 2, 3), "back", "gLinkAdultHylianShieldAndSheathNearDL", 0x20E70, ("gLinkAdultHylianShieldAndSheathNearVtx",)),
    _row("adult", (1, 2, 3), "back", "gLinkAdultHylianShieldAndSheathFarDL", 0x262B8, ("gLinkAdultHylianShieldAndSheathFarVtx",)),
    _row("adult", (1, 2, 3), "back", "gLinkAdultMirrorShieldAndSheathNearDL", 0x216B0,
         ("gLinkAdultMirrorShieldAndSheathNearVtx1", "gLinkAdultMirrorShieldAndSheathNearVtx2")),
    _row("adult", (1, 2, 3), "back", "gLinkAdultMirrorShieldAndSheathFarDL", 0x26910,
         ("gLinkAdultMirrorShieldAndSheathFarVtx1", "gLinkAdultMirrorShieldAndSheathFarVtx2")),
    _row("child", (1, 2), "hand", "gLinkChildLeftFistAndKokiriSwordNearDL", 0x13F38, ("gLinkChildLeftFistAndKokiriSwordNearVtx",)),
    _row("child", (1, 2), "hand", "gLinkChildLeftFistAndKokiriSwordFarDL", 0x17630, ("gLinkChildLeftFistAndKokiriSwordFarVtx",)),
    _row("child", (3,), "hand", "gLinkChildLeftHandHoldingMasterSwordDL", 0x15540, ("gLinkChildLeftHandHoldingMasterSwordVtx",)),
    _row("child", (1, 2, 3), "back", "gLinkChildSwordAndSheathNearDL", 0x15248, ("gLinkChildSwordAndSheathNearVtx",)),
    _row("child", (1, 2, 3), "back", "gLinkChildSwordAndSheathFarDL", 0x17360, ("gLinkChildSwordAndSheathFarVtx",)),
    _row("child", (1, 2, 3), "back", "gLinkChildDekuShieldSwordAndSheathNearDL", 0x14D68, ("gLinkChildDekuShieldSwordAndSheathNearVtx",)),
    _row("child", (1, 2, 3), "back", "gLinkChildDekuShieldSwordAndSheathFarDL", 0x16EE8, ("gLinkChildDekuShieldSwordAndSheathFarVtx",)),
    _row("child", (1, 2, 3), "back", "gLinkChildHylianShieldSwordAndSheathNearDL", 0x148A8, ("gLinkChildHylianShieldSwordAndSheathNearVtx",)),
    _row("child", (1, 2, 3), "back", "gLinkChildHylianShieldSwordAndSheathFarDL", 0x16A98, ("gLinkChildHylianShieldSwordAndSheathFarVtx",)),
    _row("child", (1, 2, 3), "back", "gLinkChildSheathNearDL", 0x15408, ("gLinkChildSheathNearVtx",)),
    _row("child", (1, 2, 3), "back", "gLinkChildSheathFarDL", 0x17500, ("gLinkChildSheathFarVtx",)),
    _row("child", (1, 2, 3), "back", "gLinkChildDekuShieldAndSheathNearDL", 0x15010, ("gLinkChildDekuShieldAndSheathNearVtx",)),
    _row("child", (1, 2, 3), "back", "gLinkChildDekuShieldAndSheathFarDL", 0x17150, ("gLinkChildDekuShieldAndSheathFarVtx",)),
    _row("child", (1, 2, 3), "back", "gLinkChildHylianShieldAndSheathNearDL", 0x14B40, ("gLinkChildHylianShieldAndSheathNearVtx",)),
    _row("child", (1, 2, 3), "back", "gLinkChildHylianShieldAndSheathFarDL", 0x16CF8, ("gLinkChildHylianShieldAndSheathFarVtx",)),
]

# sMeleeWeaponLengths (z_player_lib.c), the reach of the sword's hit quads: index = PLAYER_MELEEWEAPON_*
REACH_ORIG = struct.pack(">6f", 0.0, 4000.0, 3000.0, 5500.0, 0.0, 2500.0)
REACH_INDEX = {1: 2, 2: 1, 3: 3}                              # equips sword -> table index (Kokiri 2, Master 1, Biggoron 3)
REACH_AT = {"ntsc-1.0": 0x800F7BB0, "ntsc-1.2": 0x800F8200}  # code + 0xE6B10 / + 0xE6B20 in the retail ROMs
CODE_WINDOW = 0x104000                                        # the `code` file is 0x103D30 (1.0) / 0x103DA0 (1.2) bytes
S16 = (-32768, 32767)
HOLD_PERIOD = 0.5


def link_age(ad) -> str:
    return "child" if oot_live.u32(ad, oot.save(ad) + 4) == 1 else "adult"      # save.linkAge: 0 adult, 1 child


def equipped_sword(ad) -> int:
    return oot_live.u16(ad, oot.save(ad) + oot.S_EQUIPS) & 0xF


def object_segment(ad, oid: int) -> int:
    """Where object `oid` is loaded (play->objectCtx.slots[].segment), or 0."""
    base = oot.play(ad) + oot_live.OBJECT_CTX
    n = min(oot._rd(ad, base + 8, 1)[0], OBJECT_SLOTS)
    raw = oot._rd(ad, base + 0x0C, OBJECT_SLOT * n) if n else b""
    for i in range(n):
        sid, seg = struct.unpack_from(">h2xI", raw, OBJECT_SLOT * i)
        if sid == oid and seg in RDRAM:
            return seg
    return 0


def rows_for(age: str, sword: int, rows=None) -> list[dict]:
    return [r for r in (DLS if rows is None else rows) if r["age"] == age and sword in r["swords"]]


def _is_sword(role: str, st: dict, tex: dict) -> bool:
    if not st["tex_on"] or st["tex_src"] is None:
        return role == "back"                      # only the sheath's mouth is untextured; hand and sword are textured
    src = st["tex_src"]
    if src == METAL_TEX:
        return role == "hand"                      # the blade in hand; on the back that texture is the Mirror Shield
    if src >> 24 != 6:
        return False
    return (src & 0xFFFFFF) in tex["sword"] or (role == "back" and (src & 0xFFFFFF) in tex["sheath"])


def walk(obj: bytes, row: dict, tex: dict) -> dict:
    """Run one display list of the object: {"sword": {vertex offset: (x, y, z)}, "other": {offsets}, "conflicts",
    "ended"}. Vertex offsets are object-relative."""
    sword, other = {}, set()

    def on_tri(st, idx, _here, _which):
        mine = _is_sword(row["role"], st, tex)
        for i in idx:
            v = st["vb"][i]
            if v is None:
                continue
            if mine:
                sword[v[4] & 0xFFFFFF] = v[0]
            else:
                other.add(v[4] & 0xFFFFFF)
    st = OW.run_dl({6: obj}, 0x06000000 | row["dl"], on_tri)
    ended = bool(st["cmds"]) and st["cmds"][-1][1] >> 24 == 0xDF and any(c[1] >> 24 == 0x01 for c in st["cmds"])
    both = sword.keys() & other
    for o in both:
        sword.pop(o)
    return {"sword": sword, "other": other, "conflicts": len(both), "ended": ended}


def pivot_of(points) -> tuple[tuple[float, float, float], int, tuple[int, int]]:
    """The sword's end nearest the limb origin: along its longest axis take the extreme closest to 0, the pivot is the
    centroid of the vertices within 15% of the extent from that end (the pommel), placed exactly on the end.
    -> (pivot, axis index, (lo, hi) extent on that axis)."""
    cols = list(zip(*points))
    ext = [max(c) - min(c) for c in cols]
    axis = ext.index(max(ext))
    lo, hi = min(cols[axis]), max(cols[axis])
    end = lo if abs(lo) <= abs(hi) else hi
    slab = [p for p in points if abs(p[axis] - end) <= 0.15 * ext[axis]]
    piv = [sum(c) / len(slab) for c in zip(*slab)]
    piv[axis] = float(end)
    return tuple(piv), axis, (lo, hi)


def sword_plan(obj: bytes, age: str, sword: int, rows=None) -> dict:
    """What scaling the equipped sword means in this object: per display list its sword vertices and pivot, the original
    Vtx records, the contiguous runs to write, and the largest factor that keeps every coordinate an s16."""
    rows = rows_for(age, sword, rows)
    if not rows:
        raise ValueError(f"no sword display lists for {age} with sword {sword}")
    tex = TEX[age]
    dls, verts, orig = [], {}, {}
    for row in rows:
        w = walk(obj, row, tex)
        ranges = [VTX[n] for n in row["vtx"]]
        inside = lambda o: any(off <= o < off + 16 * cnt for off, cnt in ranges)       # noqa: E731
        if not w["ended"] or not w["sword"] or not all(inside(o) for o in (*w["sword"], *w["other"])):
            raise RuntimeError(f"{row['name']} in the loaded object is not the ROM's list (object not loaded, or replaced)")
        piv, axis, extent = pivot_of(list(w["sword"].values()))
        exp = row["expect"]
        if exp and (len(w["sword"]), len(w["other"]), *extent) != tuple(exp):
            raise RuntimeError(f"{row['name']}: found {len(w['sword'])} sword / {len(w['other'])} other vertices, extent "
                               f"{extent}; expected {exp} - the loaded model is not the ROM's (already scaled?)")
        for o, p in w["sword"].items():
            if o not in verts:
                verts[o] = (p, piv)
                orig[o] = bytes(obj[o:o + 16])
        dls.append({"name": row["name"], "dl": row["dl"], "role": row["role"], "sword": len(w["sword"]), "other": len(w["other"]),
                    "conflicts": w["conflicts"], "axis": axis, "pivot": tuple(round(v, 1) for v in piv), "extent": extent})
    maxf = 1e9
    for (x, y, z), piv in verts.values():
        for c, p in zip((x, y, z), piv):
            if c > p:
                maxf = min(maxf, (S16[1] - p) / (c - p))
            elif c < p:
                maxf = min(maxf, (S16[0] - p) / (c - p))
    offs = sorted(verts)
    runs = []
    for o in offs:
        if runs and runs[-1][0] + runs[-1][1] == o:
            runs[-1] = (runs[-1][0], runs[-1][1] + 16)
        else:
            runs.append((o, 16))
    hand = next((d for d in dls if d["role"] == "hand"), None)
    return {"age": age, "sword": sword, "object": LINK_OBJECT[age], "dls": dls, "verts": verts, "orig": orig, "runs": runs,
            "vertices": len(verts), "max_factor": int(maxf * 100) / 100,
            "reach_pivot": hand["pivot"][0] if hand and hand["axis"] == 0 else None}


def scaled_bytes(plan: dict, factor: float) -> dict[int, bytes]:
    """{vertex offset: 16-byte Vtx} with x, y, z scaled about the list's pivot; refuses an s16 overflow."""
    out = {}
    for o, (p, piv) in plan["verts"].items():
        new = [int(round(q + (c - q) * factor)) for c, q in zip(p, piv)]
        if any(not S16[0] <= v <= S16[1] for v in new):
            raise ValueError(f"factor {factor:g} would push a sword vertex past the s16 range; the largest factor that fits "
                             f"is {plan['max_factor']:g}")
        out[o] = struct.pack(">3h", *new) + plan["orig"][o][6:]
    return out


def _run_bytes(table: dict[int, bytes], run: tuple[int, int]) -> bytes:
    return b"".join(table[o] for o in range(run[0], run[0] + run[1], 16))


def reach_table(ad, version: str, sword: int, cached: int = 0) -> int:
    """Address of sMeleeWeaponLengths in the running game, verified by content (all entries original, or only the equipped
    sword's changed); 0 when not found."""
    i = REACH_INDEX.get(sword)
    ok = lambda raw: len(raw) == 24 and all(raw[k:k + 4] == REACH_ORIG[k:k + 4] for k in range(0, 24, 4) if k != 4 * i)  # noqa: E731
    for at in ([cached] if cached else []) + ([REACH_AT[version]] if version in REACH_AT else []):
        if ok(oot._rd(ad, at, 24)):
            return at
    base = OW.VERSIONS.get(version, {}).get("code_vram")
    if not base:
        return 0
    code = oot._rd(ad, base, CODE_WINDOW)
    k = code.find(REACH_ORIG)
    return base + k if k >= 0 and code.find(REACH_ORIG, k + 1) < 0 else 0


def reach_value(sword: int, pivot: float | None, factor: float) -> float:
    orig = struct.unpack(">6f", REACH_ORIG)[REACH_INDEX[sword]]
    p = pivot or 0.0
    return p + (orig - p) * factor


# ---------------------------------------------------------------- the session hold (re-apply after scene changes)

HOLDS: dict[str, dict] = {}


def hold(sid: str) -> dict:
    return HOLDS.setdefault(sid, {"link": None, "sword": None, "lock": threading.RLock(), "ticks": 0,
                                  "applied": {"link": 0, "sword": 0}, "skipped": 0, "error": None, "thread": None})


def _tick_link(ad, h: dict) -> None:
    f = h["link"]
    if f is None:
        return
    pl = player_actor(ad)
    if not pl:
        return
    want = struct.pack(">3f", *[LINK_SCALE * f] * 3)
    if oot._rd(ad, pl + A_SCALE, 12) != want:
        oot._wr(ad, pl + A_SCALE, want)
        h["applied"]["link"] += 1


def _write_sword(ad, seg: int, plan: dict, table: dict[int, bytes], accept: tuple[dict, ...]) -> tuple[int, int]:
    """Write every run whose current bytes are one of `accept` (the ROM's vertices / our previous scaling). -> (written,
    skipped runs)."""
    done = skipped = 0
    for run in plan["runs"]:
        cur = oot._rd(ad, seg + run[0], run[1])
        want = _run_bytes(table, run)
        if cur == want:
            continue
        if any(cur == _run_bytes(t, run) for t in accept):
            oot._wr(ad, seg + run[0], want)
            done += 1
        else:
            skipped += 1
    return done, skipped


def _build(ad, age: str, sword: int, seg: int, rows=None) -> dict:
    obj = oot._rd(ad, seg, OBJECT_SIZE[LINK_OBJECT[age]])
    return sword_plan(obj, age, sword, rows)


def apply_sword(ad, sid: str, factor: float, reach: bool = True, rows=None) -> dict:
    """Scale the equipped sword now and hold it (factor 1: restore and release)."""
    factor = _check_factor(factor)
    h = hold(sid)
    try:
        with h["lock"]:
            return _apply_sword(ad, sid, h, factor, reach, rows)
    finally:
        if h["sword"] is None and h["link"] is None and HOLDS.get(sid) is h:
            HOLDS.pop(sid, None)                     # nothing held (refused, or factor 1): no empty hold left behind


def _apply_sword(ad, sid: str, h: dict, factor: float, reach: bool, rows) -> dict:
    age, sword = link_age(ad), equipped_sword(ad)
    if not sword:
        raise RuntimeError("Link has no sword equipped - equip one (or zelda_oot op=kit) and ask again")
    seg = object_segment(ad, LINK_OBJECT[age])
    if not seg:
        raise RuntimeError("Link's object is not loaded right now (scene loading?) - try again in gameplay")
    s = h["sword"]
    if s and s["key"] != (age, sword):                # the operator changed age or sword since the last call
        _restore_sword(ad, s)
        s = h["sword"] = None
    plan = s["plan"] if s else _build(ad, age, sword, seg, rows)
    scaled = scaled_bytes(plan, factor)
    accept = (plan["orig"],) + ((s["scaled"],) if s else ())
    done, skipped = _write_sword(ad, seg, plan, scaled, accept)
    verified = all(oot._rd(ad, seg + r[0], r[1]) == _run_bytes(scaled, r) for r in plan["runs"])
    out = {"sword": SWORDS[sword], "age": age, "factor": factor, "object": hex(seg), "vertices": plan["vertices"],
           "lists": [d["name"] for d in plan["dls"]], "pivot": plan["dls"][0]["pivot"], "runs_written": done,
           "runs_skipped": skipped, "max_factor": plan["max_factor"], "verified": verified, "hold": factor != 1.0,
           "note": "kept across scene changes and age/equipment changes by the session's hold; factor 1 restores"}
    rt = reach_table(ad, oot.layout(ad)["version"], sword, (s or {}).get("reach_at", 0)) if reach else 0
    if rt:
        val = reach_value(sword, plan["reach_pivot"], factor)
        at = rt + 4 * REACH_INDEX[sword]
        oot._wr(ad, at, struct.pack(">f", val))
        out["reach"] = {"table": hex(rt), "length": round(val, 1), "verified": oot._rd(ad, at, 4) == struct.pack(">f", val)}
    elif reach:
        out["reach"] = {"table": None, "note": "sMeleeWeaponLengths not found in this ROM's code; the hit range is unchanged"}
    if factor == 1.0:
        h["sword"] = None
    else:
        h["sword"] = {"key": (age, sword), "plan": plan, "factor": factor, "scaled": scaled, "reach": reach,
                      "reach_at": rt, "segment": seg, "rows": rows}
        start(sid)
    return out


def _restore_sword(ad, s: dict) -> int:
    plan = s["plan"]
    seg = object_segment(ad, plan["object"])
    done = 0
    if seg:
        done, _ = _write_sword(ad, seg, plan, plan["orig"], (s["scaled"],))
        if s.get("reach_at"):
            i = REACH_INDEX[plan["sword"]]
            oot._wr(ad, s["reach_at"] + 4 * i, REACH_ORIG[4 * i:4 * i + 4])
    return done


def _tick_sword(ad, h: dict) -> None:
    s = h["sword"]
    if not s:
        return
    age, sword = link_age(ad), equipped_sword(ad)
    if (age, sword) != s["key"]:                     # the operator changed age or sword: follow the new one
        if not sword:
            return
        seg = object_segment(ad, LINK_OBJECT[age])
        if not seg:
            return
        _restore_sword(ad, s)
        plan = _build(ad, age, sword, seg, s.get("rows"))
        s.update({"key": (age, sword), "plan": plan, "scaled": scaled_bytes(plan, s["factor"]), "segment": seg})
        if s.get("reach"):
            s["reach_at"] = reach_table(ad, oot.layout(ad)["version"], sword)
    plan = s["plan"]
    seg = object_segment(ad, plan["object"])
    if not seg:
        return
    done, skipped = _write_sword(ad, seg, plan, s["scaled"], (plan["orig"],))
    h["applied"]["sword"] += done
    h["skipped"] += skipped
    s["segment"] = seg
    if s.get("reach") and s.get("reach_at"):
        i = REACH_INDEX[plan["sword"]]
        want = struct.pack(">f", reach_value(plan["sword"], plan["reach_pivot"], s["factor"]))
        if oot._rd(ad, s["reach_at"] + 4 * i, 4) != want:
            oot._wr(ad, s["reach_at"] + 4 * i, want)


def tick(ad, h: dict) -> None:
    """One pass of the hold: put Link's scale and the sword's vertices back wherever the game reset them."""
    with h["lock"]:
        h["ticks"] += 1
        _tick_link(ad, h)
        _tick_sword(ad, h)


def hold_link(ad, sid: str, factor: float) -> dict:
    """scale_link now, and keep it across scene changes (factor 1: restore and release)."""
    out = scale_link(ad, factor)
    h = hold(sid)
    with h["lock"]:
        h["link"] = None if factor == 1.0 else factor
        if h["link"] is not None:
            start(sid)
        elif h["sword"] is None:
            HOLDS.pop(sid, None)
    out["hold"] = factor != 1.0
    out["note"] = ("kept across scene changes by the session's hold; factor 1 restores" if factor != 1.0
                   else "Link is back to his normal size; nothing is held")
    return out


def start(sid: str) -> dict:
    """Run the hold thread for this session (idempotent)."""
    h = hold(sid)
    if h["thread"] and h["thread"].is_alive():
        return h

    def loop():
        from .tools import SESSIONS
        while sid in SESSIONS and HOLDS.get(sid) is h:
            try:
                tick(SESSIONS[sid][0], h)
                h["error"] = None
            except Exception as e:                   # noqa: BLE001 - the game is loading / resetting: try again
                h["error"] = f"{type(e).__name__}: {e}"
            time.sleep(HOLD_PERIOD)
    h["thread"] = threading.Thread(target=loop, daemon=True, name=f"oot-scale-{sid}")
    h["thread"].start()
    return h


def status(sid: str) -> dict:
    h = HOLDS.get(sid)
    if not h:
        return {"link": None, "sword": None, "holding": False}
    s = h["sword"]
    return {"link": h["link"], "sword": {"name": SWORDS[s["key"][1]], "age": s["key"][0], "factor": s["factor"],
                                         "object": hex(s["segment"]), "reach_table": hex(s["reach_at"]) if s.get("reach_at") else None}
            if s else None,
            "holding": bool(h["thread"] and h["thread"].is_alive()), "ticks": h["ticks"], "applied": h["applied"],
            "skipped_runs": h["skipped"], "error": h["error"]}


def release(ad, sid: str) -> dict:
    """Restore Link and the sword and stop the hold."""
    h = HOLDS.pop(sid, None)
    out = {"released": bool(h)}
    if not h:
        return out
    with h["lock"]:
        if h["link"] is not None:
            try:
                out["link"] = scale_link(ad, 1.0)
            except RuntimeError as e:
                out["link"] = {"error": str(e)}
        if h["sword"]:
            out["sword_runs_restored"] = _restore_sword(ad, h["sword"])
    return out
