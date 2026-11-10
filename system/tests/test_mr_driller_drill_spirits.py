import hashlib, os, struct, glob, pytest
from gbox import mr_driller_drill_spirits as mod


def _pak(members):
    hs = 8 + 4 * (len(members) + 1)
    offs, o = [], hs
    for m in members:
        offs.append(o); o += len(m)
    offs.append(o)
    return b"PAK0" + struct.pack("<HH", hs, len(members)) + struct.pack("<%dI" % len(offs), *offs) + b"".join(members)


def test_pak_members_roundtrip():
    ms = [b"\xe0\x03" * 32, b"abcd" * 8]
    blob = _pak(ms)
    got = mod.pak_members(blob)
    assert [blob[o:o + n] for o, n in got] == ms


def test_pak_rejects_bad():
    with pytest.raises(ValueError):
        mod.pak_members(b"XXXX" + bytes(20))


ROM = os.environ.get("DRILLER_ROM") or next(iter(glob.glob(os.path.expanduser("~/.hermes/cache/scratch/drill/*.nds"))), None)
EXPECT = "47f60500db0f91cf6bbed1b0199494be00ac1b1771339a71601715466bb9f452"


@pytest.mark.skipif(not ROM or not os.path.exists(ROM), reason="owned ROM not available")
def test_owned_rom_inventory():
    rom = open(ROM, "rb").read()
    if hashlib.sha256(rom).hexdigest() != EXPECT:
        pytest.skip("different build")
    inv = mod.inventory(rom)
    assert inv["header"]["gamecode"] == "ADRE" and inv["file_count"] == 45
    t = inv["target"]
    assert len(t["members"]) == 8 and t["size"] == 303180
    assert all(m["pal0_key"] == 0x03E0 for m in t["members"])


def test_split_member_synthetic():
    m = struct.pack("<16H", *range(16)) * 2 + bytes(1024) + b"xx"
    s = mod.split_member(m)
    assert s["cells"] == 2 and s["remainder"] == 2 and s["palettes"][1][15] == 15
    with pytest.raises(ValueError):
        mod.split_member(b"short")


def test_seam_by_width_detects_stride():
    # smooth 32x32 picture cut into 4x4 row-major tiles, 4 cells: true stride is 4 tiles
    def px(x, y):
        return ((x // 3) + (y // 3)) % 16
    cell = bytearray()
    for ty in range(4):
        for tx in range(4):
            for y in range(8):
                for x in range(0, 8, 2):
                    lo = px(tx * 8 + x, ty * 8 + y)
                    hi = px(tx * 8 + x + 1, ty * 8 + y)
                    cell.append(lo | (hi << 4))
    body = bytes(cell) * 4
    sc = {w: mod.seam_by_width(body, w) for w in (3, 5, 6, 7)}
    assert mod.seam_by_width(body, 4) > max(sc.values()), sc
    with pytest.raises(ValueError):
        mod.seam_by_width(body, 999)


@pytest.mark.skipif(not ROM or not os.path.exists(ROM), reason="owned ROM not available")
def test_owned_rom_cell_layout_peak():
    rom = open(ROM, "rb").read()
    if hashlib.sha256(rom).hexdigest() != EXPECT:
        pytest.skip("different build")
    f = {x.path: x for x in mod.list_files(rom)}[mod.TARGET_PATH]
    blob = rom[f.start:f.start + f.size]
    for i in (0, 3, 6):
        o, n = mod.pak_members(blob)[i]
        s = mod.split_member(blob[o:o + n])
        assert s["remainder"] == 0
        sc = {w: mod.seam_by_width(s["body"], w) for w in (3, 4, 5, 6, 7)}
        assert max(sc, key=sc.get) == 4, sc
