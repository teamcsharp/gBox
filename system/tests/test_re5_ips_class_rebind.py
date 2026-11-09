"""The IPS32 class-rebind patch: exact bytes, no-op control and an apply round-trip."""
import struct
import pytest

from gbox.re5_ips import OFFSET, ORIGINAL, REBIND, apply_patch, assert_original, make_ips, rebind_changes


def supported_main():
    from gbox.re_switch import RE5_MAIN_BUILD_ID
    blob = bytearray(b"\xaa" * 0x500000)
    blob[:4] = b"NSO0"
    struct.pack_into("<I", blob, 0x0c, 0)
    struct.pack_into("<3I", blob, 0x10, 0x100, 0, len(blob) - 0x100)
    blob[0x40:0x50] = bytes.fromhex(RE5_MAIN_BUILD_ID)
    struct.pack_into("<I", blob, OFFSET, ORIGINAL)
    return blob


def test_ips_records_the_uem11_to_uem10_immediate():
    ips = make_ips()
    assert ips[:5] == b"IPS32"
    assert ips[-4:] == b"EEOF"
    off, size = struct.unpack_from(">IH", ips, 5)
    assert off == OFFSET == 0x4F824
    assert size == 4
    assert ips[11:15] == struct.pack("<I", REBIND)
    assert struct.unpack("<I", ips[11:15])[0] == 0x110C0284


def test_a_noop_ips_writes_the_original_bytes_back():
    ips = make_ips(noop=True)
    assert ips[11:15] == struct.pack("<I", ORIGINAL)
    assert struct.unpack("<I", ips[11:15])[0] == 0x11100284


def test_apply_patch_changes_only_the_four_immediate_bytes():
    blob = supported_main()
    before = bytes(blob)
    assert_original(bytes(blob))
    out = apply_patch(blob)
    assert bytes(out[:OFFSET]) == before[:OFFSET]
    assert struct.unpack_from("<I", out, OFFSET)[0] == REBIND
    assert bytes(out[OFFSET + 4:]) == b"\xaa" * (len(out) - OFFSET - 4)


@pytest.mark.parametrize("raw", [b"short", bytes(OFFSET + 4)])
def test_patch_refuses_wrong_executable_without_mutating(raw):
    blob = bytearray(raw)
    with pytest.raises(ValueError):
        apply_patch(blob)
    assert blob == raw
    with pytest.raises(ValueError):
        make_ips(main=raw)


def test_rebind_overlay_contains_archive_and_ips_as_one_edit():
    from gbox import mt_arc
    archive = mt_arc.build(mt_arc.Arc(7, [mt_arc.Entry("em1000", 0, 0, 3, 0, b"arc")]))
    changes = rebind_changes(archive)
    assert changes["romfs/nativeNXx64/ImgNX/Archive/uEm11.arc"]["bytes"] == archive
    assert changes["exefs/main.ips"]["bytes"] == make_ips()


@pytest.mark.parametrize("offset,data", [(0, b"\x7fELF"), (0x40, bytes(16)), (0x0c, b"\x01\0\0\0"),
                                        (0x10, b"\x00\x02\0\0")])
def test_rebind_preflight_refuses_foreign_build_or_layout(offset, data):
    main = supported_main()
    main[offset:offset + len(data)] = data
    before = bytes(main)
    with pytest.raises(ValueError):
        make_ips(main=main)
    with pytest.raises(ValueError):
        apply_patch(main)
    assert main == before


def test_expanded_eden_dump_requires_all_original_segment_hashes_and_exact_size():
    import hashlib
    from gbox.re5_ips import assert_supported_main
    main = supported_main()[:0x50000]
    main += bytes(0x200)
    struct.pack_into("<I", main, 0x0c, 0x3f)
    for index, (memory, size) in enumerate(((0, 0x4ff00), (0x4ff00, 0x100), (0x50000, 0x80))):
        struct.pack_into("<3I", main, 0x10 + index * 16, 0x101 + index * 0x100, memory, size)
        main[0xa0 + index * 32:0xc0 + index * 32] = hashlib.sha256(main[0x100 + memory:0x100 + memory + size]).digest()
    struct.pack_into("<I", main, 0x3c, 0x80)
    assert_supported_main(main)
    for where in (OFFSET + 8, 0x50010, 0x50110):
        damaged = bytearray(main)
        damaged[where] ^= 1
        with pytest.raises(ValueError, match="verified expanded"):
            assert_supported_main(damaged)
    with pytest.raises(ValueError, match="verified expanded"):
        assert_supported_main(main + b"\0")
