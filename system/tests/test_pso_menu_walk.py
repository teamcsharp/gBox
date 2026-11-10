"""gbox.pso_menu_walk: the boot-screen id and the first P1 step, on synthetic memory."""
import pytest

from gbox import pso_menu_walk as M
from gbox import pso_ram as R


class Mem:
    def __init__(self):
        self.data = bytearray(R.RAM_END - R.RAM_START)

    def poke(self, address, blob):
        off = address - R.RAM_START
        self.data[off:off + len(blob)] = blob

    def read_memory(self, address, length):
        off = address - R.RAM_START
        if off < 0 or off + length > len(self.data):
            return None
        return bytes(self.data[off:off + length])


def game(screen, phase=0):
    m = Mem()
    m.poke(M.BOOT_SCREEN, bytes([screen]))
    m.poke(M.BOOT_SCREEN_MIRROR, bytes([screen]))
    m.poke(R.PHASE, bytes([phase]))
    return m


def test_the_proven_screen_ids_are_named():
    assert M.PRESS_START == 3 and M.MAIN_MENU == 1 and M.ONLINE_SUBMENU == 9
    assert M.BOOT_SCREEN == 0x80516303 and M.BOOT_SCREEN_MIRROR == 0x805145F7
    assert M.screen_name(3) == "press_start" and M.screen_name(1) == "main_menu"
    assert M.screen_name(9) == "online_submenu"
    assert M.screen_name(77) == "unknown(77)"
    assert M.MAIN_MENU_ITEMS[1] == "OFFLINE GAME"


def test_screen_reads_the_id_and_refuses_a_torn_read():
    assert M.screen(R.Reader(game(3))) == 3
    assert M.screen(R.Reader(game(1))) == 1
    m = game(3)
    m.poke(M.BOOT_SCREEN_MIRROR, bytes([1]))
    with pytest.raises(M.MenuError):
        M.screen(R.Reader(m))


def test_describe_separates_press_start_from_the_menu():
    a = M.describe(R.Reader(game(3)))
    assert a == {"screen": 3, "name": "press_start", "phase": 0, "at_press_start": True, "in_main_menu": False}
    b = M.describe(R.Reader(game(1, phase=0)))
    assert b["at_press_start"] is False and b["in_main_menu"] is True


def test_press_start_walks_from_press_start_to_the_menu():
    m = game(3)
    presses = []

    def press(key):
        presses.append(key)
        m.poke(M.BOOT_SCREEN, bytes([1]))              # the game reacts to START
        m.poke(M.BOOT_SCREEN_MIRROR, bytes([1]))

    out = M.press_start(R.Reader(m), press, settle=0.0, wait=1.0, sleep=lambda _s: None)
    assert out["ok"] is True and out["screen"] == 1 and out["from_press_start"] is True
    assert presses == ["start"]                        # exactly one press, not a spam
    assert out["trace"][0] == 3 and out["trace"][-1] == 1


def test_press_start_is_a_no_op_when_already_in_the_menu():
    m = game(1)
    out = M.press_start(R.Reader(m), lambda k: pytest.fail("pressed in the menu"), settle=0.0, sleep=lambda _s: None)
    assert out["ok"] is True and out["from_press_start"] is False


def test_press_start_refuses_to_press_start_on_an_unknown_screen():
    m = game(9)
    with pytest.raises(M.MenuError):
        M.press_start(R.Reader(m), lambda k: pytest.fail("pressed blind"), settle=0.0, sleep=lambda _s: None)


def test_press_start_reports_failure_when_the_press_does_nothing():
    m = game(3)
    presses = []

    def press(key):
        presses.append(key)

    out = M.press_start(R.Reader(m), press, tries=3, settle=0.0, wait=0.05, sleep=lambda _s: None)
    assert out["ok"] is False and out["screen"] == 3
    assert presses == ["start", "start", "start"]
