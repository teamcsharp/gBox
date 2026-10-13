"""SSB64 (Europe) fighter reloc-file analysis (stage 2).

Builds on gbox.ssb64_inventory and the US decomp's typed masters
(https://github.com/VetriTheRetri/ssb-decomp-re, src/relocData).  Every
offset and expectation below is reproduced from that decomp and verified
byte-level against the owned EUR ROM in tests/test_ssb64_analysis.py.

Key findings encoded here
-------------------------
1. EUR file IDs are shifted, not shared, with the US table: 13 files are
   inserted at EUR IDs 0..12 and 4 at EUR IDs 268..271
   (gbox.ssb64_inventory.eur_to_us).  Fighter files are EUR IDs 215..263
   (US 202..250).

2. LBRelocDesc chains (src/lb/lbreloc.c): a relocated pointer slot is a
   4-byte union ``{u16 next_slot; u16 words_num}`` that the loader
   overwrites in place with the resolved pointer
   (``target_base + words_num * 4``).  The internal chain head is the
   table entry's ``reloc_intern_offset`` (words); the external chain head
   is ``reloc_extern_offset``, and one u16 target file ID per extern slot
   is stored after the compressed payload, in chain order.

3. Fighter file layout (Mario example, EUR IDs):
   * 215 MarioMainMotion: pure ``ftMotionCommand`` script data
     (u32 per command: opcode in bits 31..26, parameter in 25..0;
     Subroutine/Goto consume a following pointer slot).
   * 216 MarioMain: 0x428 bytes of pre-data (the blobs FTAttributes
     fields point at) followed by the serialized ``FTAttributes`` struct
     (0x348 bytes; the two sizes sum to exactly the file's 1904 bytes).
   * The model's DObjDesc JointTree sits in the MarioModel file (EUR 313)
     at byte offset 0x2200 (extern slot (89, 2176 words) of file 216);
     DObjDesc = {s32 id; void *dl; Vec3f translate; Vec3f rotate;
     Vec3f scale} (44 bytes, src/sys/objtypes.h).
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from gbox import ssb64_inventory as inv

# ---- constants ---------------------------------------------------------

# EUR fighter file IDs (see inv.US_FIGHTERS for the US layout).
FIGHTER_FILES_EUR = {name: ids for name, ids in inv.FIGHTERS.items()}

# ftMotionEvent opcodes, in enum order (src/ft/ftdef.h FTMotionEvent).
MOTION_EVENTS = (
    "End", "SyncWait", "AsyncWait", "MakeAttackColl", "MakeAttackCollScaled",
    "ClearAttackCollID", "ClearAttackCollAll", "SetAttackCollOffset",
    "SetAttackCollDamage", "SetAttackCollSize", "SetAttackCollSoundLevel",
    "RefreshAttackCollID", "SetThrow", "SetDamageThrown", "PlayFGM",
    "PlayLoopSFXStoreInfo", "StopLoopSFX", "PlayVoiceStoreInfo",
    "PlayLoopVoiceStoreInfo", "PlayFGMStoreInfo", "PlaySmashVoice",
    "SetFlag0", "SetFlag1", "SetFlag2", "SetFlag3", "SetAirJumpAdd",
    "SetAirJumpMax", "SetHitStatusPartAll", "SetHitStatusPartID",
    "SetHitStatusAll", "ResetDamageCollPartAll", "SetDamageCollPartID",
    "LoopBegin", "LoopEnd", "Subroutine", "Return", "Goto", "PauseScript",
    "Effect", "EffectItemHold", "SetModelPartID", "ResetModelPartAll",
    "HideModelPartAll", "SetTexturePartID", "SetColAnim", "ResetColAnim",
    "SetParallelScript", "SetSlopeContour", "HideItem", "MakeRumble",
    "StopRumble", "SetAfterImage",
)

# FTAttributes serialized struct layout (src/ft/fttypes.h struct
# FTAttributes): (field_name, size_in_bytes) in declaration order.  The
# struct begins at offset 0x428 of the fighter Main file (pre-data is 266
# words).  Sum of sizes == 0x348 == file size - 0x428.
FTATTRIBUTES_FIELDS: tuple[tuple[str, int], ...] = (
    ("size", 4), ("walkslow_anim_length", 4), ("walkmiddle_anim_length", 4),
    ("walkfast_anim_length", 4), ("throw_walkslow_anim_length", 4),
    ("throw_walkmiddle_anim_length", 4), ("throw_walkfast_anim_length", 4),
    ("rebound_anim_length", 4), ("walk_speed_mul", 4), ("traction", 4),
    ("dash_speed", 4), ("dash_decel", 4), ("run_speed", 4),
    ("kneebend_anim_length", 4), ("jump_vel_x", 4), ("jump_height_mul", 4),
    ("jump_height_base", 4), ("jumpaerial_vel_x", 4),
    ("jumpaerial_height", 4), ("air_accel", 4), ("air_speed_max_x", 4),
    ("air_friction", 4), ("gravity", 4), ("tvel_base", 4), ("tvel_fast", 4),
    ("jumps_max", 4), ("weight", 4), ("attack1_followup_frames", 4),
    ("dash_to_run", 4), ("shield_size", 4), ("shield_break_vel_y", 4),
    ("shadow_size", 4), ("jostle_width", 4), ("jostle_x", 4),
    ("is_metallic", 4), ("cam_offset_y", 4), ("closeup_camera_zoom", 4),
    ("camera_zoom", 4), ("camera_zoom_base", 4), ("map_coll", 16),
    ("cliffcatch_coll", 8), ("dead_fgm_ids", 4), ("deadup_sfx", 2),
    ("damage_sfx", 2), ("smash_sfx", 6), ("pad_align_0xC2", 2),
    ("item_pickup", 32), ("itemthrow_vel_scale", 2),
    ("itemthrow_damage_scale", 2),
    ("heavyget_sfx", 2), ("pad_align_0xEA", 2), ("halo_size", 4),
    ("shade_color", 12), ("fog_color", 4), ("attack_flags", 4),
    ("damage_coll_descs", 396),
    ("hit_detect_range", 12), ("setup_parts", 4), ("animlock", 4),
    ("effect_joint_ids", 20), ("cliff_status_ga", 20), ("unused_0x2CC", 4),
    ("hiddenparts", 4), ("commonparts_container", 4), ("dobj_lookup", 4),
    ("shield_anim_joints", 32), ("joint_rfoot_id", 4),
    ("joint_rfoot_rotate", 4), ("joint_lfoot_id", 4),
    ("joint_lfoot_rotate", 4), ("filler_0x30C", 16), ("unk_0x31C", 4),
    ("unk_0x320", 4), ("translate_scales", 4), ("modelparts_container", 4),
    ("accesspart", 4), ("textureparts_container", 4),
    ("joint_itemheavy_id", 4), ("thrown_status", 4),
    ("joint_itemlight_id", 4), ("sprites", 4), ("skeleton", 4),
)

# Byte offset of the FTAttributes struct inside a fighter Main file.
FTATTRIBUTES_OFFSET = 0x428


def ft_attributes_field_offsets() -> dict[str, int]:
    """Byte offsets of FTAttributes fields relative to the struct start."""
    offs: dict[str, int] = {}
    off = 0
    for name, size in FTATTRIBUTES_FIELDS:
        offs[name] = off
        off += size
    return offs


# ---- file access -------------------------------------------------------

def load_file(rom: bytes, entry: dict[str, Any]) -> bytes:
    """Decompress (or slice) one EUR file body from the ROM."""
    src = rom[entry["rom_offset"]:entry["rom_offset"] + entry["stored_bytes"]]
    if entry["compressed"]:
        data = inv.vpk0_decode(src, entry["decompressed_bytes"])
        if data is None:
            raise ValueError(f"vpk0 decode failed for EUR file {entry['id']}")
        return data
    return src


def read_table_entry(rom: bytes, eur_id: int) -> dict[str, Any]:
    """Raw LBTableEntry for a EUR file ID, without the manifest."""
    table = inv.locate_table(rom)
    if table is None:
        raise ValueError("no LBTableEntry table found")
    table_addr, file_count = table
    if not 0 <= eur_id < file_count:
        raise ValueError(f"EUR file ID {eur_id} out of range")
    data_begin = table_addr + (file_count + 1) * inv.ENTRY_SIZE
    e = inv.parse_entry(
        rom[table_addr + eur_id * inv.ENTRY_SIZE:
            table_addr + (eur_id + 1) * inv.ENTRY_SIZE], eur_id)
    return {
        "id": eur_id,
        "rom_offset": data_begin + e.data_offset,
        "stored_bytes": e.stored_bytes,
        "decompressed_bytes": e.decompressed_bytes,
        "compressed": e.is_compressed,
        "reloc_intern": e.reloc_intern,
        "reloc_extern": e.reloc_extern,
        "data_begin": data_begin,
        "data_offset": e.data_offset,
        "compressed_size": e.compressed_size,
    }


# ---- reloc chains ------------------------------------------------------

def walk_chain(buf: bytes, start_word: int) -> list[tuple[int, int, int]]:
    """Walk an LBRelocDesc chain.

    Returns ``(slot_word, next_word, words_num)`` per slot, in chain
    order, until ``next_word == 0xFFFF``.  Raises ValueError on a malformed
    chain (out-of-bounds slot or loop).
    """
    slots: list[tuple[int, int, int]] = []
    seen: set[int] = set()
    cur = start_word
    while cur != 0xFFFF:
        if cur * 4 + 4 > len(buf):
            raise ValueError(f"reloc slot word {cur} out of file bounds")
        if cur in seen:
            raise ValueError(f"reloc chain loop at word {cur}")
        seen.add(cur)
        next_word, words_num = struct.unpack_from(">HH", buf, cur * 4)
        slots.append((cur, next_word, words_num))
        cur = next_word
    return slots


def extern_file_ids(rom: bytes, entry: dict[str, Any]) -> list[int]:
    """The u16 target file IDs that follow a file's compressed payload.

    One per extern slot, in chain order (src/lb/lbreloc.c
    lbRelocLoadAndRelocFile: ``data_rom_offset += compressed_size * 4``).
    """
    after = (entry["data_begin"] + entry["data_offset"]
             + entry["compressed_size"] * 4)
    if entry["reloc_extern"] == 0xFFFF:
        return []
    count = len(walk_chain(load_file(rom, entry), entry["reloc_extern"]))
    if after + 2 * count > len(rom):
        raise ValueError(f"extern file-ID list of EUR file {entry['id']} runs past the ROM")
    return [int.from_bytes(rom[after + 2 * i:after + 2 * i + 2], "big")
            for i in range(count)]


def resolve_chain(buf: bytes, start_word: int, target_base: int = 0) -> bytearray:
    """Apply a chain in place: each slot becomes target_base + words_num*4.

    For the internal chain target_base is 0 (pointers are file-relative);
    callers resolving an external chain supply the target file's base.
    """
    out = bytearray(buf)
    for slot_word, _next, words_num in walk_chain(buf, start_word):
        struct.pack_into(">I", out, slot_word * 4, target_base + words_num * 4)
    return out


# ---- motion script decoding --------------------------------------------

def decode_motion_script(
    buf: bytes, start: int = 0, count: int | None = None,
) -> list[dict[str, Any]]:
    """Decode ftMotionCommand words from a MainMotion file.

    Each entry: {offset, word, opcode, name, param}; Subroutine (34) and
    Goto (36) also emit the following pointer slot as {offset, slot_words,
    slot_next} (the slot holds the pre-relocation chain fields).
    """
    out: list[dict[str, Any]] = []
    off = start
    limit = None if count is None else start + count
    while off + 4 <= len(buf) and (limit is None or len(out) < limit):
        word = struct.unpack_from(">I", buf, off)[0]
        opcode = (word >> 26) & 0x3F
        param = word & 0x3FFFFFF
        entry: dict[str, Any] = {
            "offset": off, "word": word, "opcode": opcode,
            "name": MOTION_EVENTS[opcode] if opcode < len(MOTION_EVENTS)
            else f"Unknown{opcode}", "param": param,
        }
        out.append(entry)
        off += 4
        if opcode in (34, 36):  # Subroutine / Goto: pointer slot follows
            if off + 4 > len(buf):
                raise ValueError(f"{entry['name']} at {off - 4:#x} is missing its pointer slot")
            slot_next, slot_words = struct.unpack_from(">HH", buf, off)
            out.append({"offset": off, "slot_next": slot_next,
                        "slot_words": slot_words,
                        "slot_target_off": slot_words * 4})
            off += 4
    return out


# ---- FTAttributes (the fighter Main file) ------------------------------

def parse_ft_attributes(buf: bytes) -> dict[str, Any]:
    """Decode the FTAttributes struct region of a fighter Main file.

    Expects the raw (unrelocated) file body.  Returns the decoded scalar
    fields plus the raw pointer-slot fields; verify() checks the anchors.
    """
    fields = ft_attributes_field_offsets()
    base = FTATTRIBUTES_OFFSET
    if base + fields["skeleton"] + 4 > len(buf):
        raise ValueError("file too small for FTAttributes struct")

    def u32(name: str) -> int:
        return struct.unpack_from(">I", buf, base + fields[name])[0]

    def f32(name: str) -> float:
        return struct.unpack_from(">f", buf, base + fields[name])[0]

    return {
        "struct_offset": base,
        "size": f32("size"),
        "walkslow_anim_length": f32("walkslow_anim_length"),
        "walkfast_anim_length": f32("walkfast_anim_length"),
        "run_speed": f32("run_speed"),
        "jumps_max": u32("jumps_max"),
        "weight": f32("weight"),
        "joint_rfoot_id": u32("joint_rfoot_id"),
        "joint_lfoot_id": u32("joint_lfoot_id"),
        "joint_itemheavy_id": u32("joint_itemheavy_id"),
        "joint_itemlight_id": u32("joint_itemlight_id"),
        "setup_parts_slot": u32("setup_parts"),
        "animlock_slot": u32("animlock"),
        "hiddenparts_slot": u32("hiddenparts"),
        "commonparts_container_slot": u32("commonparts_container"),
        "dobj_lookup_slot": u32("dobj_lookup"),
        "modelparts_container_slot": u32("modelparts_container"),
        "textureparts_container_slot": u32("textureparts_container"),
        "thrown_status_slot": u32("thrown_status"),
        "sprites_slot": u32("sprites"),
        "skeleton_slot": u32("skeleton"),
    }


def parse_ft_attributes_pre_data(buf: bytes) -> dict[str, Any]:
    """Decode the pre-data blob anchors (src/relocData/203_MarioMain.c)."""
    if len(buf) < 0x2C:
        raise ValueError("file too small for the FTAttributes pre-data anchors")
    animlock = buf[0x0C:0x0C + 8]
    return {
        "file_handles_slots": [
            struct.unpack_from(">HH", buf, off) for off in (0x00, 0x04, 0x08)],
        "animlock": struct.unpack(">II", animlock),
        "setup_parts": struct.unpack_from(">II", buf, 0x14),
        "hiddenparts_0": struct.unpack_from(">IIII", buf, 0x1C),
    }


def probe_mario(rom_path: str | Path) -> dict[str, Any]:
    """The analysis-stage probe: decode one Mario animation (EUR 215) and
    the Mario model header (EUR 216), returning reproducible offsets."""
    rom = Path(rom_path).read_bytes()
    e215 = read_table_entry(rom, inv.us_to_eur(202))   # MarioMainMotion
    e216 = read_table_entry(rom, inv.us_to_eur(203))   # MarioMain
    motion = load_file(rom, e215)
    main = load_file(rom, e216)

    script = decode_motion_script(motion, 0, 12)
    intern_215 = walk_chain(motion, e215["reloc_intern"])
    intern_216 = walk_chain(main, e216["reloc_intern"])
    extern_216 = walk_chain(main, e216["reloc_extern"])
    ids_216 = extern_file_ids(rom, e216)
    attrs = parse_ft_attributes(main)
    pre = parse_ft_attributes_pre_data(main)

    # The model's DObjDesc JointTree: extern slot 89 of file 216
    # (commonparts_container[0].dobj) -> MarioModel (EUR 313) + 0x2200.
    slot89 = next((s for s in extern_216 if s[0] == 89), None)
    if slot89 is None:
        raise ValueError("file 216 extern chain missing slot 89 (JointTree)")
    return {
        "mario_main_motion_eur_id": 215,
        "mario_main_eur_id": 216,
        "mario_model_eur_id": inv.us_to_eur(296),
        "motion_script_head": script,
        "motion_intern_slots": intern_215,
        "main_pre_data": pre,
        "main_attrs": attrs,
        "main_intern_slots": intern_216,
        "main_extern_slots": extern_216,
        "main_extern_file_ids": ids_216,
        "dobj_jointtree_file": inv.us_to_eur(296),
        "dobj_jointtree_offset": slot89[2] * 4,
    }
