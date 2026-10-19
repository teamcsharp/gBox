"""Star Fox 64 (USA Rev A) analysis-stage object/model/display-list probe.

This is the analysis milestone for game 59a2755566b669ed: it locates the
object table (``gObjectInfo``, the gObjectTable-equivalent) in the ``main``
segment, parses its per-object entries, and enumerates the playable-craft
(Arwing) model / display-list format with reproducible ROM offsets and
cross-references.  Every offset here is grounded in the matching decomp
sonicdcer/sf64 ("Starfox 64 (US) REV 1.1") and re-verified against the owned
ROM below.

Grounding sources (decomp):
  * include/sf64object.h     -> Object / ObjectInfo structs + ObjectId enum
  * include/gfx.h            -> Limb / Animation / JointKey structs
  * src/engine/fox_edata_info.c -> gObjectInfo[] (406 entries) contents
  * assets/yaml/us/rev1/ast_*.yaml -> runtime segment slot -> v_begin,
                               per-symbol offsets inside each ast_* segment

Key facts established (all re-verified against the owned build):
  * gObjectInfo[] lives in ``main`` at ROM offset 0xCCD24 (VRAM 0x80CC124),
    406 entries of 0x24 bytes each.  Entry 0 is OBJ_SCENERY_CO_STONE_ARCH with
    dList aCoStoneArchDL (segmented 0x06015F00).
  * The playable craft (Arwing / Landmaster / Blue Marine / Versus) are all
    loaded into runtime segment slot 0x3 (mutually exclusive: one craft at a
    time).  ast_arwing = slot 0x3 @ v_begin 0x8BFC00.
  * Skinned model format (same family as OoT/MM):
      Limb      0x20 bytes {Gfx* dList; Vec3f trans; Vec3s rot; Limb* sib; Limb* child}
      Animation 0x0C bytes {s16 frameCount; s16 limbCount; u16* frameData; JointKey* jointKey}
      JointKey  0x0C bytes {u16 xLen,x; yLen,y; zLen,z}
      Skeleton  array of Limb* (segmented pointers); Arwing root limbs follow.
  * The Arwing pilot identity is a set of per-pilot head display lists inside
    ast_arwing (aAwFoxHeadDL / Falco / Slippy / Peppy / James) plus the shared
    aAwArwingSkel skeleton and aAwWings{Open,Closed}Anim animations.

This module is stdlib-only and read-only: it never writes to the source ROM.
"""

import argparse
import json
import struct

from . import sf64_inventory as _inv

# --- object table -----------------------------------------------------------

OBJECT_INFO_SIZE = 0x24
OBJ_ID_MAX = 406

# Verified: gObjectInfo[] first entry (OBJ_SCENERY_CO_STONE_ARCH) sits at
# main+0xCBCD4.  main starts at ROM 0x1050 (VRAM 0x80000450), so:
GOBJECT_INFO_ROM = 0xCCD24
GOBJECT_INFO_VRAM = 0x80CC124

# ObjectInfo field layout (include/sf64object.h).  Offsets are relative to the
# start of a 0x24-byte record.
_OI = {
    "draw": (0x00, "u32", "draw function (VRAM) or display list (segmented)"),
    "drawType": (0x04, "u8", "0 = static dList, 1/2 = per-object draw function"),
    "action": (0x08, "u32", "update/action function (VRAM) or 0"),
    "hitbox": (0x0C, "u32", "f32* hitbox dims (segmented)"),
    "cullDistance": (0x10, "f32", "draw cull distance"),
    "unk_14": (0x14, "s16", "camera/billboard flag"),
    "unk_16": (0x16, "s16", "death behaviour flag"),
    "damage": (0x18, "u8", "collision damage class"),
    "unk_19": (0x19, "u8", "camera-related flag"),
    "targetOffset": (0x1C, "f32", "target-lock y offset; 0.0f = untargetable"),
    "bonus": (0x20, "u8", "hit bonus (>=1 = hit+)"),
}

# Playable-craft object entries in the ObjectId enum (include/sf64object.h).
# 195/197/198/199 are the actor classes that render the player/team craft.
PLAYABLE_CRAFT_OBJECT_IDS = {
    195: "OBJ_ACTOR_CUTSCENE",   # ACTOR_CS_TEAM_ARWING in cutscenes
    197: "OBJ_ACTOR_ALLRANGE",   # team craft in all-range mode
    198: "OBJ_ACTOR_TEAM_BOSS",  # teammates during a boss fight
    199: "OBJ_ACTOR_JAMES",      # James McCloud's Arwing (ending)
}

# Runtime segment slot -> (file, v_begin) candidates, from the decomp's
# assets/yaml/us/rev1/<seg>.yaml ``segments:`` blocks.  Slot 0x3 is shared by
# every playable craft (loaded one-at-a-time per scene).
SEGMENT_SLOTS = {
    0x01: [("ast_common", 0x873CB0)],
    0x02: [("ast_bg_space", 0x8A68C0)],
    0x03: [("ast_arwing", 0x8BFC00), ("ast_landmaster", 0x8D99F0),
           ("ast_blue_marine", 0x8E1F80), ("ast_versus", 0x8E92D0)],
    0x04: [("ast_enmy_space", 0x922730)],
    0x06: [("ast_corneria", 0x961CE0)],
    0x0D: [("ast_allies", 0x955270)],
    0x0F: [("ast_star_wolf", 0x940AD0)],
}

# Arwing model/display-list inventory inside ast_arwing (segment slot 0x3,
# v_begin 0x8BFC00).  Offsets are relative to the segment start; symbols and
# offsets are taken from assets/yaml/us/rev1/ast_arwing.yaml.
ARWING = {
    "segment": "ast_arwing",
    "slot": 0x03,
    "v_begin": 0x8BFC00,
    "skeleton": ("aAwArwingSkel", 0x16610, "Limb*[] (root limbs)"),
    "animations": [
        ("aAwWingsClosedAnim", 0x15C28),
        ("aAwWingsOpenAnim", 0x163C4),
    ],
    "display_lists": [
        # shared craft geometry
        ("aAwBodyDL", 0x9B60),
        ("aAwRightWingDL", 0x15D80),
        ("aAwLeftWingDL", 0x16660),
        # per-pilot head display lists (the pilot identity swap surface)
        ("aAwFoxHeadDL", 0x90),
        ("aAwPeppyHeadDL", 0x3CE0),
        ("aAwSlippyHeadDL", 0x5AB0),
        ("aAwFalcoHeadDL", 0x16CC0),
        ("aAwJamesHeadDL", 0x1C90),
    ],
}


# --- low-level helpers ------------------------------------------------------

def _u32(b, o):
    return struct.unpack(">I", b[o:o + 4])[0]


def _f32(b, o):
    return struct.unpack(">f", b[o:o + 4])[0]


def file_bytes(rom, name):
    """Return the decompressed bytes of one DMA-table file by name."""
    ft = _inv.find_file_table(rom)
    entries = _inv.parse_file_table(rom, ft)
    for i, entry in enumerate(entries):
        if i < len(_inv.FILE_NAMES_US) and _inv.FILE_NAMES_US[i] == name:
            return _inv.decode_file(rom, entry)
    raise KeyError("no such file in DMA table: %s" % name)


def segmented_parts(addr):
    """Split a segmented address 0x0Nxxxxxx into (slot, offset)."""
    return (addr >> 24) & 0xFF, addr & 0xFFFFFF


def is_segmented(addr):
    hi = (addr >> 24) & 0xFF
    return 0x01 <= hi <= 0x0F


def resolve_slot(slot, offset):
    """Resolve a segment slot+offset to (file, v_begin, file_offset) options.

    Slot 0x3 is ambiguous (all four playable craft share it), so every
    candidate is returned; callers pick the one matching the scene.
    """
    out = []
    for file_name, v_begin in SEGMENT_SLOTS.get(slot, []):
        out.append((file_name, v_begin, offset))
    return out


def _entry_at(rom, index):
    """Raw bytes of one gObjectInfo entry."""
    off = GOBJECT_INFO_ROM + index * OBJECT_INFO_SIZE
    return rom[off:off + OBJECT_INFO_SIZE]


def object_info(rom, index):
    """Parse one gObjectInfo entry into a dict (values left as ints/floats)."""
    e = _entry_at(rom, index)
    draw = _u32(e, 0x00)
    out = {
        "id": index,
        "draw": draw,
        "drawType": e[0x04],
        "action": _u32(e, 0x08),
        "hitbox": _u32(e, 0x0C),
        "cullDistance": _f32(e, 0x10),
        "unk_14": struct.unpack(">h", e[0x14:0x16])[0],
        "unk_16": struct.unpack(">h", e[0x16:0x18])[0],
        "damage": e[0x18],
        "unk_19": e[0x19],
        "targetOffset": _f32(e, 0x1C),
        "bonus": e[0x20],
    }
    out["draw_kind"] = ("segmented-dlist" if is_segmented(draw)
                        else "vram-function" if (draw >> 24) in (0x80, 0x81)
                        else "null")
    return out


def parse_limb(seg, off):
    """Parse a 0x20-byte Limb at segment-relative offset."""
    dlist = _u32(seg, off)
    return {
        "dList": dlist,
        "trans": (struct.unpack(">fff", seg[off + 0x04:off + 0x10])),
        "rot": struct.unpack(">hhh", seg[off + 0x10:off + 0x16]),
        "sibling": _u32(seg, off + 0x18),
        "child": _u32(seg, off + 0x1C),
    }


def parse_animation(seg, off):
    """Parse a 0x0C-byte Animation at segment-relative offset."""
    return {
        "frameCount": struct.unpack(">h", seg[off:off + 2])[0],
        "limbCount": struct.unpack(">h", seg[off + 2:off + 4])[0],
        "frameData": _u32(seg, off + 0x04),
        "jointKey": _u32(seg, off + 0x08),
    }


# --- high-level probe -------------------------------------------------------

def probe(rom):
    """Run the full analysis probe and return a report dict."""
    ft = _inv.find_file_table(rom)
    entries = _inv.parse_file_table(rom, ft)

    # 1. verify the object table location by its known first entry signature
    head = _entry_at(rom, 0)
    sig_ok = (head[0x00:0x04] == b"\x06\x01\x5f\x00"   # aCoStoneArchDL
              and head[0x04] == 0                       # drawType 0 (dList)
              and head[0x08:0x0C] == b"\x00" * 4        # action NULL
              and head[0x0C:0x10] == b"\x06\x03\xe3\xe0"  # aCoStoneArchHitbox
              and head[0x10:0x14] == b"\x44\x48\x00\x00")  # 800.0f

    # 2. enumerate the playable-craft object entries
    craft = {}
    for oid in sorted(PLAYABLE_CRAFT_OBJECT_IDS):
        info = object_info(rom, oid)
        craft[oid] = info

    # 3. Arwing model: decode ast_arwing, walk the skeleton and animations
    arwing = dict(ARWING)
    try:
        seg = file_bytes(rom, "ast_arwing")
        skel_sym, skel_off, _ = arwing["skeleton"]
        root_limbs = []
        # skeleton = array of segmented Limb* until a non-pointer word
        i = 0
        while i < 64:
            ptr = _u32(seg, skel_off + 4 * i)
            if not is_segmented(ptr):
                break
            root_limbs.append(ptr)
            i += 1
        arwing["skeleton_root_limbs"] = root_limbs

        limbs = {}
        for ptr in root_limbs:
            slot, off = segmented_parts(ptr)
            if slot == arwing["slot"] and off + 0x20 <= len(seg):
                limb = parse_limb(seg, off)
                limb["dList_in_arwing"] = (
                    is_segmented(limb["dList"])
                    and (limb["dList"] >> 24) == arwing["slot"])
                limbs["0x%08X" % ptr] = limb
        arwing["limbs"] = limbs

        anims = {}
        for sym, off in arwing["animations"]:
            a = parse_animation(seg, off)
            a["frameData_in_arwing"] = is_segmented(a["frameData"]) \
                and (a["frameData"] >> 24) == arwing["slot"]
            a["jointKey_in_arwing"] = is_segmented(a["jointKey"]) \
                and (a["jointKey"] >> 24) == arwing["slot"]
            anims[sym] = a
        arwing["animations_parsed"] = anims

        dls = []
        for sym, off in arwing["display_lists"]:
            dls.append({"symbol": sym, "offset": off,
                        "file_offset": arwing["v_begin"] + off})
        arwing["display_lists_offsets"] = dls
        arwing["segment_size"] = len(seg)
    except KeyError:
        arwing["error"] = "ast_arwing not found in DMA table"

    return {
        "game": "Star Fox 64 (USA Rev A)",
        "object_table": {
            "rom_offset": GOBJECT_INFO_ROM,
            "vram": GOBJECT_INFO_VRAM,
            "entry_size": OBJECT_INFO_SIZE,
            "entry_count": OBJ_ID_MAX,
            "signature_verified": sig_ok,
            "first_entry": object_info(rom, 0),
        },
        "playable_craft_objects": craft,
        "arwing_model": arwing,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Star Fox 64 (USA Rev A) analysis probe")
    ap.add_argument("rom", help="path to the owned ROM (.z64 or .n64/v64)")
    ap.add_argument("--out", help="write the report JSON to this path")
    args = ap.parse_args(argv)
    rom = _inv.load_rom(args.rom)
    report = probe(rom)
    text = json.dumps(report, indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
        print("wrote %s" % args.out)
    else:
        print(text)
    return report


if __name__ == "__main__":
    main()
