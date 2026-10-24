"""Metal Gear Solid 2: Sons of Liberty (USA, PS2 SLUS-201.44): the OWNED build's disc identity, file
manifest and STAGE archive, read off the operator's own disc.

The operator owns one MGS2 disc in this collection:

    collections/Sony Playstation 2/roms/USA/Metal Gear Solid 2 - Sons of Liberty (USA).iso
    (/mnt/gbox/quickswap2/Emulation/_emulation/PS2 ISOs/iso/Metal Gear Solid 2 - Sons of Liberty (USA).iso)

Everything below was measured on that disc; no other build's numbers were copied:

* **ISO 9660, single layer** (the DVD is NOT layered like the Substance release): one volume of 2,256,304
  sectors of 2048 bytes (4,620,910,592 bytes), 11 files, no second layer (``layer1_start`` is None).
* **SYSTEM.CNF** -> ``BOOT2 = cdrom0:\\SLUS_201.44;1``, ``VER = 1.01``, ``VMODE = NTSC``.
* **SLUS_201.44** is the PS2 ELF (841,648 bytes, little-endian MIPS, entry 0x100010; two program headers, LOAD delta +0xfff80, so virtual address = file offset + 0xfff80). Its data section names the container family and the loader's own format string: ``cdrom0:\\MGS2\\%s;1`` over ``stage.dat``, ``demo.dat``, ``vox.dat``, ``movie.dat``, ``face.dat``, ``codec.dat``, beside ``STGDEC`` (the stage decoder tag), ``SLUS-20144`` and ``cdrom0:\\SLUS_201.44;1``. Every measured offset/address pair is in :data:`ELF_STRINGS`.
* **MGS2/STAGE.DAT** (624,904,192 bytes) is the same encrypted archive format as the Substance release:
  sector 0 holds a clear ``u32 key`` (0x3bb323d9) followed by a 12-byte header and one 12-byte row per
  stage, encrypted with the word stream cipher. The key and the cipher constants were *verified on this
  disc*: the TOC decrypts to 115 stage names (init, select, n_title, museum, ending, wmovie, webdemo,
  r_tnk0, r_plt0, w00a ...), a stage header decrypts to a row table, and page 0 of the ``init`` stage
  inflates to 1,021,952 bytes.
* **the .DAT payloads tile the image back to back**: DEMO.DAT -> MOVIE.DAT -> STAGE.DAT -> CODEC.DAT ->
  FACE.DAT -> VOX.DAT are contiguous in sector terms, so a reader may take the recorded (sector, size)
  pairs directly instead of walking the directory again (the walk costs ~115 s on this node).

Every hash here was computed by streaming the owned file's own bytes. ``gbox.mgs2_inventory`` (the
Substance reader) is reused only for the format primitives it already proved out - the ISO walk, the word
stream cipher and the page decoder - after those constants were checked against this disc.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path

try:                                    # package import
    from . import mgs2_inventory as inv
except ImportError:                     # direct script run
    import mgs2_inventory as inv         # type: ignore

GAME_ID = "3fc2fad561187055"
GAME_IDS = {GAME_ID: "Metal Gear Solid 2 - Sons of Liberty (USA) - the PS2 DVD SLUS-201.44 "
                     "(owned ISO, single layer, 11 files)"}
TITLE = "Metal Gear Solid 2 - Sons of Liberty (USA)"
SERIAL = "SLUS-201.44"
ELF = "SLUS_201.44"
ELF_SIZE = 841648
ELF_SHA256 = "4a3e1042d9fbeaf3d0f7031d5be9e4ca364c3f1333bdd28ff7033ed16c4dcdd1"
ELF_ENTRY = 0x100010

#: the owned ELF's LOAD delta: virtual address = file offset + ELF_LOAD_DELTA
ELF_LOAD_DELTA = 0xFFF80
#: strings measured in the owned ELF's data section: label -> (file offset, virtual address, literal)
ELF_STRINGS: dict[str, tuple[int, int, str]] = {
    "stage_dat": (0xAFB18, 0x1AFA98, "stage.dat"),
    "demo_dat": (0xAFAD0, 0x1AFA50, "demo.dat"),
    "vox_dat": (0xAFAE0, 0x1AFA60, "vox.dat"),
    "movie_dat": (0xAFAE8, 0x1AFA68, "movie.dat"),
    "face_dat": (0xAFAF8, 0x1AFA78, "face.dat"),
    "codec_dat": (0xAFB08, 0x1AFA88, "codec.dat"),
    "loader_container": (0xAFB98, 0x1AFB18, "cdrom0:\\MGS2\\%s;1"),
    "stage_decoder_tag": (0xAFBD8, 0x1AFB58, "STGDEC"),
    "self_serial": (0xAFB40, 0x1AFAC0, "SLUS-20144"),
    "elf_path": (0xAFE78, 0x1AFDF8, "cdrom0:\\SLUS_201.44;1"),
    "hdd_save": (0xAFB28, 0x1AFAA8, "hdd0:PP.%s.%08X.MGS2HD"),
    "pfs_path": (0xAFBB0, 0x1AFB30, "pfs0:/mgs2/%s"),
}
ISO_SHA256 = "7ba4ca4d06baaafe0d50fa60efcacfded6d2cb03b701c6def68ff24b978ca2f1"
ISO_SIZE = 4620910592
TOTAL_SECTORS = 2256304
LAYER0_SECTORS = 2256304
SECTOR = 2048
STAGE_FILES = ("MGS2/STAGE.DAT",)
VER = "1.01"
VMODE = "NTSC"

#: the owned disc's file map, read from the ISO 9660 tree: name -> (absolute sector, size in bytes)
MANIFEST: dict[str, tuple[int, int]] = {
    "SYSTEM.CNF": (283, 54),
    "SLUS_201.44": (284, 841648),
    "MODULES/IOPRP23.IMG": (695, 230329),
    "MODULES/MODULE.IPK": (808, 361392),
    "MODULES/PLD.IRX": (985, 1665),
    "MGS2/DEMO.DAT": (986, 1798514688),
    "MGS2/MOVIE.DAT": (879167, 913788928),
    "MGS2/STAGE.DAT": (1325353, 624904192),
    "MGS2/CODEC.DAT": (1630482, 24233248),
    "MGS2/FACE.DAT": (1642315, 30998528),
    "MGS2/VOX.DAT": (1657451, 1226426368),
}

#: the files that really do tile the image back to back (checked by :func:`verify_manifest`)
CONTIGUOUS = ("SYSTEM.CNF", "SLUS_201.44", "MODULES/IOPRP23.IMG", "MODULES/MODULE.IPK",
              "MODULES/PLD.IRX", "MGS2/DEMO.DAT")

#: MGS2/STAGE.DAT's clear key and the TOC header it decrypts to (read off the owned disc)
STAGE_KEY = 0x3BB323D9
STAGE_COUNT = 115
STAGE_TOC_SECTORS = 1
STAGE_TOC_HEADER_PLAIN = "010001007300104079860800"
#: the first TOC rows of the owned disc: (stage name, sector offset inside STAGE.DAT)
STAGE_TOC_HEAD = (("init", 1), ("select", 210), ("n_title", 448), ("museum", 1484),
                  ("ending", 1501), ("wmovie", 1813), ("webdemo", 2198), ("r_tnk0", 2533),
                  ("r_plt0", 3883), ("w00a", 5827), ("w00b", 8440), ("w00c", 11265), ("d00t", 14415))
#: the 'init' stage header decrypts to this (row count 10, first row the 0x7f page marker)
STAGE_INIT_HEADER_PLAIN = "0a0000000000017f00980f003849067e"
#: page 0 of the 'init' stage: decompressed / stored size, and the hash of the inflated block
PAGE0_DSIZE = 1021952
PAGE0_CSIZE = 411960
PAGE0_SHA256 = "ac3607a463eb7e8884d958cb38e17752f9d2e0e8a8f3ec1535a2c0f0fd4a54b9"


def source_path() -> Path:
    """The owned ISO in the operator's PS2 collection."""
    return Path("/mnt/gbox/quickswap2/Emulation/_emulation/PS2 ISOs/iso/"
                "Metal Gear Solid 2 - Sons of Liberty (USA).iso")


def _sectors(size: int) -> int:
    return -(-size // SECTOR)


def _end(name: str) -> int:
    lba, size = MANIFEST[name]
    return lba + _sectors(size)


def verify_manifest() -> list[str]:
    """Internal consistency of the recorded map. Returns a list of problems (empty = sound)."""
    problems: list[str] = []
    for i in range(len(CONTIGUOUS) - 1):
        a, na = MANIFEST[CONTIGUOUS[i]]
        b, _nb = MANIFEST[CONTIGUOUS[i + 1]]
        if a + _sectors(na) != b:
            problems.append(f"{CONTIGUOUS[i]} ends at sector {a + _sectors(na)}, "
                            f"but {CONTIGUOUS[i + 1]} starts at {b}")
    for name, (lba, size) in MANIFEST.items():
        if lba + _sectors(size) > TOTAL_SECTORS:
            problems.append(f"{name} needs sectors {lba}..{lba + _sectors(size)}, "
                            f"past the end of the image ({TOTAL_SECTORS})")
    return problems


def payload_overlaps() -> list[tuple[str, str, int]]:
    """Payload pairs whose recorded extents overlap: (earlier, later, overlap in sectors)."""
    out: list[tuple[str, str, int]] = []
    names = sorted(MANIFEST, key=lambda n: MANIFEST[n][0])
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            la, sa = MANIFEST[a]
            lb, sb = MANIFEST[b]
            lo, hi = max(la, lb), min(la + _sectors(sa), lb + _sectors(sb))
            if hi > lo:
                out.append((a, b, hi - lo))
    return out


def manifest() -> list[dict]:
    """The owned build's file map as reviewable rows."""
    rows = []
    for name, (lba, size) in sorted(MANIFEST.items()):
        rows.append({"path": name, "sector": lba, "size": size,
                     "sectors": _sectors(size), "end_sector": lba + _sectors(size)})
    return rows


def identify(disc) -> dict:
    """Read the disc's own identity and compare it with the recorded owned-build identity."""
    cnf = inv.system_cnf(disc)
    boot = re.sub(r"^cdrom0:\\?", "", cnf.get("BOOT2", "")).split(";")[0].upper()
    elf = disc.read(boot) if boot in disc.files else b""
    out = {"game_id": GAME_ID, "title": TITLE, "serial": SERIAL, "platform": "ps2",
           "boot": boot, "version": cnf.get("VER"), "vmode": cnf.get("VMODE"),
           "elf_size": len(elf),
           "elf_sha256": hashlib.sha256(elf).hexdigest() if elf else None,
           "elf_expected_sha256": ELF_SHA256,
           "elf_entry": hex(struct.unpack_from("<I", elf, 0x18)[0]) if elf else None,
           "sectors": disc.sectors_total, "layer0_sectors": disc.layer0,
           "layer1_start": disc.layer1_start, "single_layer": disc.layer1_start is None,
           "n_files": len(disc.files),
           "stage_files": {n: disc.files.get(n) for n in STAGE_FILES},
           "manifest_problems": verify_manifest(),
           "payload_overlaps": payload_overlaps()}
    out["exact_build"] = bool(boot == ELF and out["elf_sha256"] == ELF_SHA256
                               and "MGS2/STAGE.DAT" in disc.files)
    return out


def stage_toc(disc, name: str = "MGS2/STAGE.DAT") -> list[tuple[str, int]]:
    """The archive's stage table, decrypted with this build's key."""
    lba, _size = disc.files[name.upper()]
    head = disc.sectors(lba, 1)
    key = struct.unpack_from("<I", head, 0)[0]
    c = inv.Cipher.for_toc(key)
    h = c.run(head[4:16])
    toc_sectors, count = struct.unpack_from("<hh", h, 2)
    if not 0 < count < 4096 or toc_sectors <= 0:
        raise inv.FormatError(f"{name}: TOC header does not decrypt ({count} stages)")
    need = 16 + 12 * count
    buf = disc.sectors(lba, (need + SECTOR - 1) // SECTOR)
    rows = c.run(buf[16:need])
    out = []
    for i in range(count):
        r = rows[12 * i:12 * i + 12]
        out.append((r[:8].split(b"\0")[0].decode("latin-1"), struct.unpack_from("<I", r, 8)[0]))
    return out


KMS_TYPE = 0x0A          # model, as the stage file tables of this build label it
TEXPACK_TYPE = 0x13      # texture pack


def probe_stage(disc, name: str = "r_tnk0", stage_key: int = STAGE_KEY) -> dict:
    """Format probe on the OWNED build: pull one kms model and one texture pack out of a named stage and prove
    that decode -> encode_page -> decode and a whole-stage no-op rebuild_stage both reproduce the plain pages.
    Reads only; nothing is written to the disc."""
    import hashlib
    arch = inv.StageArchive(disc)
    if arch.key != stage_key:
        raise inv.FormatError(f"STAGE key {arch.key:#x} != {stage_key:#x}")
    st = arch.stage(name)
    kms = tex = None
    for k, p in enumerate(st.pages):
        for f in p.files:
            if f[0] == KMS_TYPE and kms is None:
                kms = (k, f)
            if f[0] == TEXPACK_TYPE and tex is None:
                tex = (k, f)
    if kms is None or tex is None:
        raise inv.FormatError(f"{name}: no kms/texture pack")
    plain = {k: arch.page(st, k) for k in range(len(st.pages))}
    old_raw = {k: arch.page_raw(st, k) for k in range(len(st.pages))}
    k, f = kms
    model = plain[k][f[2]:f[2] + f[3]]
    k2, g = tex
    pack = plain[k2][g[2]:g[2] + g[3]]
    # page-level no-op: re-encode the plain page and decode it again
    page_rt = all(inv.decode_page(inv.encode_page(plain[i], struct.unpack_from("<H", old_raw[i], 0)[0]),
                                  len(plain[i])) == plain[i] for i in plain)
    # stage-level no-op: every page re-encoded unchanged, header re-encrypted
    rebuilt = inv.rebuild_stage(st, stage_key, dict(plain), old_raw)
    head_plain = inv.Cipher.for_stage(stage_key, name).run(rebuilt[:st.header_bytes + (-st.header_bytes % SECTOR)])
    n = struct.unpack_from("<I", head_plain, 0)[0]
    rows2 = [struct.unpack_from("<2I", head_plain, 4 + 8 * i) for i in range(n)]
    stage_rt = (n == len(st.rows) and len(rebuilt) == st.sectors * SECTOR)
    pages_eq = True
    base = st.data_sector * SECTOR
    for i, p in enumerate(st.pages):
        w, off = rows2[p.rows[1]]
        csize = w & 0xFFFFFF
        raw = rebuilt[base + off:base + off + csize]
        pages_eq = pages_eq and inv.decode_page(raw, len(plain[i])) == plain[i]
    return {
        "stage": name, "pages": len(st.pages), "span_sectors": st.sectors, "rows": len(st.rows),
        "kms": {"page": kms[0], "hash": f"{f[1]:#x}", "offset": f[2], "size": f[3],
                "sha256": hashlib.sha256(model).hexdigest(), "magic": model[:4].hex()},
        "texpack": {"page": tex[0], "hash": f"{g[1]:#x}", "offset": g[2], "size": g[3],
                    "sha256": hashlib.sha256(pack).hexdigest(), "magic": pack[:4].hex()},
        "page_roundtrip": bool(page_rt), "stage_rebuild_fits_span": bool(stage_rt),
        "rebuilt_pages_decode_equal": pages_eq,
        "rebuilt_sha256": hashlib.sha256(rebuilt).hexdigest(),
    }


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="MGS2 Sons of Liberty (owned SLUS-201.44) inventory")
    ap.add_argument("iso", nargs="?", default=str(source_path()))
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    d = inv.Disc(a.iso)
    out = {"identify": identify(d), "manifest": manifest(), "manifest_problems": verify_manifest()}
    try:
        out["stage_toc"] = stage_toc(d)
    except Exception as e:                       # the TOC is build specific; report, never fake it
        out["stage_toc_error"] = repr(e)
    d.close()
    text = json.dumps(out, indent=1)
    if a.json:
        Path(a.json).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
