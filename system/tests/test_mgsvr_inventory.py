"""Focused tests for gbox.mgsvr_inventory (Metal Gear Solid: VR Missions PS1 USA, #1637).

Synthetic fixtures check the parsers (7z listing, CUE, SYSTEM.CNF, PS-X EXE header, STAGE.DIR -> .stg -> DAR ->
KMD/OAR) without the owned disc.  test_owned_build runs the whole manifest on the unpacked owned image when it is
present (GBOX_MGS_VR_BIN, or the Spark caches) and skips otherwise.
"""
import os
import struct
from pathlib import Path

import pytest

from gbox import mgs_kmd as K
from gbox import mgs_vr_swap, mgs_vr_tool
from gbox import mgsvr_inventory as inv

LISTING = """
7-Zip [64] 16.02 : Copyright (c) 1999-2016 Igor Pavlov : 2016-05-21

Listing archive: Metal Gear Solid - VR Missions (USA).7z

--
Path = Metal Gear Solid - VR Missions (USA).7z
Type = 7z
Physical Size = 299662626

----------
Path = Metal Gear Solid - VR Missions (USA).bin
Size = 492487632
Packed Size = 299662400
CRC = 2B5D2AC1
Method = LZMA2:24

Path = Metal Gear Solid - VR Missions (USA).cue
Size = 104
Packed Size =
CRC = 0A1B2C3D

Path = extras
Size = 0
Folder = +
"""

CUE = 'FILE "Metal Gear Solid - VR Missions (USA).bin" BINARY\r\n  TRACK 01 MODE2/2352\r\n    INDEX 01 00:00:00\r\n'


def _figure(tree=mgs_vr_swap.TREE, tex=47255) -> bytes:
    objs = [K.KmdObject(0x10001 if p >= 0 else 0x1, (0, 10, 0), p, 0xFFFFFFFF,
                        vertices=[(0, 0, 0, -1), (10, 0, 0, -1), (10, 10, 0, -1), (0, 10, 0, -1)],
                        normals=[(0, 0, 4096, 0)], faces=[(0, 1, 2, 3)], face_normals=[(0, 0, 0, 0)],
                        uvs=[bytes(8)], textures=[tex]) for p in tree]
    return K.dumps(K.Kmd(len(tree), (0, 0, 0, 10, 10, 0), objs))


def _dar(members) -> bytes:
    out = bytearray()
    for h, ext, body in members:
        out += struct.pack("<HBBI", h, ord(ext), 0, len(body)) + body
        out += bytes(-len(out) % 4)
    return bytes(out + bytes(8))


def _stg(streamed=(), cached=()) -> bytes:
    """A .stg: header, entries, then streamed bodies from +0x800 (sector aligned) and one cached block."""
    ents, bodies = [], []
    for h, ext, body in streamed:
        ents.append(struct.pack("<HBBI", h, ord("r"), ord(ext), len(body)))
        bodies.append(body + bytes(-len(body) % 2048))
    if cached:
        block, offs = bytearray(), []
        for h, ext, body in cached:
            offs.append(len(block))
            block += body + bytes(-len(body) % 4)
        for (h, ext, _b), o in zip(cached, offs):
            ents.append(struct.pack("<HBBI", h, ord("c"), ord(ext), o))
        ents.append(struct.pack("<HBBI", 0, ord("c"), 0xFF, len(block)))
        bodies.append(bytes(block) + bytes(-len(block) % 2048))
    head = struct.pack("<BBH", 1, 0, 0) + b"".join(ents) + bytes(8)
    return head + bytes(0x800 - len(head)) + b"".join(bodies)


def _stage_dir(stages) -> bytes:
    hdr = 4 + 12 * len(stages)
    table, blobs, sector = bytearray(struct.pack("<I", hdr)), bytearray(), 1
    for name, stg in stages:
        table += name.encode().ljust(8, b"\0") + struct.pack("<I", sector)
        blobs += stg + bytes(-len(stg) % 2048)
        sector += (len(stg) + 2047) // 2048
    return bytes(table + bytes(2048 - len(table)) + blobs)


def test_7z_listing_members_skip_header_and_folders():
    m = inv.parse_7z_listing(LISTING)
    assert [r["path"] for r in m] == ["Metal Gear Solid - VR Missions (USA).bin",
                                      "Metal Gear Solid - VR Missions (USA).cue"]
    assert m[0]["size"] == 492487632 and m[0]["crc32"] == "2b5d2ac1"


def test_cue_system_cnf_and_boot_name():
    cue = inv.parse_cue(CUE)
    assert cue == [{"file": "Metal Gear Solid - VR Missions (USA).bin", "type": "BINARY",
                    "tracks": [{"number": 1, "mode": "MODE2/2352", "indexes": {1: "00:00:00"}}]}]
    cnf = inv.parse_system_cnf("BOOT = cdrom:\\SLUS_009.57;1\r\nTCB = 4\r\nEVENT = 16\r\nSTACK = 801FFFF0\r\n")
    assert cnf["BOOT"] == inv.EXPECTED["boot"] and cnf["STACK"] == "801FFFF0"
    assert inv.boot_name(cnf) == "SLUS_009.57"
    assert inv.boot_name({"BOOT": "cdrom0:\\MGS\\GAME.EXE;1"}) == "MGS/GAME.EXE"
    assert inv.boot_name({}) is None


def test_exe_header_reads_entry_text_and_region():
    b = bytearray(0x800 + 0x100)
    b[:8] = b"PS-X EXE"
    struct.pack_into("<4I", b, 0x10, 0x80099908, 0, 0x80010000, 0x100)
    struct.pack_into("<I", b, 0x30, 0x801FFFF0)
    b[0x4C:0x4C + 20] = b"Sony Computer Entert"
    h = inv.exe_header(bytes(b))
    assert (h["pc0"], h["t_addr"], h["t_size"], h["stack"]) == (0x80099908, 0x80010000, 0x100, 0x801FFFF0)
    assert h["region"].startswith("Sony") and h["fits"]
    assert inv.exe_header(b"not an exe")["magic"] is None


def test_stage_inventory_finds_figures_models_and_motions():
    snake, soldier = _figure(tex=47255), _figure(tex=1000)
    prop = _figure(tree=[-1, 0])                                   # two objects: a model, not a figure
    init = _stg(streamed=[(0x1111, "d", _dar([(39213, "k", snake), (47255, "p", b"\x0a" * 40)]))])
    mission = _stg(cached=[(38582, "k", soldier), (0xA8A1, "o", b"\x01" * 24), (777, "k", prop)])
    data = _stage_dir([("init", init), ("vr_sud01", mission), ("vr_sud02", mission)])
    st = inv.stage_inventory(data)
    assert [s["name"] for s in st["stages"]] == ["init", "vr_sud01", "vr_sud02"]
    assert st["stages"][1]["family"] == mgs_vr_tool.family("vr_sud01")
    assert st["bad_dars"] == 0 and st["pcc_total"] == 1
    figs = {f["model"]: f for f in st["figures"]}
    assert set(figs) == {39213, 38582}
    assert figs[39213]["slot"] == "player" and figs[39213]["sites"] == [{"stage": "init", "in_dar": True,
                                                                         "cached": False}]
    assert figs[38582]["slot"] == "enemy:soldier" and figs[38582]["stage_count"] == 2
    assert figs[38582]["objects"] == 16 and figs[38582]["faces"] == 16 and figs[38582]["textures"] == [1000]
    assert [m["model"] for m in st["models"]] == [777]
    assert st["motions"][0]["hash"] == 0xA8A1 and st["motions"][0]["stages"] == ["vr_sud01", "vr_sud02"]
    assert st["ext_names"]["k"].startswith("kmd")


def test_check_build_names_each_difference():
    good = {"image": {"bytes": inv.EXPECTED["disc_bytes"]}, "system_cnf": {"BOOT": inv.EXPECTED["boot"]},
            "executable": {"name": "SLUS_009.57", "bytes": inv.EXPECTED["exe_bytes"],
                           "sha256": inv.EXPECTED["exe_sha256"]},
            "stage_dir": {"bytes": inv.EXPECTED["stage_dir_bytes"], "sha256": inv.EXPECTED["stage_dir_sha256"]},
            "stages": [{}] * inv.EXPECTED["stages"], "player": {"sha256": "5dda0c64" + "0" * 56}, "bad_dars": 0}
    assert inv.check_build(good) == []
    modded = {**good, "stage_dir": {"bytes": inv.EXPECTED["stage_dir_bytes"], "sha256": "ab" * 32}}
    assert [p for p in inv.check_build(modded) if "STAGE.DIR" in p]
    assert inv.check_build({**good, "player": None}) == ["init.stg player KMD 39213 is missing or not the stock Snake"]


def _owned_image():
    name = "modbase/mgs_vr_us/Metal Gear Solid - VR Missions (USA).bin"     # where mgs_vr_swap.base_bin unpacks
    cands = [os.environ.get("GBOX_MGS_VR_BIN", ""), str(Path.home() / "samples/gbox-cache" / name),
             str(Path.home() / "gBox_alt/gbox-cache" / name)]
    return next((Path(c) for c in cands if c and Path(c).is_file()), None)


@pytest.mark.skipif(_owned_image() is None, reason="owned VR Missions image not unpacked on this machine")
def test_owned_build():
    m = inv.inventory(_owned_image())
    assert m["build_check"] == [], m["build_check"]
    assert m["boot"] == "SLUS_009.57" and m["platform_check"]["psx"]
    assert m["executable"]["header"]["pc0"] == 0x80099908 and m["executable"]["header"]["t_addr"] == 0x80010000
    assert m["player"]["bytes"] == 13608 and m["player"]["objects"] == 16
    figs = {f["model"] for f in m["figures"]}
    assert {m_ for row in mgs_vr_swap.SLOTS.values() for m_ in row["models"]} <= figs
    soldier = [f for f in m["figures"] if f["model"] == 38582]
    assert len(soldier) == 1 and soldier[0]["bytes"] == 9936
