"""Dead Or Alive ++ (Korea) owned-source inventory.

doappk ("Dead Or Alive ++ (Korea)", MAME set doappk) is a clone of doapp
("Dead Or Alive ++ (Japan/USA/Export)"). Both run on the Tecmo TPS system:
BIOS set coh1002m, machine coh1002m, driver zn2p, Sony CXD8530CQ (PSX CPU/GPU)
at 64.60 MHz plus a PlayStation SPU at 32.30 MHz (src/mame/sony/zn.cpp).
The catalog platform label "arcade/MAME" is correct; this is NOT a Model 2 game.

Owned source (Hyperspin MAME collection), three zips:
  collections/Mame/roms/doappk.zip     Korea clone: only the two 1 MiB
                                       "video board" text ROMs differ.
  collections/Mame/roms/doapp.zip      Parent: 6x4 MiB program/data banks
                                       (doapp-0..5, sockets 216-221), the
                                       1 MiB doapp119/120 pair, mg05 GAL.
  collections/Mame/roms/coh1002m.zip   TPS BIOS: m534002c-61.ic353 (512 KiB
                                       english sample ROM), mg01.ic652 (8 B).
                                       The 8 KiB 78081g503.ic655 is NODUMP in
                                       MAME itself (not a gap in this library).

Layout of the merged bankedroms region (0x2800000 bytes, region "bankedroms"):
  offsets 0x0000000-0x1FFFFF: doapp_u0119.119 / doapp_u0120.120, loaded with
    ROM_LOAD16_BYTE at +1/+0, i.e. even byte = u0120, odd byte = u0119.
    Starts with the SCEI license string ("Licensed by Sony Computer
    Entertainment Inc.(SCEI)") - this is the main program/text area.
  offsets 0x0400000-0x1BFFFFF: doapp-0.216 .. doapp-5.221 (data banks:
    geometry, textures, animation, samples).
  cat702_2 security device: mg05 (8 B GAL), required for boot.

Roster (11 fighters), from two name tables in the merged image:
  table at 0x00a03fc: AYANE LEI-FANG RAIDOU BASS BAYMAN GEN-FU KASUMI
  HAYABUSA JANN-LEE TINA ZACK (followed by "TEAM BATTLE REPORT...")
  table at 0x014296c: same names in reverse, then internal 3-letter codes
  (ZAK TIN JAN ... RYU KAS GEN).

MAME dat verification: every SHA1 below is from mamedev/mame master
src/mame/sony/zn.cpp (doapp, doappk, coh1002m ROM_STARTs).
"""

from __future__ import annotations

import hashlib
import json
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


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "."
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    m = inventory(src, out)
    print(json.dumps(m, indent=2))
