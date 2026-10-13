"""gbox.live_inject on synthetic RAM and a fake paused/resumable emulator: locate, plan, verified write, rollback,
relocation (POF0 and learned), arenas, refusals, containers. No game files."""
import struct

import pytest

from gbox import live_inject as LI, ninja, pick_ram as R
from gbox.formats.lz import prs_compress

DC = 0x8C000000


class FakeEmu:
    """RAM + run state. drop_writes: writes after the n-th are ignored (a lying emulator); swapped: N64 LE words."""

    def __init__(self, data: bytes, base: int, state="RUNNING", swapped=False):
        self.mem, self.base, self.state, self.swapped = bytearray(data), base, state, swapped
        self.writes, self.drop_after, self.pauses = [], None, 0
        self.name = "fake"

    def _dev(self, b):
        return R.swap32(bytes(b)) if self.swapped else bytes(b)

    def read_memory(self, a, n):
        return self._dev(self.mem[a - self.base:a - self.base + n]) if not self.swapped else \
            R.swap32(bytes(self.mem[a - self.base:a - self.base + n]))

    def write_memory(self, a, data):
        self.writes.append((a, bytes(data)))
        if self.drop_after is not None and len(self.writes) > self.drop_after:
            return {"written": len(data)}
        raw = R.swap32(bytes(data)) if self.swapped else bytes(data)
        self.mem[a - self.base:a - self.base + len(raw)] = raw
        return {"written": len(data)}

    def query_runtime(self):
        return {"state": self.state}

    def pause(self):
        self.pauses += 1
        self.state = "PAUSED"
        return {"state": "PAUSED"}

    def resume(self):
        self.state = "RUNNING"
        return {"state": "RUNNING"}


def ram_of(emu, platform="dreamcast", big=False):
    data = bytes(emu.mem)
    return R.Ram(data, emu.base, big, platform, emu.swapped)


def pattern(n, seed=1):
    return bytes((i * 7 + seed * 13 + (i >> 5)) & 0xFF for i in range(n))


# ---------------------------------------------------------------- raw same-size diff

def setup_raw():
    orig = pattern(0x400)
    new = bytearray(orig)
    new[0x100:0x120] = b"\xAA" * 0x20
    new[0x300:0x304] = b"\x01\x02\x03\x04"
    buf = bytearray(0x40000)
    at = DC + 0x10000
    buf[at - DC:at - DC + len(orig)] = orig
    return orig, bytes(new), buf, at


def test_raw_diff_is_written_paused_verified_and_the_pause_state_is_kept():
    orig, new, buf, at = setup_raw()
    for start in ("RUNNING", "PAUSED"):
        emu = FakeEmu(buf, DC, start)
        ram = ram_of(emu)
        pl = LI.plan(ram, [LI.asset("CHAR.BIN", orig, new)])
        assert pl["ok"] and pl["assets"][0]["instances"][0]["base"] == hex(at)
        assert sum(len(w["data"]) for w in pl["writes"]) == 0x24              # only the changed bytes
        rep = LI.apply(emu, ram, pl["writes"])
        assert rep["verified"] and rep["pause_preserved"]
        assert bytes(emu.mem[at - DC:at - DC + len(new)]) == new
        assert emu.state == start and rep["paused_by_gbox"] == (start == "RUNNING")


def test_ram_that_changed_since_the_snapshot_is_never_written():
    orig, new, buf, at = setup_raw()
    emu = FakeEmu(buf, DC)
    ram = ram_of(emu)
    pl = LI.plan(ram, [LI.asset("CHAR.BIN", orig, new)])
    emu.mem[at - DC + 0x101] ^= 0xFF                       # the game moved on
    with pytest.raises(RuntimeError, match="changed since the snapshot"):
        LI.apply(emu, ram, pl["writes"])
    assert emu.writes == [] and emu.state == "RUNNING"


def test_a_write_that_does_not_read_back_is_rolled_back():
    orig, new, buf, at = setup_raw()
    emu = FakeEmu(buf, DC)
    pl = LI.plan(ram_of(emu), [LI.asset("CHAR.BIN", orig, new)])
    assert len(pl["writes"]) == 2

    class Lossy(FakeEmu):                                  # the second write reports success but never lands
        def write_memory(self, a, data):
            if len(self.writes) == 1:
                self.writes.append((a, bytes(data)))
                return {"written": len(data)}
            return super().write_memory(a, data)
    emu = Lossy(buf, DC)
    with pytest.raises(RuntimeError, match="read-back mismatch.*restored"):
        LI.apply(emu, ram_of(emu), pl["writes"])
    assert bytes(emu.mem[at - DC:at - DC + len(orig)]) == orig and emu.state == "RUNNING"

    class Stuck(FakeEmu):                                  # only the first write lands: the rollback can't verify
        def write_memory(self, a, data):
            self.writes.append((a, bytes(data)))
            if len(self.writes) == 1:
                self.mem[a - self.base:a - self.base + len(data)] = data
            return {"written": len(data)}
    emu = Stuck(buf, DC)
    with pytest.raises(RuntimeError, match="left paused"):
        LI.apply(emu, ram_of(emu), pl["writes"])
    assert emu.state == "PAUSED"                           # a half-written model is never resumed


def test_runtime_modified_bytes_inside_the_replaced_range_refuse_the_instance():
    orig, new, buf, at = setup_raw()
    buf[at - DC + 0x108] ^= 0x55                            # e.g. a skinned vertex the game rewrites every frame
    pl = LI.plan(R.Ram(bytes(buf), DC, False, "dreamcast"), [LI.asset("CHAR.BIN", orig, new)])
    assert not pl["ok"] and "runtime" in pl["reason"]
    assert LI.plan(R.Ram(bytes(0x40000), DC, False, "dreamcast"), [LI.asset("CHAR.BIN", orig, new)])["reason"].endswith(
        "keeps it in another form)")


def test_executables_are_never_live_patched():
    with pytest.raises(LI.Unplaceable, match="executable"):
        LI.expand("1ST_READ.BIN", b"a" * 8, b"b" * 8)
    with pytest.raises(LI.Unplaceable):
        LI.expand("SYS/main.dol", b"a" * 8, b"b" * 8)


# ---------------------------------------------------------------- relocated pointers (learned from the instance)

def test_heuristic_relocation_moves_changed_pointers_with_the_load_address():
    orig = bytearray(pattern(0x200))
    ptrs = [0x20, 0x80, 0x100]
    for p in ptrs:
        struct.pack_into("<I", orig, p, 0x40 + p)
    new = bytearray(orig)
    struct.pack_into("<I", new, 0x80, 0x1F0)               # the writer re-pointed one field (same layout)
    new[0x150:0x160] = b"\x77" * 16
    at = DC + 0x20000
    buf = bytearray(0x40000)
    loaded = bytearray(orig)
    for p in ptrs:
        struct.pack_into("<I", loaded, p, at + 0x40 + p)
    buf[at - DC:at - DC + len(loaded)] = loaded
    emu = FakeEmu(buf, DC)
    ram = ram_of(emu)
    pl = LI.plan(ram, [LI.asset("MDL", bytes(orig), bytes(new))])
    assert pl["ok"], pl["reason"]
    LI.apply(emu, ram, pl["writes"])
    assert struct.unpack_from("<I", emu.mem, at - DC + 0x80)[0] == at + 0x1F0
    assert struct.unpack_from("<I", emu.mem, at - DC + 0x20)[0] == at + 0x60      # untouched pointer stays relocated


def test_a_new_pointer_where_the_original_had_data_is_refused_without_a_pointer_table():
    orig = bytearray(pattern(0x200))
    struct.pack_into("<I", orig, 0x20, 0x60)
    new = bytearray(orig)
    struct.pack_into("<I", new, 0x40, 0x100)               # looks like an offset; was data
    at = DC + 0x20000
    buf = bytearray(0x40000)
    loaded = bytearray(orig)
    struct.pack_into("<I", loaded, 0x20, at + 0x60)
    buf[at - DC:at - DC + len(loaded)] = loaded
    pl = LI.plan(R.Ram(bytes(buf), DC, False, "dreamcast"), [LI.asset("MDL", bytes(orig), bytes(new))])
    assert not pl["ok"] and "pointer" in pl["reason"]


# ---------------------------------------------------------------- Ninja (NJCM + POF0): whole replacement

def nj_file(n_nodes=3, verts=4):
    trs = struct.pack("<3f3i3f", 0, 0, 0, 0, 0, 0, 1, 1, 1)
    nodes = [{"flags": 0x0C, "trs": trs, "child": i + 1 if i + 1 < n_nodes else None, "sibling": None}
             for i in range(n_nodes)]
    vl = struct.pack("<HH", 0x29, 2 + 6 * verts) + struct.pack("<HH", 0, verts) + b"".join(
        struct.pack("<3f3f", k, k * 2.0, 1.0, 0, 1, 0) for k in range(verts)) + struct.pack("<HH", 0xFF, 0)
    pl = struct.pack("<HH", 0x40, 2) + b"\x00" * 4 + struct.pack("<HH", 0xFF, 0)
    models = {i: (vl, pl, [0.0, 1.0, 0.0], 2.0) for i in range(n_nodes)}
    data, root, ptrs = ninja.write_tree(nodes, models, 0)
    return b"NJCM" + struct.pack("<I", len(data)) + data + ninja.pof0(ptrs), data, ptrs


def load_nj(buf, at, data, ptrs):
    b = bytearray(data)
    for p in ptrs:
        struct.pack_into("<I", b, p, struct.unpack_from("<I", b, p)[0] + at)
    buf[at - DC:at - DC + len(b)] = b


def test_ninja_image_reads_njcm_and_pof0():
    f, data, ptrs = nj_file()
    img, got = LI.ninja_image(f)
    assert img == data and got == sorted(ptrs)


def test_ninja_model_replaced_in_place_when_it_fits():
    big, data, ptrs = nj_file(3, 8)
    small, sdata, sptrs = nj_file(3, 3)
    [a], _ = LI.expand("PL.NJ", big, small)
    assert a["whole"] and a["orig_ptrs"] == sorted(ptrs)
    at, ent = DC + 0x20000, DC + 0x8000
    buf = bytearray(0x40000)
    load_nj(buf, at, data, ptrs)
    struct.pack_into("<I", buf, ent - DC + 0x34, at)       # the entity's model pointer -> root node
    emu = FakeEmu(buf, DC)
    ram = ram_of(emu)
    assert R.ninja_tree(ram, at)["nodes"] == 3
    pl = LI.plan(ram, [a], hint=at)
    assert pl["ok"], pl["reason"]
    LI.apply(emu, ram, pl["writes"])
    after = R.Ram(bytes(emu.mem), DC, False, "dreamcast")
    t = R.ninja_tree(after, at)
    assert t["nodes"] == 3 and t["chunk_models"] == 3
    m0 = after.u32(at + 4)
    assert after.read(after.u32(m0) + 4, 4) == struct.pack("<HH", 0, 3)        # its vertex chunk: 3 vertices now
    assert after.u32(ent + 0x34) == at


def test_a_larger_ninja_model_needs_a_declared_arena_and_repoints_its_owner():
    small, sdata, sptrs = nj_file(3, 3)
    big, bdata, bptrs = nj_file(3, 12)
    [a], _ = LI.expand("PL.NJ", small, big)
    at, ent = DC + 0x20000, DC + 0x8000
    buf = bytearray(b"\x11" * 0x80000)
    buf[0x40000:0x60000] = bytes(0x20000)                  # free (zero, unowned)
    load_nj(buf, at, sdata, sptrs)
    struct.pack_into("<I", buf, ent - DC + 0x34, 0x0C000000 | (at & 0xFFFFFF))   # P0 alias form
    ram = R.Ram(bytes(buf), DC, False, "dreamcast")
    pl = LI.plan(ram, [a])
    assert not pl["ok"] and "arena" in pl["reason"]
    emu = FakeEmu(buf, DC)
    pl = LI.plan(ram_of(emu), [a], arenas=[(DC + 0x40000, DC + 0x60000)])
    assert pl["ok"], pl["reason"]
    LI.apply(emu, ram_of(emu), pl["writes"])
    after = R.Ram(bytes(emu.mem), DC, False, "dreamcast")
    new_root = after.u32(ent + 0x34)
    assert new_root >> 24 == 0x0C and DC + 0x40000 <= (0x8C000000 | (new_root & 0xFFFFFF)) < DC + 0x60000
    t = R.ninja_tree(after, 0x8C000000 | (new_root & 0xFFFFFF))
    assert t and t["nodes"] == 3


def test_a_whole_replacement_refuses_when_something_points_into_the_model():
    big, data, ptrs = nj_file(3, 8)
    small, _sd, _sp = nj_file(3, 3)
    [a], _ = LI.expand("PL.NJ", big, small)
    at = DC + 0x20000
    buf = bytearray(0x40000)
    load_nj(buf, at, data, ptrs)
    struct.pack_into("<I", buf, 0x100, at + 0x34)          # a sub-tree table entry pointing at node 1
    pl = LI.plan(R.Ram(bytes(buf), DC, False, "dreamcast"), [a])
    assert not pl["ok"] and "point into the loaded model" in pl["reason"]


# ---------------------------------------------------------------- containers, patch, signatures, folders

def test_containers_prs_and_afs_expand_to_their_changed_members():
    orig, new = pattern(0x300, 2), bytearray(pattern(0x300, 2))
    new[0x40:0x48] = b"\x99" * 8
    [a], _ = LI.expand("SONICMDL.PRS", prs_compress(orig), prs_compress(bytes(new)))
    assert a["name"] == "SONICMDL.PRS#prs" and a["orig"] == orig and a["new"] == bytes(new)

    def afs(entries):
        hdr = bytearray(b"AFS\0" + struct.pack("<I", len(entries)))
        off = 0x800
        body = bytearray()
        for e in entries:
            hdr += struct.pack("<II", off + len(body), len(e))
            body += e + bytes((-len(e)) % 0x800)
        return bytes(hdr + bytes(0x800 - len(hdr)) + body)
    ents = [pattern(0x100, 3), pattern(0x100, 4)]
    changed = [ents[0], bytes(new[:0x100])]
    out, _ = LI.expand("PLAYER.AFS", afs(ents), afs(changed))
    assert [x["name"] for x in out] == ["PLAYER.AFS[1]"]


def test_patch_round_trip_and_learned_signatures_find_the_model():
    orig, new, buf, at = setup_raw()
    assets = [LI.asset("CHAR.BIN", orig, new)]
    back, meta = LI.unpack(LI.pack(assets, {"mod": "m", "slot": "player"}))
    assert back[0]["orig"] == orig and back[0]["new"] == new and meta["slot"] == "player"
    sig = LI.signatures(assets)
    hits = LI.find_signatures(R.Ram(bytes(buf), DC, False, "dreamcast"), sig)
    assert hits and hits[0]["base"] == at


def test_mod_files_of_a_folder_mod(tmp_path):
    import json
    base, mod = tmp_path / "base", tmp_path / "mod"
    (base / "DATA").mkdir(parents=True)
    (mod / "DATA").mkdir(parents=True)
    (base / "DATA" / "A.BIN").write_bytes(b"old!")
    (mod / "DATA" / "A.BIN").write_bytes(b"new!")
    (mod / ".gbox-mod.json").write_text(json.dumps({"name": "m", "files": ["DATA/A.BIN", "DATA/B.BIN (new)"]}))
    pairs, _ = LI.mod_files(mod, base)
    assert pairs == [("DATA/A.BIN", b"old!", b"new!")]


def iso_image(path, files: dict):
    """A minimal cooked ISO9660 image (PVD at 16, root directory at 18, files from 20)."""
    def rec(name: bytes, lba, size, flags):
        n = len(name)
        r = bytearray(33 + n + (1 - n % 2))
        r[0] = len(r)
        struct.pack_into("<I", r, 2, lba)
        struct.pack_into(">I", r, 6, lba)
        struct.pack_into("<I", r, 10, size)
        struct.pack_into(">I", r, 14, size)
        r[25], r[28], r[32] = flags, 1, n
        r[33:33 + n] = name
        return bytes(r)
    img = bytearray(2048 * 20)
    img[2048 * 16] = 1
    img[2048 * 16 + 1:2048 * 16 + 6] = b"CD001"
    img[2048 * 16 + 156:2048 * 16 + 156 + 34] = rec(b"\0", 18, 2048, 2)
    d = rec(b"\0", 18, 2048, 2) + rec(b"\1", 18, 2048, 2)
    lba = 20
    for name, data in files.items():
        d += rec(name.encode() + b";1", lba, len(data), 0)
        img += data + bytes((-len(data)) % 2048)
        lba += (len(data) + 2047) // 2048
    img[2048 * 18:2048 * 18 + len(d)] = d
    path.write_bytes(bytes(img))


def test_mod_files_of_a_ps2_style_iso_image_and_an_unlisted_change(tmp_path):
    import json
    base, mod = tmp_path / "game.iso", tmp_path / "mod"
    mod.mkdir()
    iso_image(base, {"DATA.BIN": pattern(3000, 1), "KEEP.BIN": pattern(100, 2)})
    iso_image(mod / "game.iso", {"DATA.BIN": pattern(3000, 3), "KEEP.BIN": pattern(100, 2)})
    (mod / ".gbox-mod.json").write_text(json.dumps({"name": "m", "image": "game.iso", "files": ["/data.bin"]}))
    pairs, _ = LI.mod_files(mod, base)
    assert [(n, len(a), len(b)) for n, a, b in pairs] == [("/data.bin", 3000, 3000)]
    (mod / ".gbox-mod.json").write_text(json.dumps({"name": "m", "image": "game.iso"}))   # no file list: compared
    pairs, _ = LI.mod_files(mod, base)
    assert [n for n, _a, _b in pairs] == ["DATA.BIN"]


def test_word_swapped_rdram_writes_whole_swapped_words():
    base = 0x80000000
    orig = pattern(0x100, 5)
    new = bytearray(orig)
    new[0x41] ^= 0xFF                                      # one byte: widened to its word on a swapped device
    buf = bytearray(0x10000)
    struct.pack_into(">I", buf, 0x180, R.N64_RESET_WORD)
    buf[0x2000:0x2100] = orig
    emu = FakeEmu(buf, base, swapped=True)
    ram = R.Ram.snapshot(emu, "n64", region=(base, 0x10000))
    assert ram.swapped and ram.data == bytes(buf)
    pl = LI.plan(ram, [LI.asset("OBJ", orig, bytes(new))])
    rep = LI.apply(emu, ram, pl["writes"])
    assert rep["verified"] and bytes(emu.mem[0x2000:0x2100]) == bytes(new)
    assert all(a % 4 == 0 and len(d) % 4 == 0 for a, d in emu.writes)
