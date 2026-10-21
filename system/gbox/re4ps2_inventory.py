"""Resident Evil 4 (PS2, SLUS-21134 v1.01, catalog 109d8ee7747a7dd8) source inventory (#1321).

The owned image is a CISO (`gbox.cso`) of a plain ISO9660 DVD:

  SYSTEM.CNF   BOOT2 = cdrom0:\\SLUS_211.34;1, VER = 1.01, VMODE = NTSC
  SLUS_211.34  the MIPS R5900 ELF; MODULES.DAT, IOPRP.IMG (IOP replacement image)
  DATA/0FLIST.DIR  text list of the three archives below
  DATA/BIO4DAT.AFS   CRI AFS ("AFS\\0", u32 count, count x (offset, size), then the (offset, size) of a 48-byte-record
                     name directory: name[32] + 16 bytes of date/attribute words; that tail is NOT the file size here)
  DATA/BIO4MOV.AFS, BIO4MOV2.AFS  movies

Unlike GC/Wii (em/plXX.drs UDAS), each actor is a run of AFS entries `xxNN.snd` (UDAS sound bank, 0xCAB6BE20 fill),
`xxNN.dat` (the model pack), a zero-length duplicate name, and `xxNN.rel` (an "SNR2" relocatable R5900 code module).
The model pack is the same DAT container as GC (u32 count, 12 pad, count x u32 offset, count x 4-char extension:
BIN/TPL/SEQ/FCV/EFF) but little-endian, and its BIN (0x30-byte header, cd-filled, GIF/VIF data) and TPL
(0x1000-tagged PS2 texture list) are PS2-native formats, so `re4gc_models` does not decode them.

`inventory(path)` reads only directory sectors and pack headers (works directly on the .cso), and returns a manifest:
disc identity, boot ELF sha256, archive layout and every character pack with its section counts. Names of IDs are
not guessed; only pl00 = Leon (default costume) is established (shared with the GC/Wii pl00 mapping).
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
from collections import Counter
from pathlib import Path

GAME_ID = "109d8ee7747a7dd8"
SERIAL = "SLUS_211.34"
CHAR_RE = re.compile(r"^(pl|em)([0-9a-f]{2})(low)?\.dat$", re.I)
KNOWN = {"pl00": "Leon (default costume)"}


def open_source(path):
    p = Path(path)
    if p.suffix.lower() == ".cso":
        from .cso import CSO
        return CSO(p)
    return open(p, "rb")


def system_cnf(text: str) -> dict:
    out = {}
    for line in text.replace("\r", "").split("\n"):
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip().upper()] = v.strip()
    boot = out.get("BOOT2", "")
    out["boot_file"] = re.sub(r"^cdrom0:\\+", "", boot).split(";")[0]
    return out


def afs_table(head: bytes) -> tuple[list[tuple[int, int]], tuple[int, int]]:
    if head[:4] != b"AFS\0":
        raise ValueError("not a CRI AFS archive")
    n = struct.unpack_from("<I", head, 4)[0]
    if len(head) < 16 + 8 * n:
        raise ValueError("AFS header read is too short for its entry count")
    ent = [struct.unpack_from("<II", head, 8 + 8 * i) for i in range(n)]
    return ent, struct.unpack_from("<II", head, 8 + 8 * n)


def afs_names(dirblob: bytes, n: int) -> list[str]:
    return [dirblob[48 * i:48 * i + 32].split(b"\0")[0].decode("latin-1") for i in range(n)]


def dat_sections(head: bytes) -> list[tuple[int, str]] | None:
    """(offset, ext) per slot of a little-endian RE4 DAT pack, or None when `head` isn't one."""
    if len(head) < 16:
        return None
    n = struct.unpack_from("<I", head, 0)[0]
    if not 0 < n < 4096 or head[4:16] != b"\0" * 12 or len(head) < 16 + 8 * n:
        return None
    offs = struct.unpack_from(f"<{n}I", head, 16)
    exts = [head[16 + 4 * n + 4 * k:20 + 4 * n + 4 * k].rstrip(b"\0").decode("latin-1", "replace") for k in range(n)]
    if any(e and not e.isalnum() for e in exts):
        return None
    return list(zip(offs, exts))


def inventory(path, source_sha256: str | None = None) -> dict:
    from .romexport import iso_files
    f = open_source(path)
    try:
        files = iso_files(f)

        def read(key, off=0, size=None):
            _r, lba, sz = files[key]
            f.seek(lba * 2048 + off)
            return f.read(sz - off if size is None else min(size, sz - off))

        f.seek(16 * 2048)
        pvd = f.read(2048)
        vol_date = pvd[813:829].decode("latin-1")                  # volume creation yyyymmddhhmmsscc
        cnf = system_cnf(read("SYSTEM.CNF").decode("latin-1"))
        elf = read(cnf["boot_file"].upper())
        if elf[:4] != b"\x7fELF" or struct.unpack_from("<H", elf, 18)[0] != 8:
            raise ValueError(f"{cnf['boot_file']} is not a MIPS ELF")
        _r, lba, size = files["DATA/BIO4DAT.AFS"]
        base = lba * 2048
        f.seek(base)
        n = struct.unpack_from("<I", f.read(8), 4)[0]
        f.seek(base)
        ent, (doff, dsize) = afs_table(f.read(16 + 8 * n))
        f.seek(base + doff)
        names = afs_names(f.read(dsize), n)
        exts = Counter(nm.rsplit(".", 1)[-1].lower() for nm, (_o, s) in zip(names, ent) if s)
        chars = []
        for i, (nm, (off, sz)) in enumerate(zip(names, ent)):
            m = CHAR_RE.match(nm)
            if not m or not sz:
                continue
            f.seek(base + off)
            secs = dat_sections(f.read(16 + 8 * 4096 if sz > 16 + 8 * 4096 else sz))
            if secs is None:
                continue
            cid = (m.group(1) + m.group(2)).lower()
            # the run is snd, dat, (empty dup), rel; a costume may reuse another actor's module (pl15 -> pl11.rel)
            snd = next((j for j in range(i - 1, max(-1, i - 3), -1) if ent[j][1] and names[j].lower().endswith(".snd")), None)
            rel = next((j for j in range(i + 1, min(n, i + 4)) if ent[j][1] and names[j].lower().endswith(".rel")), None)
            chars.append({"id": cid, "variant": "low" if m.group(3) else "", "afs_index": i, "name": nm,
                          "offset": off, "size": sz, "sections": dict(Counter(e for _o, e in secs if e)),
                          "slots": len(secs), "snd_index": snd, "rel_index": rel,
                          "rel_name": names[rel] if rel is not None else None, "label": KNOWN.get(cid),
                          "unknown": cid not in KNOWN, "variant_of": None})
        return {
            "game_id": GAME_ID, "platform": "ps2", "container": Path(path).suffix.lower().lstrip("."),
            "source_sha256": source_sha256, "volume_date": vol_date,
            "system_cnf": cnf, "boot_elf": {"name": cnf["boot_file"], "size": len(elf),
                                             "sha256": hashlib.sha256(elf).hexdigest()},
            "iso_files": {k: {"lba": v[1], "size": v[2]} for k, v in sorted(files.items())},
            "afs": {"file": "DATA/BIO4DAT.AFS", "entries": n, "nonempty": sum(1 for _o, s in ent if s),
                    "name_dir": [doff, dsize], "extensions": dict(exts.most_common())},
            "characters": chars,
            "player_ids": sorted({c["id"] for c in chars if c["id"].startswith("pl")}),
            "enemy_ids": sorted({c["id"] for c in chars if c["id"].startswith("em")}),
            "formats": {"dat": "LE RE4 DAT pack (count, 12 pad, offsets, 4-char exts)",
                        "bin": "PS2 mesh, 0x30-byte header, VIF/GIF packets (undecoded)",
                        "tpl": "PS2 TPL, 0x1000 tag, count at +4 (undecoded)",
                        "rel": "SNR2 relocatable R5900 module", "snd": "UDAS sound bank"},
        }
    finally:
        f.close()


def read_char_dat(path, cid: str) -> bytes:
    """Read the `xxNN.dat` model pack for a character id (e.g. 'pl00') from the owned disc/cso."""
    from .romexport import iso_files
    f = open_source(path)
    try:
        files = iso_files(f)
        _r, lba, size = files["DATA/BIO4DAT.AFS"]
        base = lba * 2048
        f.seek(base)
        n = struct.unpack_from("<I", f.read(8), 4)[0]
        f.seek(base)
        ent, (doff, dsize) = afs_table(f.read(16 + 8 * n))
        f.seek(base + doff)
        names = afs_names(f.read(dsize), n)
        want = f"{cid.lower()}.dat"
        for i, (nm, (off, sz)) in enumerate(zip(names, ent)):
            if nm.lower() == want and sz:
                f.seek(base + off)
                return f.read(sz)
        raise FileNotFoundError(f"{want} not found in DATA/BIO4DAT.AFS")
    finally:
        f.close()


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
