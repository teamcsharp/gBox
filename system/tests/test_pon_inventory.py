"""Path of Neo inventory (gbox.pon_inventory): actor table, level packages (chunk rows, model chunks, names
confirmed by the archive hash) on synthetic data, and the owned PS2 disc when it is reachable."""
import os
import struct
from pathlib import Path

import pytest

from gbox import pon_inventory as P
from gbox.defjam_inventory import Iso
from gbox.shiny_dfu import Dfu
from matrix_synth import make_dfu, make_iso

OWNED = Path(os.environ.get("GBOX_PON_PS2_CHD") or "//10.89.1.125/HyperSpin Attraction/Arcade/collections/"
             "Sony Playstation 2/roms/USA/Matrix, The - Path of Neo (USA).chd")


def package(level: str, chunks: list[tuple[int, bytes]]) -> bytes:
    start = (0x80 + 16 * len(chunks) + 63) & ~63
    head = bytearray(0x80)
    struct.pack_into("<5I", head, 0, start, len(chunks), 0x000B003F, 0x00280007, 0x37D)
    head[0x14:0x34] = b"AUTHOR".ljust(32, b"\0")
    head[0x34:0x54] = level.encode().ljust(32, b"\0")
    rows, data, off = b"", b"", start
    for i, (typ, blob) in enumerate(chunks):
        rows += struct.pack("<4I", 0x1000 + i, off, len(blob), typ)
        data += blob
        off += len(blob)
    return bytes(head) + rows + b"\0" * (start - 0x80 - len(rows)) + data


def model_chunk(name: str) -> bytes:
    return struct.pack("<4I", 64, 1, 1, 64) + b"\xff" * 48 + b"_HEADER_ \0\0\0" + b"\0" * 20 + \
        name.encode()[:16].ljust(16, b"\0") + b"\0" * 64


def actors_table() -> bytes:
    r = bytearray(P.ACTOR_REC)
    r[0:64] = b"actors\\neo.dcn".ljust(64, b"\0")
    r[64:128] = b"actors\\neo_lp.dcn".ljust(64, b"\0")
    r[0xC4:0xE4] = b"Neo".ljust(32, b"\0")
    return bytes(r) + bytes(P.ACTOR_REC)


def test_package_parse_and_bounds():
    b = package("b5_lobby", [(3, model_chunk("neo.dcn_11")), (3, model_chunk("agentsmith.dcn_11")), (9, b"CORE" * 9)])
    p = P.parse_package(b)
    assert p["level"] == "b5_lobby" and p["count"] == 3
    assert [c.get("model") for c in p["chunks"]] == ["neo", "agentsmith", None]
    assert p["chunks"][2]["kind"] == "animation set"
    bad = bytearray(b)
    struct.pack_into("<I", bad, 0x80 + 8, 10 ** 6)          # chunk size past the end
    with pytest.raises(P.FormatError):
        P.parse_package(bytes(bad))
    with pytest.raises(P.FormatError):
        P.parse_package(b"\0" * 16)


def test_levels_found_by_header_and_confirmed_by_hash(tmp_path):
    lvl = package("b5_lobby", [(3, model_chunk("neo.dcn_11"))])
    files = {"common\\misc\\ActorHeadersV11.Bin": actors_table(), "levels\\b5_lobby.lvl_3": lvl,
             "levels\\impostor.lvl_9": package("not_this_name", [(3, model_chunk("x.dcn_11"))])}
    w1, w2 = make_dfu(files, "pon")
    p = tmp_path / "pon.iso"
    p.write_bytes(make_iso({"WAD1.DFU": w1, "WAD1_B.DFU": w2}))
    d = Dfu(Iso(p), "pon")
    assert [r["level"] for r in P.levels(d)] == ["b5_lobby"]
    assert P.level_models(d, "b5_lobby") == [{"model": "neo", "size": len(model_chunk("x")), "chunk": 0}]
    acts = P.actors(d)
    assert acts == [{"index": 0, "name": "Neo", "models": ["actors\\neo.dcn", "actors\\neo_lp.dcn"]}]


@pytest.mark.skipif(not OWNED.exists(), reason="owned Path of Neo CHD not reachable")
def test_owned_path_of_neo():
    from gbox.etm_inventory import open_disc
    disc = open_disc(OWNED)
    ident = P.identify(disc)
    assert ident["exact_build"] and ident["chd_sha1"] == P.CHD_SHA1
    d = Dfu(disc, "pon")
    assert d.count == P.DFU_COUNT and d.base == 0xC800
    acts = P.actors(d)
    assert any(a["name"] == "Neo" for a in acts) and any(a["name"] == "AgentSmith" for a in acts)
    ms = {m["model"] for m in P.level_models(d, "b5_lobby")}
    assert {"neo", "trinity_lobby", "swat"} <= ms
