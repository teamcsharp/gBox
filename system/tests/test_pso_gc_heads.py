"""CP13: the GameCube head/hair/cap part naming, and the opt-in that replaces them with stand-ins."""
import pathlib

import pytest

from gbox import pso_player

DISC = pathlib.Path(r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved"
                    r"\Phantasy Star Online Episode I & II Plus (USA).iso")


def test_gc_head_parts_matches_the_flat_lower_case_naming():
    names = ["plChed00.nj", "plChed01.nj", "plChai00.nj", "plCcap07.nj", "PLCHED00.NJ",
             "pso/PLCBDY00.NJ", "plCbdy00.nj", "plAbdy00.nj"]
    assert pso_player.gc_head_parts(names, "c") == ["PLCHED00.NJ", "plCcap07.nj", "plChai00.nj", "plChed00.nj", "plChed01.nj"]
    assert pso_player.gc_head_parts(names, "A") == []          # no class-A parts in this list


def test_gc_head_parts_finds_the_real_class_parts():
    from gbox import gcdisc
    if not DISC.is_file():
        pytest.skip("the disc is not on this machine")
    disc = gcdisc.GCDisc(str(DISC))
    c_parts = pso_player.gc_head_parts(list(disc.files), "C")
    assert "plChed00.nj" in c_parts
    assert len(c_parts) == 5                                  # measured: C has five heads, no hair (an android)
    a_parts = pso_player.gc_head_parts(list(disc.files), "A")
    assert any("hed" in n for n in a_parts) and any("hai" in n for n in a_parts)


def test_build_swap_advertises_the_opt_in():
    import inspect
    sig = inspect.signature(pso_player.build_swap)
    assert sig.parameters["replace_heads"].default is False     # off by default: not yet verified in game
