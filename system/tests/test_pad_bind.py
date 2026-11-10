"""gbox.pad_bind: which XInput slot Dolphin's Player 1 should read (no emulator, no Windows)."""
from gbox import pad_bind as B

DEAD = (0, 0, 0, 0, 0, 0, 0)                 # the phantom virtual pad: exactly zero forever
REAL = (0, -160, 1387, -543, 1916, 0, 0)     # the operator's pad at rest (drift below XInput's deadzone)

INI = ("[GCPad1]\nOptions/Always Connected = True\nDevice = XInput/0/Gamepad\nButtons/A = `Button A`\n")
TWO = "[GCPad1]\nDevice = XInput/0/Gamepad\n[GCPad2]\nDevice = XInput/0/Gamepad\n"


def test_alive_separates_a_resting_controller_from_the_phantom():
    assert B.alive(REAL) is True
    assert B.alive(DEAD) is False
    assert B.alive((0, 0, 0, 0, 0, 40, 0)) is True           # a trigger alone is life
    assert B.alive({"buttons": 0, "lx": 0, "ly": 9000}) is True
    assert B.alive({"buttons": 0x1000}) is True


def test_choose_slot_skips_the_phantom():
    assert B.choose_slot({0: DEAD, 1: REAL}) == 1
    assert B.choose_slot({0: DEAD}) is None                  # nothing real to bind: leave the INI alone
    assert B.choose_slot({}) is None
    assert B.choose_slot({0: REAL, 1: REAL}) == 0             # lowest real slot when several report


def test_a_pad_gbox_just_created_wins_even_while_idle():
    assert B.choose_slot({0: DEAD, 1: REAL, 2: DEAD}, created=2) == 2
    assert B.choose_slot({0: DEAD, 1: REAL}, created=3) == 1  # a created slot that does not report is ignored


def test_bind_device_rewrites_the_first_device_line_only():
    out = B.bind_device(INI, 1)
    assert "Device = XInput/1/Gamepad" in out and "XInput/0" not in out
    assert B.bind_device(INI, None) == INI                   # no slot: untouched
    out2 = B.bind_device(TWO, 2)
    assert out2.count("XInput/2/Gamepad") == 1 and out2.count("XInput/0/Gamepad") == 1


def test_bind_note_says_why():
    out = B.bind_note(INI, 1)
    assert out.startswith("# gBox: Player 1 bound to XInput slot 1") and "Device = XInput/1/Gamepad" in out
    assert "virtual pad" in B.bind_note(INI, 1, created=True)
    assert B.bind_note(INI, None) == INI
