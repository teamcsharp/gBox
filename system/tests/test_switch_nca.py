"""NCA reading (gbox.switch_nca): the conventions measured against the RE6 update (01002A000CD48800 v131072).

The header and PFS0 vectors are the real encrypted bytes; the test reads the operator's `prod.keys` through
gbox.hactool.keys_path() and skips when this PC has none (no keys belong in the repository). No decrypted game data
is stored here.
"""
import base64

import pytest

from gbox import hactool
from gbox import switch_nca as N

HEADER = base64.b64decode("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")
PFS_HEAD = base64.b64decode("IijTnZHXmQ9Z2qiVVN7HPUwdTCiIgedwinJQw8I/KM1fWf1KdGQgOXLEYdydiH414lKfLPokKZywL5U4lptVOQ==")
TICKET_BLOCK = base64.b64decode("IySmnmQRZKeRVZPH858DpQ==")
KEYS = {}


def setup_module():
    path = hactool.keys_path()
    if not path:
        return
    KEYS.update(N.load_keys(path))


needs_keys = pytest.mark.skipif(not KEYS or "header_key" not in KEYS, reason="no prod.keys on this PC")


@needs_keys
def test_header_decrypts_to_the_update_identity():
    header = N.decrypt_header(HEADER, KEYS)
    assert header["magic"] == b"NCA3"
    assert header["title_id"] == "01002A000CD48000"
    assert header["size"] == 0x61D8200
    assert header["keyblob"] == 8 and N.titlekek_index(header) == 7
    assert header["rights_id"].startswith("01002a000cd48800")
    assert [s["fs_type"] for s in header["sections"]] == [N.FS_PFS0, N.FS_ROMFS]
    assert [s["crypt_type"] for s in header["sections"]] == [N.CRYPT_CTR, N.CRYPT_BKTR]
    assert header["sections"][0]["offset"] == 0x4794200
    assert header["sections"][0]["pfs0_offset"] == 0x8000
    assert header["sections"][0]["pfs0_size"] == 0x1A3B14E


def test_a_wrong_header_key_is_refused():
    with pytest.raises(ValueError, match="not an NCA header"):
        N.decrypt_header(HEADER, {"header_key": "00" * 32})


def test_section_iv_is_reversed_section_ctr_then_the_big_endian_offset():
    assert N.section_iv(bytes.fromhex("0100000001000000"), 0x479C200) == bytes.fromhex(
        "00000001000000010000000000479c20")


@needs_keys
def test_title_key_and_the_pfs0_head():
    key = N.title_key(bytes(0x180) + TICKET_BLOCK, KEYS, N.titlekek_index(N.decrypt_header(HEADER, KEYS)))
    iv = N.section_iv(bytes.fromhex("0100000001000000"), 0x479C200)
    plain = N.ctr_decrypt(key, PFS_HEAD, iv)
    assert plain[:4] == b"PFS0"


def test_read_pfs0_returns_members():
    table = b"main\x00abc\x00"
    entries = b"".join([N.struct.pack("<QQII", 0, 4, 0, 0), N.struct.pack("<QQII", 4, 3, 5, 0)])
    blob = N.struct.pack("<4sIII", b"PFS0", 2, len(table), 0) + entries + table + b"MAIN" + b"ABC"
    files = N.read_pfs0(blob)
    assert files == {"main": b"MAIN", "abc": b"ABC"}
    with pytest.raises(ValueError, match="not a PFS0"):
        N.read_pfs0(b"NOPE" + bytes(12))
