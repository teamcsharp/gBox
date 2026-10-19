"""Devil May Cry (USA) SLUS_202.16 (PS2) ISO-9660 inventory (#1856).

Read-only.  Owned source is a CHD v5 (gBox native reader is v4-only), so the
authoritative raw image is produced with ``chdman extractcd`` from:

    /mnt/gbox/hyperspin/Arcade/collections/Sony Playstation 2/roms/USA/Devil May Cry (USA).chd
    sha256 = 1e6d865218bfb4abf1f6e35cbcc244fbd4fcc68aef558ae2403e3d4944693a60

Extracted raw image (4,698,767,360 B, 2,294,320 MODE1/2048 sectors):
    dmc1_usa.bin sha256 = 9e4d87fa0bae06e7282c085bb58693f83cf857bede9803f4bd235e3dfcfe0726

Disc layout (verified against the raw bytes):
    SYSTEM.CNF        -> BOOT2 = cdrom0:\SLUS_202.16;1 / VER = 1.10 / VMODE = NTSC
    SLUS_202.16       ELF32 little-endian MIPS (32-bit PS2 EE), sha256
                       ac1a1e72845f04e6683d8ecd9e223f5297200bf2133709d5391925ad98e7be68
    DATA/EMD          178 files (enemy/player models .EMD, TIM2 textures .TM2/.T32)
    DATA/PLD          80 files (player containers .PLD/.PWS/.PWD)
    DATA/ETC|FSD|MODULES|ADS|STATUS|STATUS_U  (609 further files)

Player container format (DIFFERENT from gbox.dmc3_mod's PAC/AFS layout -- the
fingerprint suggestion gbox.dmc3_mod does NOT apply to this build):
    u32 child_count, then child_count u32 offsets (relative to container start,
    first child at 48 = 4 + 4*count); a child runs to the next larger offset
    (or EOF).  PL00.PLD (Dante) and PL05.PLD have 11 children; PL01..PL04/PL06
    have child_count == 0 (packed/different header form -- unresolved).
    Children carry no PAC/MOD/TIM2/zlib magic; entropy 4.6-7.2 (child0 228 KB
    likely mesh, child6 1 MB likely texture bulk).  No standard magic => a
    native DMC1 reader is required; the .PLD layout above is the probe starting
    point.

Target slot for the eventual native replacement:
    DATA/PLD/PL00.PLD  (Dante default) LBA 1043291 size 1,547,616
    sha256 = 450f16f7d23e827ca8213d187e093e489c086e9c5bf497a0c943e252307378ea
    (PL05.PLD alt-costume: 6bdddd0666959d7d9abb47914b753df114642e7b48f4973db6f0bd0a85f62847;
     EM00.EMD first enemy model: 4cb173e7907b20f1345e28a1dc4285484528ab294983c5142d7b2395a1ee4d9f)

Usage:  python -m gbox.dmc1_iso <raw.bin> --out manifest.json
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

SECTOR = 2048
PVD_LBA = 16
ROOT_DIR_LBA = 261
DATA_DIR_LBA = 262
GROUP_LBAS = {
    "EMD": (264, 3498), "ETC": (266, 3882), "FSD": (268, 6318),
    "MODULES": (272, 818), "ADS": (273, 214), "PLD": (274, 1082),
    "STATUS": (275, 3192), "STATUS_U": (277, 840),
}
SOURCE_CHD_SHA256 = "1e6d865218bfb4abf1f6e35cbcc244fbd4fcc68aef558ae2403e3d4944693a60"
RAW_BIN_SHA256 = "9e4d87fa0bae06e7282c085bb58693f83cf857bede9803f4bd235e3dfcfe0726"
ELF_SHA256 = "ac1a1e72845f04e6683d8ecd9e223f5297200bf2133709d5391925ad98e7be68"
TARGET_PL00_SHA256 = "450f16f7d23e827ca8213d187e093e489c086e9c5bf497a0c943e252307378ea"


def walk_dir(f, lba: int, nbytes: int) -> list[tuple[str, int, bool, int]]:
    """ISO-9660 directory records at ``lba`` spanning ``nbytes``."""
    f.seek(lba * SECTOR)
    d = f.read(nbytes + 8192)
    i, files = 0, []
    while i + 34 <= len(d):
        ln = d[i]
        if ln == 0:
            nxt = (i // SECTOR + 1) * SECTOR
            if nxt <= i:
                break
            i = nxt
            continue
        if ln < 33:
            i += 1
            continue
        size = struct.unpack_from("<I", d, i + 10)[0]
        flags = d[i + 25]
        fnlen = d[i + 32]
        name = d[i + 33:i + 33 + fnlen].decode("latin1").split(";")[0]
        ext = struct.unpack_from("<I", d, i + 2)[0]
        if name not in ("\x00", "\x01", ".", ".."):
            files.append((name, size, bool(flags & 2), ext))
        i += ln
    return files


def parse_pld_children(f, lba: int, size: int) -> tuple[int, list[tuple[int, int]]]:
    """(child_count, [(offset, length)]) for a .PLD container header."""
    f.seek(lba * SECTOR)
    head = f.read(4 + 4 * 64)
    n = struct.unpack_from("<I", head, 0)[0]
    offs = list(struct.unpack_from(f"<{n}I", head, 4)) if n else []
    out = []
    for o in offs:
        nxts = [x for x in offs if x > o]
        out.append((o, (min(nxts) if nxts else size) - o))
    return n, out


def stream_sha256(f, lba: int, size: int) -> str:
    f.seek(lba * SECTOR)
    h = hashlib.sha256()
    rem = size
    while rem > 0:
        b = f.read(min(1 << 20, rem))
        if not b:
            break
        h.update(b)
        rem -= len(b)
    return h.hexdigest()


def inventory(iso: Path) -> dict:
    with open(iso, "rb") as f:
        groups = {}
        for g, (lba, sz) in GROUP_LBAS.items():
            groups[g] = [
                {"name": n, "size": s, "lba": e}
                for n, s, dr, e in walk_dir(f, lba, sz) if not dr
            ]
        pld = {n: (s, e) for n, s, dr, e in walk_dir(f, GROUP_LBAS["PLD"][0], GROUP_LBAS["PLD"][1]) if not dr}
        targets = {}
        for name, (size, lba) in pld.items():
            if name.startswith("PL0"):
                n, ch = parse_pld_children(f, lba, size)
                targets[name] = {"lba": lba, "size": size, "child_count": n, "children": ch}
        hashes = {}
        for nm in ("PL00.PLD", "PL05.PLD"):
            if nm in pld:
                s, e = pld[nm]
                hashes[nm] = stream_sha256(f, e, s)
        emd = {n: (s, e) for n, s, dr, e in walk_dir(f, GROUP_LBAS["EMD"][0], GROUP_LBAS["EMD"][1]) if not dr}
        if "EM00.EMD" in emd:
            s, e = emd["EM00.EMD"]
            hashes["EM00.EMD"] = stream_sha256(f, e, s)
    return {"groups": groups, "pld_targets": targets, "asset_sha256": hashes}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("iso")
    ap.add_argument("--out", default="dmc1_manifest.json")
    a = ap.parse_args(argv)
    m = inventory(Path(a.iso))
    Path(a.out).write_text(json.dumps(m, indent=1))
    print(f"wrote {a.out}: {sum(len(v) for v in m['groups'].values())} files")


if __name__ == "__main__":
    main()
