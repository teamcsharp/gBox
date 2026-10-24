"""#2854: Resident Evil 4 Mobile Edition (Zeebo / BREW) is catalogued as platform zeebo, not 'unknown'."""
from gbox import systems


def test_zeebo_and_brew_classify_as_zeebo():
    assert systems.classify("Zeebo") == ("zeebo", None, [])
    assert systems.classify("Qualcomm BREW")[0] == "zeebo"


def test_neighbours_unchanged():
    assert systems.classify("Nintendo GameCube")[0] == "gamecube"
    assert systems.classify("Sony PlayStation")[0] == "psx"
