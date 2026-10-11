import struct

from gbox import doa2_rtt_trace as t


def _ram(words: dict[int, int], size: int = 0x300000) -> bytes:
    b = bytearray(size)
    for addr, v in words.items():
        struct.pack_into("<I", b, addr - t.RAM_BASE, v)
    return bytes(b)


def _backdrop_words():
    p = t.BACKDROP_P
    s = p - 0x20
    vals = [0x28, 2, 1, 0x8000000, 0x200, 0x100, 0x40000, 0x4000035, 0x473800, 0, 0, 0, 6, 0x35, 0x0C08E700]
    w = {s + 4 * i: v for i, v in enumerate(vals)}
    node = 0x8C2C292C
    w.update({node: 0, node + 4: 0x8C2C2910, node + 8: 0x473800, node + 12: 0x40000, node + 16: p, node + 20: 0x11})
    return w, node


def test_surface_record_decodes_backdrop():
    w, _ = _backdrop_words()
    s = t.surface_at(_ram(w), t.BACKDROP_P)
    assert (s.ident, s.width, s.height, s.size, s.vram) == (0x28, 512, 256, 0x40000, 0x473800)
    assert s.tcw_vram == s.vram


def test_allocator_walk_finds_backdrop_node_and_stops():
    w, node = _backdrop_words()
    nodes = t.allocator_nodes(_ram(w), node)
    assert len(nodes) == 1 and nodes[0]["record"] == t.BACKDROP_P and nodes[0]["flags"] == 0x11


def test_find_value_is_word_aligned():
    w, node = _backdrop_words()
    assert node + 16 in t.find_value(_ram(w), t.BACKDROP_P)


def test_sh4_pool_ref():
    base = 0x8C010000
    code = bytearray(16)
    struct.pack_into("<H", code, 0, 0xD301)  # mov.l @(1*4+4, PC&~3), r3 -> literal at base+8
    struct.pack_into("<I", code, 8, 0xA05F8060)
    assert t.sh4_pool_refs(bytes(code), base, {0xA05F8060}) == [(base, 3, 0xA05F8060)]


def test_surface_sha_slices_vram():
    w, _ = _backdrop_words()
    s = t.surface_at(_ram(w), t.BACKDROP_P)
    vram = bytes(0x473800) + b"\x01" * 0x40000
    import hashlib
    assert t.surface_sha(vram, s) == hashlib.sha256(b"\x01" * 0x40000).hexdigest()
