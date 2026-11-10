import struct, pytest
from gbox.cvs2eo_plpak_probe import parse_plpak

def synth():
    secA, n = 0x20, 4
    first = secA + 4 * n
    tbl = [first, first + 8, first + 16, first + 20]
    body = b"\0" * 24
    secB = first + len(body)
    tb = [0x10, 0x20, 0x30]
    d = struct.pack("<8I", 0, secA, 0, secB, 0, secB + 12 + 4, 0, 0)
    d += struct.pack("<4I", *tbl) + body + struct.pack("<3I", *tb) + b"\0" * 8
    return d

def test_synth():
    r = parse_plpak(synth())
    assert r["a_count"] == 4 and r["a_monotone"] and r["a_in_range"]

def test_bad():
    with pytest.raises(ValueError):
        parse_plpak(b"\1" * 64)


def test_frames_synth():
    from gbox.cvs2eo_plpak_probe import parse_frames
    rec0 = struct.pack("<H", 2) + struct.pack("<hhhH", 8, 24, 16, 0) + struct.pack("<hhhH", -48, -8, 16, 1)
    rec1 = struct.pack("<H", 1) + struct.pack("<hhhH", 0, 0, 16, 2)
    tbl = struct.pack("<2I", 8, 8 + len(rec0))
    secB = 0x40
    d = struct.pack("<8I", 0, 0x20, 0, secB, 0, secB + 8 + len(rec0) + len(rec1), 0, 0) + b"\0" * 0x20
    d = d[:secB] + tbl + rec0 + rec1
    r = parse_frames(d)
    assert r["frame_count"] == 2 and r["exact_tiling"] == 2 and r["max_sprite_idx"] == 2
    assert r["frames"][0][1] == (-48, -8, 16, 1)

def test_frames_bad():
    from gbox.cvs2eo_plpak_probe import parse_frames
    with pytest.raises(ValueError):
        parse_frames(b"\0" * 64)

import os
_ISO = "/mnt/gbox/quickswap2/Emulation/_emulation/GC ISO/Capcom vs. SNK 2 EO - Millionaire Fighting 2001 (USA).iso"

@pytest.mark.skipif(not os.path.exists(_ISO), reason="owned ISO not mounted")
def test_frames_owned_pl00_pl01():
    from gbox.cvs2eo_plpak_probe import parse_frames
    from gbox.cvs2eo_inventory import afs_entries, find_name_dir
    with open(_ISO, "rb") as f:
        f.seek(1168816944)
        a = f.read(95453184)
    cnt, offs, sizes, te = afs_entries(a)
    names = find_name_dir(lambda at, n: a[at:at + n], len(a), cnt, offs, sizes, te)[0]
    exp = {"pl00pak.bin": 660, "pl01pak.bin": 602}
    for nm, n in exp.items():
        i = names.index(nm)
        r = parse_frames(a[offs[i]:offs[i] + sizes[i]])
        assert r["frame_count"] == n and r["exact_tiling"] == n
