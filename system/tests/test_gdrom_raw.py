import os, struct
import pytest
from gbox.formats.gdrom_raw import RawGDRom, RAW, USER_OFFSET, HD_LBA

def _dirrec(name: bytes, lba: int, size: int, flags: int = 0) -> bytes:
    n = 33 + len(name)
    n += n % 2
    r = bytearray(n)
    r[0] = n; struct.pack_into("<I", r, 2, lba); struct.pack_into("<I", r, 10, size)
    r[25] = flags; r[32] = len(name); r[33:33 + len(name)] = name
    return bytes(r)

def _build(path, low=20):
    sectors = [bytearray(RAW) for _ in range(low + 24)]
    def put(fs, data): sectors[fs][USER_OFFSET:USER_OFFSET + len(data)] = data
    def pvd(root_lba):
        p = bytearray(2048); p[0] = 1; p[1:6] = b"CD001"
        struct.pack_into("<I", p, 80, low); struct.pack_into("<I", p, 158, root_lba); struct.pack_into("<I", p, 166, 2048)
        return bytes(p)
    put(16, pvd(18))
    hd = lambda l: low + (l - HD_LBA)
    put(hd(HD_LBA + 16), pvd(HD_LBA + 20))
    put(hd(HD_LBA + 20), _dirrec(b"\0", HD_LBA + 20, 2048, 2) + _dirrec(b"\1", HD_LBA + 20, 2048, 2)
        + _dirrec(b"A.BIN;1", HD_LBA + 21, 5))
    put(hd(HD_LBA + 21), b"hello")
    open(path, "wb").write(b"".join(bytes(s) for s in sectors))

def test_raw_gdrom_walk(tmp_path):
    p = tmp_path / "x.bin"; _build(p)
    g = RawGDRom(str(p))
    assert g.low_blocks == 20 and g.hd_root() == (HD_LBA + 20, 2048)
    f = g.files()
    assert f == {"A.BIN": (HD_LBA + 21, 5)}
    assert g.read(*f["A.BIN"]) == b"hello"
    g.close()

JSR = "/home/ehm_eckx/.hermes/cache/scratch/jsr/jsr_eu.bin"

@pytest.mark.skipif(not os.path.exists(JSR), reason="extracted JSR EU image absent")
def test_jsr_eu_player_afs():
    g = RawGDRom(JSR)
    f = g.files()
    assert len(f) == 526
    lba, size = f["JETRADIO/PLAYER.AFS"]
    assert (lba, size) == (347639, 14143488)
    assert g.read(lba, 4) == b"AFS\0"
    g.close()
