"""gbox.pick_ram on synthetic RAM images (no game files): detectors, pointer walks, relocation-tolerant search,
texture re-encoding, free space."""
import struct

from gbox import pick_ram as R

DC = 0x8C000000


def dc_ram(size=0x100000):
    return bytearray(size)


def put(buf, base, addr, fmt, *v):
    struct.pack_into(fmt, buf, addr - base, *v)


def ninja_tree_at(buf, base, at, e="<", n=3, model_at=None):
    """n NJS_OBJECTs (root -> child -> child), each with a chunk model + a vertex chunk."""
    nodes = [at + 0x34 * i for i in range(n)]
    models = model_at or at + 0x34 * n + 0x40
    for i, a in enumerate(nodes):
        m = models + 0x40 * i
        put(buf, base, a, e + "II3f3i3fII", 0x0C if i else 0x00, m, 0.0, 10.0 * i, 0.0, 0, 0x4000 * i, 0, 1.0, 1.0, 1.0,
            nodes[i + 1] if i + 1 < n else 0, 0)
        vl = m + 0x18
        put(buf, base, m, e + "II4f", vl, 0, 0.0, 1.0, 0.0, 5.0)
        put(buf, base, vl, e + "I", (8 << 16) | 0x29 if e == "<" else (8 << 16) | 0x29)   # chunk type 0x29 (VN)
    return nodes, models


def test_ninja_tree_is_found_through_the_entity_struct_with_an_alias_pointer():
    buf = dc_ram()
    nodes, _ = ninja_tree_at(buf, DC, DC + 0x20000)
    ent = DC + 0x10000
    put(buf, DC, ent + 0x10, "<I", 0x0C000000 | (nodes[0] & 0xFFFFFF))       # P0 alias of the root
    put(buf, DC, ent + 0x14, "<f", 3.5)
    ram = R.Ram(bytes(buf), DC, False, "dreamcast")
    t = R.ninja_tree(ram, nodes[0])
    assert t and t["nodes"] == 3 and t["chunk_models"] == 3 and t["depth"] == 2
    found = R.walk(ram, ent, 0x40, depth=1)
    hit = next(f for f in found if f["at"] == nodes[0])
    assert hit["path"] == [(ent, 0x10)] and hit["found"][0]["kind"] == "ninja_object"
    assert R.ROLES[hit["found"][0]["kind"]] == "model"


def test_pointer_scan_matches_every_alias_and_back_chains_reach_a_root():
    buf = dc_ram()
    target = DC + 0x30000
    put(buf, DC, DC + 0x100, "<I", target)                 # P1
    put(buf, DC, DC + 0x200, "<I", 0xAC000000 | (target & 0xFFFFFF))   # P2
    put(buf, DC, DC + 0x300, "<I", 0x0C000000 | (target & 0xFFFFFF))   # P0
    table = DC + 0x8000
    put(buf, DC, table, "<I", DC + 0x200 - 0x10)            # a static table -> a struct holding the pointer at +0x10
    ram = R.Ram(bytes(buf), DC, False, "dreamcast")
    refs = {a for a, _v in ram.pointers_to(target, target + 1)}
    assert refs == {DC + 0x100, DC + 0x200, DC + 0x300}
    chains = R.back_chains(ram, target, depth=3, roots=lambda a: "table" if a == table else None)
    assert any(c[-1].get("root") == "table" and c[0]["at"] == DC + 0x200 for c in chains)


def test_n64_display_list_both_dialects_and_word_swapped_rdram():
    base, size = 0x80000000, 0x10000
    buf = bytearray(size)
    put(buf, base, base + 0x180, ">I", R.N64_RESET_WORD)
    dl = base + 0x1000
    cmds = [(0x01, 0x80002000), (0x05000204, 0), (0x06000204, 0x00060402), (0xDF000000, 0)]
    for i, (w0, w1) in enumerate(cmds):
        put(buf, base, dl + 8 * i, ">II", w0 << 24 if w0 < 0x100 else w0, w1)
    f3d = base + 0x2000
    for i, (w0, w1) in enumerate([(0x04000000, 0x80003000), (0xBF000000, 0x00020406), (0xB8000000, 0)]):
        put(buf, base, f3d + 8 * i, ">II", w0, w1)
    ram = R.Ram(bytes(buf), base, True, "n64")
    a = R.n64_display_list(ram, dl)
    assert a["dialect"] == "F3DEX2" and a["triangles"] == 3 and a["vertex_addresses"] == [0x80002000]
    b = R.n64_display_list(ram, f3d)
    assert b["dialect"] == "F3D" and b["triangles"] == 1
    assert R.n64_display_list(ram, base + 0x4000) is None  # zeros are NOOPs without an end: not a list

    class Swapped:                                          # ParaLLEl RDRAM: little-endian words
        def read_memory(self, a, n):
            raw = R.swap32(bytes(buf))
            return raw[a - base:a - base + n]
    snap = R.Ram.snapshot(Swapped(), "n64", region=(base, size))
    assert snap.swapped and snap.data == bytes(buf)
    assert snap.device_bytes(base, b"\x01\x02\x03\x04") == b"\x04\x03\x02\x01"
    assert snap.read_live(Swapped(), dl + 2, 4) == bytes(buf)[0x1002:0x1006]


def test_vertex_and_matrix_arrays_and_zero_fill_is_not_geometry():
    buf = dc_ram()
    va = DC + 0x40000
    for i in range(20):
        put(buf, DC, va + 24 * i, "<3f3f", i * 1.5, (i % 7) * 2.0, -i * 0.25, 0.0, 1.0, 0.0)
    mx = DC + 0x50000
    for i in range(4):
        put(buf, DC, mx + 48 * i, "<12f", 1, 0, 0, i, 0, 1, 0, 0, 0, 0, 1, 0)
    ram = R.Ram(bytes(buf), DC, False, "dreamcast")
    v = R.vertex_array(ram, va)
    assert v["format"] == "f32x3" and v["stride"] == 24 and v["count"] >= 20
    m = R.matrix_array(ram, mx)
    assert m["layout"] == "3x4" and m["count"] == 4
    assert R.vertex_array(ram, DC + 0x80000) is None
    assert R.find_vertices(ram, [(i * 1.5, (i % 7) * 2.0, -i * 0.25) for i in range(6)])[0]["addr"] == va


def test_find_window_exact_and_relocated():
    buf = dc_ram()
    asset = bytearray(0x100)
    for i in range(0, 0x100, 4):
        struct.pack_into("<I", asset, i, 0x11110000 + i)
    ptrs = [0x10, 0x40, 0x80]
    for p in ptrs:
        struct.pack_into("<I", asset, p, 0x20 + p)          # in-file offsets
    at = DC + 0x60000
    loaded = bytearray(asset)
    for p in ptrs:
        struct.pack_into("<I", loaded, p, at + 0x20 + p)    # the loader added the load address
    buf[at - DC:at - DC + 0x100] = loaded
    ram = R.Ram(bytes(buf), DC, False, "dreamcast")
    known = R.find_window(ram, bytes(asset), set(ptrs))
    assert known[0]["addr"] == at and known[0]["delta"] == at and sorted(known[0]["relocated"]) == ptrs
    guessed = R.find_window(ram, bytes(asset))
    assert guessed[0]["addr"] == at and sorted(guessed[0]["relocated"]) == ptrs and not guessed[0]["mismatched"]
    exact = R.find_window(ram, bytes(loaded))
    assert exact[0]["exact"] and exact[0]["addr"] == at


def test_texture_re_encoded_in_gx_rgb5a3_is_found():
    w = h = 8
    rgba = bytearray()
    for y in range(h):
        for x in range(w):
            rgba += bytes((x * 32, y * 32, (x * y) % 256 & 0xF8, 255))
    enc = dict(R.tex_encodings(bytes(rgba), w, h))
    base = 0x80000000
    buf = bytearray(0x10000)
    put(buf, base, base + 0x180, ">I", R.N64_RESET_WORD)
    buf[0x4000:0x4000 + len(enc["gx_rgb5a3"])] = enc["gx_rgb5a3"]
    ram = R.Ram(bytes(buf), base, True, "gamecube")
    hits = R.find_texture(ram, bytes(rgba), w, h)
    assert hits and hits[0]["addr"] == base + 0x4000 and hits[0]["format"] == "gx_rgb5a3"


def test_free_region_needs_an_unreferenced_zero_run_inside_a_declared_arena():
    buf = bytearray(b"\x55" * 0x20000)
    buf[0x8000:0x10000] = bytes(0x8000)
    ram = R.Ram(bytes(buf), DC, False, "dreamcast")
    arena = [(DC + 0x8000, DC + 0x10000)]
    fr = R.free_region(ram, 0x1000, arena)
    assert fr and DC + 0x8000 < fr["start"] and fr["end"] <= DC + 0x10000
    assert R.free_region(ram, 0x1000, []) is None            # no declared arena: no free region
    put(buf, DC, DC + 0x100, "<I", DC + 0x9000)               # something owns it
    assert R.free_region(R.Ram(bytes(buf), DC, False, "dreamcast"), 0x1000, arena) is None
