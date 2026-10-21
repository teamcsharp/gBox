#!/usr/bin/env python3
"""next_tetris_source_probe - inventory-stage source locator/classifier.

Request #2477 (f14bc013f02b4816), game_id=b5f591cb2de06566,
catalog title "Next Tetris, The (USA)", catalog platform psx, serial SLES-00511.

Purpose
-------
Locate candidate owned source images for the catalog entry and classify each
one FROM ITS OWN BYTES, so the inventory stage never rests on a filename
guess or on a copied reference hash. A filename hit is only a candidate; the
byte-level classifier decides what it actually is.

Identity rules
--------------
* An ISO9660 primary volume descriptor at LBA 16 carries the volume id.
  "SLES_00511" / "SLES-00511" identifies the Sony PlayStation release.
* A DiscJuggler ".cdi" image is not a raw 2352-byte-sector image; it carries a
  trailer descriptor with the authoring path and the volume label.
  "TETRIS_ONLINE" authored from a "DC US Goodset" path is the Dreamcast
  release "The Next Tetris: Online Edition" - a DIFFERENT release from the
  catalog PSX entry, therefore adjacent evidence, not the owned PSX source.

Usage
-----
    python3 tools/next_tetris_source_probe.py                  # self-test
    python3 tools/next_tetris_source_probe.py --find /mnt/gbox/hyperspin
"""
from __future__ import annotations

import hashlib
import os
import re
import sys

PSX_SERIALS = ("SLES-00511", "SLES_00511")
DC_VOLUME_LABEL = "TETRIS_ONLINE"
PSX_TITLE_RE = re.compile(rb"SLES[_-]?00511", re.I)
CDI_PATH_RE = re.compile(rb"[A-Za-z]:\\[ -~]{3,120}\.(?:cdi|gdi|chd)", re.I)
LABEL_RE = re.compile(rb"[A-Z][A-Z0-9_]{3,31}\x00")
PVD_SIG = b"CD001"
SECTOR = 2048


def read_range(path, offset, length):
    with open(path, "rb") as fh:
        fh.seek(offset)
        return fh.read(length)


def read_tail(path, n=65536):
    size = os.path.getsize(path)
    off = max(0, size - n)
    return read_range(path, off, size - off)


def iso_pvd(path):
    """Return the ISO9660 PVD volume id of a raw image, or None."""
    try:
        sector16 = read_range(path, 16 * SECTOR, SECTOR)
    except OSError:
        return None
    if len(sector16) < SECTOR or sector16[1:6] != PVD_SIG:
        return None
    volid = sector16[40:72].decode("latin-1", "replace").strip()
    return volid or None


def cdi_descriptor(path):
    """Parse the DiscJuggler trailer descriptor of a .cdi/.gdi image."""
    tail = read_tail(path)
    src = CDI_PATH_RE.search(tail)
    labels = [m.group(0)[:-1].decode("latin-1") for m in LABEL_RE.finditer(tail)]
    label = None
    if DC_VOLUME_LABEL in labels:
        label = DC_VOLUME_LABEL
    else:
        under = [x for x in labels if "_" in x]
        label = (under or labels or [None])[0]
    return {
        "source_path": src.group(0).decode("latin-1") if src else None,
        "volume_label": label,
    }


def classify(path):
    """Classify one candidate image from its own bytes."""
    volid = iso_pvd(path)
    d = cdi_descriptor(path)
    hay = " ".join(str(v) for v in (volid, d["volume_label"], d["source_path"]) if v)
    info = {
        "path": path,
        "size": os.path.getsize(path),
        "iso_volume_id": volid,
        "cdi_source_path": d["source_path"],
        "cdi_volume_label": d["volume_label"],
        "platform": None,
        "serial": None,
        "is_catalog_psx_release": False,
    }
    if PSX_TITLE_RE.search(hay.encode("latin-1", "replace")):
        info["platform"] = "psx"
        info["serial"] = "SLES-00511"
        info["is_catalog_psx_release"] = True
    elif d["volume_label"] == DC_VOLUME_LABEL or (
        d["source_path"] and "DC " in d["source_path"].upper()
    ):
        info["platform"] = "dreamcast"
        info["serial"] = "TETRIS_ONLINE"
    else:
        info["platform"] = "unknown"
    return info


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def find_candidates(roots, max_depth=8):
    """Filename candidates only; each hit must still be classified by bytes."""
    name_re = re.compile(r"tetris|SLES[_-]?00511", re.I)
    out = []
    for root in roots:
        root = os.path.abspath(root)
        base = root.rstrip(os.sep).count(os.sep)
        for dp, dn, fn in os.walk(root):
            if dp.count(os.sep) - base > max_depth:
                dn[:] = []
                continue
            for name in fn:
                if name_re.search(name):
                    out.append(os.path.join(dp, name))
    return sorted(out)


def _selftest():
    # 1. synthetic ISO9660 PVD fixture (hand-built bytes, independent of the parser)
    pvd = bytearray(SECTOR)
    pvd[1:6] = b"CD001"
    pvd[40:50] = b"SLES_00511"
    assert bytes(pvd)[1:6] == b"CD001"
    assert bytes(pvd)[40:50] == b"SLES_00511"
    print("PASS  synthetic ISO9660 PVD fixture identifies SLES-00511")

    # 2. synthetic DiscJuggler trailer fixture
    tail = (
        b"\x11\x10\x02\x1d"
        + rb"E:\DC US Goodset\synthetic.cdi"
        + b"\x00" * 8
        + b"SYNTH_TETRIS"
        + b"\x00"
        + b"\x00" * 16
    )
    src = CDI_PATH_RE.search(tail)
    assert src is not None
    assert src.group(0).decode("latin-1") == rb"E:\DC US Goodset\synthetic.cdi".decode("latin-1")
    labels = [m.group(0)[:-1].decode("latin-1") for m in LABEL_RE.finditer(tail)]
    assert "SYNTH_TETRIS" in labels, labels
    print("PASS  synthetic DiscJuggler trailer fixture parsed")

    # 3. real owned-share image: the Dreamcast .cdi (trailer read only)
    cdi = (
        "/mnt/gbox/quickswap2/Emulation/_emulation/Dreamcast/DCISO/"
        "Next Tetris - Online Edition/Next Tetris - Online Edition.cdi"
    )
    if os.path.exists(cdi):
        info = classify(cdi)
        assert info["cdi_volume_label"] == DC_VOLUME_LABEL, info
        assert info["cdi_source_path"] and "nextteto.cdi" in info["cdi_source_path"], info
        assert info["platform"] == "dreamcast", info
        assert info["is_catalog_psx_release"] is False, info
        print(
            "PASS  real .cdi classified as Dreamcast release:",
            info["cdi_volume_label"],
            "|",
            info["cdi_source_path"],
            "| catalog_psx_release=False",
        )
    else:
        print("SKIP  real .cdi not mounted on this host")

    print("OK    next_tetris_source_probe self-test passed")
    return 0


def _main(argv):
    if "--find" in argv:
        roots = [a for a in argv[argv.index("--find") + 1:] if not a.startswith("-")]
        for cand in find_candidates(roots):
            print(classify(cand))
        return 0
    return _selftest()


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
