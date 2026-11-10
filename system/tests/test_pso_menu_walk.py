"""gbox.pso_menu_walk: the RAM probe, its false positives, and the pad precondition.

No emulator: a synthetic memory image proves the constancy filter, the diff, the signature and the pad check.
"""
import pytest

from gbox import pso_menu_walk as M
from gbox import pso_ram as R


class Mem:
    """read_memory over a 24 MiB image, with optional bytes that change on every read (animated UI)."""

    def __init__(self, animated=()):
        self.data = bytearray(R.RAM_END - R.RAM_START)
        self.animated = list(animated)
        self.reads = 0

    def poke(self, address, blob):
        off = address - R.RAM_START
        self.data[off:off + len(blob)] = blob

    def read_memory(self, address, length):
        off = address - R.RAM_START
        if off < 0 or off + length > len(self.data):
            return None
        blob = bytearray(self.data[off:off + length])
        self.reads += 1
        for a in self.animated:
            k = a - address
            if 0 <= k < length:
                blob[k] = (self.reads * 7) & 0xFF
        return bytes(blob)


def test_the_mode_byte_is_documented_as_not_a_screen_id():
    assert M.MODE_BYTE == 0x80516303 and M.MODE_BYTE_MIRROR == 0x805145F7
    # the same value appears on two different screens: that is the documented fact, not a bug
    assert len(M.MODES_SEEN[1]) == 2 and "SELECT CHARACTER" in M.MODES_SEEN[1]
    assert M.MODES_SEEN[9] == ("SELECT GAME MODE",)
    assert M.OFFLINE_PATH[2] == "OFFLINE GAME" and M.OFFLINE_PATH[-1] == "SELECT CHARACTER"
    assert M.MAIN_MENU_ITEMS[1] == "OFFLINE GAME"


def test_stable_keeps_a_constant_byte_and_drops_an_animated_one():
    m = Mem(animated=[0x804E0010])
    m.poke(0x804E0010, b"\x01")
    m.poke(0x804E0020, b"\x05")
    values, constancy = M.stable(M.Counting(m), [(0x804E0000, 0x40)], samples=3, gap=0.0, sleep=lambda _s: None)
    assert constancy[0x10] == 0                       # animated: dropped
    assert constancy[0x20] == 1 and values[0x20] == 5  # constant: kept
    assert len(values) == 0x40


def test_stable_diff_reports_only_the_bytes_that_track_the_state():
    m = Mem(animated=[0x804E0010])
    m.poke(0x804E0020, b"\x00")
    a = M.stable(M.Counting(m), [(0x804E0000, 0x40)], samples=3, gap=0.0, sleep=lambda _s: None)
    m.poke(0x804E0020, b"\x02")
    b = M.stable(M.Counting(m), [(0x804E0000, 0x40)], samples=3, gap=0.0, sleep=lambda _s: None)
    assert M.stable_diff(a, b, [(0x804E0000, 0x40)]) == [(0x804E0020, 0, 2)]


def test_stable_rejects_a_short_read():
    class Short:
        def read_memory(self, address, length):
            return b"\x00" * (length - 1)

    with pytest.raises(M.MenuError):
        M.stable(Short(), [(0x804E0000, 8)], samples=2, gap=0.0, sleep=lambda _s: None)


def test_signature_drops_volatile_addresses_and_similarity_compares_them():
    m = Mem(animated=[0x80516200])
    m.poke(0x80516200, b"\x01")
    m.poke(0x80516201, b"\x02")
    m.poke(0x80516202, b"\x03")
    addrs = [0x80516200, 0x80516201, 0x80516202]
    s1 = M.signature(M.Counting(m), addrs, samples=3, gap=0.0, sleep=lambda _s: None)
    assert s1["dropped"] == 1 and s1["count"] == 2       # the animated one is not in the vector
    assert M.similarity(s1, s1) == 1.0

    m2 = Mem(animated=[0x80516200])
    m2.poke(0x80516200, b"\x01")
    m2.poke(0x80516201, b"\x99")                          # one kept byte differs
    m2.poke(0x80516202, b"\x03")
    s2 = M.signature(M.Counting(m2), addrs, samples=3, gap=0.0, sleep=lambda _s: None)
    assert M.similarity(s1, s2) == pytest.approx(0.5)
    assert len(s1["sha256"]) == 64


def test_verify_pad_binding_accepts_a_virtual_pad_and_rejects_the_keyboard(tmp_path):
    cfg = tmp_path / "User" / "Config"
    cfg.mkdir(parents=True)
    ini = cfg / "GCPadNew.ini"
    ini.write_text("[GCPad1]\nOptions/Always Connected = True\nDevice = XInput/2/Gamepad\nButtons/A = `Button A`\n")
    ok = M.verify_pad_binding(tmp_path / "User")
    assert ok["bound"] is True and ok["device"] == "XInput/2/Gamepad"
    ini.write_text("[GCPad1]\nDevice = XInput/0/Gamepad\nButtons/A = `Button A` | `DInput/0/Keyboard Mouse:X`\n")
    bad = M.verify_pad_binding(tmp_path / "User")
    assert bad["bound"] is False and "keyboard" in bad["why"]
    assert M.verify_pad_binding(tmp_path / "nope")["bound"] is False


def test_counting_reports_what_it_read():
    m = Mem()
    w = M.Counting(m)
    w.read_memory(0x804E0000, 16)
    assert w.calls == 1 and w.bytes_read == 16
