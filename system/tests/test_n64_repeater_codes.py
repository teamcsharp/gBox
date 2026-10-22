from gbox import cheats


def test_turok_rage_wars_repeater_codes_decode():
    # libretro Turok - Rage Wars (E): "All Characters" 50000301 0000;8010EB51 00FF -> 3 bytes at 8010EB51..53
    ops, bad = cheats.decode("n64", "50000301 0000;8010EB51 00FF")
    assert not bad
    assert [o[1] for o in ops] == [(0x8010EB51 + i) ^ 3 for i in range(3)]
    assert all(o == ("w", o[1], b"\xff") for o in ops)
    # "Have All Medals": plain write, then repeater of 6 at step 1
    ops, bad = cheats.decode("n64", "8010EB50 0003;50000601 0000;8010EB4A 00FF")
    assert not bad and len(ops) == 7
    # 16-bit repeater with value step, and the repeater applies only to the next line
    ops, bad = cheats.decode("n64", "50000202 0001;8110EB72 0010;8010EB00 0001")
    assert not bad
    assert [o[2] for o in ops] == [b"\x10\x00", b"\x11\x00", b"\x01"]
    # step 0 / malformed repeater is refused, not guessed
    assert cheats.decode("n64", "50000300 0000;8010EB51 00FF")[1]
    assert cheats.decode("n64", "50000001 0000;8010EB51 00FF")[1]
    # placeholder XXXX modifiers stay unsupported
    assert cheats.decode("n64", "8110EB76 XXXX")[1]
