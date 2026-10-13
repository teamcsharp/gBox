"""gbox.formats: shared codecs, disc walkers, texture/rig helpers, the routine oracle and instruction patterns, with
synthetic round trips (no game data), plus checks that the migrated title modules still answer through them."""
import io
import random
import struct
import zlib

import numpy as np
import pytest

from gbox import formats
from gbox.formats import gcfst, insn_pattern as ip, iso9660, lz, oracle, rig, texture

RNG = random.Random(1234)


def sample(n: int) -> bytes:
    b = bytearray()
    while len(b) < n:
        if b and RNG.random() < 0.55:
            s = RNG.randrange(len(b))
            b += b[s:s + RNG.randrange(1, 60)]
        else:
            b += bytes(RNG.randrange(5) for _ in range(RNG.randrange(1, 9)))
    return bytes(b[:n])


DATA = [b"", b"x", b"\0" * 300, bytes(range(256)) * 3] + [sample(RNG.randrange(1, 2500)) for _ in range(12)]


# ---------------------------------------------------------------- codecs

@pytest.mark.parametrize("d", DATA)
def test_lz_round_trips(d):
    assert lz.prs_decompress(lz.prs_compress(d)) == d
    assert lz.prs_msb_decompress(lz.prs_msb_compress(d), len(d)) == d
    assert lz.yaz0_decompress(lz.yaz0_compress(d)) == d
    assert lz.lzss_decompress(lz.lzss_compress(d))[0] == d
    if d:
        assert lz.mio0_decompress(lz.mio0_compress(d)) == d


def test_title_modules_answer_through_the_shared_codecs():
    from gbox import aki_wrestling, cnr2, con2_inventory, ff7_models, mm64_inventory, ninja, oot_writer, sf64_inventory
    from gbox import sm64_mario, ssb64_inventory, tetris_ds, turok_inventory
    d = DATA[-1]
    assert ninja.prs_decompress is lz.prs_decompress and ninja.prs_compress is lz.prs_compress
    assert oot_writer.yaz0_decompress is lz.yaz0_decompress and mm64_inventory.lzss_decompress is lz.lzss_decompress
    assert ssb64_inventory.vpk0_decode is lz.vpk0_decode and tetris_ds.lz10_decompress is lz.lz10_decompress
    assert turok_inventory.decode_rnc is formats.rnc.decode_rnc
    p = lz.prs_msb_compress(d)
    assert cnr2.prs_decompress(p, len(d)) == con2_inventory.prs_decompress(p, len(d)) == d
    m = b"pad!" + lz.mio0_compress(d)
    assert sm64_mario.mio0(m, 4) == d and sf64_inventory.mio0_decompress(m[4:]) == d
    z = lz.lzss_compress(d)
    assert ff7_models.lzs(struct.pack("<I", len(z)) + z) == d
    assert aki_wrestling.lzss(b"\0" + len(d).to_bytes(3, "big") + z) == d


def test_mio0_strict_errors_and_header():
    m = lz.mio0_compress(b"abcabcabcabc")
    assert lz.mio0_header(m) == (12, 16 + 4, struct.unpack_from(">I", m, 12)[0])
    with pytest.raises(ValueError):
        lz.mio0_decompress(b"MIO1" + m[4:])
    with pytest.raises(ValueError):
        lz.mio0_decompress(m[:-3])                          # raw section cut


def test_prs_msb_strict_size_and_cnr2_window():
    p = lz.prs_msb_compress(b"hello hello hello")
    with pytest.raises(ValueError, match="produced"):
        lz.prs_msb_decompress(p, 40)
    assert len(lz.prs_msb_decompress(p, 40, strict=False)) == 40


def test_lz10_literal_stream_and_inflate_variants():
    raw = b"literal-only LZ10!"
    s = bytearray([0x10]) + len(raw).to_bytes(3, "little")
    for k in range(0, len(raw), 8):
        s += b"\0" + raw[k:k + 8]
    assert lz.lz10_decompress(bytes(s)) == raw
    d = sample(4000)
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    rawdef = co.compress(d) + co.flush()
    import gzip
    assert lz.inflate(zlib.compress(d)) == lz.inflate(gzip.compress(d)) == lz.inflate(rawdef) == d


def test_rnc_rejects_and_crc():
    from gbox.formats import rnc
    assert rnc.crc16(b"123456789") == 0xBB3D               # CRC-16/ARC check value
    with pytest.raises(ValueError):
        rnc.decode_rnc(b"RNC\x03" + bytes(20))


def test_refpack_facade():
    from gbox import refpack
    assert lz.refpack_decompress(refpack.compress_literal(b"refpack!")) == b"refpack!"


# ---------------------------------------------------------------- disc filesystems

def build_iso(tree: dict) -> bytes:
    """Minimal ISO9660: PVD at 16, directories and files laid out from LBA 20. tree: {name: bytes | dict}."""
    sectors: dict[int, bytes] = {}
    nxt = [20]

    def alloc(n):
        a = nxt[0]
        nxt[0] += max(1, (n + 2047) // 2048)
        return a

    def rec(name: bytes, lba, size, is_dir):
        r = bytearray(33 + len(name) + (1 - len(name) % 2))
        r[0] = len(r)
        struct.pack_into("<I", r, 2, lba)
        struct.pack_into(">I", r, 6, lba)
        struct.pack_into("<I", r, 10, size)
        struct.pack_into(">I", r, 14, size)
        r[25] = 2 if is_dir else 0
        r[32] = len(name)
        r[33:33 + len(name)] = name
        return bytes(r)

    def place(node) -> tuple[int, int]:
        lba = alloc(2048 * 3)
        recs = [rec(b"\0", lba, 6144, True), rec(b"\1", lba, 6144, True)]
        for name, v in node.items():
            if isinstance(v, dict):
                sl, ss = place(v)
                recs.append(rec(name.encode(), sl, ss, True))
            else:
                fl = alloc(len(v))
                sectors[fl] = v
                recs.append(rec(name.encode() + b";1", fl, len(v), False))
        buf, cur = bytearray(), bytearray()
        for r in recs:                                     # records never cross a sector
            if len(cur) + len(r) > 2048:
                buf += cur + bytes(2048 - len(cur))
                cur = bytearray()
            cur += r
        buf += cur + bytes(2048 - len(cur))
        sectors[lba] = bytes(buf)
        return lba, len(buf)

    root_lba, root_size = place(tree)
    pvd = bytearray(2048)
    pvd[0:6] = b"\x01CD001"
    pvd[8:40] = b"PLAYSTATION".ljust(32)
    pvd[156:156 + 34] = rec(b"\0", root_lba, root_size, True)
    sectors[16] = bytes(pvd)
    img = bytearray(2048 * nxt[0])
    for lba, data in sectors.items():
        img[lba * 2048:lba * 2048 + len(data)] = data
    return bytes(img)


TREE = {"SYSTEM.CNF": b"BOOT2 = cdrom0:\\SLUS_123.45;1\n", "SLUS_123.45": b"\x7fELF" + bytes(60),
        "DATA": {"MODEL.BIN": b"NJCM" + bytes(100), "TEX": {"A.TIM": b"\x10\0\0\0\x09\0\0\0" + bytes(40)}},
        **{f"F{i:03d}.DAT": bytes([i]) * (i + 1) for i in range(90)}}       # > one directory sector


def test_iso9660_walk_and_every_migrated_reader_agree(tmp_path):
    img = build_iso(TREE)
    f = io.BytesIO(img)
    lba, size = iso9660.pvd_root(img[16 * 2048:17 * 2048])
    table = iso9660.files(iso9660.file_reader(f), lba, size)
    assert table["DATA/TEX/A.TIM"][1] == 48 and table["F089.DAT"][1] == 90 and len(table) == 94
    from gbox import defjam_inventory, raidou2_inventory, romexport
    assert raidou2_inventory.iso_files(io.BytesIO(img)) == {"/" + k: v for k, v in table.items()}
    rx = romexport.iso_files(io.BytesIO(img))
    assert {k: v[1:] for k, v in rx.items()} == {k.upper(): v for k, v in table.items()}
    off, lba_t, size_t = rx["DATA/TEX/A.TIM"]
    rec_at = img[off:off + 40]
    assert struct.unpack_from("<I", rec_at, 2)[0] == lba_t and rec_at[33:38] == b"A.TIM"
    p = tmp_path / "game.iso"
    p.write_bytes(img)
    iso = defjam_inventory.Iso(p)
    assert iso.files == {k.upper(): v for k, v in table.items()} and iso.read("DATA/MODEL.BIN")[:4] == b"NJCM"


def test_iso9660_bounds():
    img = build_iso({"A": {"B": {"C": {"D.BIN": b"d"}}}})
    lba, size = iso9660.pvd_root(img[16 * 2048:17 * 2048])
    read = iso9660.file_reader(io.BytesIO(img))
    assert iso9660.files(read, lba, size, max_depth=2) == {}
    with pytest.raises(ValueError, match="too deep"):
        iso9660.files(read, lba, size, max_depth=2, too_deep="raise")
    bad = bytearray(img)
    bad[lba * 2048 + 68] = 10                               # a 10-byte record: malformed
    assert iso9660.files(iso9660.file_reader(io.BytesIO(bytes(bad))), lba, size) == {}
    with pytest.raises(ValueError, match="bad ISO9660"):
        iso9660.files(iso9660.file_reader(io.BytesIO(bytes(bad))), lba, size, strict=True)


def build_gc_disc(files: dict[str, bytes], game_id=b"GTST01", title=b"Synthetic") -> bytes:
    disc = bytearray(0x10000)
    disc[0:6] = game_id
    disc[0x1C:0x20] = struct.pack(">I", 0xC2339F3D)
    disc[0x20:0x20 + len(title)] = title
    dol = bytearray(0x200)
    struct.pack_into(">I", dol, 0, 0x100)                  # text0 offset
    struct.pack_into(">I", dol, 0x48, 0x80003100)
    struct.pack_into(">I", dol, 0x90, 0x100)               # text0 size
    dol_off, pos, entries = 0x2000, 0x3000, []
    disc[dol_off:dol_off + len(dol)] = dol
    for name, data in files.items():
        disc[pos:pos + len(data)] = data
        entries.append((name, pos, len(data)))
        pos = (pos + len(data) + 31) & ~31
    fst = gcfst.build_fst(entries)
    fst_off = pos
    disc[fst_off:fst_off + len(fst)] = fst
    struct.pack_into(">III", disc, 0x420, dol_off, fst_off, len(fst))
    return bytes(disc[:max(fst_off + len(fst), 0x3000)])


def test_gc_fst_round_trip_and_gcdisc(tmp_path):
    files = {"opening.bnr": b"BNR1", "ct/polDC0.all": b"\0" * 70, "ct/sub/cube0.shp": b"shape", "z.tpl": b"\x00\x20\xaf\x30"}
    img = build_gc_disc(files)
    h = gcfst.disc_header(img[:0x440])
    ents = gcfst.parse_fst(img[h["fst_offset"]:h["fst_offset"] + h["fst_size"]], h["fst_offset"])
    assert {p for p, *_ in ents} == set(files)
    p = tmp_path / "g.iso"
    p.write_bytes(img)
    from gbox.gcdisc import GCDisc
    g = GCDisc(p)
    assert g.read("ct/sub/cube0.shp") == b"shape" and g.game_id == "GTST01"
    assert struct.unpack_from(">I", img, g.entries["z.tpl"] + 8)[0] == 4


def test_disc_listing_on_iso_gc_and_folder(tmp_path):
    from gbox.formats import disc
    (tmp_path / "ps2.iso").write_bytes(build_iso(TREE))
    L = disc.listing(tmp_path / "ps2.iso")
    assert L.kind == "iso9660" and L.executable_name == "SLUS_123.45" and L.executable[:4] == b"\x7fELF"
    assert next(f for f in L.files if f["path"] == "DATA/MODEL.BIN")["head"][:4] == b"NJCM"
    (tmp_path / "gc.iso").write_bytes(build_gc_disc({"a.nj": b"NJTL" + bytes(12)}))
    G = disc.listing(tmp_path / "gc.iso")
    assert G.kind == "gc_disc" and G.executable_name == "main.dol" and G.files[0]["head"][:4] == b"NJTL"
    pc = tmp_path / "pc"
    (pc / "Paks").mkdir(parents=True)
    (pc / "Game.exe").write_bytes(b"MZ" + bytes(100))
    (pc / "Paks" / "a.pak").write_bytes(bytes(64))
    F = disc.listing(pc)
    assert F.kind == "folder" and F.executable_name == "Game.exe" and len(F.files) == 2


# ---------------------------------------------------------------- textures

def test_twiddle_helpers_and_their_users():
    from gbox import doa2_textures, mkgold_geo, ninja
    assert texture.morton(1, 0) == 2 and texture.morton(0, 1) == 1 and texture.morton(3, 3) == 15
    assert ninja._twiddle is texture.morton is doa2_textures._twiddle
    assert mkgold_geo.twiddled_index(5, 2, 16, 8) == texture.twiddled_index(5, 2, 16, 8)
    for w, h in ((8, 8), (16, 4), (4, 32)):
        lin = bytes(RNG.randrange(256) for _ in range(w * h * 2))
        assert texture.detwiddle(texture.twiddle(lin, w, h), w, h) == lin
        assert sorted(texture.twiddled_index(x, y, w, h) for y in range(h) for x in range(w)) == list(range(w * h))
        assert sorted(texture.twiddle_rect(x, y, w, h) for y in range(h) for x in range(w)) == list(range(w * h))


@pytest.mark.parametrize("fmt", sorted(texture.PIXEL16))
def test_pixels16_matches_scalar(fmt):
    words = [RNG.randrange(0x10000) for _ in range(200)] + [0, 0x8000, 0xFFFF]
    want = np.array([texture.PIXEL16[fmt](w) for w in words], np.uint8)
    assert (texture.pixels16(words, fmt) == want).all()


def test_tim_round_trip_and_rgba():
    from gbox import yukes_sd
    clut = np.arange(256, dtype="<u2") * 97
    tim = {"bpp": 1, "clut_xy": (0, 480, 256, 1), "clut": clut, "rect": (320, 0, 8, 4),
           "pix": np.arange(64, dtype=np.uint8).reshape(4, 16)}
    b = texture.tim_build(tim)
    assert yukes_sd.tim_build is texture.tim_build and b[:4] == b"\x10\0\0\0"
    back = texture.tim_parse(b)
    assert texture.tim_build(back) == b and back["rect"] == (320, 0, 8, 4)
    rgba = texture.tim_rgba(back)
    assert rgba.shape == (4, 16, 4) and tuple(rgba[0, 1]) == texture.psx15(97)
    t4 = dict(tim, bpp=0, clut=clut[:16], clut_xy=(0, 480, 16, 1))
    assert texture.tim_indices(texture.tim_parse(texture.tim_build(t4))).shape == (4, 32)


def test_gc_tiles_cover_the_block_grid():
    pts = list(texture.gc_tiles(8, 8, "RGB5A3"))
    assert pts[:5] == [(0, 0), (1, 0), (2, 0), (3, 0), (0, 1)] and len(set(pts)) == 64


# ---------------------------------------------------------------- rig role maps

PARENTS = [-1, 0, 1, 2, 2, 4, 5, 2, 7, 8, 0, 10, 11, 0, 13, 14]
WORLD = [(0, 10, 0), (0, 10, 0), (0, 14, 0), (0, 17, 0), (2, 15, 0), (3, 13, 0), (4, 12, 0), (-2, 15, 0), (-3, 13, 0),
         (-4, 12, 0), (1, 9, 0), (1, 5, 0), (1, 1, 0), (-1, 9, 0), (-1, 5, 0), (-1, 1, 0)]
ROLES = {"hip": 0, "chest": 2, "head": 3, "l_upper": 4, "l_fore": 5, "l_hand": 6, "r_upper": 7, "r_fore": 8, "r_hand": 9,
         "l_thigh": 10, "l_shin": 11, "l_foot": 12, "r_thigh": 13, "r_shin": 14, "r_foot": 15}


def test_check_role_map_and_role_of_joint():
    assert rig.check_role_map(PARENTS, WORLD, ROLES) == []
    swapped = dict(ROLES, l_hand=9, r_hand=6)
    bad = rig.check_role_map(PARENTS, WORLD, swapped)
    assert any("isn't below" in b for b in bad) and any("on the" in b for b in bad)
    assert rig.check_role_map(PARENTS, WORLD, {"hip": 0}) [0].startswith("no ")
    assert rig.check_role_map(PARENTS, WORLD, ROLES, drawn={0: 3}) != []
    jr = rig.role_of_joint({"roles": ROLES, "parent": PARENTS})
    assert jr[1] == "hip" and jr[6] == "l_hand"
    from gbox import pso_player, re4gc_enemies
    assert re4gc_enemies._role_of_joint is rig.role_of_joint
    assert pso_player.check_roles(PARENTS, WORLD, ROLES)[0].startswith("not the PSO player body tree")


# ---------------------------------------------------------------- oracle + instruction patterns

COPY = [0x10C00007, 0, 0x90880000, 0x24840001, 0xA0A80000, 0x24A50001, 0x1000FFF9, 0x24C6FFFF, 0x03E00008, 0x00A01021]
FN = 0x80010000


def test_routine_oracle_runs_game_code_and_checks_an_inverse():
    ram = bytearray(0x200000)
    ram[0x10000:0x10000 + 40] = struct.pack("<10I", *COPY)
    o = oracle.RoutineOracle("mips_le", bytes(ram), ram_size=0x200000)
    v0, got = o.run(FN, inputs={0x80100000: b"oracle!"}, args=(0x80100000, 0x80120000, 7), read=(0x80120000, 7))
    assert got == b"oracle!" and v0 == 0x80120007

    def game_decode(blob):                                 # the "game's routine": copies the payload after a length
        n = struct.unpack_from("<I", blob)[0]
        return o.run(FN, inputs={0x80100000: blob[4:]}, args=(0x80100000, 0x80140000, n), read=(0x80140000, n))[1]
    good = oracle.check_inverse(lambda d: struct.pack("<I", len(d)) + d, game_decode, [b"a", b"bcd", bytes(300)])
    assert good == {"checked": 3, "matched": 3, "mismatches": []}
    bad = oracle.check_inverse(lambda d: struct.pack("<I", len(d)) + d[::-1], game_decode, [b"ab"])
    assert bad["mismatches"] == [{"index": 0, "size": 2, "first_diff": 0}]
    with pytest.raises(NotImplementedError, match="ghidra_bridge"):
        oracle.RoutineOracle("sh4")
    assert "ghidra_bridge" in oracle.oracle_route("ppc")


def test_insn_pattern_finds_the_routine_wherever_it_moved():
    # lui rS, hi ; addiu rV, $zero, 2 ; sw rV, lo(rS)  (MGS VR clear routine head), at two different addresses
    body = struct.pack("<3I", 0x3C03800E, 0x24020002, 0xAC622BB0)
    code = bytes(64) + body + bytes(32) + struct.pack("<3I", 0x3C05800F, 0x24040002, 0xACA41000) + bytes(16)
    pat = [ip.mips_lui("rS"), ip.Insn(0x24000002, 0xFFE0FFFF, {"rV": (16, 5)}), ip.mips_mem(0x2B, "rV", "rS", "lo")]
    hits = ip.search(code, pat, base=0x800C4350)
    assert [h.address - 0x800C4350 for h in hits] == [64, 108]
    assert ip.hi_lo(hits[0].fields["hi"], hits[0].fields["lo"]) == 0x800E2BB0
    broken = code[:72] + struct.pack("<I", 0xAC422BB0) + code[76:]     # sw through another register: no match
    assert len(ip.search(broken, pat)) == 1
    calls = ip.mips_jal_targets(struct.pack("<2I", 0x0C004000, 0), 0x80010000)
    assert calls == {0x80010000: [0x80010000]}
    ppc = struct.pack(">2I", 0x3C608040, 0x38631234)       # lis r3,0x8040 ; addi r3,r3,0x1234
    assert ip.ppc_lis_addi(ppc, 0x80003100) == {0x80401234: [0x80003100]}


def test_index_names_real_modules():
    import importlib
    for users in formats.INDEX.values():
        for u in users:
            name = u.split(" ")[0]
            if name.startswith(("formats.", "assimilate", "pattern")):
                continue
            importlib.import_module(f"gbox.{name}")
