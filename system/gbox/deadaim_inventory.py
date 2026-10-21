"""Resident Evil - Dead Aim (PS2, USA disc, SLUS-20669 / SLUS_206.69, catalog f2b204a34366254b) source inventory (#2035).

NOTE: despite the catalog title, the owned USA image boots `SLUS_206.69` (the earlier checkpoint's
`SLES_008.20` guess was wrong). All constants here are read from the real disc, not from the title.

The owned image is a CHD v5 CD (gbox.chd.ChdDisc) holding a MODE1 ISO9660 disc:

  SYSTEM.CNF        BOOT2 = cdrom0:\\SLUS_206.69;1 (VER per the CNF)
  SLUS_206.69       the MIPS R5900 boot ELF  -> sha256 = the revision-guard anchor
  IMAGE.BIN         254,732,288 B main game data blob
  SNDIMAGE.BIN      67,108,864 B CRI sound image
  MOVIE0UC.BIN      1,139,851,264 B movies
  MOVIE1UC.BIN      917,889,024 B movies
  MODULES/*.IRX     IOP drivers incl. USBGUN.IRX and USBMOUSE.IRX (Light Gun Commander)

`inventory(path)` reads only directory sectors plus bounded blob headers (works directly on the .chd;
~15 s on the SMB mount) and returns a manifest: disc identity, boot ELF sha256, and per-blob header
probes (magic, embedded name directory) used to bind the unlock profile to this exact revision.

No unlock is claimed here; names of locked content are not guessed — evidence comes from REA/Ghidra
(x64 worker) against the boot ELF hash recorded by this module.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path

GAME_ID = "f2b204a34366254b"
SERIAL = "SLUS_206.69"
ROM_HINT = "Resident Evil - Dead Aim (USA).chd"
BLOBS = ("IMAGE.BIN", "SNDIMAGE.BIN", "MOVIE0UC.BIN", "MOVIE1UC.BIN")
# revision-guard anchor: pinned from the owned USA CHD (gbox-data/deadaim/inventory.json, this host).
# An unlock implementation must refuse to run unless the boot ELF it targets hashes to BOOT_ELF_SHA256.
BOOT_ELF_SHA256 = "030a18d56b1aa7ed735382022607d8e788771982326bdb1a46adf6f7f83a7a49"
BOOT_ELF_SIZE = 2362892


def system_cnf(text: str) -> dict:
    out = {}
    for line in text.replace("\r", "").split("\n"):
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip().upper()] = v.strip()
    boot = out.get("BOOT2", "")
    out["boot_file"] = re.sub(r"^cdrom0:\\+", "", boot).split(";")[0]
    return out


def elf_info(data: bytes) -> dict:
    if data[:4] != b"\x7fELF":
        raise ValueError("boot file is not an ELF")
    e_machine = struct.unpack_from("<H", data, 18)[0]
    if e_machine != 8:
        raise ValueError(f"e_machine={e_machine}, expected 8 (MIPS)")
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "e_machine": e_machine, "e_entry": hex(struct.unpack_from("<I", data, 24)[0]),
            "e_shoff": struct.unpack_from("<I", data, 32)[0],
            "e_shnum": struct.unpack_from("<H", data, 48)[0],
            "e_phnum": struct.unpack_from("<H", data, 44)[0]}


def blob_probe(head: bytes) -> dict:
    """Magic + CRI-style name directory probe for a *.BIN blob head."""
    out: dict = {"magic": head[:8].hex(), "head_sha256_1k": hashlib.sha256(head[:1024]).hexdigest()}
    if head[:4] == b"AFS\x00":
        n = struct.unpack_from("<I", head, 4)[0]
        out["container"] = "AFS"
        out["entries"] = n
    elif head[:4] == b"UCB ":
        out["container"] = "UCB"
    # scan the first 64 KiB for embedded ASCII name runs (e.g. "menu", "stage", "char")
    names = sorted({m.decode("ascii") for m in re.findall(rb"[a-zA-Z][a-zA-Z0-9_\-\.]{5,31}", head[:1 << 16])})
    interesting = [nm for nm in names if re.search(r"(stage|chapter|char|menu|unlock|bonus|mode|diff|extra|miss)", nm, re.I)]
    out["name_sample"] = names[:40]
    out["interesting_names"] = interesting[:60]
    return out


def inventory(path, source_sha256: str | None = None) -> dict:
    from .chd import ChdDisc

    d = ChdDisc(path)
    try:
        cnf = system_cnf(d.read("SYSTEM.CNF").decode("latin-1"))
        if cnf["boot_file"].upper() != SERIAL:
            raise ValueError(f"unexpected BOOT2 {cnf.get('BOOT2')!r}, expected {SERIAL}")
        elf = d.read(SERIAL)
        info = elf_info(elf)
        blobs = {}
        for name in BLOBS:
            lba, size = d.files[name]
            blobs[name] = {"lba": lba, "size": size, "probe": blob_probe(d.read(name, 0, 1 << 16))}
        modules = sorted(nm for nm in d.files if nm.startswith("MODULES/"))
        pvd = d.pvd
        return {
            "game_id": GAME_ID, "platform": "ps2", "container": "chd",
            "serial": SERIAL, "source_sha256": source_sha256,
            "volume_date": pvd[813:829].decode("latin-1"),
            "track_type": d.track_type, "frames": d.frames,
            "system_cnf": cnf,
            "boot_elf": {"name": SERIAL, **info},
            "blobs": blobs,
            "modules": modules,
            "gun_support": "USBGUN.IRX" in modules,
            "iso_files": {k: {"lba": v[0], "size": v[1]} for k, v in sorted(d.files.items())},
        }
    finally:
        d.chd.close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--sha256")
    ap.add_argument("--out")
    a = ap.parse_args()
    m = inventory(a.source, a.sha256)
    s = json.dumps(m, indent=1)
    (Path(a.out).write_text(s) if a.out else print(s))
