"""DOA3's virtual controller (gbox.doa3_pad): gBox's pad on the game's 4th port, in guest RAM, and nothing else."""
import struct
from types import SimpleNamespace

import pytest

from gbox import doa3_native as native
from gbox import doa3_pad as P
from gbox.config import Config


class Mem:
    """Guest RAM with a write log; refuses anything outside the pad's block like the adapter's channel does."""

    def __init__(self):
        self.ram = bytearray(0x600000)
        self.writes = []

    def read(self, address, n):
        return bytes(self.ram[address:address + n])

    def write(self, address, data):
        assert any(lo <= address and address + len(data) <= lo + n for lo, n in P.BLOCK), hex(address)
        self.writes.append((address, bytes(data)))
        self.ram[address:address + len(data)] = data


def gamepad(mem):
    buttons, *analog = struct.unpack_from("<H8B", mem.ram, P.STATE_AT + 4)
    return buttons, analog


def test_the_block_is_port_4_of_the_games_own_pad_table():
    assert (P.HANDLE_AT, P.STATE_AT) == (0x5E5EC8, 0x5E5E69)          # 0x5E5D48 / 0x5E5CE9 + 3 * 0x80 (0x0009EAF0)
    assert P.BLOCK == ((0x5E5EC8, 4), (0x5E5E69, 22))
    assert P.SENTINEL & 0xFFFF0000 != P.RUNNER_HANDLE                 # never a handle the runner answers


def test_encode_maps_retropad_names_to_xinput():
    assert P.encode({"up", "start"}) == struct.pack("<H", 0x11) + bytes(8)
    data = P.encode({"b", "a", "y", "x", "r", "l", "l2", "r2", "right"})
    assert struct.unpack("<H8B", data) == (0x8, 255, 255, 255, 255, 255, 255, 255, 255)
    assert P.encode({"y"})[2:] == bytes([0, 0, 255, 0, 0, 0, 0, 0])   # RetroPad west = Xbox X
    with pytest.raises(ValueError):
        P.encode({"z"})


def test_claim_installs_a_neutral_pad_then_its_handle():
    mem = Mem()
    pad = P.VirtualPad(mem)
    assert pad.claim() is True
    assert [a for a, _ in mem.writes] == [P.STATE_AT, P.HANDLE_AT]    # state first: the first poll reads neutral
    assert struct.unpack_from("<I", mem.ram, P.HANDLE_AT)[0] == P.SENTINEL
    assert gamepad(mem) == (0, [0] * 8)
    assert pad.claim() is False and len(mem.writes) == 2               # already ours


def test_a_real_controller_on_port_4_is_never_taken():
    mem = Mem()
    struct.pack_into("<I", mem.ram, P.HANDLE_AT, 0x58490004)          # the runner's handle for a 4th real pad
    with pytest.raises(P.PadTaken):
        P.VirtualPad(mem).claim()
    struct.pack_into("<I", mem.ram, P.HANDLE_AT, 0x12345678)
    with pytest.raises(P.PadTaken):
        P.VirtualPad(mem).set({"a"})
    assert mem.writes == []


def test_apply_holds_and_releases_and_shows_a_tap_for_two_frames():
    mem, slept = Mem(), []
    pad = P.VirtualPad(mem)
    pad.apply([{"key": "left", "down": True}, {"key": "y", "down": True}])
    assert gamepad(mem) == (0x4, [0, 0, 255, 0, 0, 0, 0, 0]) and pad.held == {"left", "y"}
    pad.apply([{"key": "y", "down": False}])
    assert gamepad(mem) == (0x4, [0] * 8)
    states = []
    real = mem.write
    mem.write = lambda a, d: (states.append(d[4:]) if a == P.STATE_AT else None, real(a, d))
    pad.apply([{"key": "start", "down": True}, {"key": "start", "down": False}], sleep=slept.append)
    assert slept == [P.VirtualPad.TAP_S]                              # pressed long enough for a frame to see it
    assert [struct.unpack("<H", s[:2])[0] for s in states] == [0x14, 0x4]
    pad.apply([{"key": "lup", "down": True}, {"key": "a", "down": True, "player": 2}])   # not on this pad: ignored
    assert gamepad(mem) == (0x4, [0] * 8)


def test_packets_count_like_a_real_pad_and_unclaim_gives_the_port_back():
    mem = Mem()
    pad = P.VirtualPad(mem)
    pad.set({"b"})
    pad.set(set())
    assert struct.unpack_from("<I", mem.ram, P.STATE_AT)[0] == 3       # neutral at claim, b, release
    pad.unclaim()
    assert struct.unpack_from("<I", mem.ram, P.HANDLE_AT)[0] == 0 and gamepad(mem) == (0, [0] * 8)
    assert not pad.claimed


def test_connected_and_player_port_read_the_games_own_tables():
    mem = Mem()
    pad = P.VirtualPad(mem)
    assert not pad.connected()
    mem.ram[P.CONNECTED_AT] = 0x9                                      # ports 1 and 4 polled this frame
    mem.ram[P.PLAYER_PORT_AT:P.PLAYER_PORT_AT + 4] = bytes([3, 1, 2, 3])
    assert pad.connected() and pad.player_port(0) == 3 and pad.player_port(1) == 1


def test_adapter_send_input_goes_through_its_channel_to_port_4_only():
    ad = native.Doa3NativeAdapter(Config(), {})
    mem = Mem()
    ad._channel = SimpleNamespace(read=mem.read, write=mem.write, broken=None, close=lambda: None)
    out = ad.send_input([{"key": "b", "down": True}])
    assert out["sent"] == 1 and out["held"] == ["b"] and gamepad(mem)[1][0] == 255
    assert {a for a, _ in mem.writes} <= {P.HANDLE_AT, P.STATE_AT}
    ad._drop_pad()                                                     # stop: released, channel closed
    assert gamepad(mem) == (0, [0] * 8) and ad._channel is None and ad._pad is None
