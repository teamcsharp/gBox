import os
import struct
from pathlib import Path

import pytest

from gbox.melee_dol_probe import Dol, probe


def _synthetic_dol():
    """Hand-laid DOL: one data section (index 7) at 0x80100000 with strings + pointer tables."""
    base = 0x80100000
    blob = bytearray(0x200)
    strs = {}
    off = 0x100

    def put(s):
        nonlocal off
        strs[s] = base + off
        blob[off:off + len(s) + 1] = s.encode() + b"\0"
        off += len(s) + 1 + (-(len(s) + 1) % 4)
    for s in ("PlPe.dat", "ftDataPeach", "PlPeNr.dat", "PlyPeach5K_Share_joint", "PlyPeach5K_Share_matanim_joint",
              "PlBoNr.dat", "PlyBoy_Share_joint"):
        put(s)
    words = [strs["PlPe.dat"], strs["ftDataPeach"],
             strs["PlPeNr.dat"], strs["PlyPeach5K_Share_joint"], strs["PlyPeach5K_Share_matanim_joint"],
             strs["PlBoNr.dat"], strs["PlyBoy_Share_joint"], 0]
    for i, w in enumerate(words):
        struct.pack_into(">I", blob, i * 4, w)
    hdr = bytearray(0x100)
    struct.pack_into(">I", hdr, 7 * 4, 0x100)       # file offset
    struct.pack_into(">I", hdr, 0x48 + 7 * 4, base)  # load address
    struct.pack_into(">I", hdr, 0x90 + 7 * 4, len(blob))
    struct.pack_into(">I", hdr, 0xE0, 0x80003100)
    return bytes(hdr + blob)


def test_synthetic_tables():
    r = probe(_synthetic_dol())
    assert r["fighters"]["Pe"]["symbol"] == "ftDataPeach"
    pe = r["costumes"]["Pe"][0]
    assert (pe["file"], pe["joint"], pe["matanim"]) == ("PlPeNr.dat", "PlyPeach5K_Share_joint", "PlyPeach5K_Share_matanim_joint")
    assert r["costumes"]["Bo"][0]["matanim"] is None  # matanim pointer may be null


def test_rejects_truncated():
    with pytest.raises(ValueError):
        Dol(b"\0" * 16)
    hdr = bytearray(0x100)
    struct.pack_into(">I", hdr, 7 * 4, 0x100)
    struct.pack_into(">I", hdr, 0x90 + 7 * 4, 0x1000)
    with pytest.raises(ValueError):
        Dol(bytes(hdr))


@pytest.mark.skipif(not os.environ.get("MELEE_MAIN_DOL"), reason="owned main.dol path not provided")
def test_owned_dol_peach():
    data = Path(os.environ["MELEE_MAIN_DOL"]).read_bytes()
    r = probe(data)
    assert len(r["fighters"]) == 33
    assert r["fighters"]["Pe"]["table_va"] == "0x803c1f88"
    assert [c["file"] for c in r["costumes"]["Pe"]] == ["PlPeNr.dat", "PlPeYe.dat", "PlPeWh.dat", "PlPeBu.dat", "PlPeGr.dat"]
