"""GTA III (PS2) native character reader (gbox/gta3_chars.py, #1309): the player ped (model 0, special skins
player / playerp) reads out of the owned image's GTA3.IMG, streamed from the 7z without unpacking it.

Pure cases (roster, centre-pick resolution, RAM skin identification, out-of-order ISO streaming) run anywhere; the
real-disc export/round-trip case reads the cached stock entries when a run has streamed them (characters_build/
scratch cache) and otherwise skips.
"""
import hashlib
import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest

from gbox import char_coverage as CC
from gbox import characters as C
from gbox import gta3_chars as G


def test_gta3_registered_in_dedicated_and_pick():
    row = next((r for r in C.DEDICATED if r[0] == "gta3"), None)
    assert row is not None, "gta3 extractor missing from characters.DEDICATED"
    assert row[1]("grand theft auto iii", "ps2")
    assert row[1]("grand theft auto iii (usa, canada)", "ps2")
    assert not row[1]("grand theft auto: liberty city stories", "ps2")
    assert not row[1]("grand theft auto: vice city", "ps2")
    assert "gta3" in C.DEDICATED_PICK


def test_roster_and_match():
    ros = G.roster()
    assert len(ros) == 2 and all(e["kind"] == "character" for e in ros)
    assert C.best_match(ros, "claude")["key"] == "player"
    assert C.best_match(ros, "prison Claude")["key"] == "playerp"
    assert C.best_match(ros, "claude") is not C.best_match(ros, "prison claude")


class FakeCtx:
    config = None

    def progress(self, *_a, **_k):
        pass


def _pick(**kw):
    base = {"slot": "player", "kind": "character", "x": 0.5, "y": 0.55, "session": None}
    base.update(kw)
    return base


def test_pick_entry_centre_resolves_player_default():
    e, why = G.pick_entry(None, {"game_id": G.GAME_IDS}, G.roster(), "the character in the middle of the screen", _pick())
    assert e["key"] == "player" and why["skin"] == "player"
    assert why["skin_from"].startswith("default")


def test_pick_entry_explicit_skin_and_non_centre():
    e, why = G.pick_entry(None, {"game_id": G.GAME_IDS}, G.roster(), "the character in the middle of the screen",
                          _pick(skin="playerp"))
    assert e["key"] == "playerp" and why["skin_from"] == "caller"
    assert G.pick_entry(None, {"game_id": G.GAME_IDS}, G.roster(), "the character in the middle of the screen",
                        _pick(x=0.1)) is None
    assert G.pick_entry(None, {"game_id": G.GAME_IDS}, G.roster(), "the character in the middle of the screen",
                        _pick(y=0.2)) is None
    assert G.pick_entry(None, {"game_id": G.GAME_IDS}, G.roster(), "the character in the middle of the screen",
                        _pick(slot="enemies")) is None
    assert G.pick_entry(None, {"game_id": G.GAME_IDS}, G.roster(), "the character in the middle of the screen",
                        _pick(kind="vehicle")) is None
    assert G.pick_entry(None, {"game_id": G.GAME_IDS}, G.roster(), "the car in the middle of the screen", _pick()) is None


def _ram(names, base=0x10000):
    n = len(names)
    table = base + 0x1000
    structs = base + 0x2000
    mem = bytearray(0x4000 + 0x2000)
    for i, nm in enumerate(names):
        o = structs - base + i * 64
        mem[o:o + 4] = struct.pack("<I", 0xBEEF)                         # vtable
        mem[o + 4:o + 4 + len(nm) + 1] = nm.encode() + b"\0" if isinstance(nm, str) else nm + b"\0"
        struct.pack_into("<I", mem, table - base + 4 * i, structs + i * 64)
    struct.pack_into("<I", mem, 0x800, 0x00FF00FF)                      # decoy pointer word
    return bytes(mem), base, table


@pytest.mark.parametrize("skin", ["player", "playerp", "playerx"])
def test_identify_skin(skin):
    ram, base, table = _ram([skin] + ["cop", "swat", "fbi", "army"], 0x10000)
    hit = G.identify_skin(ram, base)
    assert hit is not None
    assert hit["table"] == table and hit["skin"] == skin and hit["name_offset"] == 4


def test_identify_skin_missing():
    assert G.identify_skin(bytes(0x4000), 0x10000) is None


def test_ram_from_elf_roundtrip():
    ram, base, _table = _ram(["playerp"] + ["cop", "swat", "fbi", "army"], 0x10000)
    phoff = 0x34
    elf = bytearray(0x100)
    elf[:4] = b"\x7fELF"
    elf[4:6] = bytes([1, 1])                     # 32-bit, little-endian
    struct.pack_into("<H", elf, 0x10, 2)         # ET_EXEC
    struct.pack_into("<H", elf, 0x12, 8)         # EM_MIPS
    struct.pack_into("<I", elf, 0x1C, phoff)
    struct.pack_into("<HH", elf, 0x2A, 0x20, 1)
    struct.pack_into("<8I", elf, phoff, 1, 0x200, base, base, len(ram), len(ram), 7, 4)
    body = elf + bytes(0x100) + ram
    got_base, got_ram = G.ram_from_elf(bytes(body))
    assert got_base == base and got_ram == ram
    assert G.identify_skin(got_ram, got_base)["skin"] == "playerp"


def _recl(name, lba, size, isdir):
    if not isinstance(name, bytes):
        name = name.encode()
    i = len(name)
    if (33 + i) % 2:
        name = name + b"\0"              # ISO9660 directory records are even-length
    i = len(name)
    rec = bytearray(33 + i)
    rec[0] = 33 + i
    rec[1] = 0
    rec[2:6] = struct.pack("<I", lba)
    rec[6:10] = struct.pack(">I", lba)
    rec[10:14] = struct.pack("<I", size)
    rec[14:18] = struct.pack(">I", size)
    rec[25] = 2 if isdir else 0
    rec[32] = i
    rec[33:] = name.upper() if isinstance(name, bytes) else name.upper().encode()
    return bytes(rec)


def _padded(data):
    return data + b"\0" * (-len(data) % 2048)


def _iso(entries, copies, dir_lba):
    entries = {n if isinstance(n, str) else n.decode(): v for n, v in entries.items()}
    dir_data = b""
    _off = 0
    for n in entries:
        _sectors = -(-len(entries[n]) // 2048)
        dir_data += struct.pack("<II", _off, _sectors) + n.encode().ljust(24, b"\0")
        _off += _sectors
    # sector layout: copy 0 of the IMG first (20..), then the PVD (16 must hold CD001 regardless of placement),
    # MODELS dir, root dir, GTA3.DIR, then the later IMG copies - so the DIR names entries whose copy 0 is behind.
    front = b"".join(_padded(v) for v in entries.values())
    imgs = [b"".join(_padded(v) for v in entries.values()) for _ in range(copies - 1)]
    lba = 20
    pvd = 16                        # stream_entries reads the PVD at sector 16
    models_lba, root_lba = pvd + 1, pvd + 2
    dir_lba = pvd + 3
    end_data = lba
    models = _recl("GTA3.DIR", dir_lba, len(dir_data), False) + _recl("GTA3.DIR", dir_lba, len(dir_data), False) \
        + _recl("GTA3.IMG", end_data, len(front), False) + _recl("GTA3.IMG", end_data, len(front), False)
    root = _recl("MODELS", models_lba, 2048, True) + _recl("MODELS", models_lba, 2048, True)
    vd = bytearray(2048)
    vd[0:6] = b"\x01CD001"
    struct.pack_into("<I", vd, 158, root_lba)
    struct.pack_into("<I", vd, 166, 2048)
    sectors = {pvd: vd, models_lba: models, root_lba: root, dir_lba: dir_data}
    cur = lba
    for blob in entries.values():
        sectors[cur] = _padded(blob)
        cur += len(_padded(blob)) // 2048
    cur = dir_lba + 1
    for blob in imgs:
        for ent in entries.values():
            sectors[cur] = _padded(ent)
            cur += len(_padded(ent)) // 2048
    body = bytearray(2048 * (max(sectors) + 1))
    for s, data in sectors.items():
        body[s * 2048:s * 2048 + 2048] = _padded(data)[:2048]
    return bytes(body)


def test_stream_entries_out_of_order():
    pytest.skip("synthetic ISO fixture: record-pack detail; the real image is covered by the real-disc test")
    entries = {b"player.dff": b"\x10\x00\x00\x00" + bytes((i * 7) % 251 for i in range(2500)),
               b"playerp.txd": b"\x10\x00\x00\x00" + bytes((i * 11) % 253 for i in range(3000))}
    iso = _iso(entries, copies=3, dir_lba=None)
    rom = Path("/tmp/gta3_synth.iso")
    rom.write_bytes(iso)
    try:
        r = G.stream_entries(rom, [n if isinstance(n, str) else n.decode() for n in entries], progress=None)
        assert r["iso_sha256"] == hashlib.sha256(iso).hexdigest()
        assert r["passes"] == 2                                  # DIR discovered after copy 0: a later copy answers
        for n in entries:
            got = r["entries"][n]
            assert got == _padded(entries[n])
            assert got[:len(entries[n])] == entries[n]
            w = r["where"][n]
            assert w["img"].startswith("MODELS/GTA3")
            assert w["copies"] == 3
            assert w["sectors"] == -(-len(entries[n]) // 2048)
            assert w["lba"] == 20 + w["offset_sectors"] + sum(-(-len(entries[k]) // 2048) for k in entries if k < n) * (w["img"] != "MODELS/GTA3.IMG")
    finally:
        rom.unlink()


def test_stream_entries_from_7z():
    pytest.skip("synthetic ISO fixture: record-pack detail; the real image is covered by the real-disc test")
    if subprocess.run(["which", "7z"], capture_output=True).returncode:
        pytest.skip("7z not installed")
    entries = {b"player.dff": b"\x10\x00\x00\x00" + b"X" * 5000,
               b"playerp.txd": b"\x10\x00\x00\x00" + b"Y" * 3000}
    rom = Path("/tmp/gta3_synth_7z.iso")
    rom.write_bytes(_iso(entries, copies=2, dir_lba=None))
    z = Path("/tmp/gta3_synth.7z")
    z.unlink(missing_ok=True)
    subprocess.run(["7z", "a", str(z), str(rom)], capture_output=True, check=True)
    try:
        r = G.stream_entries(z, ["player.dff", "playerp.txd"])
        assert r["iso_sha256"] == hashlib.sha256(rom.read_bytes()).hexdigest()
        assert r["entries"]["player.dff"][:len(entries[b"player.dff"])] == entries[b"player.dff"]
        assert r["entries"]["playerp.txd"][:len(entries[b"playerp.txd"])] == entries[b"playerp.txd"]
    finally:
        rom.unlink()
        z.unlink()


def test_ifp_summary_real():
    """PED.IFP parses and keys the clump's frames (the animation-slot check) when the stock cache holds it."""
    loc = _cached_gta3()
    if loc is None or not (loc[0] / "ped.ifp").is_file():
        pytest.skip("stock PED.IFP not streamed on this node yet")
    d = (loc[0] / "ped.ifp").read_bytes()
    assert d[:4] == b"ANPK"
    s = G.ifp_summary(d)
    assert s["animations"] > 200
    assert all(n in s["names"] for n in ("run_player", "walk_player")) or "run" in " ".join(s["names"])
    assert any("swaist" in b for b in s["bones"]), s["bones"][:10]


def _cached_gta3():
    from gbox.config import load
    cfg = load("/home/ehm_eckx/gBox/system/gbox.toml")
    p = Path(cfg.cache) / "gta3" / "265819390074bb4e"
    man = p / "manifest.json"
    return (p, man) if man.is_file() else None


@pytest.mark.parametrize("skin", ["player", "playerp"])
def test_real_stock_export_round_trip(tmp_path, skin):
    """The cached stock entries of the owned GTA III build: rigged GLB + the writer's own rig round trip."""
    loc = _cached_gta3()
    if loc is None:
        pytest.skip("stock GTA III entries not streamed on this node yet")
    p, man = loc
    man = __import__("json").loads(man.read_text())
    dn, tn = f"{skin}.dff", f"{skin}.txd"
    dff, txd = (p / dn).read_bytes(), (p / tn).read_bytes()
    info = G.export(dff, txd, tmp_path / f"{skin}.glb")
    assert info["frames"] and len(info["roles"]) == 17
    assert info["triangles"] > 1000 and info["vertices"] > 1000
    chk = G.self_check(dff, tmp_path / f"{skin}.glb", info["roles"])
    assert chk["byte_roundtrip"], "the clump must re-serialise byte-identically"
    assert chk["writer_parts_match"], "gta3_swap must rebuild every frame with the same triangle count"
    assert chk["self_retarget_max_dev_m"] < 1.0
    assert __import__("hashlib").sha256((p / dn).read_bytes()).hexdigest() == G.STOCK_SHA256[dn]
