"""gbox.switch_patch: rebuilding a base RomFS file from a BKTR patch's ranges (base + patch recombination)."""
import pytest

from gbox import switch_patch as P

ROMFS = 0x1000
DATA = 0x200


def base_file(offset, size):
    return {"path": "arc/a.arc", "offset": offset, "size": size}


def test_patched_files_finds_overlaps_across_boundaries():
    files = [base_file(0x0, 0x100), base_file(0x100, 0x100), base_file(0x800, 0x100)]
    regions = [{"virt": 0x1000 + 0x200 + 0x80, "end": 0x1000 + 0x200 + 0x180, "phys": 0x0}]
    out = P.patched_files(files, regions, ROMFS, DATA)
    assert [f["path"] for f in out] == ["arc/a.arc", "arc/a.arc"]
    assert out[0]["size"] == 0x100 and out[1]["size"] == 0x100
    assert out[0]["regions"][0]["virt"] == 0x1000 + 0x200 + 0x80
    assert out[0]["regions"][0]["end"] == 0x1000 + 0x200 + 0x100      # clipped to the file
    assert out[1]["regions"][0]["virt"] == 0x1000 + 0x200 + 0x100      # starts at the file
    assert P.changed_ranges(out[0]) == [{"offset": 0x80, "size": 0x80}]


def test_rebuild_uses_base_outside_and_patch_inside():
    file = {"path": "arc/a.arc", "size": 0x200, "virtual": 0x1000,
            "regions": [{"virt": 0x1080, "end": 0x1180, "region": {}}]}
    base = bytes([0x41]) * 0x200
    patch = bytes([0x50]) * 0x200

    def base_read(offset, size):
        assert 0x1000 <= offset and offset + size <= 0x1200
        return base[offset - 0x1000:offset - 0x1000 + size]

    def patch_read(offset, size):
        assert 0x1080 <= offset and offset + size <= 0x1180
        return patch[offset - 0x1000:offset - 0x1000 + size]

    out = P.rebuild(base_read, patch_read, file, chunk=0x40)
    assert len(out) == 0x200
    assert out[:0x80] == b"A" * 0x80 and out[0x80:0x180] == b"P" * 0x100 and out[0x180:] == b"A" * 0x80


def test_rebuild_refuses_a_short_read():
    file = {"path": "arc/a.arc", "size": 0x40, "virtual": 0x1000, "regions": []}

    def short(offset, size):
        return b"x" * (size - 1)

    with pytest.raises(ValueError, match="returned"):
        P.rebuild(short, short, file)


def test_a_file_without_regions_is_not_patched():
    files = [base_file(0x0, 0x100)]
    assert P.patched_files(files, [{"virt": 0x9000, "end": 0x9100, "phys": 0}], ROMFS, DATA) == []
