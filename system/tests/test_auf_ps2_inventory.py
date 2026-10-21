"""Focused tests for gbox.auf_ps2_inventory (007: Agent Under Fire PS2, #1599)."""
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gbox import auf_ps2_inventory as a  # noqa: E402
from gbox.auf_ngc import boa_store  # noqa: E402

DISC = os.path.expanduser("~/gBox_alt/gbox-cache/ps2/a911b8d231ef883a/disc.bin")


def _chunk(cid: str, payload: bytes, compress: bool) -> bytes:
    mem = (len(payload) + 15) & ~15
    body = boa_store(payload.ljust(mem, b"\0")) if compress else payload
    h = cid.encode().ljust(8, b"\0") + struct.pack("<IfIIII", len(payload), 1.0, int(compress), 0xCDCDCDCD,
                                                   len(body), mem)
    out = h + body
    return out + b"\0" * (-len(out) % 32)


def _restable(files: dict) -> bytes:
    recs = sorted(files.items(), key=lambda kv: a.hash_string(kv[0]))
    n = len(recs)
    pos = 0x10 + 16 * n
    data, offs = b"", []
    for _, blob in recs:
        offs.append(pos + len(data))
        data += blob + b"\0" * (-len(blob) % 16)
    names_at = pos + len(data)
    names, noffs = b"", []
    for name, _ in recs:
        noffs.append(names_at + len(names))
        names += name.encode() + b"\0"
    head = struct.pack("<I12x", n)
    for (name, blob), do, no in zip(recs, offs, noffs):
        head += struct.pack("<4I", no, do, len(blob), a.hash_string(name))
    return head + data + names


def test_hash_string_matches_known_shape():
    assert a.hash_string("AB") == a.hash_string("ab") == (ord("a") * 65599 + ord("b"))


def test_package_roundtrip_synthetic():
    files = {"models/actors/bond/bond_combat_l.mdl": struct.pack("<I", 0x18400001) + b"x" * 12,
             "models/anims/walk.a3d": b"anim"}
    pkg = _chunk("snd_alb", b"ALBK" + b"\0" * 20, True) + _chunk("restable", _restable(files), True)
    s = a.package_summary(pkg)
    assert [c["id"] for c in s["chunks"]] == ["snd_alb", "restable"]
    assert s["restable_errors"] == []
    assert s["actor_models"] == ["models/actors/bond/bond_combat_l.mdl"]
    assert s["mdl_first_words"] == {"01004018": 1}
    assert s["anims"] == 1
    assert a.ChkPackage(pkg).read("models/anims/WALK.a3d") == b"anim"


def test_restable_check_flags_bad_hash_and_order():
    recs = [("b", 0, 0, a.hash_string("b")), ("a", 0, 0, 1)]
    errs = a.restable_check(recs)
    assert any("HashString" in e for e in errs)


def test_iter_chunks_rejects_overrun():
    bad = b"restable" + struct.pack("<IfIIII", 64, 1.0, 0, 0xCDCDCDCD, 64, 64)
    with pytest.raises(ValueError):
        list(a.iter_chunks(bad))


def test_parse_bigf():
    recs = [(b"maps\\dm1.chk", 0x800, 10), (b"fonts\\a.tga", 0x1000, 4)]
    toc = b"".join(struct.pack(">II", o, s) + n + b"\0" for n, o, s in recs)
    head = b"BIGF" + struct.pack("<I", 0) + struct.pack(">II", len(recs), 16 + len(toc)) + toc
    assert a.parse_bigf(head) == [("maps\\dm1.chk", 0x800, 10), ("fonts\\a.tga", 0x1000, 4)]


@pytest.mark.skipif(not os.path.exists(DISC), reason="owned PS2 disc image not extracted")
def test_owned_disc_dm1():
    inv = a.inventory(DISC, maps=["dm1.chk"])
    assert inv["executables"]["ACTION.ELF"].startswith("3920449225fc81e1")
    m = inv["maps"]["dm1.chk"]
    assert m["restable_errors"] == [] and m["resources"] == 870
    assert "models/actors/bond/bond_combat_l.mdl" in m["actor_models"]
    assert "models/actors/thugs/thug_uwb_l.mdl" in m["actor_models"]
    assert set(m["mdl_first_words"]) == {"01004018"}
