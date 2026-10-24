"""Ready 2 Rumble Boxing Round 2 (Dreamcast, USA, GD-ROM) inventory reader.

Verified against the owned CHD (sha256 bd33199e...9a53), extracted with
``chdman extractcd`` to a 2352-byte/sector BIN. Facts established:

* CHD frame index == ISO9660 LBA (T3 starts at LBA 45000; PVD at 45016,
  root dir at 45020). Track 5 (high density) starts at LBA 72921.
* Files: 1ST_READ.BIN, 0GDTEX.PVR, AUDIO64.DRV, ZERO.DAT, MOVIES/*.SFD and
  BOXING.RAT (795 MB asset archive).
* BOXING.RAT ("RAT\0" "1.0A"): 32-byte header (count u32 at 8), then ``count``
  32-byte little-endian entries: name[16] (type+ext fused, e.g.
  ``BUTCHER2GMDLRII`` = BUTCHER2 + GMDL + RII), size, ts, ts, absolute offset.
  Entries tile the file exactly (last end == file size).

An archive listing is NOT a model reader; this only identifies containers.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Callable, Iterator

RAW_SECTOR = 2352
USER_OFFSET = 16
USER_SIZE = 2048
RAT_MAGIC = b"RAT\x001.0A"
RAT_HEADER = 32
RAT_ENTRY = 32
PVD_LBA = 45016


@dataclass(frozen=True)
class RatEntry:
    index: int
    name: str
    size: int
    offset: int


class RawDisc:
    """Mode1/2352 BIN where frame index == LBA."""

    def __init__(self, data):
        self.data = data

    def sector(self, lba: int) -> bytes:
        o = lba * RAW_SECTOR + USER_OFFSET
        return bytes(self.data[o:o + USER_SIZE])

    def read(self, lba: int, size: int, skip: int = 0) -> bytes:
        out = bytearray()
        pos = skip
        while pos < skip + size:
            s = self.sector(lba + pos // USER_SIZE)
            so = pos % USER_SIZE
            k = min(USER_SIZE - so, skip + size - pos)
            out += s[so:so + k]
            pos += k
        return bytes(out)


def _dir_records(disc: RawDisc, lba: int, size: int):
    data = disc.read(lba, size)
    i = 0
    while i < len(data):
        n = data[i]
        if n == 0:
            i = (i // USER_SIZE + 1) * USER_SIZE
            continue
        e = data[i:i + n]
        yield (e[33:33 + e[32]].decode("latin1"),
               struct.unpack("<I", e[2:6])[0],
               struct.unpack("<I", e[10:14])[0],
               bool(e[25] & 2))
        i += n


def walk_iso(disc: RawDisc, pvd_lba: int = PVD_LBA) -> list[tuple[str, int, int]]:
    """Return [(path, lba, size)] for every file below the root."""
    pvd = disc.sector(pvd_lba)
    if pvd[1:6] != b"CD001":
        raise ValueError("no ISO9660 PVD at LBA %d" % pvd_lba)
    root = pvd[156:190]
    out: list[tuple[str, int, int]] = []

    def rec(lba, size, prefix):
        for nm, l, s, d in _dir_records(disc, lba, size):
            if nm in ("\x00", "\x01"):
                continue
            if d:
                rec(l, s, prefix + nm + "/")
            else:
                out.append((prefix + nm.split(";")[0], l, s))

    rec(struct.unpack("<I", root[2:6])[0], struct.unpack("<I", root[10:14])[0], "")
    return out


def parse_rat_table(read_at: Callable[[int, int], bytes], file_size: int) -> list[RatEntry]:
    """Parse the BOXING.RAT table; validates magic and exact tiling."""
    hdr = read_at(0, RAT_HEADER)
    if hdr[:8] != RAT_MAGIC:
        raise ValueError("bad RAT magic %r" % hdr[:8])
    count = struct.unpack("<I", hdr[8:12])[0]
    tab = read_at(RAT_HEADER, count * RAT_ENTRY)
    ents = []
    for i in range(count):
        e = tab[i * RAT_ENTRY:(i + 1) * RAT_ENTRY]
        name = e[:16].split(b"\0")[0].decode("latin1")
        size, _t1, _t2, off = struct.unpack("<IIII", e[16:32])
        if off + size > file_size:
            raise ValueError("entry %d (%s) exceeds file" % (i, name))
        ents.append(RatEntry(i, name, size, off))
    return ents


_SPLIT = re.compile(r"^(?P<stem>.+?)(?P<kind>GMDL|WTEX|DTEX|DMMF|DSPR|DFX|DLTD|TEXT)(?P<ext>[A-Z]{3})$")


def classify(entry_name: str) -> tuple[str, str, str]:
    """Split a fused name into (stem, kind, ext); kind may be '' if unknown."""
    m = _SPLIT.match(entry_name)
    if m:
        return m["stem"], m["kind"], m["ext"]
    return entry_name, "", ""


def character_models(ents: list[RatEntry]) -> list[RatEntry]:
    """Per-costume model entries (kind GMDL, ext RII) - the replacement targets."""
    return [e for e in ents if classify(e.name)[1:] == ("GMDL", "RII")]


def parse_charlist(blob: bytes) -> list[str]:
    """Display names from CHARLISTCHLTRII (names are NUL-padded at 52-byte stride starts)."""
    names = []
    for m in re.finditer(rb"[A-Z][A-Za-z.' ]{2,31}\x00", blob):
        names.append(m.group(0)[:-1].decode("latin1"))
    return names
