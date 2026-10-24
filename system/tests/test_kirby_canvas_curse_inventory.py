import glob
import os
import struct

import pytest

from gbox.formats import kirby_cc
from gbox.formats.nitro import NitroROM, build_fnt

TITLE = b"TOUCH!KIRBY"


def _rom(members: dict[str, bytes], title=TITLE, code=b"ATKE") -> bytes:
    fnt, order = build_fnt(list(members))
    hdr = bytearray(0x200)
    hdr[0:len(title)] = title
    hdr[12:16] = code
    fnt_off = 0x200
    fat_off = fnt_off + len(fnt)
    pos = fat_off + 8 * len(order)
    fat, body = [], b""
    for p in order:
        fat.append((pos + len(body), pos + len(body) + len(members[p])))
        body += members[p]
    struct.pack_into("<4I", hdr, 0x40, fnt_off, len(fnt), fat_off, 8 * len(order))
    return bytes(hdr) + fnt + b"".join(struct.pack("<II", *e) for e in fat) + body


def _bundle(count: int, size: int) -> bytes:
    # independent construction from the observed rule len == size + 4*count + 4
    return struct.pack("<3I", 6, count, size) + bytes(size + 4 * count + 4 - 12)


def test_inventory_classifies_character_bundles():
    members = {"romdir/bank01bin/kbynmlwait.bin": _bundle(5, 5768),
               "romdir/bank01bin/dedenmlwait.bin": _bundle(5, 100),
               "romdir/bank00bin/dfont.bin": struct.pack("<3I", 5, 1, 4) + b"\0" * 8,
               "romdir/bank01bin/tiny.bin": b"\0\0"}
    inv = kirby_cc.inventory(_rom(members))
    assert inv["is_canvas_curse"] and inv["members"] == 4
    assert inv["kind_census"] == {5: 1, 6: 2}
    cb = inv["character_bundles"]
    assert set(cb) == {"romdir/bank01bin/kbynmlwait.bin", "romdir/bank01bin/dedenmlwait.bin"}
    assert all(v["table_hypothesis_ok"] for v in cb.values())


def test_wrong_cartridge_and_truncated_inputs_rejected():
    assert not kirby_cc.inventory(_rom({"a/b.bin": b"x" * 16}, title=b"OTHER", code=b"XXXX"))["is_canvas_curse"]
    with pytest.raises(ValueError):
        kirby_cc.inventory(b"\0" * 0x100)
    assert kirby_cc.bundle_header(b"\0" * 11) is None


OWNED = os.environ.get("KIRBY_CC_ROM") or next(iter(glob.glob(os.path.expanduser("~/.hermes/cache/scratch/kirby_cc/*.nds"))), None)


@pytest.mark.skipif(not OWNED, reason="owned Kirby: Canvas Curse ROM not extracted on this host")
def test_owned_build_identity_and_counts():
    inv = kirby_cc.inventory(open(OWNED, "rb").read())
    assert inv["sha256"] == kirby_cc.SOURCE_SHA256
    assert inv["is_canvas_curse"] and inv["members"] == 2178
    assert inv["arm9"] == {"offset": 0x4000, "entry": 0x02000800, "ram": 0x02000000, "size": 875384}
    nml = inv["character_bundles"]["romdir/bank01bin/kbynml_0000_bnd.bin"]
    assert (nml["kind"], nml["count"], nml["size"]) == (6, 9, 5424) and nml["table_hypothesis_ok"]
