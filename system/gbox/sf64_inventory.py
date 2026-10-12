"""Star Fox 64 (USA Rev A, N64) owned-build inventory.

Owned source (hyperspin catalog, game_id 59a2755566b669ed):
    collections/Nintendo 64/roms/USA/Star Fox 64 (USA).7z
    archive sha256 b7726c67db890eb2ae87de78de512629480c80af965699c4c9bab63b19d80389
    The archive holds one .n64 member (v64 byte order, 12,582,912 bytes) that
    normalizes to the US Rev A z64 build:
        md5    741a94eee093c4c8684e66b89f8685e8
        sha1   09f0d105f476b00efa5303a3ebc42e60a7753b7a
        sha256 385bcf1901ed12fb1152f3c227d1968cc54ae41e8566da66695df71af40a573f
    This is the exact baserom of the matching decompilation sonicdcer/sf64
    ("Starfox 64 (US) REV 1.1").  A second catalog file
    "Star Fox 64 (USA) (Rev A).zip" holds the same member bytes.

Container layout (retail build, 12 MiB):
    The retail ROM packs every segment through a 64-entry DMA file table at
    0xDE480 (16-byte entries: v_begin, p_begin, p_end, comp_flag).  The first
    six files (makerom..audio_table) and seven more (ast_great_fox,
    ast_star_wolf, ast_7_ti_2, ast_8_ti, ast_9_ti, ast_A_ti, ast_logo) are
    stored raw; the remaining 51 files are MIO0-compressed with a
    1-bit-per-output-byte layout variant (see mio0_decompress).  v_begin of a
    file is its offset in the uncompressed working image that splat maps
    (yamls/us/rev1/*.yaml in the decomp), p_begin/p_end bound the packed blob
    in the retail ROM.

    Rebuilding the uncompressed image (decompress every MIO0 file, place at
    v_begin, rewrite the table entries and header CRCs the way the decomp's
    tools/comptool.py does) reproduces the decomp's
    starfox64.us.rev1.uncompressed md5 23e24fb0f090c6c0b3793a96169dce51,
    which verifies the decode end to end (see rebuild_uncompressed).

Character/asset inventory (segment-level, grounded in the decomp scene
tables src/engine/fox_load_inits.c and the splat segment map; the per-object
offsets inside each segment are analysis-stage work):
    * ast_common       - assets shared by every scene (slot 0x1 in every
                         Scene table): common player-craft data.
    * ast_arwing / ast_landmaster / ast_blue_marine / ast_versus - the
                         playable crafts (Arwing, Landmaster, Blue Marine)
                         and their versus variants.
    * ast_allies       - ally wingman craft (Bill Grey on Katina, Katt Monroe
                         on Zoness, James McCloud on Venom).
    * ast_star_wolf    - Star Wolf team craft (Wolf, Leon, Pigma, Andrew).
    * ast_great_fox    - Great Fox carrier (and its support assets).
    * ast_andross      - Andross and his forms.
    * ast_enmy_planet / ast_enmy_space - generic enemy craft pools per theater.
    * ast_bg_space / ast_bg_planet - planet/space backdrops.
    * ast_radio        - 2D pilot radio portraits (CI8 TLUT sprites, see
                         sVsCharNameTex/TLUT use in ovl_menu/fox_option.c).
    * ast_text / ast_font_3d - HUD text sprites and the 3D font.
    * ast_<level>      - per-stage geometry/props/bosses (corneria, meteo,
                         titania, sector_x/z/y, aquas, area_6, venom_1/2,
                         ve1_boss, bolse, fortuna, solar, zoness, katina,
                         macbeth, warp_zone, title, map, training, ...).
    * ovl_i1..i6 / ovl_menu / ovl_ending / ovl_unused - code overlays.

This module is stdlib-only and read-only: it never writes to the source ROM.
"""

import argparse
import hashlib
import json
import struct

# Comptool (tools/comptool.py in sonicdcer/sf64) facts for the US build.
FILE_TABLE_US11 = 0xDE480
FILE_NAMES_US = [
    "makerom", "main", "dma_table", "audio_seq", "audio_bank", "audio_table",
    "ast_common", "ast_bg_space", "ast_bg_planet",
    "ast_arwing", "ast_landmaster", "ast_blue_marine", "ast_versus",
    "ast_enmy_planet", "ast_enmy_space", "ast_great_fox",
    "ast_star_wolf", "ast_allies", "ast_corneria", "ast_meteo", "ast_titania",
    "ast_7_ti_2", "ast_8_ti", "ast_9_ti", "ast_A_ti",
    "ast_7_ti_1", "ast_sector_x", "ast_sector_z", "ast_aquas", "ast_area_6",
    "ast_venom_1", "ast_venom_2", "ast_ve1_boss", "ast_bolse", "ast_fortuna",
    "ast_sector_y", "ast_solar", "ast_zoness", "ast_katina", "ast_macbeth",
    "ast_warp_zone", "ast_title", "ast_map", "ast_option", "ast_vs_menu",
    "ast_text", "ast_font_3d", "ast_andross", "ast_logo", "ast_ending",
    "ast_ending_award_front", "ast_ending_award_back", "ast_ending_expert",
    "ast_training", "ast_radio",
    "ovl_i1", "ovl_i2", "ovl_i3", "ovl_i4", "ovl_i5", "ovl_i6",
    "ovl_menu", "ovl_ending", "ovl_unused",
]
UNCOMPRESSED_RAW = {15, 16, 21, 22, 23, 24, 48}  # comptool decomp_inds_ntsc minus 0..5

REV_A_IDENTITY = {
    "md5": "741a94eee093c4c8684e66b89f8685e8",
    "sha1": "09f0d105f476b00efa5303a3ebc42e60a7753b7a",
    "sha256": "385bcf1901ed12fb1152f3c227d1968cc54ae41e8566da66695df71af40a573f",
    "size": 0xC00000,
    "name": "STARFOX64",
    "region": "E",
    "rev": 1,
    "label": "US Rev A (1.1)",
}
UNCOMPRESSED_MD5 = "23e24fb0f090c6c0b3793a96169dce51"

SEGMENT_ROLES = {
    "makerom": "boot", "main": "main_code", "dma_table": "file_table",
    "audio_seq": "audio_sequence", "audio_bank": "audio_bank",
    "audio_table": "audio_table",
    "ast_common": "player_craft_common",
    "ast_bg_space": "backdrop_space", "ast_bg_planet": "backdrop_planet",
    "ast_arwing": "player_craft_arwing", "ast_landmaster": "player_craft_landmaster",
    "ast_blue_marine": "player_craft_blue_marine", "ast_versus": "player_craft_versus",
    "ast_enmy_planet": "enemy_planet", "ast_enmy_space": "enemy_space",
    "ast_great_fox": "great_fox", "ast_star_wolf": "star_wolf",
    "ast_allies": "allies",
    "ast_corneria": "level_corneria", "ast_meteo": "level_meteo",
    "ast_titania": "level_titania", "ast_7_ti_2": "level_titania_2",
    "ast_8_ti": "level_8_ti", "ast_9_ti": "level_9_ti", "ast_A_ti": "level_A_ti",
    "ast_7_ti_1": "level_titania_1", "ast_sector_x": "level_sector_x",
    "ast_sector_z": "level_sector_z", "ast_aquas": "level_aquas",
    "ast_area_6": "level_area_6", "ast_venom_1": "level_venom_1",
    "ast_venom_2": "level_venom_2", "ast_ve1_boss": "level_venom_1_boss",
    "ast_bolse": "level_bolse", "ast_fortuna": "level_fortuna",
    "ast_sector_y": "level_sector_y", "ast_solar": "level_solar",
    "ast_zoness": "level_zoness", "ast_katina": "level_katina",
    "ast_macbeth": "level_macbeth", "ast_warp_zone": "level_warp_zone",
    "ast_title": "ui_title", "ast_map": "ui_map", "ast_option": "ui_option",
    "ast_vs_menu": "ui_vs_menu", "ast_text": "ui_text_sprites",
    "ast_font_3d": "ui_font_3d", "ast_andross": "boss_andross",
    "ast_logo": "ui_logo", "ast_ending": "ui_ending",
    "ast_ending_award_front": "ui_ending_award_front",
    "ast_ending_award_back": "ui_ending_award_back",
    "ast_ending_expert": "ui_ending_expert",
    "ast_training": "level_training", "ast_radio": "ui_radio_portraits",
    "ovl_i1": "overlay_i1", "ovl_i2": "overlay_i2", "ovl_i3": "overlay_i3",
    "ovl_i4": "overlay_i4", "ovl_i5": "overlay_i5", "ovl_i6": "overlay_i6",
    "ovl_menu": "overlay_menu", "ovl_ending": "overlay_ending",
    "ovl_unused": "overlay_unused",
}

ROSTER = {
    "playable_pilots": ["Fox McCloud", "Falco Lombardi", "Slippy Toad", "Peppy Hare"],
    "multiplayer_only": ["Bill Grey", "Katt Monroe", "James McCloud"],
    "star_wolf_team": ["Wolf O'Donnell", "Leon Powalski", "Pigma Dengar", "Andrew Oikonny"],
    "playable_vehicles": ["Arwing", "Landmaster", "Blue Marine"],
    "supporting": ["General Pepper (radio portraits)", "ROB64 (Great Fox)", "Andross (final boss)"],
    "asset_segments": {
        "playable_pilots": ["ast_common", "ast_arwing", "ast_landmaster",
                            "ast_blue_marine", "ast_versus"],
        "multiplayer_only": ["ast_allies"],
        "star_wolf_team": ["ast_star_wolf"],
        "supporting": ["ast_radio", "ast_great_fox", "ast_andross"],
    },
    "note": ("Segment-level mapping is grounded in the sonicdcer/sf64 scene "
             "tables (src/engine/fox_load_inits.c) and segment names; the "
             "per-object model/sprite offsets inside each segment are "
             "analysis-stage work."),
}


def load_rom(path):
    """Read a ROM image and normalize its byte order to z64 (big endian).

    Detects .z64 (name reads STAR), .n64 little endian (RATS) and .n64
    byteswapped/v64 (TSRA) the same way the decomp's comptool.py does, via
    the game name string at 0x20.
    """
    with open(path, "rb") as fh:
        raw = fh.read()
    game_str = raw[0x20:0x24]
    if game_str == b"STAR":
        return bytes(raw)
    if game_str == b"RATS":
        return bytes(raw[::-1])
    if game_str == b"TSRA":
        return b"".join(bytes((raw[i + 1], raw[i]))
                        for i in range(0, len(raw) - 1, 2))
    raise ValueError("Unknown ROM byte order (name string %r)" % game_str)


def rom_identity(rom):
    """Header facts and hashes of a z64-normalized ROM."""
    out = {
        "size": len(rom),
        "md5": hashlib.md5(rom).hexdigest(),
        "sha1": hashlib.sha1(rom).hexdigest(),
        "sha256": hashlib.sha256(rom).hexdigest(),
        "name": rom[0x20:0x34].decode("ascii", "replace").rstrip("\x00 "),
        "region": chr(rom[0x3E]),
        "rev": rom[0x3F],
        "build": None,
    }
    if (out["md5"] == REV_A_IDENTITY["md5"] and out["size"] == REV_A_IDENTITY["size"]):
        out["build"] = REV_A_IDENTITY["label"]
    return out


def find_file_table(rom):
    """Locate the DMA file table with the comptool signature search.

    The comptool signature can match two bytes before the first entry (the
    tail of `main` is zero-padded), so the hit is snapped to the entry whose
    first record is makerom {v_begin=0, p_begin=0, p_end=0x1050, flag=0}.
    """
    for sig in (b"\x00" * 12 + b"\x10\x50\x00\x00\x00\x00",
                b"\x00" * 12 + b"\x10\x60\x00\x00\x00\x00"):
        hit = rom.find(sig)
        if hit != -1:
            for off in (hit, hit + 2, hit - 2):
                if (off >= 0 and off + 16 <= len(rom)
                        and rom[off:off + 16] == b"\x00" * 8 + b"\x00\x00\x10\x50" + b"\x00" * 4):
                    return off
            raise ValueError("DMA file table signature found at %#x but "
                             "no aligned makerom entry" % hit)
    raise ValueError("DMA file table not found")


def parse_file_table(rom, ft):
    """Parse 16-byte table entries (v_begin, p_begin, p_end, comp_flag)."""
    entries = []
    for i in range(256):
        off = ft + 0x10 * i
        if off + 16 > len(rom):
            break
        v_begin, p_begin, p_end, flag = struct.unpack(">IIII", rom[off:off + 16])
        if v_begin == 0 and p_end == 0:
            break
        entries.append((v_begin, p_begin, p_end, flag))
    return entries


def mio0_decompress(blob):
    """Decompress the MIO0 variant used by Star Fox 64.

    Unlike the Super Mario 64 flavor (1 control bit per 16 compressed bytes),
    this variant stores one control bit per OUTPUT byte: a 1 bit copies one
    byte from the uncompressed section, a 0 bit reads a 2-byte back-reference
    (length = (b0 >> 4) + 3, distance = ((b0 & 0xF) << 8 | b1) + 1).
    Header: "MIO0", u32 dest_size, u32 comp_offset, u32 uncomp_offset,
    all section offsets relative to the blob start (see
    tools/mio0-decompressor/libmio0.c in sonicdcer/sf64).
    """
    if len(blob) < 16 or blob[:4] != b"MIO0":
        raise ValueError("not a MIO0 blob")
    dest_size, comp_off, uncomp_off = struct.unpack(">III", blob[4:16])
    bits = blob[16:comp_off]
    comp = blob[comp_off:uncomp_off]
    uncomp = blob[uncomp_off:]
    out = bytearray()
    ci = ui = 0
    for bit_i in range(len(bits) * 8):
        if len(out) >= dest_size:
            break
        if bits[bit_i // 8] & (1 << (7 - bit_i % 8)):
            if ui >= len(uncomp):
                raise ValueError("MIO0 uncompressed section overrun")
            out.append(uncomp[ui])
            ui += 1
        else:
            if ci + 2 > len(comp):
                raise ValueError("MIO0 compressed section overrun")
            b0, b1 = comp[ci], comp[ci + 1]
            ci += 2
            length = (b0 >> 4) + 3
            dist = ((b0 & 0x0F) << 8) + b1 + 1
            for _ in range(length):
                if len(out) < dist:
                    raise ValueError("MIO0 back-reference before output start")
                out.append(out[-dist])
    if len(out) != dest_size:
        raise ValueError("MIO0 size mismatch: decoded %d, header says %d"
                         % (len(out), dest_size))
    return bytes(out)


def decode_file(rom, entry):
    """Return the decompressed bytes of one DMA table entry."""
    v_begin, p_begin, p_end, flag = entry
    if not (0 <= p_begin < p_end <= len(rom)):
        raise ValueError("packed range %#x-%#x outside ROM" % (p_begin, p_end))
    data = rom[p_begin:p_end]
    if flag == 1:
        data = mio0_decompress(data)
    elif flag != 0:
        raise ValueError("invalid compression flag %d" % flag)
    return data


def _crc_update(buf, seed=0xF8CA4DDC, start=0x1000, end=0x101000):
    t1 = t2 = t3 = t4 = t5 = t6 = seed
    for d, in struct.iter_unpack(">I", buf[start:end]):
        r = ((d << (d & 0x1F)) | (d >> (32 - (d & 0x1F)))) & 0xFFFFFFFF
        if (t6 + d) & 0xFFFFFFFF < t6:
            t4 = (t4 + 1) & 0xFFFFFFFF
        t3 ^= d
        t6 = (t6 + d) & 0xFFFFFFFF
        t2 ^= r if (t2 > d) else (t6 ^ d)
        t5 = (t5 + r) & 0xFFFFFFFF
        t1 = (t1 + (t5 ^ d)) & 0xFFFFFFFF
    return ((t6 ^ t4 ^ t3) & 0xFFFFFFFF, (t5 ^ t2 ^ t1) & 0xFFFFFFFF)


def rebuild_uncompressed(rom):
    """Reconstruct the uncompressed working image the way comptool -dse does.

    Returns the image bytes; verified against the decomp's published md5
    (UNCOMPRESSED_MD5) by verify=True callers.  The image is ~15.7 MiB
    (last file ovl_unused ends at 0xEFFAE0).
    """
    ft = find_file_table(rom)
    entries = parse_file_table(rom, ft)
    placed = []
    size = 0
    for entry in entries:
        v_begin = entry[0]
        data = decode_file(rom, entry)
        placed.append((v_begin, data))
        size = max(size, v_begin + len(data))
    out = bytearray(size)
    for v_begin, data in placed:
        out[v_begin:v_begin + len(data)] = data
    for i, (v_begin, data) in enumerate(placed):
        struct.pack_into(">IIII", out, ft + 0x10 * i,
                         v_begin, v_begin, v_begin + len(data), 0)
    crc1, crc2 = _crc_update(out)
    struct.pack_into(">II", out, 0x10, crc1, crc2)
    return bytes(out)


def inventory(rom_path, archive_sha256=None):
    """Build the inventory manifest for an owned ROM image path."""
    rom = load_rom(rom_path)
    ident = rom_identity(rom)
    ft = find_file_table(rom)
    entries = parse_file_table(rom, ft)
    files = []
    n_mio0 = 0
    for i, entry in enumerate(entries):
        v_begin, p_begin, p_end, flag = entry
        data = decode_file(rom, entry)
        name = FILE_NAMES_US[i] if i < len(FILE_NAMES_US) else "file_%d" % i
        if flag == 1:
            n_mio0 += 1
            dest_size = struct.unpack(">I", rom[p_begin + 4:p_begin + 8])[0]
            assert dest_size == len(data)
        else:
            dest_size = len(data)
        files.append({
            "index": i,
            "name": name,
            "role": SEGMENT_ROLES.get(name, "unknown"),
            "v_begin": v_begin,
            "v_end": v_begin + len(data),
            "packed_begin": p_begin,
            "packed_end": p_end,
            "packed_size": p_end - p_begin,
            "compressed": flag == 1,
            "size": len(data),
        })
    raw_count = sum(1 for e in entries if e[3] == 0)
    manifest = {
        "game": "Star Fox 64 (USA)",
        "game_id": "59a2755566b669ed",
        "platform": "n64",
        "source": {
            "catalog_rel_path": "collections/Nintendo 64/roms/USA/Star Fox 64 (USA).7z",
            "archive_sha256": archive_sha256,
            "rom": ident,
        },
        "container": {
            "file_table_offset": ft,
            "file_count": len(entries),
            "mio0_compressed_files": n_mio0,
            "raw_files": raw_count,
            "retail_size": len(rom),
            "uncompressed_size": max(f["v_end"] for f in files),
            "uncompressed_md5": UNCOMPRESSED_MD5,
            "uncompressed_md5_verified": hashlib.md5(
                rebuild_uncompressed(rom)).hexdigest() == UNCOMPRESSED_MD5,
        },
        "files": files,
        "roster": ROSTER,
        "formats": {
            "compression": "MIO0 (1-bit-per-output-byte layout variant)",
            "rom_byte_order": "z64 after normalization (.n64 member is v64)",
            "asset_formats": ("Object/display-list structures inside the ast_* "
                              "segments are analysis-stage work; 2D portraits "
                              "in ast_radio/ast_text are TLUT-based CI sprites "
                              "per ovl_menu/fox_option.c usage."),
        },
        "launch_prerequisites": {
            "emulator": "RetroArch (Windows worker)",
            "core": "parallel_n64 (gBox forces parallel_n64 on Windows N64)",
            "rsp": "cxd4 LLE (angrylion gfxplugin; auto/hle RSP renders 3D black)",
            "bios": "none",
            "input": "RetroArch network gamepad / session_op send_input",
            "audio": "agent jobs enforce 2% playback volume on the test PC",
        },
    }
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description="Star Fox 64 (USA Rev A) inventory")
    ap.add_argument("rom", help="path to the owned ROM (.z64 or .n64/v64)")
    ap.add_argument("--out", help="write the manifest JSON to this path")
    ap.add_argument("--archive-sha256", default=None,
                    help="sha256 of the owned archive (recorded as source identity)")
    ap.add_argument("--verify-uncompressed", action="store_true",
                    help="rebuild the uncompressed image and check its md5")
    args = ap.parse_args(argv)
    manifest = inventory(args.rom, args.archive_sha256)
    if args.verify_uncompressed and not manifest["container"]["uncompressed_md5_verified"]:
        raise SystemExit("uncompressed image md5 does not match the decomp reference")
    text = json.dumps(manifest, indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
        print("wrote %s" % args.out)
    else:
        print(text)
    return manifest


if __name__ == "__main__":
    main()
