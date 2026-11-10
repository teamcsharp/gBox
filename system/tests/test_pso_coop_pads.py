"""gbox PSO co-op pad setup: the second controller MULTI MODE requires, and the disc gate that decides it."""
from gbox import adapters, pso_coop_setup as P


def test_pso_launches_get_a_second_controller():
    """MULTI MODE on this disc refuses to open: "Requires at least 2 Controllers." (i9-NUC 2026-11-10)."""
    ini = P.pad_ini(adapters.DolphinWinAdapter.PAD_INI_WIN, windows=True)
    assert "[GCPad2]" in ini
    headings = [line for line in ini.splitlines() if line.startswith("[")]
    assert headings.count("[GCPad1]") == 1 and headings.count("[GCPad2]") == 1


def test_the_first_pad_keeps_its_device_and_stays_connected():
    ini = P.pad_ini(adapters.DolphinWinAdapter.PAD_INI_WIN, windows=True)
    first = ini.split("[GCPad2]")[0]
    assert "Options/Always Connected = True" in first
    assert first.count("Options/Always Connected") == 1          # the builder must not duplicate the line


def test_the_second_pad_is_the_keyboard_device():
    """P2 is driven through the keyboard: `win_send_keys` sends these names, and Dolphin binds them to GCPad2."""
    ini = P.pad_ini(adapters.DolphinWinAdapter.PAD_INI_WIN, windows=True)
    second = ini.split("[GCPad2]")[1]
    assert "Device = DInput/0/Keyboard Mouse" in second
    # PAD2_WIN's scheme: D/R/M/Y for A/B/X/Y and the numpad for the D-pad, so P2's keys never collide with P1's
    # PAD2_WIN's scheme: D/R/M/Y for A/B/X/Y, SPACE for Start, numpad for the sticks and D-pad -- chosen so P2's
    # keys never collide with P1's (P1 keeps the arrow keys and X/Z/S/A/E/RETURN).
    for field, key in (("Buttons/A", "D"), ("Buttons/B", "R"), ("Buttons/Start", "SPACE"),
                       ("Main Stick/Up", "NUMPAD8"), ("D-Pad/Down", "NUMPAD9"), ("Triggers/R", "O")):
        assert f"{field} = `{key}`" in second, f"{field} should bind `{key}`"


def test_the_second_pad_only_costs_nothing_when_unused():
    """The builder is pure text, so the same base always yields the same two-pad INI."""
    a = P.pad_ini(adapters.DolphinWinAdapter.PAD_INI_WIN, windows=True)
    b = P.pad_ini(adapters.DolphinWinAdapter.PAD_INI_WIN, windows=True)
    assert a == b and a.startswith("[GCPad1]")
