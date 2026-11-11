import io, struct, pytest
from gbox import br2_inventory as B


def _dat(n=9):
    hdr = struct.pack("<13I", 9, 0, 0x40, 0x80, 0x100, 0x100, 0x120, 0x140, 0x150, 0x160, 2, 0, 0)
    return hdr + b"\0" * (0x200 - len(hdr))


def test_dat_offsets_ok():
    assert B.dat_offsets(_dat())[0] == 0x40


def test_dat_offsets_rejects():
    bad = bytearray(_dat()); struct.pack_into("<I", bad, 8, 0x900)
    with pytest.raises(ValueError):
        B.dat_offsets(bytes(bad))


def test_exe_info():
    exe = b"PS-X EXE" + b"\0" * 8 + struct.pack("<4I", 0x80125f34, 0, 0x8011e800, 0x9f800) + b"\0" * 64
    i = B.exe_info(exe)
    assert i["pc"] == 0x80125f34 and i["text_size"] == 0x9f800


def test_raw_iso_roundtrip():
    # build 3-sector MODE2/2352 image: PVD at LBA16 with root at 17 containing one file at 18
    def rec(name, lba, size, d=0):
        n = name.encode(); l = 33 + len(n); l += l & 1
        r = bytearray(l); r[0] = l; struct.pack_into("<I", r, 2, lba); struct.pack_into("<I", r, 10, size)
        r[25] = 2 if d else 0; r[32] = len(n); r[33:33 + len(n)] = n; return bytes(r)
    secs = {16: bytearray(2048), 17: bytearray(2048), 18: bytearray(2048)}
    p = secs[16]; p[0] = 1; p[1:6] = b"CD001"; struct.pack_into("<I", p, 158, 17); struct.pack_into("<I", p, 166, 2048)
    secs[17][:] = (rec("\0", 17, 2048, 1) + rec("\1", 17, 2048, 1) + rec("A.DAT;1", 18, 5)).ljust(2048, b"\0")
    secs[18][:5] = b"hello"
    img = bytearray(19 * 2352)
    for l, s in secs.items():
        img[l * 2352 + 24:l * 2352 + 24 + 2048] = s
    sec = B.raw_sector_reader(io.BytesIO(bytes(img)))
    t = B.file_table(sec)
    assert t == {"A.DAT": (18, 5)} or list(t.values()) == [(18, 5)]
    assert B.read_file(sec, 18, 5) == b"hello"


def test_dat_absent_slot():
    h = bytearray(_dat()); struct.pack_into("<I", h, 8 + 5 * 4, 0xFFFFFFFF)
    assert B.dat_offsets(bytes(h))[5] is None
