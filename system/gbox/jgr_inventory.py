"""Exact-build inventory for Jet Grind Radio (USA), Dreamcast (game 4187aeab4d67638c).

Reads the unpacked GD-ROM (``disc.gdi`` from ``chdman extractcd`` of the owned HyperSpin CHD) read-only
and writes a JSON manifest: source/track hashes, IP.BIN identity, the 1ST_READ.BIN hash and its native
character debug-name table, launch prerequisites, a census of every CRI AFS archive on the disc, the
PLAYER.AFS entry layout (each entry's growth room, bounded by the next entry or the CRI file-name
directory) and the per-character inventory: native ID, the six draw groups (raw Ninja chunk-model trees:
nodes/vertices/triangles/texture ids), the PTEX texture set (PVR formats and sizes), each group's
texlist and the PLAY data-record spans (kinds 0 and 4-7: motion/other data, decoded at analysis).
ENEMY.AFS (police, NPC and rival-gang models) is listed by name.

    python -m gbox.jgr_inventory disc.gdi --chd OWNED.chd --out manifest.json

Build: MK-51058 V1.005 (2000-10-02), area U. PLAY/PTEX parsing reuses :mod:`gbox.jgr` (the existing
reader/writer); this module adds the build pin, the disc census and the manifest.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import struct
import sys
from pathlib import Path

from . import jgr
from .pstone2_inventory import _gdi_audio, file_room, parse_ip, sha256_file

GAME_ID = "4187aeab4d67638c"
TITLE = "Jet Grind Radio (USA)"
PRODUCT = "MK51058"
VERSION = "V1.005"
RELEASE_DATE = "20001002"
AREA = "U"
# 1ST_READ.BIN of the owned MK-51058 V1.005 disc; addresses found in it are build-specific.
FIRST_READ_SHA256 = "8b294765225fc32020dd59010464a730b710d0bd79f69c79f16218cc4feac6a6"
FIRST_READ_BASE = 0x8C010000
DEBUG_NAME_TABLE = 0x8C10DF40      # VA of 16 char* character debug names in native-ID order (BEAT(EREKI) = 0)
ENEMY_AFS = "JETRADIO/ENEMY.AFS"
PLAYER_AFS_ENTRIES = 34            # 16 (PLAY dat, PTEX txr) pairs + player_effect (main, EFTX)

_MAGIC_KINDS = {b"PLAY": "play", b"PTEX": "ptex", b"main": "main", b"EFTX": "eftx", b"GBIX": "pvr",
                b"SOSB": "sound_bank", b"SMSB": "sound_bank", b"SMPB": "sound_bank", b"SFOB": "sound_bank",
                b"SFPB": "sound_bank", b"JMDc": "mission", b"JMSb": "mission", b"JMSc": "mission"}


def entry_kind(head: bytes) -> str:
    """Coarse kind of an AFS entry from its first four bytes (format decoding is the analysis stage)."""
    head = bytes(head[:4])
    if len(head) < 4:
        return "empty"
    if head in _MAGIC_KINDS:
        return _MAGIC_KINDS[head]
    if head[:2] == b"\x80\x00":
        return "adx"                    # CRI ADX audio stream
    if head[3] == 0x8C:
        return "ram_linked"             # leads with a 0x8Cxxxxxx pointer: data pre-linked to a fixed RAM address
    if 0x10 <= head[0] <= 0x17 and head[3] == 0:
        return "ninja_chunk"            # raw Ninja chunk data that starts with a material chunk (ENEMY/FONT3D dat)
    return "other"


def debug_names(exe: bytes, va: int = DEBUG_NAME_TABLE, n: int = jgr.CHARACTER_COUNT,
                base: int = FIRST_READ_BASE) -> list[str | None]:
    """The executable's character debug-name table (one char* per native ID); None where a pointer does not
    resolve to a short printable string inside the image."""
    at = va - base
    if not 0 <= at <= len(exe) - 4 * n:
        raise ValueError(f"debug-name table {va:#x} is outside the {len(exe)}-byte image")
    out: list[str | None] = []
    for p in struct.unpack_from(f"<{n}I", exe, at):
        o = p - base
        end = exe.find(b"\0", o) if 0 <= o < len(exe) else -1
        if end <= o or end - o > 64:
            out.append(None)
            continue
        try:
            s = exe[o:end].decode("ascii")
        except UnicodeDecodeError:
            out.append(None)
            continue
        out.append(s if s.isprintable() else None)
    return out


def afs_directory(data: bytes) -> tuple[int, int] | None:
    """(offset, size) of the CRI file-name directory (48-byte records, entry size at +44), or None."""
    count, offs, sizes = jgr.afs_entries(data)
    if not count:
        return None
    table_end = 8 + 8 * count
    for at in dict.fromkeys((min(offs) - 8, table_end)):
        if not table_end <= at <= len(data) - 8:
            continue
        o, s = struct.unpack_from("<II", data, at)
        if o < table_end or s < 48 * count or o + s > len(data):
            continue
        if all(struct.unpack_from("<I", data, o + 48 * i + 44)[0] == sizes[i] for i in range(count)):
            return o, s
    return None


def afs_layout(data: bytes, hashes: bool = False) -> list[dict]:
    """Every AFS entry: index, directory name (None without a directory), offset, size, kind and room -- the
    bytes it may occupy without moving the next entry or the file-name directory."""
    count, offs, sizes = jgr.afs_entries(data)
    try:
        names: list[str | None] = list(jgr.afs_names(data))
    except ValueError:
        names = [None] * count
    d = afs_directory(data)
    bounds = sorted(set(offs) | ({d[0]} if d else set()))
    out = []
    for i, (o, s) in enumerate(zip(offs, sizes)):
        nxt = next((b for b in bounds if b > o), len(data))
        e = {"index": i, "name": names[i], "offset": o, "size": s, "room": nxt - o,
             "kind": entry_kind(data[o:o + 4]) if s else "empty"}
        if hashes:
            e["sha256"] = hashlib.sha256(data[o:o + s]).hexdigest()
        out.append(e)
    return out


def record_spans(recs: list[tuple[int, int]], end: int) -> list[dict]:
    """PLAY header records that are not model roots (kinds 0 and 4-7) with the span to the next record."""
    offs = sorted({v for v, _ in recs if 0 < v < end})
    out = []
    for v, k in recs:
        if k in jgr.MODEL_KINDS:
            continue
        nxt = next((x for x in offs if x > v), end)
        out.append({"kind": k, "offset": v, "span": nxt - v})
    return out


def _entry(data: bytes, e: dict) -> dict:
    return {k: e[k] for k in ("index", "name", "offset", "size", "room")} | {
        "sha256": hashlib.sha256(data[e["offset"]:e["offset"] + e["size"]]).hexdigest()}


def characters(data: bytes, debug: list[str | None] | None = None) -> list[dict]:
    """Per-character inventory of PLAYER.AFS in archive order (the reader's ``jgr_charNN`` slugs)."""
    index = {e["offset"]: e for e in afs_layout(data)}
    ids = jgr.native_ids(data)
    ros = jgr.roster()
    out = []
    for i in range(jgr.CHARACTER_COUNT):
        play, ptex = jgr.character_pair(data, i)
        pe, te = index[play], index[ptex]
        buf = jgr.play_bytes(data, play)
        texlists = jgr.ptex_texlists(data, ptex)
        texs = jgr.ptex_textures(data, ptex)
        groups = []
        for k, root in enumerate(jgr.play_groups(data, play)):
            grp = {"group": k, "role": jgr.GROUP_ROLES[k], "root": root,
                   "texlist": texlists[k] if k < len(texlists) else []}
            if root is not None:
                nj = jgr.play_model(buf, root)
                grp.update(nodes=len(nj.bones), vertices=len(nj.vbuf),
                           triangles=sum(len(t) for t in nj.tris.values()), texture_ids=sorted(nj.tris))
            groups.append(grp)
        _, recs = jgr.container_header(data, play)
        kinds = collections.Counter(k for _, k in recs)
        name = pe["name"] or ""
        out.append({
            "archive_slot": i, "slug": ros[i]["slug"], "name": ros[i]["name"],
            "resource": name[:-len("dat.bin")] if name.endswith("dat.bin") else None,
            "native_id": ids[i], "debug_name": debug[ids[i]] if debug and ids[i] < len(debug) else None,
            "play": _entry(data, pe), "ptex": _entry(data, te),
            "draw_groups": groups,
            "textures": [{"index": j, "gbix": t["gbix"], "pixfmt": t["pixfmt"], "datafmt": t["datafmt"],
                          "width": t["width"], "height": t["height"], "bytes": len(t["bytes"])}
                         for j, t in enumerate(texs)],
            "atlas_texture": jgr.atlas_texture(data, ptex, texlists),
            "records": {"count": len(recs), "kinds": {str(k): n for k, n in sorted(kinds.items())},
                        "data": record_spans(recs, len(buf))},
        })
    return out


def afs_census(g, room: dict[str, int]) -> dict:
    """Entry counts and coarse kinds of every AFS archive on the disc."""
    out = {}
    for n in sorted(g.files):
        if not n.upper().endswith(".AFS"):
            continue
        d = g.read(n)
        lay = afs_layout(d)
        out[n] = {"lba": g.files[n][0], "size": g.files[n][1], "room": room[n], "entries": len(lay),
                  "named": any(e["name"] for e in lay),
                  "kinds": dict(sorted(collections.Counter(e["kind"] for e in lay).items())),
                  "sha256": hashlib.sha256(d).hexdigest()}
    return out


def parse_chd_info(text: str) -> dict:
    """Selected fields of ``chdman info`` output."""
    keys = {"File Version": "version", "Logical size": "logical_size", "Hunk Size": "hunk_size",
            "SHA1": "sha1", "Data SHA1": "data_sha1", "Compression": "compression"}
    out = {}
    for ln in text.splitlines():
        k, sep, v = ln.partition(":")
        if sep and k.strip() in keys:
            out[keys[k.strip()]] = v.strip()
    return out


def compare_tracks(tracks: list[dict], other: str | Path) -> dict[str, bool]:
    """Whether each hashed track equals the same-named file in ``other`` (e.g. a fresh chdman extraction)."""
    return {t["file"]: (Path(other) / t["file"]).is_file() and sha256_file(Path(other) / t["file"]) == t["sha256"]
            for t in tracks}


def inventory(gdi: str | Path, chd: str | Path | None = None, chd_sha256: str | None = None,
              hash_tracks: bool = True, chd_info: str | None = None, bios_dir: str | Path | None = None,
              verify_dir: str | Path | None = None) -> dict:
    from .gdrom import GDRom
    gdi = Path(gdi)
    g = GDRom(gdi)
    ip = parse_ip(g.sector(45000))
    if ip["product"].replace("-", "") != PRODUCT or ip["version"] != VERSION:
        raise ValueError(f"not {TITLE} {PRODUCT} {VERSION}: {ip['product']} {ip['version']}")
    exe = g.read("1ST_READ.BIN")
    exe_sha = hashlib.sha256(exe).hexdigest()
    debug = debug_names(exe)
    room = file_room(g.files)
    player = g.read(jgr.PLAYER_AFS)
    layout = afs_layout(player, hashes=True)
    for e in layout:
        e["jgr_entry_room"] = jgr.entry_room(player, e["offset"])
    chars = characters(player, debug)
    enemy = afs_layout(g.read(ENEMY_AFS))
    last = max(layout, key=lambda e: e["offset"])
    man: dict = {
        "game_id": GAME_ID, "title": TITLE, "platform": "dreamcast", "ip": ip,
        "first_read": {"sha256": exe_sha, "size": len(exe), "base": hex(FIRST_READ_BASE),
                       "matches_pinned": exe_sha == FIRST_READ_SHA256, "head": exe[:16].hex(),
                       "debug_name_table": {"va": hex(DEBUG_NAME_TABLE), "names": debug}},
        "launch": {"core": "retroarch flycast", "media": "GD-ROM: 3 tracks (gdi: data LBA 0, CDDA, high-density LBA 45000)",
                   "bios": "dc/dc_boot.bin + dc/dc_flash.bin in the RetroArch system dir",
                   "boot_file": ip["boot"], "peripherals": ip["peripherals"],
                   "first_read_scrambled": False if debug[0] else None,
                   "catalog": {"library": "hyperspin",
                               "rel_path": "collections/Sega Dreamcast/roms/Jet Grind Radio (USA).chd",
                               "launch_kind": "attract"}},
        "files": len(g.files),
        "extensions": dict(sorted(collections.Counter(
            n.rsplit(".", 1)[-1] if "." in n.rsplit("/", 1)[-1] else "" for n in g.files).items())),
    }
    if chd:
        man["source"] = {"path": str(chd), "sha256": chd_sha256 or sha256_file(chd),
                         "size": Path(chd).stat().st_size, **({"chd": parse_chd_info(chd_info)} if chd_info else {})}
    if hash_tracks:
        man["tracks"] = [{"lba": lba, "sector": ss, "file": p.name, "sha256": sha256_file(p)}
                         for lba, ss, p in g.tracks] + _gdi_audio(gdi)
        if verify_dir:
            man["unpack_matches_fresh_extract"] = compare_tracks(man["tracks"], verify_dir)
    if bios_dir:
        man["launch"]["bios_files"] = {
            f: ({"size": (Path(bios_dir) / f).stat().st_size, "sha256": sha256_file(Path(bios_dir) / f)}
                if (Path(bios_dir) / f).is_file() else None) for f in ("dc/dc_boot.bin", "dc/dc_flash.bin")}
    man["afs_census"] = afs_census(g, room)
    man["player_afs"] = {"path": jgr.PLAYER_AFS, "lba": g.files[jgr.PLAYER_AFS][0], "size": len(player),
                         "room": room[jgr.PLAYER_AFS], "sha256": hashlib.sha256(player).hexdigest(),
                         "directory": afs_directory(player), "entries": layout,
                         "shared": [e["name"] for e in layout if e["kind"] in ("main", "eftx")],
                         # jgr.entry_room (the writer's bound) ignores the directory after the last entry
                         "writer_room_last_entry": {"name": last["name"], "room": last["room"],
                                                    "jgr_entry_room": jgr.entry_room(player, last["offset"])}}
    man["enemy_afs"] = {"path": ENEMY_AFS, "entries": enemy, "count": len(enemy),
                        "models": sorted({(e["name"] or "")[:-len("dat.bin")] for e in enemy
                                          if (e["name"] or "").endswith("dat.bin")}),
                        "kinds": dict(sorted(collections.Counter(e["kind"] for e in enemy).items()))}
    man["characters"] = chars
    man["checks"] = {
        "platform_is_dreamcast": ip["hardware"] == "SEGA SEGAKATANA",
        "build": f"{ip['product']} {ip['version']} {ip['date']} area {ip['area']}",
        "first_read_pinned": exe_sha == FIRST_READ_SHA256,
        "debug_names_match_reader": [debug[i] for i in range(10)] == jgr.NATIVE_DEBUG_NAMES[:10],
        "roster_matches_reader": ([c["resource"] for c in chars] == jgr.ARCHIVE_NAMES
                                  and [c["native_id"] for c in chars] == jgr.USA_NATIVE_IDS),
        "player_afs_entries": len(layout) == PLAYER_AFS_ENTRIES,
        "body_groups_20_nodes": all(c["draw_groups"][0].get("nodes") == 20 for c in chars),
    }
    return man


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("--chd")
    ap.add_argument("--chd-sha256")
    ap.add_argument("--chd-info", help="saved `chdman info` output for the CHD")
    ap.add_argument("--bios-dir", help="RetroArch system dir (records dc_boot/dc_flash presence)")
    ap.add_argument("--verify-extract", help="directory of a fresh chdman extraction to compare tracks with")
    ap.add_argument("--no-track-hashes", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    man = inventory(a.gdi, a.chd, a.chd_sha256, hash_tracks=not a.no_track_hashes,
                    chd_info=Path(a.chd_info).read_text() if a.chd_info else None,
                    bios_dir=a.bios_dir, verify_dir=a.verify_extract)
    text = json.dumps(man, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    else:
        sys.stdout.write(text + "\n")
    return 0 if all(v for k, v in man["checks"].items() if k != "build") else 1


if __name__ == "__main__":
    raise SystemExit(main())
