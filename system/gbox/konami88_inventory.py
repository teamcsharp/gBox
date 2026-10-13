"""Inventory for '88 Games (Konami 1988), MAME parent set ``88games``.

The game is 2D sprite/tile based: there are no 3D meshes. "Characters"
(the athletes, referees, crowd) are K051960 sprites composed by the main
CPU; the K052109 tilemaps draw the background layers and the K051316
zoom layer draws the track/crowd zoom plane.

Hardware (MAME ``src/mame/konami/88games.cpp``):
  * main CPU: Konami 6809 @ 24MHz/2, fixed code 861m01.k18 @0x8000,
    8 x 8KB banks from 861m02.k16 @0x10000 mapped at 0x0000-0x1fff;
    palette RAM (2048 xBGR555 + shadows) at 0x1000-0x1fff.
  * audio: Z80 @ 3.579545MHz (861d01.d9), YM2151, 2x uPD7759 ADPCM
    (samples 861a07.a-b and 861a07.c-d).
  * video: 3 x K052109 tilemap layers (8x8 4bpp, 16384 codes, 512KB),
    K051960 sprite engine (128 sprites, 16x16 4bpp codes, 8192 codes,
    1MB), K051316 zoom layer (16x16 packed 4bpp, 2048 codes, 256KB).
    Screen 320x240 (raw 384x264). Sprite color base 512/16, zoom
    color base 768/16, layer color bases 0/16/64 *16.

The owned artifact is the hyperspin zip
``collections/Mame/roms/88games.zip``
(sha256 e3e1ef1cce6c7df6e23734159a9352bb996973bc65fdbf6bd0356ddd555e8065).
Every zip member must match the MAME 88games parent set; verification is
CRC32+SHA1 against the values baked into MAME's driver (authoritative
for this build). A missing member or a hash mismatch is a hard blocker:
the set is incomplete or modified, and no writer may target it.

Pixel formats (all 4bpp, derived from the MAME gfx_layouts):
  * sprite code (128 B): row y - left 8 px in u32 word y (bytes 4y..4y+3),
    right 8 px in u32 word y+8 (bytes 32+4y..35+4y). Byte b of a word is
    plane b, bit (x&7) LSB-first. (k051960 spritelayout, plane offsets
    0/8/16/24 bits, xoffsets 0..7 and 8*32+0..7, yoffsets r*32.)
  * tile code (32 B): row y = bytes 4y..4y+3; plane b = byte 3-b.
    (k052109 charlayout, plane offsets 24/16/8/0 bits.)
  * zoom code (128 B): packed nibbles, row y = bytes 8y..8y+7,
    pixel x = nibble x of byte x>>1. (k051316 charlayout4.)
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import zipfile
import zlib

__all__ = [
    "KNOWN",
    "verify_zip",
    "region_bytes",
    "sprite_px",
    "tile_px",
    "zoom_px",
    "decode_code",
    "inventory",
]

# name -> {region, offset, size, interleave, crc32, sha1} from MAME's
# ROM_START( 88games ) in src/mame/konami/88games.cpp (parent set).
KNOWN = {
    "861.g3": {"region": "proms", "offset": 0x0000, "size": 0x0100, "interleave": False, "crc32": "429785db", "sha1": "d27e8e180f19d2b160f18c79520a77182a62218c"},
    "861a04.a": {"region": "k051316", "offset": 0x000000, "size": 0x10000, "interleave": False, "crc32": "092a8b15", "sha1": "d98a81bfa4bba73805f0236f8a80da130fcb378d"},
    "861a04.b": {"region": "k051316", "offset": 0x010000, "size": 0x10000, "interleave": False, "crc32": "75744b56", "sha1": "5133d8f6622796ed6b9e6a0d0f1df28f00331fc7"},
    "861a04.c": {"region": "k051316", "offset": 0x020000, "size": 0x10000, "interleave": False, "crc32": "a00021c5", "sha1": "f73f88af33387d73b4262e8652507e699926fabe"},
    "861a04.d": {"region": "k051316", "offset": 0x030000, "size": 0x10000, "interleave": False, "crc32": "d208304c", "sha1": "77dd31163c8431416ab0593f084719c914222912"},
    "861a05.a": {"region": "k051960", "offset": 0x000000, "size": 0x10000, "interleave": True, "crc32": "cedc19d0", "sha1": "6eb2a292d574dee06e214e61c0e08fa233ac68e8"},
    "861a05.b": {"region": "k051960", "offset": 0x040000, "size": 0x10000, "interleave": True, "crc32": "db2a8808", "sha1": "dad6b127761889aac198014139cc524a4cea32e7"},
    "861a05.c": {"region": "k051960", "offset": 0x080000, "size": 0x10000, "interleave": True, "crc32": "cf03c449", "sha1": "234714212dd7288a5128d36c96cca5b62e86d37d"},
    "861a05.d": {"region": "k051960", "offset": 0x0c0000, "size": 0x10000, "interleave": True, "crc32": "97d78c77", "sha1": "2c123fd08cb9626cf309e7320fe2eb99e4b483fb"},
    "861a05.e": {"region": "k051960", "offset": 0x000001, "size": 0x10000, "interleave": True, "crc32": "725af3fc", "sha1": "98ac364db4b2c5682a299f4d2a288ebc8a303b1f"},
    "861a05.f": {"region": "k051960", "offset": 0x040001, "size": 0x10000, "interleave": True, "crc32": "32d830ca", "sha1": "a3f10720151f538cf1bec5953a4212bc96ba42fe"},
    "861a05.g": {"region": "k051960", "offset": 0x080001, "size": 0x10000, "interleave": True, "crc32": "fd51c4ea", "sha1": "fc8923819fa7f3d02b4d159aea45cb5d1a80f1b0"},
    "861a05.h": {"region": "k051960", "offset": 0x0c0001, "size": 0x10000, "interleave": True, "crc32": "60d0c8a5", "sha1": "c7d3531eb65abd51ae4e6f55244d674353d23d36"},
    "861a06.a": {"region": "k051960", "offset": 0x000002, "size": 0x10000, "interleave": True, "crc32": "85e2e30e", "sha1": "11010727db8c71650c5b9df5340f9bc412435d11"},
    "861a06.b": {"region": "k051960", "offset": 0x040002, "size": 0x10000, "interleave": True, "crc32": "ce17eaf0", "sha1": "cc121c5742428e2613b7da2d8357f15e897161ca"},
    "861a06.c": {"region": "k051960", "offset": 0x080002, "size": 0x10000, "interleave": True, "crc32": "a568b34e", "sha1": "8b69a0ac90f32cea31f8c7fcd985ad58fb6c009e"},
    "861a06.d": {"region": "k051960", "offset": 0x0c0002, "size": 0x10000, "interleave": True, "crc32": "bc70ab39", "sha1": "a6fa0502ceb6862e7b1e4815326e268fd6511881"},
    "861a06.e": {"region": "k051960", "offset": 0x000003, "size": 0x10000, "interleave": True, "crc32": "6f96651c", "sha1": "c740a814a3e203348b269a70256e01fe2a914118"},
    "861a06.f": {"region": "k051960", "offset": 0x040003, "size": 0x10000, "interleave": True, "crc32": "88310bf3", "sha1": "77bac66489e7fc2ddd714fc684e79d70b089ee84"},
    "861a06.g": {"region": "k051960", "offset": 0x080003, "size": 0x10000, "interleave": True, "crc32": "4a55beb3", "sha1": "35088bf7f6acd2bc95f673a2816b35238d611308"},
    "861a06.h": {"region": "k051960", "offset": 0x0c0003, "size": 0x10000, "interleave": True, "crc32": "d906b79b", "sha1": "905814ce708d80fd4d1a398f60faa0bc680fccaf"},
    "861a07.a": {"region": "upd1", "offset": 0x000000, "size": 0x10000, "interleave": False, "crc32": "5d035d69", "sha1": "9df63e004a4f52768331dfb3c3889301ac174ea1"},
    "861a07.b": {"region": "upd1", "offset": 0x010000, "size": 0x10000, "interleave": False, "crc32": "6337dd91", "sha1": "74ba58f1664abd1491598c1a9467f470304fa430"},
    "861a07.c": {"region": "upd2", "offset": 0x000000, "size": 0x10000, "interleave": False, "crc32": "5067a38b", "sha1": "b5a8f7122356dd72a97e71b480835ba500116aaf"},
    "861a07.d": {"region": "upd2", "offset": 0x010000, "size": 0x10000, "interleave": False, "crc32": "86731451", "sha1": "c1410f6c7a23aa0c213878a6531d3e7eb966b0a4"},
    "861a08.a": {"region": "k052109", "offset": 0x000000, "size": 0x10000, "interleave": True, "crc32": "77a00dd6", "sha1": "e3667839f8ae3699236da3e312c20d571db38670"},
    "861a08.b": {"region": "k052109", "offset": 0x040000, "size": 0x10000, "interleave": True, "crc32": "28a8304f", "sha1": "6b4037eff6d209fec29d05f1071ed3bf9c2bd098"},
    "861a08.c": {"region": "k052109", "offset": 0x000001, "size": 0x10000, "interleave": True, "crc32": "b422edfc", "sha1": "b3842c8dc60975cc71812df098f29b4571b18120"},
    "861a08.d": {"region": "k052109", "offset": 0x040001, "size": 0x10000, "interleave": True, "crc32": "e01a3802", "sha1": "3fb5fe512c2497160a66e9de0cd45c38dfe46410"},
    "861a09.a": {"region": "k052109", "offset": 0x000002, "size": 0x10000, "interleave": True, "crc32": "df8917b6", "sha1": "3614b78c2100f135ea0701409ce279a423decb23"},
    "861a09.b": {"region": "k052109", "offset": 0x040002, "size": 0x10000, "interleave": True, "crc32": "4917158d", "sha1": "b53da3f29c9aeb59933dc3a8214cc1314e21000b"},
    "861a09.c": {"region": "k052109", "offset": 0x000003, "size": 0x10000, "interleave": True, "crc32": "f577b88f", "sha1": "7d5d88e1492ed361dc7b2135595393b89b9cb5b1"},
    "861a09.d": {"region": "k052109", "offset": 0x040003, "size": 0x10000, "interleave": True, "crc32": "2bb3282c", "sha1": "6ca54948a02c91543b7e595641b0edc2564f83ff"},
    "861d01.d9": {"region": "audiocpu", "offset": 0x00000, "size": 0x08000, "interleave": False, "crc32": "0ff1dec0", "sha1": "749dc98f8740beee1383f85effc9336081315f4b"},
    "861m01.k18": {"region": "maincpu", "offset": 0x08000, "size": 0x08000, "interleave": False, "crc32": "4a4e2959", "sha1": "95572686bef48b5c1ce1dedf0afc891d92aff00d"},
    "861m02.k16": {"region": "maincpu", "offset": 0x10000, "size": 0x10000, "interleave": False, "crc32": "e19f15f6", "sha1": "6c801b274e87eaff7f40148381ade5b38120cc12"},
}

REGION_SIZES = {
    "maincpu": 0x20000,
    "audiocpu": 0x10000,
    "k052109": 0x80000,
    "k051960": 0x100000,
    "k051316": 0x40000,
    "proms": 0x100,
    "upd1": 0x20000,
    "upd2": 0x20000,
}

SPRITE_CODE = 128  # 16x16 4bpp
TILE_CODE = 32  # 8x8 4bpp
ZOOM_CODE = 128  # 16x16 packed 4bpp


def verify_zip(zip_path: str | pathlib.Path) -> dict:
    """Check every member of the owned zip against the MAME parent set.

    Returns a dict {name: {size, crc32, sha1, sha256, region, offset,
    interleave, match}} plus a ``summary`` key with counts. A missing
    member or a mismatch is a hard blocker.
    """
    zip_path = pathlib.Path(zip_path)
    found: dict[str, dict] = {}
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            data = zf.read(info)
            found[info.filename] = {
                "size": len(data),
                "crc32": format(zlib.crc32(data) & 0xFFFFFFFF, "08x"),
                "sha1": hashlib.sha1(data).hexdigest(),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
    extra = sorted(set(found) - set(KNOWN))
    result: dict[str, dict] = {}
    bad = []
    for name, exp in sorted(KNOWN.items()):
        row = dict(exp)
        got = found.pop(name, None)
        if got is None:
            row.update(match=False, missing=True)
            bad.append(name)
        else:
            row.update(**{k: got[k] for k in ("size", "crc32", "sha1", "sha256")})
            row["match"] = (
                got["size"] == exp["size"]
                and got["crc32"] == exp["crc32"]
                and got["sha1"] == exp["sha1"]
            )
            if not row["match"]:
                bad.append(name)
        result[name] = row
    result["summary"] = {
        "expected": len(KNOWN),
        "ok": len(KNOWN) - len(bad),
        "mismatched": bad,
        "extra_members": extra,
        "complete": not bad and not extra,
    }
    return result


def region_bytes(rom_dir: str | pathlib.Path, region: str) -> bytes:
    """Interleaved region bytes, using MAME's byte-lane ordering.

    Linear regions concatenate by offset. For an interleaved region
    (ROM_LOAD32_BYTE), the members whose offsets differ only in the
    low bits of the same 64KB bank contribute bytes 0/1/2/3 of each
    32-bit word.
    """
    rom_dir = pathlib.Path(rom_dir)
    members = sorted(
        ((n, e) for n, e in KNOWN.items() if e["region"] == region),
        key=lambda t: t[1]["offset"],
    )
    out = bytearray(REGION_SIZES[region])
    if not members[0][1]["interleave"]:
        for name, e in members:
            out[e["offset"] : e["offset"] + e["size"]] = (rom_dir / name).read_bytes()
        return bytes(out)
    banks: dict[int, list[tuple[str, dict]]] = {}
    for name, e in members:
        banks.setdefault(e["offset"] & ~0xFFFF, []).append((name, e))
    for base, group in banks.items():
        group.sort(key=lambda t: t[1]["offset"])
        bufs = [(rom_dir / n).read_bytes() for n, _ in group]
        lane = len(bufs)
        for i in range(group[0][1]["size"]):
            for l, b in enumerate(bufs):
                out[base + i * lane + l] = b[i]
    return bytes(out)


def sprite_px(spr: bytes | bytearray, code: int, x: int, y: int) -> int:
    """4bpp pixel of a K051960 16x16 sprite code (word-interleaved planes)."""
    base = code * SPRITE_CODE
    off = 4 * y + (0 if x < 8 else 32)
    v = 0
    for b in range(4):
        v |= ((spr[base + off + b] >> (x & 7)) & 1) << b
    return v


def tile_px(tiles: bytes | bytearray, code: int, x: int, y: int) -> int:
    """4bpp pixel of a K052109 8x8 tile code (plane b in byte 3-b)."""
    base = code * TILE_CODE + 4 * y
    v = 0
    for b in range(4):
        v |= ((tiles[base + (3 - b)] >> x) & 1) << b
    return v


def zoom_px(zm: bytes | bytearray, code: int, x: int, y: int) -> int:
    """4bpp pixel of a K051316 16x16 zoom code (packed nibbles)."""
    by = zm[code * ZOOM_CODE + y * 8 + (x >> 1)]
    return (by >> ((x & 1) * 4)) & 0xF


def decode_code(data: bytes | bytearray, kind: str, code: int) -> list[list[int]]:
    """Decode one code page to a 2D list of 4bpp pixel indices."""
    if kind == "sprite":
        return [[sprite_px(data, code, x, y) for x in range(16)] for y in range(16)]
    if kind == "tile":
        return [[tile_px(data, code, x, y) for x in range(8)] for y in range(8)]
    if kind == "zoom":
        return [[zoom_px(data, code, x, y) for x in range(16)] for y in range(16)]
    raise ValueError(f"unknown kind {kind!r}")


def inventory(zip_path: str | pathlib.Path, out_dir: str | pathlib.Path) -> dict:
    """Verify the owned zip, extract ROMs, build regions, write manifest.

    Writes ``roms/``, ``<region>.bin`` for every region and
    ``manifest.json`` under out_dir. Returns the manifest dict.
    """
    zip_path = pathlib.Path(zip_path)
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = verify_zip(zip_path)
    if not summary["summary"]["complete"]:
        raise ValueError(
            "owned zip does not match the MAME 88games parent set: "
            f"mismatched={summary['summary']['mismatched']} "
            f"extra={summary['summary']['extra_members']}"
        )
    rom_dir = out_dir / "roms"
    rom_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(rom_dir)
    regions: dict[str, dict] = {}
    for region, size in REGION_SIZES.items():
        data = region_bytes(rom_dir, region)
        (out_dir / f"{region}.bin").write_bytes(data)
        regions[region] = {"size": size, "sha256": hashlib.sha256(data).hexdigest()}
    manifest = {
        "game": "'88 Games",
        "mame_set": "88games",
        "manufacturer": "Konami",
        "year": 1988,
        "source_zip_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
        "roms": {n: {k: v for k, v in e.items() if k != "summary"} for n, e in summary.items() if n != "summary"},
        "regions": regions,
        "summary": summary["summary"],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="'88 Games inventory")
    ap.add_argument("zip_path", help="path to the owned 88games.zip")
    ap.add_argument("--out", default=".", help="output directory")
    args = ap.parse_args()
    m = inventory(args.zip_path, args.out)
    print(json.dumps({"source_zip_sha256": m["source_zip_sha256"], "regions": m["regions"], "summary": m["summary"]}, indent=1))
