"""Exact-build inventory for Power Stone 2 (USA), Dreamcast (game 690a402443c15668).

Reads the unpacked GD-ROM (``disc.gdi`` made by ``chdman extractcd`` from the owned
HyperSpin CHD) read-only and writes a JSON manifest: source/track hashes, IP.BIN identity,
the 1ST_READ.BIN hash and its file-name table, the ``*_CONNECT.BIN`` container layout and
the per-character inventory (models, texture packs, motion banks, small data blocks, the
per-player-port DTPK sound banks) together with each file's LBA room on the disc, which
bounds a same-size native writer.

    python -m gbox.pstone2_inventory disc.gdi --chd OWNED.chd --out manifest.json

Build: T-1211N V1.000 (2000-04-28), area U. Characters are 3D Capcom models (not Ninja
NJCM); every playable character lives in one ``PLxy_CONNECT.BIN``. A CONNECT file starts
with a 16-slot table of (u32 offset, u32 size) pairs; the first offset is the table size
(0x80). Only a leading chain of slots is valid -- each next offset is the previous end
rounded up to 32 bytes -- and the remaining slots hold stale values from the tool's
buffer (they can even point past the end of the file), so they must never be trusted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

GAME_ID = "690a402443c15668"
TITLE = "Power Stone 2 (USA)"
PRODUCT = "T1211N"
VERSION = "V1.000"
# 1ST_READ.BIN of the owned T-1211N V1.000 disc; addresses found in it are build-specific.
FIRST_READ_SHA256 = "a3dcd09a96045839dbbc35697eb4336e4eba79b52203a46bb2f8ee9a4ba2eed8"
FIRST_READ_BASE = 0x8C010000
NAME_TABLE = 0x194024           # file offset of the 497-entry file-name table (disc order)
SOUND_NAMES = 0x1F4DC8          # 6-char sound-test player names (8-byte stride)
SECTOR = 2048
SLOTS = 16

# sound-test player order (debug menu in 1ST_READ); the first 14 have per-port DTPK banks
PLAYER_KEYS = ["FOKKER", "RYOMA", "WANG", "JACK", "GUNROCK", "GALUDA", "AYAME", "ROUGE",
               "PITO", "GURMAN", "JULIA", "KID", "BOSS1", "BOSS2"]
DISPLAY = {"FOKKER": "Falcon (Fokker)", "RYOMA": "Ryoma", "WANG": "Wang-Tang", "JACK": "Jack",
           "GUNROCK": "Gunrock", "GALUDA": "Galuda", "AYAME": "Ayame", "ROUGE": "Rouge",
           "PITO": "Pete (Pito)", "GURMAN": "Gourmand", "JULIA": "Julia", "KID": "Accel (Kid)",
           "BOSS1": "Pharaoh Walker (Boss 1)", "BOSS2": "Dr. Erode (Boss 2)",
           "MERU": "Mel (Meru)", "PAPA": "Papa"}


def sha256_file(path: str | Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def parse_ip(sector: bytes) -> dict:
    """Dreamcast IP.BIN meta block (first 0x100 bytes of the high-density data track)."""
    if sector[:16] != b"SEGA SEGAKATANA ":
        raise ValueError("No Dreamcast IP.BIN at the start of the high-density area")
    f = lambda a, b: sector[a:b].decode("latin-1").strip()  # noqa: E731
    return {"hardware": f(0x00, 0x10), "maker": f(0x10, 0x20), "device": f(0x20, 0x30),
            "area": f(0x30, 0x38), "peripherals": f(0x38, 0x40), "product": f(0x40, 0x4A),
            "version": f(0x4A, 0x50), "date": f(0x50, 0x60), "boot": f(0x60, 0x70),
            "company": f(0x70, 0x80), "title": f(0x80, 0x100)}


def file_room(files: dict[str, tuple[int, int]]) -> dict[str, int]:
    """Bytes each file may occupy without moving another file: up to the next file's LBA."""
    order = sorted(files.items(), key=lambda kv: (kv[1][0], kv[0]))
    room = {}
    for i, (name, (lba, size)) in enumerate(order):
        own = (size + SECTOR - 1) // SECTOR * SECTOR
        nxt = next((l for _, (l, _s) in order[i + 1:] if l > lba), None)
        room[name] = max(own, (nxt - lba) * SECTOR) if nxt is not None else own
    return room


def name_table(exe: bytes, at: int = NAME_TABLE) -> list[str]:
    """The executable's file-name table: NUL-terminated names, each 4-byte aligned."""
    out, o = [], at
    while o < len(exe):
        e = exe.find(b"\0", o)
        s = exe[o:e] if e >= 0 else b""
        if not s or not re.fullmatch(rb"[0-9A-Z_./]+", s):
            break
        out.append(s.decode())
        o = (e + 4) & ~3
    return out


def sound_players(exe: bytes, at: int = SOUND_NAMES, n: int = 21) -> list[str]:
    return [exe[at + 8 * i:at + 8 * i + 6].rstrip(b"\0 ").decode("latin-1") for i in range(n)]


def connect_table(data: bytes) -> list[tuple[int, int]]:
    """Valid (offset, size) entries of a ``*_CONNECT.BIN`` (the leading 32-byte-aligned chain)."""
    first = struct.unpack_from("<I", data, 0)[0]
    if first != SLOTS * 8:
        raise ValueError(f"CONNECT table size {first:#x} != {SLOTS * 8:#x}")
    raw = [struct.unpack_from("<II", data, 8 * i) for i in range(SLOTS)]
    out, expect = [], first
    for off, size in raw:
        # a zero-size slot inside the chain is a real empty placeholder (bosses PLC0/PLD0 slot 3)
        if off != expect or off + size > len(data):
            break
        out.append((off, size))
        expect = (off + size + 31) & ~31
    if not out or (out[-1][0] + out[-1][1] + 31) & ~31 < (len(data) & ~31):
        raise ValueError("CONNECT chain does not reach the end of the file")
    return out


def classify(blob: bytes, prev: str | None = None) -> dict:
    """Coarse kind of a CONNECT entry (format decoding is the analysis stage).

    Models and motion banks are identified by their headers; the entry right after a model
    is that model's texture pack (the ``*_MODEL_VQ.MDL`` + ``*_MODEL_VQ_BIN.PAC`` pairing of
    the shared files). Its lead varies, so it is assigned by position, not by magic.
    """
    if not blob:
        return {"kind": "empty", "head": []}
    w = struct.unpack_from("<4I", blob.ljust(16, b"\0"))
    if w[0] == 0xFFFFFFFF:
        # Capcom model: -1, object count, first-table size, ... (same header as *_MODEL_VQ.MDL)
        return {"kind": "model", "head": [w[1], w[2], w[3]]}
    if w[0] == 0x10 and w[1] == 0x2010:
        return {"kind": "motion", "head": [w[2]]}   # same header as CMN_MOT.BIN
    if prev == "model":
        return {"kind": "texture_pack", "head": [struct.unpack_from("<H", blob.ljust(4, b"\0"), 2)[0]]}
    if blob[:2] == b"\x01\x00":
        return {"kind": "data", "head": [struct.unpack_from("<H", blob.ljust(4, b"\0"), 2)[0]]}
    return {"kind": "unknown", "head": list(w)}


# Fixed CONNECT slot roles of a playable character (verified on all 18 PL files of this build):
# a power-change character has three model/texture pairs; Mel (PLE0) has only the first.
PL_ROLES = {0: "body_model", 1: "body_textures", 2: "power_change_model", 3: "power_change_textures",
            4: "motion_bank", 5: "extra_model", 6: "extra_textures", 7: "data_a", 8: "data_b"}
PL_ROLES_SINGLE = {0: "body_model", 1: "body_textures", 2: "motion_bank", 3: "data_a", 4: "data_b"}


def compare_names(table: list[str], disc: dict[str, tuple[int, int]]) -> dict:
    """The executable names files by basename; report what the table and the disc disagree on."""
    base = {n.rsplit("/", 1)[-1]: n for n in disc}
    return {"count": len(table), "missing_on_disc": [n for n in table if n not in base],
            "not_in_table": sorted(n for b, n in base.items() if b not in set(table)),
            "load_id": {n: i for i, n in enumerate(table)}}


def inventory(gdi: str | Path, chd: str | Path | None = None, chd_sha256: str | None = None,
              hash_tracks: bool = True) -> dict:
    from .gdrom import GDRom
    gdi = Path(gdi)
    g = GDRom(gdi)
    ip = parse_ip(g.sector(45000))
    if ip["product"].replace("-", "") != PRODUCT or ip["version"] != VERSION:
        raise ValueError(f"not {TITLE} {PRODUCT} {VERSION}: {ip['product']} {ip['version']}")
    exe = g.read("1ST_READ.BIN")
    exe_sha = hashlib.sha256(exe).hexdigest()
    names = name_table(exe)
    cmp = compare_names(names, g.files)
    load_id = cmp.pop("load_id")
    room = file_room(g.files)
    man: dict = {"game_id": GAME_ID, "title": TITLE, "platform": "dreamcast", "ip": ip,
                 "first_read": {"sha256": exe_sha, "size": len(exe), "base": hex(FIRST_READ_BASE),
                                "matches_pinned": exe_sha == FIRST_READ_SHA256,
                                "name_table": {"offset": hex(NAME_TABLE), **cmp}},
                 "launch": {"core": "flycast", "media": "GD-ROM (3 tracks)", "bios": "dc_boot.bin + dc_flash.bin",
                            "boot_file": ip["boot"], "scrambled_1st_read": False},
                 "files": len(g.files)}
    if chd:
        man["source"] = {"path": str(chd), "sha256": chd_sha256 or sha256_file(chd),
                         "size": Path(chd).stat().st_size}
    if hash_tracks:
        man["tracks"] = [{"lba": lba, "sector": ss, "file": p.name, "sha256": sha256_file(p)}
                         for lba, ss, p in g.tracks] + _gdi_audio(gdi)
    kinds: dict[str, int] = {}
    for n in g.files:
        k = n.rsplit(".", 1)[-1] if "." in n.rsplit("/", 1)[-1] else ""
        kinds[k] = kinds.get(k, 0) + 1
    man["extensions"] = dict(sorted(kinds.items()))
    sound = sound_players(exe)
    man["sound_test_players"] = sound
    containers = {}
    for n in sorted(g.files):
        if n.endswith("_CONNECT.BIN"):
            d = g.read(n)
            ents, prev = [], None
            for i, (o, s) in enumerate(connect_table(d)):
                blob = d[o:o + s]
                c = classify(blob, prev)
                prev = c["kind"]
                ents.append({"slot": i, "offset": o, "size": s, **c,
                             "sha256": hashlib.sha256(blob).hexdigest()})
            if re.fullmatch(r"PL[0-9A-F]{2}_CONNECT\.BIN", n):
                roles = PL_ROLES if len(ents) == len(PL_ROLES) else PL_ROLES_SINGLE
                for e in ents:
                    e["role"] = roles.get(e["slot"], "unknown")
            containers[n] = {"lba": g.files[n][0], "size": len(d), "room": room[n], "load_id": load_id.get(n),
                             "sha256": hashlib.sha256(d).hexdigest(), "entries": ents}
    man["containers"] = containers
    roster = []
    for n in sorted(c for c in containers if re.fullmatch(r"PL[0-9A-F]{2}_CONNECT\.BIN", c)):
        code = n[2:4]
        idx = int(code[0], 16)
        key = sound[idx] if idx < len(sound) else None
        key = {"RYOUMA": "RYOMA", "WANTAN": "WANG", "GUNROK": "GUNROCK", "GARUDA": "GALUDA",
               "ROUAGE": "ROUGE", "BOSS 1": "BOSS1", "BOSS 2": "BOSS2"}.get(key, key)
        ents = containers[n]["entries"]
        want = {"model": "model", "textures": "texture_pack", "bank": "motion", "data": "data"}
        layout_ok = all(e["kind"] == next(v for k, v in want.items() if k in e["role"]) or
                        (e["role"] == "power_change_textures" and e["kind"] == "empty")  # bosses' stub form
                        for e in ents)
        base = f"PL{code[0]}0_CONNECT.BIN"
        bank = {p: f"{key}_{p}.BIN" for p in ("1P", "2P", "3P", "4P", "1PB", "2PB", "3PB", "4PB", "MP")
                if f"{key}_{p}.BIN" in g.files}
        roster.append({"pl": code, "file": n, "char_index": idx, "key": key,
                       "name": DISPLAY.get(key, key), "variant_of": base if code[1] != "0" else None,
                       "shared_with_base": sorted({e["role"] for e in ents} & {
                           e["role"] for e in containers.get(base, {"entries": []})["entries"]
                           if any(e["sha256"] == f["sha256"] and e["role"] == f["role"] for f in ents)})
                       if code[1] != "0" else [],
                       "mapping": "pl high nibble = sound-test player index (to confirm at analysis)",
                       "layout_ok": layout_ok,
                       "models": sum(e["kind"] == "model" for e in ents),
                       "texture_packs": sum(e["kind"] == "texture_pack" for e in ents),
                       "motions": sum(e["kind"] == "motion" for e in ents),
                       "data_blocks": sum(e["kind"] == "data" for e in ents),
                       "sound_banks": bank})
    man["roster"] = roster
    man["shared"] = {n: {"lba": g.files[n][0], "size": g.files[n][1], "room": room[n]}
                     for n in ("CMN_MOT.BIN", "CMN_HITTBL_BIN.PAC", "COMN_HITDAT_BIN.PAC", "CMN_MODEL_VQ.MDL",
                               "CMN_MODEL_VQ_BIN.PAC", "ITEM_MODEL_VQ.MDL", "ITEM_MODEL_VQ_BIN.PAC",
                               "FONT_MODEL_VQ.MDL", "PIT_MODEL.MDL", "PIT_MODEL_BIN.PAC", "SELECT.BIN")
                     if n in g.files}
    return man


def _gdi_audio(gdi: Path) -> list[dict]:
    out = []
    for ln in gdi.read_text().splitlines()[1:]:
        p = ln.split()
        if len(p) >= 5 and p[2] == "0":
            out.append({"lba": int(p[1]), "sector": int(p[3]), "file": p[4].strip('"'), "audio": True,
                        "sha256": sha256_file(gdi.parent / p[4].strip('"'))})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("--chd")
    ap.add_argument("--chd-sha256")
    ap.add_argument("--no-track-hashes", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    man = inventory(a.gdi, a.chd, a.chd_sha256, hash_tracks=not a.no_track_hashes)
    text = json.dumps(man, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
