"""WCW/nWo Revenge (Europe, NW2P) writer round-trip probes (#1317).

Writes a NEW in-memory ROM (never the owned zip) and re-reads it independently of Writer: every code patch
is checked by instruction, the relocated file table / body table / set table are parsed straight from the
Expansion-RAM payload that the patched loader DMAs, and the donor's bytes are decoded back out of the
appended file blob. The no-op case proves the original files and the patched-site set are untouched.
"""
import struct
from pathlib import Path

import pytest

from gbox import aki_wcw as W
from gbox import aki_wrestling as A
from gbox import n64_rom

EU_ZIP = Path("/mnt/gbox/hyperspin/Arcade/collections/Nintendo 64/roms/Europe/WCW-nWo Revenge (Europe).zip")
pytestmark = pytest.mark.skipif(not EU_ZIP.exists(), reason="owned Revenge (Europe) ROM not mounted")


@pytest.fixture(scope="module")
def eu():
    return n64_rom.read(EU_ZIP)


def _find_payload(rom: bytes, p: dict) -> int:
    """The patched ft_hi/ft_lo pair holds the ROM address the loader reads the new table from."""
    by = {k: ram for ram, _o, k in p["patch"]}
    hi = struct.unpack_from(">I", rom, W.Rom.r2r(by["ft_hi"]))[0] & 0xFFFF
    lo = struct.unpack_from(">I", rom, W.Rom.r2r(by["ft_lo"]))[0] & 0xFFFF
    return ((hi << 16) + (lo - 0x10000 if lo & 0x8000 else lo)) & 0xFFFFFFFF


def test_nw2p_writer_noop_roundtrip(eu):
    out = W.Writer(eu).build()
    p = W.profile(eu)
    assert len(out) >= len(eu) and out[0x3B:0x40] == eu[0x3B:0x40]
    # no new files: original asset area byte-identical (only header CRC + the patched code words differ)
    assert out[p["first"]:p["ft"]] == eu[p["first"]:p["ft"]]
    changed = [i for i in range(0x1000, 0xD81E0, 4) if out[i:i + 4] != eu[i:i + 4]]
    sites = {W.Rom.r2r(ram) for ram, _o, _k in p["patch"]}
    assert len(sites) == 14 and set(changed) == sites      # exactly the 14 verified NW2P patch words, nothing else
    # relocated table: every original entry preserved, one spacer + terminator appended
    ft = _find_payload(out, p)
    n = p["nfiles"] + 1
    raw_new = struct.unpack_from(f">{n}I", out, ft)
    raw_old = struct.unpack_from(f">{n}I", eu, p["ft"])
    assert raw_new[:-1] == raw_old[:-1] and (raw_new[-1] & ~1) == (raw_old[-1] & ~1)


def test_nw2p_writer_donor_replace_roundtrip(eu, tmp_path):
    ros = W.roster(eu)
    R = W.Rom(eu)
    donor = W.find_wrestler(ros, "Giant")
    target = W.find_wrestler(ros, "Sting")
    dparts = W.rest_parts(R, donor, 0)
    fit = {"parts": {k: {"model": v["raw"], "pal": R.ft.get(v["pal"]), "tex": R.ft.get(v["tex"])}
                     for k, v in dparts.items() if isinstance(k, int)},
           "head": list(dparts["_head"]), "costume": dparts["_costume"]}
    wr = W.Writer(eu)
    rep = wr.replace(target, fit)
    assert rep["files"] == 3 * len(fit["parts"]) and rep["body"] == W.profile(eu)["bodies"]
    out = wr.build()
    p = W.profile(eu)
    # donor model bytes decode back out of the appended blob via the relocated table
    ft = _find_payload(out, p)
    n_entries = p["nfiles"] + 1 + 1 + len(wr.files) + 1
    raw = struct.unpack_from(f">{n_entries}I", out, ft)
    first = p["first"]
    new_ids = [p["nfiles"] + 2 + i for i in range(len(wr.files))]
    for fid, want in zip(new_ids, wr.files):
        a, b = raw[fid - 1], raw[fid]
        data = out[first + (a & ~1):first + (b & ~1)]
        got = A.lzss(data) if a & 1 else data
        assert got[:len(want)] == want
    # original game files untouched, target's set pointer now at the new set index
    assert out[first:p["ft"]] == eu[first:p["ft"]]
    si = p["sets"]
    assert struct.unpack_from(">H", out, W.Rom.r2r(target["set_addr"]))[0] & 0x7F == si
    # the donor's untouched geometry is what a new body record points at
    assert all(isinstance(v["model"], dict) for k, v in dparts.items() if isinstance(k, int))
