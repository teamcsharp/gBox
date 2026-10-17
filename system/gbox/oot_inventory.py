"""Ocarina of Time (N64) owned-build inventory for the character-replacement pipeline.

`python -m gbox.oot_inventory SRC [--out manifest.json]` reads the operator's ROM or archive (never modified) and
writes a manifest of the exact build:

  * source identity: container sha256, archive member, its on-disk byte order (No-Intro "(USA) (Rev B).zip" ships a
    `.n64`-named member that is really v64 halfword-swapped), the normalized big-endian sha256/md5, header title, game
    code, revision, CRC pair, and the version gbox.oot_writer resolves (md5 -> ntsc-1.0/1.1/1.2, pal-1.0/1.1);
  * launch prerequisites: CIC, save type, ROM size, core, no BIOS / Expansion Pak;
  * container layout: dmadata offset, file count, Yaz0-compressed files, `code` (DMA index, VRAM, size),
    gObjectTable and gActorOverlayTable offsets inside `code`;
  * the character inventory: every object in gObjectTable with its skeletons (limb count, LOD/flex, display-list
    count) and the animation headers that drive each limb count; Link's two playable slots (object_link_boy /
    object_link_child FlexSkeletons, link_animetion, ovl_player_actor) checked against the offsets gbox.oot_swap
    writes to.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zipfile
from pathlib import Path

from . import n64_rom
from . import oot_writer as OW

OBJECT_ID_MAX = 0x192            # gObjectTable entries in every retail build (object_ids 0..0x191)
BYTE_ORDERS = {b"\x80\x37\x12\x40": "z64 (big-endian)", b"\x37\x80\x40\x12": "v64 (halfword-swapped)",
               b"\x40\x12\x37\x80": "n64 (word-swapped)"}
# big-endian md5 -> human-readable build label recorded in the manifest's source block
BUILD_LABELS = {"1618403427e4344a57833043db5ce3c3": "Master Quest retail (NZLP, PAL GameCube disc)"}


def _names() -> dict:
    return json.loads((Path(__file__).with_name("oot_names.json")).read_text())


def byte_order(head: bytes) -> str:
    return BYTE_ORDERS.get(bytes(head[:4]), "unknown")


def raw_source(path: Path) -> tuple[str, bytes]:
    """-> (member name or file name, the file's raw bytes as stored), so the stored byte order can be reported."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            m = next(m for m in z.infolist() if not m.is_dir() and m.filename.lower().endswith(n64_rom.ROM_EXTENSIONS))
            return m.filename, z.read(m)
    return path.name, path.read_bytes()


def header(rom: bytes) -> dict:
    crc1, crc2 = struct.unpack_from(">II", rom, 0x10)
    return {"title": rom[0x20:0x34].decode("ascii", "replace").strip(), "game_code": rom[0x3B:0x3F].decode("ascii", "replace"),
            "revision": rom[0x3F], "crc1": f"{crc1:08x}", "crc2": f"{crc2:08x}",
            "entry": f"{struct.unpack_from('>I', rom, 8)[0]:08x}"}


def object_entries(rom: OW.Rom) -> list[tuple[int, int, int]]:
    """gObjectTable -> [(object_id, vromStart, vromEnd)] for ids 0..OBJECT_ID_MAX-1."""
    code = rom.file(rom.v["code"])
    return [(i, *struct.unpack_from(">II", code, rom.obj_table + 8 * i)) for i in range(OBJECT_ID_MAX)]


def find_skeletons(obj: bytes) -> list[int]:
    """SkeletonHeader / FlexSkeletonHeader offsets in an object: a segment-6 pointer to `count` segment-6 limb pointers,
    then the count. Unlike the old scan this reaches a header in the object's last 12 bytes (object_link_boy's
    FlexSkeleton at 0x377F4 ends the file)."""
    out = []
    for o in range(0, len(obj) - 7, 4):
        w = struct.unpack_from(">I", obj, o)[0]
        cnt = obj[o + 4]
        if w >> 24 != 6 or not 2 <= cnt <= 80 or obj[o + 5:o + 8] != b"\0\0\0":
            continue
        t = w & 0xFFFFFF
        if t + 4 * cnt > len(obj) or t % 4:
            continue
        ptrs = [struct.unpack_from(">I", obj, t + 4 * i)[0] for i in range(cnt)]
        if not all(p >> 24 == 6 and (p & 0xFFFFFF) + 12 <= len(obj) for p in ptrs):
            continue
        try:
            sk = OW.skeleton(obj, o)
        except struct.error:
            continue
        if all(lb["child"] == 0xFF or lb["child"] < cnt for lb in sk["limbs"]) and \
                all(lb["sibling"] == 0xFF or lb["sibling"] < cnt for lb in sk["limbs"]):
            out.append(o)
    return out


def count_animations(obj: bytes, limbs: int) -> int:
    """Standard AnimationHeaders in `obj` whose joint-index table covers `limbs` limbs (+ the root translation)."""
    n = 0
    for o in range(0, len(obj) - 16, 4):
        fc, pad, fd, ji, smax = struct.unpack_from(">hhIIH", obj, o)
        if not 0 < fc < 2000 or pad or fd >> 24 != 6 or ji >> 24 != 6:
            continue
        fd, ji = fd & 0xFFFFFF, ji & 0xFFFFFF
        if ji + 6 * (limbs + 1) > len(obj) or fd >= ji:
            continue
        idx = struct.unpack_from(f">{3 * (limbs + 1)}H", obj, ji)
        if max(idx) < (ji - fd) // 2:
            n += 1
    return n


def link_animation_headers(keep: bytes, anim_size: int, limbs: int = 21) -> int:
    """LinkAnimationHeaders in gameplay_keep: {s16 frameCount, pad, segment-7 offset into link_animetion}, each frame
    (limbs + 1) * 6 + 2 bytes (joint rotations, root translation, face index)."""
    per = (limbs + 1) * 6 + 2
    n = 0
    for o in range(0, len(keep) - 7, 4):
        fc, pad, seg = struct.unpack_from(">hhI", keep, o)
        if 0 < fc < 1000 and not pad and seg >> 24 == 7 and (seg & 0xFFFFFF) % 2 == 0 and \
                (seg & 0xFFFFFF) + fc * per <= anim_size:
            n += 1
    return n


def settimg_count(obj: bytes) -> int:
    """Distinct segment-6 texture addresses loaded by G_SETTIMG (0xFD) commands at 8-byte-aligned display-list words."""
    seen = set()
    for o in range(0, len(obj) - 7, 8):
        if obj[o] == 0xFD and obj[o + 4] == 6 and (lo := struct.unpack_from(">I", obj, o + 4)[0] & 0xFFFFFF) < len(obj):
            seen.add(lo)
    return len(seen)


def skeleton_summary(obj: bytes, off: int) -> dict:
    sk = OW.skeleton(obj, off)
    dls = sum(1 for lb in sk["limbs"] if lb["dls"][0])
    return {"offset": f"0x{off:X}", "limbs": sk["count"], "lod": sk["lod"], "limbs_with_dl": dls,
            "flex_dlcount": sk["dlcount"] if sk["dlcount"] and sk["dlcount"] <= sk["count"] and
            obj[off + 5:off + 8] == b"\0\0\0" and off + 12 <= len(obj) else None}


def link_slots(rom: OW.Rom) -> dict:
    from .oot_swap import LINK, IDLE_ANIM
    out = {}
    for age, d in LINK.items():
        obj = rom.object(d["obj"])
        sk = OW.skeleton(obj, d["skel"])
        out[age] = {"object_id": f"0x{d['obj']:02X}", "dma_index": rom.object_index(d["obj"]), "size": len(obj),
                    "skeleton": skeleton_summary(obj, d["skel"]), "found_by_scan": d["skel"] in find_skeletons(obj),
                    "writer_offset_ok": sk["count"] == 21 and sk["lod"],
                    "textures": settimg_count(obj)}
    keep = rom.object(OW.OBJECT_GAMEPLAY_KEEP)
    fc = struct.unpack_from(">h", keep, IDLE_ANIM)[0]
    out["shared"] = {"gameplay_keep_size": len(keep), "idle_anim": f"0x{IDLE_ANIM:X}", "idle_anim_frames": fc,
                     "link_animetion": {"dma_index": rom.v["link_anim"], "size": len(rom.file(rom.v["link_anim"]))},
                     "link_animation_headers": link_animation_headers(keep, len(rom.file(rom.v["link_anim"]))),
                     "ovl_player_actor": {"dma_index": rom.v["player"], "size": len(rom.file(rom.v["player"]))}}
    return out


def inventory(src: str | Path, objects: bool = True) -> dict:
    src = Path(src)
    container = src.read_bytes()
    member, raw = raw_source(src)
    data = n64_rom.normalize(raw)
    rom = OW.Rom(data)
    names = _names()["objects"]
    code = rom.file(rom.v["code"])
    from .oot_swap import actor_table
    m = {
        "game": "The Legend of Zelda: Ocarina of Time", "platform": "n64",
        "source": {"file": src.name, "sha256": hashlib.sha256(container).hexdigest(), "size": len(container),
                   "member": member, "member_byte_order": byte_order(raw),
                   "normalized_sha256": hashlib.sha256(data).hexdigest(), "normalized_md5": hashlib.md5(data).hexdigest(),
                   "rom_size": len(data), "version": rom.version, "version_by_md5": hashlib.md5(data).hexdigest() in OW.MD5,
                   "build_label": BUILD_LABELS.get(hashlib.md5(data).hexdigest(), "")},
        "header": header(data),
        "launch": {"core": "parallel_n64 (RetroArch)", "bios": "none", "cic": "CIC-NUS-6105", "save": "SRAM 32 KiB",
                   "expansion_pak": "not required", "crc_valid": struct.unpack_from(">II", data, 0x10) == OW.crc6105(data)},
        "layout": {"dmadata": f"0x{rom.v['dma']:X}", "files": len(rom.dma),
                   "yaz0_files": sum(1 for e in rom.dma if e[3]),
                   "code": {"dma_index": rom.v["code"], "vram": f"0x{rom.v['code_vram']:08X}", "size": len(code)},
                   "gObjectTable": f"code+0x{rom.obj_table:X}", "gActorOverlayTable": f"code+0x{actor_table(rom):X}",
                   "object_ids": OBJECT_ID_MAX},
        "link": link_slots(rom),
    }
    if objects:
        vroms = {e[0]: i for i, e in enumerate(rom.dma)}
        objs, skel_objs, skels, anims = [], 0, 0, 0
        for oid, vs, ve in object_entries(rom):
            if vs == ve or vs not in vroms:
                continue
            i = vroms[vs]
            obj = rom.file(i)
            sk = [skeleton_summary(obj, o) for o in find_skeletons(obj)]
            na = {n: count_animations(obj, n) for n in sorted({s["limbs"] for s in sk})}
            skel_objs += bool(sk)
            skels += len(sk)
            anims += sum(na.values())
            objs.append({"id": f"0x{oid:03X}", "name": names.get(hex(oid), ""), "dma_index": i, "size": len(obj),
                         "yaz0": bool(rom.dma[i][3]), "skeletons": sk, "textures": settimg_count(obj),
                         "animations_by_limbs": {str(k): v for k, v in na.items()}})
        m["objects"] = objs
        m["summary"] = {"objects": len(objs), "skeletal_objects": skel_objs, "skeletons": skels,
                        "animation_headers": anims, "playable_slots": ["link_adult (object_link_boy)",
                                                                       "link_child (object_link_child)"]}
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ocarina of Time owned-build inventory")
    ap.add_argument("src")
    ap.add_argument("--out")
    ap.add_argument("--no-objects", action="store_true")
    a = ap.parse_args(argv)
    m = inventory(a.src, objects=not a.no_objects)
    text = json.dumps(m, indent=1)
    if a.out:
        Path(a.out).write_text(text)
        print(json.dumps({k: m[k] for k in ("source", "header", "launch", "layout", "summary") if k in m}, indent=1))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
