"""Metroid Prime (GM8E01) inventory: pak container parser + owned-disc enumeration."""
import os
import struct
from pathlib import Path

import pytest

from gbox import metroidprime_inventory as mi

SRC = Path(
    os.environ.get(
        "GBOX_METROIDPRIME_GCZ", Path.home() / "gbox-cache/gc/bbc9d43db663e1aa/source.gcz"
    )
)


def _cc(cc: str) -> int:
    return int.from_bytes(cc.encode("latin-1"), "big")


def _build_pak(names, resources):
    """names: [(fourCC_str, id, name)]; resources: [(flags, fourCC_str, id, size, blob)]."""
    head = struct.pack(">3I", mi.PAK_VERSION, 0, len(names))
    for cc, rid, name in names:
        head += struct.pack(">2I", _cc(cc), rid)
        head += struct.pack(">I", len(name)) + name.encode()
    head += struct.pack(">I", len(resources))
    base = len(head) + 20 * len(resources)
    table = b""
    data = b""
    for flags, cc, rid, size, blob in resources:
        cur = len(data)
        offset = (base + cur + 31) & ~31
        data += b"\0" * (offset - base - cur)
        table += struct.pack(">5I", flags, _cc(cc), rid, size, offset)
        data += blob
        data += b"\0" * (((len(blob) + 31) & ~31) - len(blob))
    return head + table + data


def test_pak_directory_roundtrip():
    blob = bytes(range(64))
    pak = _build_pak(
        [("CMDL", 0x11111111, "samus_cmdl"), ("TXTR", 0x22222222, "samus_tex")],
        [(1, "CMDL", 0x11111111, 64, blob), (0, "TXTR", 0x22222222, 64, blob)],
    )
    d = mi.pak_directory(pak)
    assert d["version"] == mi.PAK_VERSION
    assert d["name_count"] == 2
    assert [n["name"] for n in d["names"]] == ["samus_cmdl", "samus_tex"]
    assert d["res_count"] == 2
    assert [mi.fourcc(r["type"]) for r in d["resources"]] == ["CMDL", "TXTR"]
    assert d["resources"][0]["size"] == 64
    assert d["resources"][0]["offset"] & 31 == 0


def test_pak_directory_rejects_wrong_version_and_bad_offset():
    with pytest.raises(ValueError):
        mi.pak_directory(struct.pack(">3I", 0xDEAD, 0, 0) + struct.pack(">I", 0))
    pak = bytearray(_build_pak([], [(0, "TXTR", 1, 64, b"x" * 64)]))
    head_len = 12 + 4  # header + resTableCount (no names)
    struct.pack_into(">I", pak, head_len + 16, 3)  # misalign the offset field
    with pytest.raises(ValueError):
        mi.pak_directory(bytes(pak))


@pytest.mark.skipif(not SRC.exists(), reason="owned Metroid Prime GCZ not staged (GBOX_METROIDPRIME_GCZ)")
def test_owned_disc_inventory():
    from gbox.gcdisc import GCDisc

    disc = GCDisc(str(SRC))
    assert disc.game_id == mi.DISC_ID
    ident = mi.disc_identity(SRC)
    assert ident["game_id"] == "GM8E01"
    assert ident["dol_size"] > 1_000_000
    assert len(ident["paks"]) >= 17
    type_hist = {}
    total = 0
    for pak in ident["paks"]:
        d = mi.pak_directory(disc.read(pak))
        assert d["version"] == mi.PAK_VERSION
        for r in d["resources"]:
            total += 1
            cc = mi.fourcc(r["type"])
            type_hist[cc] = type_hist.get(cc, 0) + 1
    assert total > 0
    for cc in ("CMDL", "TXTR", "CSKR", "ANIM", "ANCS", "MLVL"):
        assert cc in type_hist, f"missing {cc}: {sorted(type_hist)}"
    # Retro 'Kyoto' engine, not Unreal: no UE-flavoured resource fourCCs.
    assert not any(k.startswith(("UASS", "UEXP")) for k in type_hist)


@pytest.mark.parametrize("blob", [
    struct.pack(">3I", mi.PAK_VERSION, 0, 0),
    struct.pack(">3I", mi.PAK_VERSION, 0, 1) + bytes(8),
    struct.pack(">3I", mi.PAK_VERSION, 0, 1) + bytes(8) + struct.pack(">I", 100),
    struct.pack(">4I", mi.PAK_VERSION, 0, 0, 0xffffffff),
])
def test_pak_rejects_truncated_tables_without_struct_error(blob):
    with pytest.raises(ValueError, match="truncated pak"):
        mi.pak_directory(blob)
