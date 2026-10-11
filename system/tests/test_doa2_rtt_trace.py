"""Source-only bounds and linked-record regressions for offline RTT diagnostics."""
import hashlib
import json
import struct
import pytest

from gbox import doa2_rtt_trace as t


def _ram(words, size=0x300000):
    buf = bytearray(size)
    for addr, value in words.items():
        struct.pack_into("<I", buf, addr - t.RAM_BASE, value)
    return bytes(buf)


def _node_words(addr, *, flags=0x11, nxt=0, prev=0, vram=0x473800,
                size=0x40000, record=t.BACKDROP_P):
    return {addr + i * 4: value for i, value in enumerate((flags, nxt, prev, vram, size, record))}


def _backdrop_words():
    vals = [0x28, 2, 1, 0x8000000, 0x200, 0x100, 0x40000, 0x4000035,
            0x473800, 0, 0, 0, 6, 0x35, 0x0C08E700]
    words = {t.BACKDROP_P - 0x20 + i * 4: value for i, value in enumerate(vals)}
    # Exact observed node addresses/field order, with a synthetic closed ring.
    prev, node, nxt = 0x8C2C2910, 0x8C2C2928, 0x8C2C2940
    words.update(_node_words(prev, nxt=node, prev=nxt, vram=0x46AD00, size=0x80,
                             record=0x8C20CCEC))
    words.update(_node_words(node, nxt=nxt, prev=prev))
    words.update(_node_words(nxt, flags=0x41, nxt=prev, prev=node,
                             vram=0x4B3800, size=0xC00, record=0x8C20CD64))
    return words, node


def test_surface_record_decodes_observed_backdrop_fields():
    words, _ = _backdrop_words()
    s = t.surface_at(_ram(words), t.BACKDROP_P)
    assert (s.ident, s.flags, s.width, s.height, s.size, s.kind, s.vram, s.tcw) == (
        0x28, 0x8000000, 512, 256, 0x40000, 0x4000035, 0x473800, 0x0C08E700)
    assert s.tcw_vram == s.vram


def test_allocator_actual_flags_first_layout_and_cycle():
    words, node = _backdrop_words()
    nodes = t.allocator_nodes(_ram(words), node)
    assert [n["node"] for n in nodes] == [node, 0x8C2C2940, 0x8C2C2910]
    assert nodes[0] == {"node": node, "flags": 0x11, "next": 0x8C2C2940,
                        "prev": 0x8C2C2910, "vram": 0x473800,
                        "size": 0x40000, "record": t.BACKDROP_P}
    assert len(t.allocator_nodes(_ram(words), node, limit=2)) == 2


def test_allocator_accepts_complete_record_at_final_byte_boundary():
    ram = _ram(_node_words(t.RAM_BASE), size=t.ALLOCATOR_STRIDE)
    assert t.allocator_nodes(ram, t.RAM_BASE)[0]["record"] == t.BACKDROP_P


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_allocator_rejects_invalid_limit(limit):
    with pytest.raises(ValueError):
        t.allocator_nodes(bytes(24), t.RAM_BASE, limit)


@pytest.mark.parametrize("addr", [t.RAM_BASE - 4, t.RAM_BASE + 1, t.RAM_BASE + 16])
def test_word_read_rejects_negative_unaligned_and_past_end(addr):
    ram = bytes(12) + struct.pack("<I", 0xAABBCCDD)
    with pytest.raises(ValueError):
        t.u32(ram, addr)
    assert t.u32(ram, t.RAM_BASE + 12) == 0xAABBCCDD


def test_surface_record_rejects_truncated_capture():
    with pytest.raises(ValueError):
        t.surface_at(bytes(t.RECORD_STRIDE - 1), t.RAM_BASE + 0x20)


def test_allocator_malformed_next_does_not_silently_look_complete():
    ram = _ram(_node_words(t.RAM_BASE, nxt=t.RAM_BASE + 24), size=24)
    with pytest.raises(ValueError):
        t.allocator_nodes(ram, t.RAM_BASE)


def test_matching_literal_before_real_node_is_not_selected():
    words, node = _backdrop_words()
    # The PR13 implementation inferred a node from this earlier unrelated literal.
    words[t.RAM_BASE + 0x1000] = t.BACKDROP_P
    ram = _ram(words)
    assert t.find_value(ram, t.BACKDROP_P)[0] == t.RAM_BASE + 0x1000
    found = t.surface_allocator_nodes(ram, t.surface_at(ram, t.BACKDROP_P))
    assert [n["node"] for n in found] == [node]


@pytest.mark.parametrize("change", ["wrong_size", "wrong_vram", "broken_next_prev",
                                    "broken_prev_next", "unaligned_next", "truncated_next",
                                    "isolated_literal"])
def test_surface_node_rejects_unproven_membership(change):
    words, node = _backdrop_words()
    if change == "wrong_size":
        words[node + 16] = 4
    elif change == "wrong_vram":
        words[node + 12] = 0x100
    elif change == "broken_next_prev":
        words[0x8C2C2940 + 8] = 0
    elif change == "broken_prev_next":
        words[0x8C2C2910 + 4] = 0
    elif change == "unaligned_next":
        words[node + 4] += 1
    elif change == "truncated_next":
        words[node + 4] = t.RAM_BASE + 0x300000 - 20
    else:
        words[node + 4] = words[node + 8] = 0
    ram = _ram(words)
    assert t.surface_allocator_nodes(ram, t.surface_at(ram, t.BACKDROP_P)) == []


def test_self_linked_singleton_is_valid():
    words, node = _backdrop_words()
    words[node + 4] = words[node + 8] = node
    ram = _ram(words)
    assert [n["node"] for n in t.surface_allocator_nodes(ram, t.surface_at(ram, t.BACKDROP_P))] == [node]


def test_multiple_linked_candidates_are_reported_as_ambiguous(tmp_path, capsys):
    words, _ = _backdrop_words()
    duplicate = t.RAM_BASE + 0x1000
    words.update(_node_words(duplicate, nxt=duplicate, prev=duplicate))
    (tmp_path / "ram.bin").write_bytes(_ram(words))
    (tmp_path / "vram.bin").write_bytes(bytes(0x4B3800))
    assert t.main([str(tmp_path)]) == 1
    row = json.loads(capsys.readouterr().out)
    assert row["allocator_status"] == "ambiguous"
    assert row["allocator_node"] is None and len(row["allocator_candidates"]) == 2


def test_find_value_only_returns_aligned_hits():
    ram = b"\0" + struct.pack("<I", 0xDEADBEEF) + bytes(3) + struct.pack("<I", 0xDEADBEEF)
    assert t.find_value(ram, 0xDEADBEEF) == [t.RAM_BASE + 8]


@pytest.mark.parametrize("base,inst_offset", [(0x8C010000, 0), (0x8C010000, 2), (0x8C010002, 0)])
def test_sh4_pool_ref_uses_aligned_pc_plus_four(base, inst_offset):
    code = bytearray(16)
    struct.pack_into("<H", code, inst_offset, 0xD301)
    pc = base + inst_offset
    literal_offset = (pc & ~3) + 8 - base
    struct.pack_into("<I", code, literal_offset, 0xA05F8060)
    assert t.sh4_pool_refs(bytes(code), base, {0xA05F8060}) == [(pc, 3, 0xA05F8060)]


def test_sh4_truncated_literal_is_not_read():
    assert t.sh4_pool_refs(struct.pack("<H", 0xD301) + bytes(9), 0x8C010000, {0}) == []


def test_surface_sha_hashes_full_exact_span():
    words, _ = _backdrop_words()
    s = t.surface_at(_ram(words), t.BACKDROP_P)
    vram = bytes(s.vram) + b"\x01" * s.size
    assert t.surface_sha(vram, s) == hashlib.sha256(b"\x01" * s.size).hexdigest()


@pytest.mark.parametrize("offset,size", [(-1, 1), (16, 128), (0, 0), (0, -1), (0, 2)])
def test_surface_sha_rejects_invalid_or_truncated_spans(offset, size):
    s = t.Surface(0, 0, 0, 1, 1, size, 0, offset, 0)
    with pytest.raises(ValueError):
        t.surface_sha(b"\x01", s)


def test_cli_missing_allocator_pointer_is_controlled(tmp_path, capsys):
    words, node = _backdrop_words()
    words[node + t.ALLOCATOR_RECORD_OFFSET] = 0
    (tmp_path / "ram.bin").write_bytes(_ram(words))
    (tmp_path / "vram.bin").write_bytes(bytes(0x4B3800))
    assert t.main([str(tmp_path)]) == 1
    row = json.loads(capsys.readouterr().out)
    assert row["allocator_status"] == "missing" and row["allocator_node"] is None


def test_cli_invalid_capture_continues_to_valid_capture(tmp_path, capsys):
    bad, good = tmp_path / "bad", tmp_path / "good"
    bad.mkdir()
    good.mkdir()
    (bad / "ram.bin").write_bytes(bytes(4))
    (bad / "vram.bin").write_bytes(bytes(4))
    words, node = _backdrop_words()
    (good / "ram.bin").write_bytes(_ram(words))
    (good / "vram.bin").write_bytes(bytes(0x4B3800))
    assert t.main([str(bad), str(good)]) == 1
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert "error" in rows[0]
    assert rows[1]["allocator_status"] == "unique"
    assert rows[1]["allocator_node"]["node"] == hex(node)
