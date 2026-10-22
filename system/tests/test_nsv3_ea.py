"""Focused tests for the NBA Street V3 native reader (gbox.nsv3_ea).

The synthetic tests always run.  The owned-build tests run against the real ROM when it can be
located, and are skipped otherwise (so the suite stays usable on a machine without the disc).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox.nsv3_ea import (  # noqa: E402
    BigArchive, build_big, character_slots, decode_gsh, parse_header,
)

GAME_ID = "c7c407414dfd06b4"
EXPECTED_PLAYER_COUNT = 177
TARGET_SLOT = "warriorsDUNLEAVY_lrg.gsh"
TARGET_TAG = "warr"


def locate_rom():
    """Find the owned NBA Street V3 ISO, or None."""
    cands = []
    env = os.environ.get("NSV3_ROM")
    if env:
        cands.append(Path(env))
    roots = [os.environ.get("GBOX_MODBASE"),
             "/home/ehm_eckx/gBox_alt/gbox-cache/modbase/" + GAME_ID]
    for root in roots:
        if not root:
            continue
        p = Path(root)
        if p.is_file():
            cands.append(p)
        elif p.is_dir():
            cands.extend(sorted(p.glob("*.iso")))
    for c in cands:
        if c.is_file():
            return c
    return None


def test_build_big_roundtrip():
    """A container we build parses back to the same members and bytes."""
    blobs = [("a.gsh", b"AAA"), ("b.gsh", b"BBBB")]
    data = build_big(blobs)
    arc = BigArchive(lambda o, n: data[o:o + n])
    assert arc.header.magic == b"BIGF"
    assert arc.header.count == 2
    assert arc.names() == ["a.gsh", "b.gsh"]
    assert arc.read_member("a.gsh") == b"AAA"
    assert arc.read_member("b.gsh") == b"BBBB"
    assert arc.member("b.gsh").offset == arc.header.data_start + 3


def test_parse_header_rejects_foreign_magic():
    try:
        parse_header(b"XXXX" + b"\0" * 12)
    except ValueError as exc:
        assert "not an EA BIG container" in str(exc)
    else:
        raise AssertionError("foreign magic accepted")


def test_owned_build_player_archive():
    """The owned ROM exposes the real character roster through the BIG walk."""
    rom = locate_rom()
    if rom is None:
        import pytest
        pytest.skip("owned NBA Street V3 ROM not present")
    from gbox.gcdisc import GCDisc
    disc = GCDisc(str(rom))
    try:
        arc = BigArchive(lambda o, n: disc._r(disc.files["fe/players.viv"][0] + o, n))
        assert arc.header.magic in (b"BIGF", b"BIG4")
        assert arc.header.count == len(arc.members) == 519
        for m in arc.members:
            assert m.offset + m.size <= arc.header.total_size, m.name
        slots = character_slots(arc)
        assert len(slots) == EXPECTED_PLAYER_COUNT
        assert TARGET_SLOT in slots
        gsh = decode_gsh(arc.read_member(TARGET_SLOT))
        assert gsh.payload[:4] == b"SHPG"
        assert gsh.tag == TARGET_TAG
        assert gsh.unpacked_size > gsh.compressed_size
    finally:
        disc.f.close()


def _main():
    failed = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print("PASS", name)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("FAIL", name, type(exc).__name__, exc)
    print("failed:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
