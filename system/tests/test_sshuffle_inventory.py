"""Sonic Shuffle (USA) DC inventory: MDL container parsing, PVM names, name lists and the real-disc manifest.

The disc test needs the unpacked owned GD-ROM (``GBOX_SSHUFFLE_GDI`` or the default cache path)
and is skipped without it; the container tests use synthetic bytes.
"""
import os
import struct
from pathlib import Path

import pytest

from gbox import sshuffle_inventory as inv

GDI = Path(os.environ.get("GBOX_SSHUFFLE_GDI",
                          Path.home() / "gbox-cache/dc/79ade87c3c2fad3e/disc.gdi"))


def _pvm(names):
    body = b"".join(struct.pack("<H", i) + n.encode().ljust(28, b"\0") + struct.pack("<HHI", 0x0101, 0, 0)
                    for i, n in enumerate(names))
    return b"PVMH" + struct.pack("<IHH", 4 + len(body), 0x000F, len(names)) + body


def _nmdm(frames):
    return b"NMDM" + struct.pack("<I", 0x20) + struct.pack("<IIHH", 0x10, frames, 3, 2) + b"\0" * 0x14


def _mdl(blobs):
    """[(type, payload)] -> MDL container: 0x800-aligned payloads, max_entry = largest aligned entry."""
    out = bytearray(8 + 12 * len(blobs))
    ents = []
    for t, b in blobs:
        off = (len(out) + 0x7FF) & ~0x7FF
        out.extend(b"\0" * (off - len(out)))
        ents.append((t, len(b), off))
        out.extend(b)
    out.extend(b"\0" * (-len(out) % 0x800))
    struct.pack_into("<HHI", out, 0, 2, len(blobs), max((s + 0x7FF) & ~0x7FF for _, s, _ in ents))
    for i, e in enumerate(ents):
        struct.pack_into("<3I", out, 8 + 12 * i, *e)
    return bytearray(out)


def test_mdl_inventory_entries_room_names_and_frames():
    model = b"NJCM" + struct.pack("<I", 0x900) + b"\0" * 0x900      # 0x908 bytes -> 0x1000 aligned
    d = _mdl([(1, _pvm(["sonicA", "sonich"])), (2, model), (4, _nmdm(61))])
    t = inv.mdl_inventory(bytes(d), decode=False)
    assert t["counts"] == {"pvm": 1, "model": 1, "motion": 1}
    assert t["max_entry"] == 0x1000 and t["max_entry_ok"]
    assert all(e["magic_ok"] for e in t["entries"])
    assert t["texture_names"] == ["sonicA", "sonich"]
    assert [e["room"] for e in t["entries"]] == [0x800, 0x1000, 0x800]
    assert t["entries"][2]["frames"] == 61 and t["motions_with_frames"] == 1


def test_mdl_table_rejects_unaligned_overlap_and_eof():
    base = _mdl([(1, _pvm(["a"])), (4, _nmdm(2))])
    for word, value in ((4, 0x804), (4, 0x800 + 0x10), (3, 0x10000)):   # unaligned, overlap, past EOF
        d = bytearray(base)
        if word == 4 and value == 0x800 + 0x10:
            struct.pack_into("<I", d, 8 + 12 + 8, 0x800)                   # entry 1 onto entry 0
            struct.pack_into("<I", d, 8 + 4, 0x900)
        elif word == 3:
            struct.pack_into("<I", d, 8 + 4, value)
        else:
            struct.pack_into("<I", d, 8 + 8, value)
        with pytest.raises(ValueError):
            inv.mdl_table(bytes(d))
    with pytest.raises(ValueError):
        inv.mdl_table(b"\x03\x00\x01\x00" + b"\0" * 12)                     # wrong version


def test_max_entry_mismatch_and_wrong_magic_are_reported():
    d = _mdl([(1, _pvm(["a"])), (4, b"NJCM" + b"\0" * 12)])
    struct.pack_into("<I", d, 4, 0x2000)
    t = inv.mdl_table(bytes(d))
    assert not t["max_entry_ok"] and [e["magic_ok"] for e in t["entries"]] == [True, False]


def test_name_list_and_file_room():
    exe = b"\0" * 4 + b"SONIC\0\0\0TAILS\0\0\0KNUCKLES\0\0\0\0SUPER SONIC\0" + b"\x09\x00"
    assert inv.name_list(exe, 4, 4) == ["SONIC", "TAILS", "KNUCKLES", "SUPER SONIC"]
    with pytest.raises(ValueError):
        inv.name_list(exe, 4, 5)
    room = inv.file_room({"A.MDL": (100, 4096), "B.MDL": (102, 100), "C.PVM": (110, 10)})
    assert room == {"A.MDL": 4096, "B.MDL": 8 * 2048, "C.PVM": 2048}


@pytest.mark.skipif(not GDI.exists(), reason="owned Sonic Shuffle (USA) GD-ROM not unpacked")
def test_real_disc_manifest():
    m = inv.inventory(GDI, hash_tracks=False)
    ip = m["ip"]
    assert (ip["product"], ip["version"], ip["area"], ip["date"]) == ("MK-51060", "V1.000", "U", "20001019")
    fr = m["first_read"]
    assert fr["sha256"] == inv.FIRST_READ_SHA256 and fr["unscrambled_sh4"]
    assert fr["chr_files"]["names"] == [f"C0{i}.MDL" for i in range(8)]
    assert fr["player_names"]["names"] == ["SONIC", "TAILS", "KNUCKLES", "AMY", "BIG", "GAMMA", "CHAO",
                                           "SUPER SONIC"]
    f = m["mdl_format"]
    assert f["mdl_files"] == f["valid"] == f["max_entry_ok"] == 274 and not f["errors"]
    assert m["files"] == 485 and m["extensions"]["MDL"] == 274
    r = m["roster"]
    assert [e["file"] for e in r] == [f"CHRDATA/C0{i}.MDL" for i in range(8)]
    assert all(e["name_check"] for e in r)                       # texture names confirm the name order
    assert r[0]["counts"] == {"pvm": 8, "model": 9, "motion": 131}
    assert all(e["decoded_models"] == len(e["models"]) for e in r)
    body = r[0]["models"][0]                                     # Sonic's board body: entry 8
    assert (body["index"], body["bones"], body["verts"], body["tex_ids"]) == (8, 38, 656, [0, 1])
    assert body["tris"] > 0 and body["room"] - body["size"] == 1540
    assert all(e["motions_with_frames"] == e["motions"] for e in r)
    assert all(e["room"] >= e["size"] for e in r)
    assert {n for n, c in m["other_characters"].items() if c["group"] == "event_hi_detail"} == {
        f"CHRDATA/H{i}.MDL" for i in ("00", "01", "02", "03", "11", "12", "13")}


def test_truncated_inputs_raise_valueerror():
    pvm = _pvm(["sonic_body", "sonic_head"])
    assert inv.pvm_names(pvm) == ["sonic_body", "sonic_head"]
    for n in range(len(pvm)):
        with pytest.raises(ValueError):
            inv.pvm_names(pvm[:n])
    mdl = bytes(_mdl([(1, pvm), (4, _nmdm(30))]))
    for n in (0, 7, 8, 20, inv.mdl_table(mdl)["data_end"] - 1):
        with pytest.raises(ValueError):
            inv.mdl_table(mdl[:n])
