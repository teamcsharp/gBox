"""Encrypted GameCube Action Replay codes decrypt (a port of Dolphin's ARDecrypt) and decode to gBox writes.

The published Soul Calibur II (USA) codes: every batch's verification line carries a CRC over the batch plus the
game id and region, so a batch that verifies proves the port and the transcription at once."""
import pytest

from gbox import ar_decrypt as A, cheats as C

SC2 = {
    "master": (["ZNKR-J50V-BV1NH", "2MXM-TPTG-U7B4G"], ["C418C6D0 0000FF00"]),
    "all characters": (["DH6Z-D4P8-0A4BF", "R3DX-AMGV-49BQR"], ["02402160 00030303"]),
    "everything": (["BDWH-6JW4-YRFYG", "AT34-4G4T-3DYGQ"], ["00402160 00011303"]),
    "all levels": (["46QK-1AW0-FJ1AZ", "1JBT-4T4H-GUWPA", "EXZF-8Y18-8UP2T"], ["004021B3 00000003", "044021B4 03030303"]),
    "p1 health": (["9YYT-HGKH-4ZM97", "D98U-7AP4-UMHA2"], ["0434EA1C 43700000"]),
}


def test_every_published_batch_verifies_and_names_the_same_game():
    for name, (lines, raw) in SC2.items():
        got = A.decrypt(lines)
        assert got["verified"] and got["raw"] == raw, name
        assert (got["game_id"], got["region"]) == (485, 0), name
    assert A.decrypt(["dh6z-d4p8-0a4bf", "r3dxamgv49bqr"])["raw"] == ["02402160 00030303"], "case and hyphens are free"


def test_a_wrong_character_fails_parity_or_the_batch_crc():
    with pytest.raises(ValueError, match="parity"):
        A.decrypt(["DH6Z-D4P9-0A4BF", "R3DX-AMGV-49BQR"])
    assert A.decrypt(["DH6Z-D4P8-0A4BA", "R3DX-AMGV-49BQR"])["verified"] is False, "a slip that keeps parity still fails the CRC"
    swapped = A.decrypt(["R3DX-AMGV-49BQR", "DH6Z-D4P8-0A4BF"])    # lines out of order: no verification line first
    assert swapped["verified"] is False and len(swapped["codes"]) == 2
    with pytest.raises(ValueError, match="13 characters"):
        A.decrypt(["DH6Z-D4P8"])


def test_gamecube_decode_takes_encrypted_codes_and_counts_action_replay_fills_like_dolphin():
    ops, bad = C.decode("gamecube", "DH6Z-D4P8-0A4BF\nR3DX-AMGV-49BQR")
    assert bad == [] and ops == [("w", 0x80402160 + 2 * i, b"\x03\x03") for i in range(4)]
    ops, bad = C.decode("gamecube", "BDWH-6JW4-YRFYG;AT34-4G4T-3DYGQ")
    assert bad == [] and len(ops) == 0x113 + 1 and ops[0] == ("w", 0x80402160, b"\x03") and ops[-1][1] == 0x80402160 + 0x113
    ops, bad = C.decode("gamecube", "46QK-1AW0-FJ1AZ\n1JBT-4T4H-GUWPA\nEXZF-8Y18-8UP2T")
    assert bad == [] and ops == [("w", 0x804021B3, b"\x03"), ("w", 0x804021B4, b"\x03\x03\x03\x03")]
    assert C.decode("gamecube", "R3DX-AMGV-49BQR\nDH6Z-D4P8-0A4BF") == ([], ["R3DX-AMGV-49BQR: the batch did not verify (a line is wrong or missing)"])
    assert C.decode("gamecube", "DH6Z-D4P8-0A4BA\nR3DX-AMGV-49BQR")[0] == []


def test_raw_lines_keep_the_gecko_count_and_action_replay_lines_get_theirs():
    gecko, _ = C.decode_writes(["00402160 00011303"])
    assert len(gecko) == 2, "a raw line without a kind is a Gecko code: (v >> 16) + 1 writes"
    ar, _ = C.decode_writes(["00402160 00011303"], "ar")
    assert len(ar) == 0x114 and ar[0] == (0x80402160, b"\x03")
    assert C.decode_writes(["02402160 00030303"], "ar")[0] == C.decode_writes(["02402160 00030303"])[0], "16-bit counts agree"
