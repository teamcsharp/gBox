"""Dead Or Alive ++ (Tecmo TPS / Sony ZN) owned-source inventory: Japan parent doapp and Korea clone doappk.

Catalog entries: a19b4e641b155364 "Dead Or Alive ++ (Japan)" = MAME set doapp ("Japan/USA/Export", region chosen in the
test menu), 59c55e95af61abbe "Dead Or Alive ++ (Korea)" = doappk. Both run on the Tecmo TPS system: BIOS set coh1002m,
driver zn2p, Sony CXD8530CQ (PSX CPU/GPU) at 64.60 MHz plus a PlayStation SPU (src/mame/sony/zn.cpp). It is PlayStation
hardware without a disc: the game lives in a 0x2800000-byte "bankedroms" region the CPU sees through an 8 MiB window at
0x1f000000 (bank byte written to 0x1fb00006).

Owned source (Hyperspin MAME collection):
  collections/Mame/roms/doapp.zip      parent: doapp119.bin/doapp120.bin (program, 16-bit interleaved at 0),
                                       doapp-0..5 (4 MiB data banks at 0x400000..0x1bfffff), mg05 (ROM-board CAT702).
  collections/Mame/roms/doappk.zip     Korea clone: only the two program ROMs differ.
  collections/Mame/roms/coh1002m.zip   TPS BIOS m534002c-61.ic353 + mg01 (CPU-board CAT702). The 8 KiB
                                       78081g503.ic655 is NODUMP in MAME itself (not a gap in this library).

bankedroms layout (Japan, decoded with gbox.zn_tps_boot):
  0x000000  0x0000020b, the SCEI licence string, then the ENCODED main program (to 0x88880, 0xff padded to 0xa0000).
            The BIOS decodes it through the CAT702 pair into RAM 0x80010000..0x80097e18, entry 0x800107d8.
  0x0a0000  FILE_TABLE[0]: plain overlay code+data loaded at 0x80097e18 (0x90930 bytes).
  everything after: 279 more files addressed only by the 12-byte records (u8 bank, u32 offset in the 8 MiB bank,
            u32 size) at RAM 0x800515a4 inside the decoded program -> FILE_TABLE below. Nothing in the data banks names
            or indexes its files, so the table cannot be recovered without decoding the program.

Fighters: per-fighter tables in the decoded program, indexed by the internal fighter id (0..13; ids 3/7/10 are unused
slots that alias Kasumi's files): model files per costume at 0x80087334 (19 costume slots x 4 bytes; costumes 0-3 are
real, 4 is a zero-size table entry), and six one-file-per-fighter tables (CHAR_TABLES). Ids come from the ranking
tables at 0x80087940 (u8 id + name). A model file is [geometry block][TIMs]: u32[0] is the offset of the TIM run.
"""

from __future__ import annotations

import hashlib
import json
import struct
import zipfile

GAME_ID = "59c55e95af61abbe"
GAME_TITLE = "Dead Or Alive ++ (Korea)"
MAME_SET = "doappk"
PARENT_SET = "doapp"
BIOS_SET = "coh1002m"

# name -> (bankedroms offset, size, MAME sha1) for the doappk set
BANKED_ROMS = {
    # ROM_LOAD16_BYTE at +1 (odd bytes) / +0 (even bytes)
    "doapp_u0119.119": (0x0000001, 0x100000, "616b3e65a32768767209ae77c48ad34d11b31754"),
    "doapp_u0120.120": (0x0000000, 0x100000, "d38783110440ffa00036b86f97bff5edb6a5673f"),
    "doapp-0.216": (0x0400000, 0x400000, "a744567a3d75634098b1749103307981be9acbdd"),
    "doapp-1.217": (0x0800000, 0x400000, "3fae1fcb4665ba8bad391881b26c2d087718d42f"),
    "doapp-2.218": (0x0c00000, 0x400000, "6422972cf5d30a0f09f0c20f042691d5969207b4"),
    "doapp-3.219": (0x1000000, 0x400000, "8631fde93a1da6325d7b31c7edf12c964f0ac4fc"),
    "doapp-4.220": (0x1400000, 0x400000, "5bd66da993f0db966581dde80dd7e5b377754412"),
    "doapp-5.221": (0x1800000, 0x400000, "b1d1b9532b5f074ce216a603436d5674d136865d"),
}

# the dat also requires the parent's shared ROMs for a split-set launch;
# we verify them from doapp.zip
PARENT_ROMS = {
    "doapp119.bin": ("bbe04cef", "f2dae4810ca78075fc3007a6001531a455235a2e"),
    "doapp120.bin": ("b614d7e6", "373756d9b88b45c677e987ee1e5cb2d5446ecfe8"),
    "mg05": (None, "c88d73f6a646a9ddefdfd84cba70d591759c069f"),
}

BIOS_ROMS = {
    "m534002c-61.ic353": "03eb2febfab3fcde716defff291babd9392de965",
    "mg01.ic652": "cef4011c6c06d6fce546e1db5d9fbae155eabf57",
}

ROSTER = ["AYANE", "LEI-FANG", "RAIDOU", "BASS", "BAYMAN", "GEN-FU",
          "KASUMI", "HAYABUSA", "JANN-LEE", "TINA", "ZACK"]
ROSTER_TABLE_OFFSETS = (0x00A03FC, 0x014296C)

SCEI_LICENSE = b"Licensed by Sony Computer Entertainment Inc.(SCEI)"


def merge_banked(clone_zip_path: str, parent_zip_path: str) -> bytes:
    """Build the 40 MiB 'bankedroms' image exactly as MAME loads it.

    119/120 are 16-bit interleaved: even byte from u0120, odd byte from u0119.
    doapp-0..5 fill 0x400000+ in order.
    """
    out = bytearray(0x2800000)
    with zipfile.ZipFile(clone_zip_path) as z:
        d119 = z.read("doapp_u0119.119")
        d120 = z.read("doapp_u0120.120")
    for i in range(len(d119)):
        out[2 * i] = d120[i]
        out[2 * i + 1] = d119[i]
    with zipfile.ZipFile(parent_zip_path) as z:
        for name in ("doapp-0.216", "doapp-1.217", "doapp-2.218",
                     "doapp-3.219", "doapp-4.220", "doapp-5.221"):
            off = BANKED_ROMS[name][0]
            data = z.read(name)
            out[off:off + len(data)] = data
    return bytes(out)


def verify_rom_sha1(zip_path: str, roms: dict) -> list[str]:
    """Return a list of 'name: expected <sha1>' lines for every mismatch."""
    problems = []
    with zipfile.ZipFile(zip_path) as z:
        for name, expected in roms.items():
            if name not in z.namelist():
                problems.append(f"{name}: missing from {zip_path}")
                continue
            got = hashlib.sha1(z.read(name)).hexdigest()
            if got != expected:
                problems.append(f"{name}: expected {expected}, got {got}")
    return problems


def find_roster(data: bytes) -> list[tuple[str, int]]:
    """Locate the ordered 11-name roster table(s) in the merged image."""
    found = []
    target = ROSTER[0].encode("ascii")
    start = 0
    while True:
        i = data.find(target, start)
        if i < 0:
            break
        window = data[i:i + 256]
        names = []
        pos = i
        for name in ROSTER:
            j = window.find(name.encode("ascii"))
            if j < 0:
                break
            names.append((name, pos + j))
            window = window[j + 1:]
            pos += j + 1
        if len(names) == len(ROSTER):
            found.append((i, names[0][1]))
        start = i + 1
    return [(off, off) for off in set(o for _, o in found)]


def tim_count(data: bytes) -> int:
    """Count PSX TIM texture headers (magic 0x10, version 0)."""
    return data.count(b"\x10\x00\x00\x00")


def inventory(src_dir: str, out_json: str | None = None) -> dict:
    """Verify the owned zips and emit the inventory manifest."""
    import os
    clone_zip = os.path.join(src_dir, "doappk.zip")
    parent_zip = os.path.join(src_dir, "doapp.zip")
    bios_zip = os.path.join(src_dir, "coh1002m.zip")
    for p in (clone_zip, parent_zip, bios_zip):
        if not os.path.exists(p):
            raise FileNotFoundError(p)

    merged = merge_banked(clone_zip, parent_zip)
    roster_hits = find_roster(merged)
    manifest = {
        "game_id": GAME_ID,
        "title": GAME_TITLE,
        "mame_set": MAME_SET,
        "clone_of": PARENT_SET,
        "bios_set": BIOS_SET,
        "platform": {
            "system": "Tecmo TPS (ZN-2 variant, BIOS coh1002m)",
            "driver": "zn2p",
            "source": "src/mame/sony/zn.cpp",
            "chips": ["Sony CXD8530CQ @ 64.60 MHz", "PlayStation SPU @ 32.30 MHz"],
            "screen": "640x480 raster, 60 Hz",
            "savestate": True,
        },
        "sources": {
            "clone_zip": {
                "file": "collections/Mame/roms/doappk.zip",
                "sha256": hashlib.sha256(open(clone_zip, "rb").read()).hexdigest(),
            },
            "parent_zip": {
                "file": "collections/Mame/roms/doapp.zip",
                "sha256": hashlib.sha256(open(parent_zip, "rb").read()).hexdigest(),
            },
            "bios_zip": {
                "file": "collections/Mame/roms/coh1002m.zip",
                "sha256": hashlib.sha256(open(bios_zip, "rb").read()).hexdigest(),
            },
        },
        "rom_verification": {
            "clone_vs_dat": verify_rom_sha1(
                clone_zip,
                {n: v[2] for n, v in BANKED_ROMS.items()
                 if n.startswith("doapp_u0")},
            ),
            "parent_vs_dat": verify_rom_sha1(
                parent_zip,
                {n: v[2] for n, v in BANKED_ROMS.items()
                 if n.startswith("doapp-")} | {
                    n: v[1] for n, v in PARENT_ROMS.items()},
            ),
            "bios_vs_dat": verify_rom_sha1(bios_zip, BIOS_ROMS),
        },
        "container": {
            "bankedroms_size": len(merged),
            "license_string_offset": merged.find(SCEI_LICENSE),
            "bankedroms_layout": [
                {"name": n, "offset": o, "size": s}
                for n, (o, s, _) in sorted(BANKED_ROMS.items(),
                                            key=lambda kv: kv[1][0])
            ],
            "security_device": "cat702_2: mg05 (8 B GAL, in parent zip)",
        },
        "characters": {
            "roster": ROSTER,
            "roster_table_offsets": sorted({o for o, _ in roster_hits}),
            "notes": "11 fighters; names are ASCII (not Shift-JIS) in the "
                     "merged bankedroms image; second table at 0x14296c "
                     "carries internal 3-letter codes (ZAK, TIN, JAN, ...).",
        },
        "assets": {
            "tim_texture_magic_count": tim_count(merged),
            "notes": "PSX TIM containers; model/animation format not yet "
                     "identified (analysis stage).",
        },
        "launch": {
            "mame_set": "doappk",
            "prerequisites": [
                "doappk.zip + doapp.zip + coh1002m.zip in MAME rompath",
                "MAME (recent build with zn2p/coh1002m support; RetroArch MAME core works)",
            ],
            "catalog_launch_name": "doappk",
        },
    }
    if out_json:
        with open(out_json, "w") as f:
            json.dump(manifest, f, indent=2)
    return manifest


# --------------------------------------------------------------------------------------------- Japan parent: doapp
GAME_ID_JP = "a19b4e641b155364"
GAME_IDS = {GAME_ID_JP: "doapp", GAME_ID: "doappk"}
DATA_BANKS = ("doapp-0.216", "doapp-1.217", "doapp-2.218", "doapp-3.219", "doapp-4.220", "doapp-5.221")
PROGRAM_SHA1 = {"doapp": "614873868c77e64076730e3525c672f20363d654"}   # merged bankedroms[0:0x200000]
ENTRY_POINT = 0x800107D8
FILE_TABLE_RAM = 0x800515A4
FILE_COUNT = 280
OVERLAY_RAM = 0x80097E18          # FILE_TABLE[0] is loaded here (main program loader at 0x800ff67c)
BANK_SIZE = 0x800000

# (bank, offset in bank, size) - the program's table at FILE_TABLE_RAM, decoded with gbox.zn_tps_boot (doapp)
FILE_TABLE = (
    (0, 0xa0000, 0x90930), (0, 0x130930, 0x12721), (0, 0x143054, 0x0), (0, 0x143054, 0x4afa), (0, 0x147b50, 0xa25c),
    (0, 0x151dac, 0xa5de), (0, 0x15c38c, 0x8cb0), (0, 0x16503c, 0x9ce8), (0, 0x16ed24, 0xac78), (0, 0x17999c, 0x9468),
    (0, 0x182e04, 0xa346), (0, 0x18d14c, 0xb9e0), (0, 0x198b2c, 0xb48e), (0, 0x1a3fbc, 0x9bbc), (0, 0x1adb78, 0xca24),
    (0, 0x1ba59c, 0x5d68), (0, 0x1c0304, 0x613e), (0, 0x1c6444, 0x4b24), (0, 0x1caf68, 0x5904), (0, 0x1d086c, 0x66dc),
    (0, 0x1d6f48, 0x5598), (0, 0x1dc4e0, 0x5dc6), (0, 0x1e22a8, 0x6128), (0, 0x1e83d0, 0x6622), (0, 0x1ee9f4, 0x5978),
    (0, 0x1f436c, 0x7610), (0, 0x400000, 0x38c7e), (0, 0x438c80, 0x57a30), (0, 0x4906b0, 0x5a2e8),
    (0, 0x4ea998, 0x64572), (0, 0x54ef0c, 0x3c726), (0, 0x58b634, 0x4cc64), (0, 0x5d8298, 0x50c08),
    (0, 0x628ea0, 0x42442), (0, 0x66b2e4, 0x5867e), (0, 0x6c3964, 0x5502a), (0, 0x718990, 0x5e3e4),
    (0, 0x776d74, 0x499f4), (0, 0x7c0768, 0x383a), (0, 0x7c3fa4, 0x3eea), (0, 0x7c7e90, 0x2c9e),
    (0, 0x7cab30, 0x39ca), (0, 0x7ce4fc, 0x3da4), (0, 0x7d22a0, 0x36f6), (0, 0x7d5998, 0x5de2), (0, 0x7db77c, 0x3086),
    (0, 0x7de804, 0x2d1c), (0, 0x7e1520, 0x4a1a), (0, 0x7e5f3c, 0x53da), (1, 0x0, 0x1bab4), (1, 0x1bab4, 0x1b714),
    (1, 0x371c8, 0x17c58), (1, 0x4ee20, 0x17924), (1, 0x66744, 0x0), (1, 0x66744, 0x1d520), (1, 0x83c64, 0x1db20),
    (1, 0xa1784, 0x1b28c), (1, 0xbca10, 0x1e074), (1, 0xdaa84, 0x0), (1, 0xdaa84, 0x193d0), (1, 0xf3e54, 0x191e0),
    (1, 0x10d034, 0x17f94), (1, 0x124fc8, 0x17b70), (1, 0x13cb38, 0x0), (1, 0x13cb38, 0x23370),
    (1, 0x15fea8, 0x23370), (1, 0x183218, 0x22748), (1, 0x1a5960, 0x22748), (1, 0x1c80a8, 0x0),
    (1, 0x1c80a8, 0x19a34), (1, 0x1e1adc, 0x19a48), (1, 0x1fb524, 0x19e90), (1, 0x2153b4, 0x19e90),
    (1, 0x22f244, 0x0), (1, 0x22f244, 0x1994c), (1, 0x248b90, 0x1994c), (1, 0x2624dc, 0x1ad78),
    (1, 0x27d254, 0x1ad10), (1, 0x297f64, 0x0), (1, 0x297f64, 0x1d988), (1, 0x2b58ec, 0x1d248),
    (1, 0x2d2b34, 0x1d4fc), (1, 0x2f0030, 0x1dbb8), (1, 0x30dbe8, 0x0), (1, 0x30dbe8, 0x193a4),
    (1, 0x326f8c, 0x193a4), (1, 0x340330, 0x18888), (1, 0x358bb8, 0x19f90), (1, 0x372b48, 0x0),
    (1, 0x372b48, 0x1b7b8), (1, 0x38e300, 0x1b2b4), (1, 0x3a95b4, 0x1a888), (1, 0x3c3e3c, 0x1ad1c),
    (1, 0x3deb58, 0x0), (1, 0x3deb58, 0x181f4), (1, 0x400000, 0x181f4), (1, 0x4181f4, 0x18578),
    (1, 0x43076c, 0x185f8), (1, 0x448d64, 0x0), (1, 0x448d64, 0x170a8), (1, 0x45fe0c, 0x1af90),
    (1, 0x47ad9c, 0x1c128), (1, 0x496ec4, 0x168fc), (1, 0x4ad7c0, 0x0), (1, 0x4ad7c0, 0x19b54),
    (1, 0x4c7314, 0x19b54), (1, 0x4e0e68, 0x310e4), (1, 0x511f4c, 0x31e54), (1, 0x543da0, 0x19974),
    (1, 0x55d714, 0x19974), (1, 0x577088, 0x19b54), (1, 0x590bdc, 0x19974), (1, 0x5aa550, 0x31e54),
    (1, 0x5dc3a4, 0x1b6f4), (1, 0x5f7a98, 0x1aa74), (1, 0x61250c, 0x19974), (1, 0x62be80, 0x19b54),
    (1, 0x6459d4, 0x32074), (1, 0x677a48, 0x34c54), (1, 0x6ac69c, 0x31e54), (1, 0x6de4f0, 0x19d34),
    (1, 0x6f8224, 0x1cc10), (1, 0x714e34, 0xe520), (1, 0x723354, 0xeef0), (1, 0x732244, 0xbae0),
    (1, 0x73dd24, 0x86d0), (1, 0x7463f4, 0xc6d0), (1, 0x752ac4, 0x8700), (1, 0x75b1c4, 0x5d90), (1, 0x760f54, 0xb670),
    (1, 0x76c5c4, 0x8ee0), (1, 0x7754a4, 0x9b30), (1, 0x77efd4, 0xb650), (1, 0x78a624, 0x7a90),
    (1, 0x7920b4, 0x24930), (1, 0x7b69e4, 0x16d10), (1, 0x7cd6f4, 0x21cf0), (2, 0x0, 0x200d0), (2, 0x200d0, 0x2c8b0),
    (2, 0x4c980, 0x213e0), (2, 0x6dd60, 0x1a600), (2, 0x88360, 0x2f9b0), (2, 0xb7d10, 0x357e0), (2, 0xed4f0, 0x2ead0),
    (2, 0x11bfc0, 0x1c400), (2, 0x1383c0, 0x32ff0), (2, 0x16b3b0, 0x5c20), (2, 0x170fd0, 0x339f0),
    (2, 0x1a49c0, 0x7ec9), (2, 0x1ac88c, 0x29d30), (2, 0x1d65bc, 0x66b0), (2, 0x1dcc6c, 0x329f0),
    (2, 0x20f65c, 0x62e4), (2, 0x215940, 0x335f0), (2, 0x248f30, 0x66e3), (2, 0x24f614, 0x326c0),
    (2, 0x281cd4, 0xabdf), (2, 0x28c8b4, 0x30e70), (2, 0x2bd724, 0x9be5), (2, 0x2c730c, 0x32a30),
    (2, 0x2f9d3c, 0x5574), (2, 0x2ff2b0, 0x32ce0), (2, 0x331f90, 0x6fa6), (2, 0x338f38, 0x31630),
    (2, 0x36a568, 0x5853), (2, 0x36fdbc, 0x323c0), (2, 0x3a217c, 0x57c6), (2, 0x3a7944, 0x5820), (2, 0x3ad164, 0x22),
    (2, 0x3ad188, 0x31ff0), (2, 0x3df178, 0x1a01), (2, 0x400000, 0x32210), (2, 0x432210, 0x1c51),
    (2, 0x433e64, 0x31370), (2, 0x4651d4, 0x1925), (2, 0x466afc, 0x2fe30), (2, 0x49692c, 0x210c),
    (2, 0x498a38, 0xe060), (2, 0x4a6a98, 0x1e220), (2, 0x4c4cb8, 0x4b03c), (2, 0x50fcf4, 0x27e44),
    (2, 0x537b38, 0x3b78c), (2, 0x5732c4, 0xf040), (2, 0x582304, 0xf040), (2, 0x591344, 0xf040),
    (2, 0x5a0384, 0xf040), (2, 0x5af3c4, 0xf040), (2, 0x5be404, 0xf040), (2, 0x5cd444, 0xf040), (2, 0x5dc484, 0xf040),
    (2, 0x5eb4c4, 0xf040), (2, 0x5fa504, 0xf040), (2, 0x609544, 0xf040), (2, 0x618584, 0xf040), (2, 0x6275c4, 0xf040),
    (2, 0x636604, 0xf040), (2, 0x645644, 0xf040), (2, 0x654684, 0xf040), (2, 0x6636c4, 0xf040), (2, 0x672704, 0xf040),
    (2, 0x681744, 0xf040), (2, 0x690784, 0xf040), (2, 0x69f7c4, 0xf040), (2, 0x6ae804, 0xf040), (2, 0x6bd844, 0x9324),
    (2, 0x6c6b68, 0x1ea4), (2, 0x6c8a0c, 0x342c), (2, 0x6cbe38, 0x1e220), (2, 0x6ea058, 0x1e220),
    (2, 0x708278, 0x1e220), (2, 0x726498, 0x1e220), (2, 0x7446b8, 0x1e220), (2, 0x7628d8, 0x1e220),
    (2, 0x780af8, 0x1e220), (2, 0x79ed18, 0x1e220), (2, 0x7bcf38, 0x1e220), (2, 0x7db158, 0x1e220), (3, 0x0, 0x1e220),
    (3, 0x1e220, 0x1e220), (3, 0x3c440, 0x1e220), (3, 0x5a660, 0x1e220), (3, 0x78880, 0x1e220), (3, 0x96aa0, 0x1e220),
    (3, 0xb4cc0, 0x1e220), (3, 0xd2ee0, 0x1e220), (3, 0xf1100, 0x1e220), (3, 0x10f320, 0x1e220),
    (3, 0x12d540, 0x1e220), (3, 0x14b760, 0x1e220), (3, 0x169980, 0x1e220), (3, 0x187ba0, 0x5c0),
    (3, 0x188160, 0x358), (3, 0x1884b8, 0x6da0), (3, 0x18f258, 0x544), (3, 0x18f79c, 0x544), (3, 0x18fce0, 0x544),
    (3, 0x190224, 0x544), (3, 0x190768, 0x544), (3, 0x190cac, 0x544), (3, 0x1911f0, 0x500), (3, 0x1916f0, 0x544),
    (3, 0x191c34, 0x500), (3, 0x192134, 0x500), (3, 0x192634, 0x500), (3, 0x192b34, 0x1c0), (3, 0x192cf4, 0x3444),
    (3, 0x196138, 0x1d64), (3, 0x197e9c, 0xbc8), (3, 0x198a64, 0x8aed4), (3, 0x223938, 0xcce4),
    (3, 0x23061c, 0x5376c), (3, 0x283d88, 0x38a9c), (3, 0x2bc824, 0x38a9c), (3, 0x2f52c0, 0x9f24),
    (3, 0x2ff1e4, 0x47f4), (3, 0x3039d8, 0x1e804), (3, 0x3221dc, 0x135d4), (3, 0x3357b0, 0x5a84),
    (3, 0x33b234, 0x12d24), (3, 0x34df58, 0xb7e4), (3, 0x35973c, 0x3964), (3, 0x35d0a0, 0x36d0),
    (3, 0x360770, 0x2198), (3, 0x362908, 0x1e44), (3, 0x36474c, 0x12c0), (3, 0x365a0c, 0x18c0), (3, 0x3672cc, 0x3cc0),
    (3, 0x36af8c, 0x97cc), (3, 0x374758, 0x12a7c), (3, 0x3871d4, 0xb4f4), (3, 0x3926c8, 0xc63c),
    (3, 0x39ed04, 0x731c), (3, 0x3a6020, 0x7514), (3, 0x3ad534, 0xb1fc), (3, 0x3b8730, 0x8ac0), (3, 0x3c11f0, 0x4254),
    (3, 0x3c5444, 0xb884), (3, 0x3d0cc8, 0xfb34), (3, 0x3e07fc, 0x2640), (3, 0x3e2e3c, 0x2d64),
)
# internal fighter id -> name (ranking tables at 0x80087940: u8 id + name); 3/7/10 are unused ids that alias Kasumi
FIGHTER_IDS = {0: "ZACK", 1: "TINA", 2: "JANN LEE", 4: "HAYABUSA", 5: "KASUMI", 6: "GEN FU", 8: "BAYMAN", 9: "BASS",
               11: "RAIDOU", 12: "LEI FANG", 13: "AYANE"}
MODEL_TABLE_RAM = 0x80087334      # u16 file index, 4-byte stride, 19 costume slots per fighter id
COSTUME_SLOTS = 19
COSTUMES = 4                      # slots 0-3 hold distinct files; slot 4 is a zero-size entry; 5-18 repeat slot 0
# one u16 file index per fighter id (0..13); the role is what the file looks like, see docs/doapp_pipeline.md
CHAR_TABLES = {
    "small_a": 0x800872FC,        # files 4-14, ~40 KiB
    "motion": 0x80087318,         # files 27-37, 250-410 KiB (largest per-fighter files)
    "bank_c": 0x80088704,         # files 134-144 (0 for the unused ids)
    "small_b": 0x80088F78,        # files 15-25, ~24 KiB
    "small_c": 0x80088F94,        # files 38-48, 11-24 KiB, u16 0x0c00-step offset tables
    "tim_large": 0x8008911C,      # files 267-277, TIMs
    "tim_small": 0x80106700,      # files 233-243, 0x500-0x544 byte TIMs (table lives in the FILE_TABLE[0] overlay)
}


def merge_parent(parent_zip_path: str) -> bytes:
    """The doapp bankedroms image as MAME loads it (0x1c00000 bytes: banks 0-3; the region's tail is unused)."""
    out = bytearray(0x1C00000)
    with zipfile.ZipFile(parent_zip_path) as z:
        hi, lo = z.read("doapp119.bin"), z.read("doapp120.bin")
        out[0:2 * len(lo):2] = lo
        out[1:2 * len(hi):2] = hi
        for i, name in enumerate(DATA_BANKS):
            data = z.read(name)
            out[0x400000 * (i + 1):0x400000 * (i + 1) + len(data)] = data
    return bytes(out)


def file_table_from_ram(ram: bytes, count: int = FILE_COUNT) -> tuple:
    """The (bank, offset, size) records out of a decoded program image (RAM from address 0x80000000)."""
    base = FILE_TABLE_RAM & 0x1FFFFF
    if len(ram) < base + 12 * count:
        raise ValueError("RAM image too short for the file table")
    out = []
    for i in range(count):
        bank, off, size = struct.unpack_from("<III", ram, base + 12 * i)
        if bank > 3 or off + size > BANK_SIZE:
            raise ValueError(f"file {i}: bank {bank} offset {off:#x} size {size:#x} is not a bankedroms span")
        out.append((bank, off, size))
    return tuple(out)


def file_span(index: int, table=FILE_TABLE) -> tuple[int, int]:
    """(absolute bankedroms offset, size) of a file."""
    if not 0 <= index < len(table):
        raise IndexError(f"file {index} outside the {len(table)}-entry table")
    bank, off, size = table[index]
    return bank * BANK_SIZE + off, size


def read_file(banked: bytes, index: int, table=FILE_TABLE) -> bytes:
    start, size = file_span(index, table)
    if start + size > len(banked):
        raise ValueError(f"file {index} runs past the bankedroms image")
    return banked[start:start + size]


def file_room(index: int, table=FILE_TABLE) -> int:
    """Bytes file `index` may grow to in place: up to the next file that starts after it in the same bank (the last
    file of the last populated bank may run to the end of the 4 MiB ROM that holds it)."""
    bank, off, size = table[index]
    later = [o for b, o, s in table if b == bank and o >= off + size and s and o != off]
    end = min(later, default=BANK_SIZE if bank < 3 else 0x400000)
    return end - off


def _u16_table(ram: bytes, addr: int, n: int) -> list[int]:
    return [struct.unpack_from("<H", ram, (addr & 0x1FFFFF) + 2 * i)[0] for i in range(n)]


def fighters_from_ram(ram: bytes) -> list[dict]:
    """Fighter id -> name, costume model files and the per-fighter files, read from a decoded program image (with
    FILE_TABLE[0] placed at OVERLAY_RAM for the overlay table)."""
    out = []
    for fid, name in FIGHTER_IDS.items():
        models = [struct.unpack_from("<H", ram, (MODEL_TABLE_RAM & 0x1FFFFF) + 4 * (fid * COSTUME_SLOTS + c))[0]
                  for c in range(COSTUMES + 1)]
        row = {"id": fid, "name": name, "models": models[:COSTUMES], "hidden_costume_file": models[COSTUMES]}
        for key, addr in CHAR_TABLES.items():
            row[key] = _u16_table(ram, addr, 14)[fid]
        out.append(row)
    return out


# Snapshot of fighters_from_ram() on the decoded doapp program (tests/test_doapp_inventory.py re-derives it when the
# owned ROMs are present).
FIGHTERS = (
    {"id": 0, "name": "ZACK", "models": [59, 60, 61, 62], "hidden_costume_file": 63, "small_a": 12, "motion": 37,
     "bank_c": 134, "small_b": 23, "small_c": 48, "tim_large": 275, "tim_small": 243},
    {"id": 1, "name": "TINA", "models": [49, 50, 51, 52], "hidden_costume_file": 53, "small_a": 4, "motion": 36,
     "bank_c": 139, "small_b": 15, "small_c": 47, "tim_large": 271, "tim_small": 242},
    {"id": 2, "name": "JANN LEE", "models": [89, 90, 91, 92], "hidden_costume_file": 93, "small_a": 7, "motion": 31,
     "bank_c": 137, "small_b": 18, "small_c": 42, "tim_large": 269, "tim_small": 237},
    {"id": 4, "name": "HAYABUSA", "models": [87, 84, 85, 86], "hidden_costume_file": 88, "small_a": 11, "motion": 35,
     "bank_c": 135, "small_b": 22, "small_c": 46, "tim_large": 273, "tim_small": 241},
    {"id": 5, "name": "KASUMI", "models": [79, 80, 81, 82], "hidden_costume_file": 83, "small_a": 8, "motion": 32,
     "bank_c": 142, "small_b": 19, "small_c": 43, "tim_large": 267, "tim_small": 238},
    {"id": 6, "name": "GEN FU", "models": [74, 75, 76, 77], "hidden_costume_file": 78, "small_a": 6, "motion": 30,
     "bank_c": 138, "small_b": 17, "small_c": 41, "tim_large": 276, "tim_small": 236},
    {"id": 8, "name": "BAYMAN", "models": [69, 70, 71, 72], "hidden_costume_file": 73, "small_a": 5, "motion": 29,
     "bank_c": 140, "small_b": 16, "small_c": 40, "tim_large": 272, "tim_small": 235},
    {"id": 9, "name": "BASS", "models": [94, 95, 96, 97], "hidden_costume_file": 98, "small_a": 13, "motion": 28,
     "bank_c": 141, "small_b": 24, "small_c": 39, "tim_large": 274, "tim_small": 234},
    {"id": 11, "name": "RAIDOU", "models": [64, 65, 66, 67], "hidden_costume_file": 68, "small_a": 10, "motion": 34,
     "bank_c": 144, "small_b": 21, "small_c": 45, "tim_large": 277, "tim_small": 240},
    {"id": 12, "name": "LEI FANG", "models": [54, 55, 56, 57], "hidden_costume_file": 58, "small_a": 9, "motion": 33,
     "bank_c": 136, "small_b": 20, "small_c": 44, "tim_large": 270, "tim_small": 239},
    {"id": 13, "name": "AYANE", "models": [99, 100, 101, 102], "hidden_costume_file": 103, "small_a": 14,
     "motion": 27, "bank_c": 143, "small_b": 25, "small_c": 38, "tim_large": 268, "tim_small": 233},
)


def fighter(query) -> dict:
    """A fighter by name (case/space/hyphen-insensitive) or internal id."""
    q = str(query).strip().casefold().replace("-", " ").replace("_", " ")
    for f in FIGHTERS:
        n = f["name"].casefold()
        if q in (n, str(f["id"])) or q.replace(" ", "") == n.replace(" ", ""):
            return f
    raise KeyError(f"no Dead Or Alive ++ fighter {query!r}; fighters: {[f['name'] for f in FIGHTERS]}")


def decode_owned(src_dir: str) -> tuple[bytes, bytes, int]:
    """(merged bankedroms, decoded program RAM with the overlay placed, entry point) from the owned zips. Slow (~40 s):
    runs the TPS BIOS decoder on gbox.zn_tps_boot's interpreter."""
    import os
    from . import zn_tps_boot
    parent = os.path.join(src_dir, "doapp.zip")
    banked = merge_parent(parent)
    with zipfile.ZipFile(os.path.join(src_dir, "coh1002m.zip")) as z:
        bios, mg01 = z.read("m534002c-61.ic353"), z.read("mg01.ic652")
    with zipfile.ZipFile(parent) as z:
        mg05 = z.read("mg05")
    ram, entry = zn_tps_boot.decode_program(bios, banked, mg01, mg05)
    ram = bytearray(ram)
    start, size = file_span(0, file_table_from_ram(ram))
    ram[OVERLAY_RAM & 0x1FFFFF:(OVERLAY_RAM & 0x1FFFFF) + size] = banked[start:start + size]
    return banked, bytes(ram), entry


def inventory_jp(src_dir: str, out_json: str | None = None, *, decode: bool = False) -> dict:
    """Japan (doapp) manifest. decode=True re-derives the file table and fighter tables from the program instead of
    trusting the FILE_TABLE / FIGHTERS snapshot (the manifest says whether they agree)."""
    import os
    parent = os.path.join(src_dir, "doapp.zip")
    bios_zip = os.path.join(src_dir, "coh1002m.zip")
    for p in (parent, bios_zip):
        if not os.path.exists(p):
            raise FileNotFoundError(p)
    problems = verify_rom_sha1(parent, {n: v[2] for n, v in BANKED_ROMS.items() if n.startswith("doapp-")}
                               | {n: v[1] for n, v in PARENT_ROMS.items()}) + verify_rom_sha1(bios_zip, BIOS_ROMS)
    derived = None
    if decode:
        banked, ram, entry = decode_owned(src_dir)
        table, fighters = file_table_from_ram(ram), fighters_from_ram(ram)
        derived = {"entry_point": hex(entry), "file_table_matches_snapshot": table == FILE_TABLE,
                   "fighters_match_snapshot": [dict(f) for f in FIGHTERS] == fighters}
    else:
        banked = merge_parent(parent)
    program_sha1 = hashlib.sha1(banked[:0x200000]).hexdigest()
    files = []
    for i, (bank, off, size) in enumerate(FILE_TABLE):
        start = bank * BANK_SIZE + off
        files.append({"index": i, "offset": start, "size": size, "room": file_room(i),
                      "head": banked[start:start + 16].hex()})
    manifest = {
        "game_id": GAME_ID_JP, "title": "Dead Or Alive ++ (Japan)", "mame_set": "doapp", "bios_set": BIOS_SET,
        "platform": {"system": "Tecmo TPS (ZN-1 board, BIOS coh1002m)", "driver": "zn2p", "cpu": "Sony CXD8530CQ",
                     "bankedroms_window": "0x1f000000 (8 MiB, bank byte at 0x1fb00006)"},
        "rom_verification": problems,
        "program": {"sha1": program_sha1, "known": program_sha1 == PROGRAM_SHA1["doapp"],
                    "encoded_span": [0, 0x88880], "entry_point": hex(ENTRY_POINT),
                    "file_table_ram": hex(FILE_TABLE_RAM), "overlay_ram": hex(OVERLAY_RAM),
                    "decoder": "gbox.zn_tps_boot (runs the TPS BIOS decode with the mg01/mg05 CAT702 pair)"},
        "files": files,
        "fighters": [dict(f, model_sizes=[FILE_TABLE[m][2] for m in f["models"]],
                          model_room=[file_room(m) for m in f["models"]]) for f in FIGHTERS],
        "derived": derived,
    }
    if out_json:
        with open(out_json, "w") as f:
            json.dump(manifest, f, indent=2)
    return manifest


def main(argv=None) -> int:
    import argparse
    import os
    ap = argparse.ArgumentParser(prog="python -m gbox.doapp_inventory",
                                 description="Dead Or Alive ++ inventory (doapp Japan by default, doappk Korea)")
    ap.add_argument("src", help="directory holding doapp.zip, coh1002m.zip (and doappk.zip for --set doappk)")
    ap.add_argument("--set", choices=("doapp", "doappk"), default="doapp")
    ap.add_argument("--decode", action="store_true", help="re-derive the file/fighter tables by decoding the program")
    ap.add_argument("--extract", metavar="DIR", help="also write every table file as DIR/NNN.bin (doapp)")
    ap.add_argument("--out", help="write the manifest JSON here")
    a = ap.parse_args(argv)
    if a.set == "doappk":
        m = inventory(a.src, a.out)
    else:
        m = inventory_jp(a.src, a.out, decode=a.decode)
        if a.extract:
            os.makedirs(a.extract, exist_ok=True)
            banked = merge_parent(os.path.join(a.src, "doapp.zip"))
            for i in range(len(FILE_TABLE)):
                with open(os.path.join(a.extract, f"{i:03d}.bin"), "wb") as f:
                    f.write(read_file(banked, i))
        m = {k: v for k, v in m.items() if k != "files"} | {"files": len(m["files"])}
    print(json.dumps(m, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
