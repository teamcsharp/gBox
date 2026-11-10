"""eden_memory.writable_alias: a read-only guest page's bytes found in a writable mapping of the same memfd."""
from gbox import eden_memory as E

MAPS = [
    "7f0000000000-7f0000100000 rw-s 00000000 00:01 5 /memfd:HostMemory (deleted)",   # Eden's own view, offset 0
    "5d00000000-5d00010000 r--s 00020000 00:01 5 /memfd:HostMemory (deleted)",       # the guest's rodata page(s)
    "5d00010000-5d00020000 rw-s 00030000 00:01 5 /memfd:HostMemory (deleted)",       # the guest's data
]


def test_a_read_only_page_has_a_writable_alias_at_the_same_file_offset():
    arena = E.guest_arena(MAPS)
    host = 0x5D00000010
    alias = E.writable_alias(arena, host, 16)
    assert alias == 0x7F0000000000 + 0x20000 + 0x10


def test_no_alias_when_nothing_writable_covers_it():
    arena = E.guest_arena(MAPS[1:])
    assert E.writable_alias(arena, 0x5D00000010, 16) is None


def test_the_offsets_are_parsed():
    rows = E.parse_maps(MAPS)
    assert rows[1]["offset"] == 0x20000 and rows[0]["perms"] == "rw-s"
