"""GTA III (PS2) exact-build inventory (#1405, stage 1).

Reads the owned image streamed from its .7z (no full unpack: the ISO9660 tree, SYSTEM.CNF,
SLUS_200.62, MODELS/GTA3.DIR, ANIM/PED.IFP and the four player IMG entries are captured in
stream order while the whole image is hashed) or from a plain .iso, verifies it is the known
owned build, and writes the authoritative inventory manifest plus the small extracted files.

Lineage: the streaming reader and the 32-byte DIR layout match gbox.gta3_chars.stream_entries
(#1309 branch) and gbox.gta_rw.dir_read; this module is stdlib-only so stage-1 evidence does
not depend on the RenderWare reader.

Layout facts (ISO9660 record walk: PVD at sector 16, "CD001"; root dir record at PVD+156;
records are <len, ext_lba(+2 LE), size(+10 LE), flags(+25), namelen(+32), name(+33)> padded
to even. DIR entries are <uint32 offset_sectors, uint32 size_sectors, char[24] name>.)
"""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

SECTOR = 2048

SOURCE_7Z_SHA256 = "98d17cb759d5a4c09d9e596ed6fc602c64ef9a79e881af4a51aa2f2e59d4550c"
ISO_SHA256 = "707714a290e8a6b700fb424dc437ffe0ee580181243ad6fa56b2c025bdca9e68"
ISO_BYTES = 4640997376
BUILD = "Grand Theft Auto III (USA, Canada), SLUS-20062"

# Sector-padded GTA3.IMG entry hashes of the vanilla player ped (model 0, special skins
# 'player' / 'playerp'), as recorded from the unpacked vanilla image (Oct 11 manifest and the
# collection entries' meta.json). These pin the exact build before any modding.
STOCK_SHA256 = {
    "player.dff": "922b2758090d55e4095d27c69825d619211f5b200e5d015c417ecad800e968a1",
    "player.txd": "2a7cc19ba52cd969832c6aede7151d42f664ebb064cfa0410a508cedd4c29872",
    "playerp.dff": "aabbd81e865f96822d7bdabcaed85876f5b3a0cefe312eb0f0a7b79f74e3a544",
    "playerp.txd": "3cd4467d852994111facd46736fbad51758a69297d23878c1623a369ce8016ef",
}
PED_IFP_SHA256 = "c3d8f689eb52ad041a42e74ee788c60003c3eb8b5fd0604c5df7030124a1bc64"

IMG = "MODELS/GTA3.IMG"
DIR = "MODELS/GTA3.DIR"
PLAYER_ENTRIES = ("player.dff", "player.txd", "playerp.dff", "playerp.txd")
ISO_FILES = ("SYSTEM.CNF", "SLUS_200.62", DIR, "ANIM/PED.IFP")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------------------------------ streamed disc
def iso_chunks(rom: Path, size: int = 1 << 24):
    """Yield the 2048-byte-sector image of a .7z/.zip (its .iso member, streamed by 7-Zip) or of a plain .iso."""
    rom = Path(rom)
    if rom.suffix.lower() in (".7z", ".zip"):
        lst = subprocess.run(["7z", "l", "-slt", str(rom)], capture_output=True, text=True, timeout=900)
        members = [ln[7:] for ln in lst.stdout.splitlines() if ln.startswith("Path = ") and ln.lower().endswith(".iso")]
        if lst.returncode or not members:
            raise ValueError(f"{rom.name}: no .iso member ({(lst.stdout + lst.stderr)[-300:]})")
        p = subprocess.Popen(["7z", "x", "-so", str(rom), members[0]], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL)
        assert p.stdout is not None
        try:
            while True:
                b = p.stdout.read(size)
                if not b:
                    break
                yield b
        finally:
            p.stdout.close()
            if p.poll() is None:
                p.kill()
            p.wait()
    else:
        with open(rom, "rb") as f:
            while b := f.read(size):
                yield b


# ------------------------------------------------------------------------------------------ ISO9660 walk
def dir_records(buf: bytes, pre: str):
    """Directory records: yield (PATH, lba, size, is_dir) with UPPERCASE `;1`-stripped names."""
    o = 0
    while o < len(buf):
        ln = buf[o]
        if ln == 0:
            o = (o // SECTOR + 1) * SECTOR
            continue
        if o >= SECTOR and not any(buf[o - o % SECTOR:]):
            break
        lba, size = struct.unpack_from("<I", buf, o + 2)[0], struct.unpack_from("<I", buf, o + 10)[0]
        nm = buf[o + 33:o + 33 + buf[o + 32]]
        if nm not in (b"\0", b"\1"):
            yield pre + nm.decode("ascii", "replace").split(";")[0].upper(), lba, size, bool(buf[o + 25] & 2)
        o += ln


def walk_tree(rom: Path):
    """Pass 1: hash the whole image and map the ISO9660 tree -> {PATH: (lba, size)}, (sha256, nbytes)."""
    want: dict[str, tuple[int, int]] = {"pvd": (16 * SECTOR, SECTOR)}
    files: dict[str, tuple[int, int]] = {}
    dirs: dict[str, tuple[int, int]] = {}
    got: dict[str, bytes] = {}

    def follow(key: str, data: bytes):
        if key == "pvd":
            if data[1:6] != b"CD001":
                raise ValueError("not an ISO9660 image (no CD001 at sector 16)")
            lba = struct.unpack_from("<I", data, 158)[0]
            size = struct.unpack_from("<I", data, 166)[0]
            dirs[""] = (lba, size)
            return [("dir:", (lba * SECTOR, size))]
        for path, lba, size, isdir in dir_records(data, key[4:]):
            if isdir:
                dirs[path + "/"] = (lba, size)
            else:
                files[path] = (lba, size)
        return [(f"dir:{p}", (lba * SECTOR, size)) for p, (lba, size) in dirs.items()
                if f"dir:{p}" not in want and f"dir:{p}" not in got]

    bufs: dict[str, list] = {}
    pos = 0
    h = hashlib.sha256()

    def arm(key, at):
        a, n = want[key]
        if a >= at:
            bufs[key] = [a, n, bytearray()]
            return True
        return False

    arm("pvd", 0)
    for chunk in iso_chunks(rom):
        end = pos + len(chunk)
        h.update(chunk)
        busy = True
        while busy:
            busy = False
            for k in list(bufs):
                a, n, b = bufs[k]
                lo, hi = max(a + len(b), pos), min(a + n, end)
                if lo < hi:
                    b += chunk[lo - pos:hi - pos]
                if len(b) == n:
                    got[k] = bytes(b)
                    del bufs[k]
                    for k2, (a2, n2) in follow(k, got[k]):
                        want[k2] = (a2, n2)
                        if arm(k2, pos):
                            busy = True
        pos = end
    missing = [k for k in want if k not in got]
    if missing:
        raise RuntimeError(f"tree walk missed: {missing}")
    return files, (h.hexdigest(), pos)


def capture(rom: Path, want: dict[str, tuple[int, int]]):
    """Pass 2: read the wanted (offset, size) regions in stream order -> {key: bytes}."""
    order = sorted(want.items(), key=lambda kv: kv[1][0])
    got, bufs = {}, {}
    pos = 0
    for key, (a, n) in order:
        bufs[key] = [a, n, bytearray()]
    for chunk in iso_chunks(rom):
        end = pos + len(chunk)
        for k in list(bufs):
            a, n, b = bufs[k]
            lo, hi = max(a + len(b), pos), min(a + n, end)
            if lo < hi:
                b += chunk[lo - pos:hi - pos]
            if len(b) == n:
                got[k] = bytes(b)
                del bufs[k]
        pos = end
        if not bufs:
            break
    missing = [k for k in bufs]
    if missing:
        raise RuntimeError(f"capture missed: {missing}")
    return got


# ------------------------------------------------------------------------------------------ container parsers
def dir_stats(d: bytes) -> dict:
    """MODELS/GTA3.DIR: one <uint32 offset_sectors, uint32 size_sectors, char[24] name> per entry."""
    ents = []
    for i in range(0, len(d), 32):
        o, s = struct.unpack_from("<II", d, i)
        name = d[i + 8:i + 32].split(b"\0")[0].decode("ascii", "replace")
        if not name and not o and not s and not any(d[i + 32:]):
            break  # trailing all-zero tail, not an entry
        ents.append({"offset_sectors": o, "sectors": s, "name": name})
    by_ext: dict[str, int] = {}
    for e in ents:
        ext = e["name"].rsplit(".", 1)[-1].lower() if "." in e["name"] else "(none)"
        by_ext[ext] = by_ext.get(ext, 0) + 1
    return {"count": len(ents), "by_extension": dict(sorted(by_ext.items())), "entries": ents}


def elf_info(b: bytes) -> dict:
    """PS2 ELF header facts for SLUS_200.62 (e_machine 8 = MIPS R5900)."""
    if len(b) < 52 or b[:4] != b"\x7fELF":
        raise ValueError("not an ELF image")
    e_machine, = struct.unpack_from("<H", b, 18)
    entry, = struct.unpack_from("<I", b, 24)
    return {"magic": "\\x7fELF", "class": 32 if b[4] == 1 else 64, "data": "LSB" if b[5] == 1 else "MSB",
            "e_machine": e_machine, "entry": hex(entry), "bytes": len(b)}


# ------------------------------------------------------------------------------------------ inventory
def inventory(rom: Path, out_dir: Path | None = None) -> dict:
    """Stream the owned image, verify the exact build, and return the inventory manifest.

    Raises ValueError on any identity mismatch (wrong source or non-vanilla disc)."""
    rom = Path(rom)
    files, (iso_sha, iso_bytes) = walk_tree(rom)
    if iso_sha != ISO_SHA256:
        raise ValueError(f"{rom.name}: sha256 {iso_sha} is not the owned GTA III PS2 build ({ISO_SHA256[:12]}...)")

    missing = [f for f in ISO_FILES if f not in files]
    if missing:
        raise ValueError(f"disc layout differs from the known build, missing: {missing}")
    copies = sorted([f for f in files if f.startswith("MODELS/GTA3") and f.endswith(".IMG")],
                    key=lambda f: (files[f][0], f))
    if IMG not in copies:
        raise ValueError("MODELS/GTA3.IMG missing from the disc tree")

    want = {f: (files[f][0] * SECTOR, files[f][1]) for f in ISO_FILES}
    got = capture(rom, want)

    dir_b = got[DIR]
    stats = dir_stats(dir_b)
    idx = {e["name"].lower(): e for e in stats["entries"]}

    img_lba = files[IMG][0]
    entries: dict[str, dict] = {}
    for n in PLAYER_ENTRIES:
        if n not in idx:
            raise KeyError(f"{n} not in {DIR}")
        e = idx[n]
        entries[n] = {"offset_sectors": e["offset_sectors"], "sectors": e["sectors"],
                      "lba": img_lba + e["offset_sectors"], "img": IMG, "copies": len(copies)}

    want2 = {f"entry:{n}": (entries[n]["lba"] * SECTOR, entries[n]["sectors"] * SECTOR) for n in PLAYER_ENTRIES}
    got2 = capture(rom, want2)
    for n in PLAYER_ENTRIES:
        h = _sha(got2[f"entry:{n}"])
        entries[n]["sha256"] = h
        if h != STOCK_SHA256[n]:
            raise ValueError(f"{n}: hash {h} does not match the vanilla build (a modded image?)")

    cnf = got["SYSTEM.CNF"].decode("ascii", "replace")
    slus = got["SLUS_200.62"]
    ped_ifp = got["ANIM/PED.IFP"]
    ped_sha = _sha(ped_ifp)
    if ped_sha != PED_IFP_SHA256:
        raise ValueError(f"ANIM/PED.IFP: hash {ped_sha} does not match the vanilla build")

    manifest = {
        "game_id": "265819390074bb4e",
        "title": "Grand Theft Auto III",
        "platform": "ps2",
        "build": BUILD,
        "source": {"7z_sha256": SOURCE_7Z_SHA256, "iso_sha256": iso_sha, "iso_bytes": iso_bytes},
        "launch": {"core": "pcsx2", "system_cnf": cnf.splitlines(), "boot": "cdrom0:\\SLUS_200.62;1",
                   "status": "launches (retroarch)"},
        "executable": {"path": "SLUS_200.62", "sha256": _sha(slus), **elf_info(slus)},
        "container": {
            "iso_files": {f: {"lba": files[f][0], "bytes": files[f][1]} for f in ISO_FILES},
            "img_copies": {f: {"lba": files[f][0], "bytes": files[f][1]} for f in copies},
            "dir": {"path": DIR, "sha256": _sha(dir_b), "bytes": len(dir_b), "entries": stats["count"],
                    "by_extension": stats["by_extension"]},
            "player_entries": entries,
            "animation": {"path": "ANIM/PED.IFP", "sha256": ped_sha, "bytes": len(ped_ifp), "animations": 207},
        },
        "characters": {
            "player": "Claude (model 0, special skin 'player'): 17 frames, 1550 tris, playa5nu 256x256 8-bit",
            "playerp": "Claude prison outfit (special skin 'playerp'): 17 frames, 1362 tris, playa_prison 256x256 8-bit",
            "reader": "gbox.gta3_chars (PR #1309 branch, not yet on main)",
            "collection": "gta3_claude, gta3_claude_prison (stored with rig + native hashes)",
        },
    }
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        names = {"SLUS_200.62": slus, "SYSTEM.CNF": got["SYSTEM.CNF"], "GTA3.DIR": dir_b, "PED.IFP": ped_ifp}
        for n, data in names.items():
            (out_dir / n).write_bytes(data)
        for n in PLAYER_ENTRIES:
            (out_dir / n).write_bytes(got2[f"entry:{n}"])
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
        manifest["out_dir"] = str(out_dir)
    return manifest


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="GTA III PS2 exact-build inventory")
    ap.add_argument("rom", help="owned .7z/.zip (its .iso member) or a plain .iso")
    ap.add_argument("-o", "--out", default=None, help="write extracted evidence + manifest.json here")
    args = ap.parse_args(argv)
    m = inventory(Path(args.rom), Path(args.out) if args.out else None)
    print(json.dumps(m, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
