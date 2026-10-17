import os

import pytest

from gbox.sfxt_inventory import eaf_header, inventory


def test_eaf_header_big_endian_cmn_boot():
    # CMN_boot.eaf header (first 32 bytes observed on the owned disc).
    head = bytes.fromhex(
        "23454146"  # #EAF
        "00010000"  # version_word 0x00010000
        "00000000"
        "00b6dc2f"  # data_size 0x00b6dc2f == 11983919 == file size
        "00000043"  # entry_count 67
        "00000001"
        "00000000"
        "00000000"
    )
    h = eaf_header(head)
    assert h["magic"] == "#EAF"
    assert h["version_word"] == 0x00010000
    assert h["data_size"] == 11983919
    assert h["entry_count"] == 67


def test_eaf_header_big_endian_cmn():
    # CMN.eaf header (first 32 bytes): entry_count 11610, big-endian.
    head = bytes.fromhex(
        "23454146"
        "00010000"
        "00000000"
        "7f64a660"
        "00002d5a"  # 11610 entries
        "00000001"
        "00000000"
        "00000000"
    )
    h = eaf_header(head)
    assert h["magic"] == "#EAF"
    assert h["entry_count"] == 11610


@pytest.mark.skipif(
    not os.environ.get("GBOX_SFXT_ISO"),
    reason="set GBOX_SFXT_ISO to the owned Street Fighter X Tekken.iso",
)
def test_inventory_owned_iso():
    result = inventory(os.environ["GBOX_SFXT_ISO"])
    assert result["platform"] == "xbox360"
    assert result["executable"]["magic"] == "XEX2"
    assert result["executable"]["name"] == "default.xex"
    assert any(e["path"] == "archive/CMN/CMN.eaf" for e in result["eaf_archives"])


@pytest.mark.parametrize("size", range(4, 24))
def test_eaf_header_rejects_truncated_words(size):
    with pytest.raises(ValueError, match="truncated EAF"):
        eaf_header((b"#EAF" + bytes(20))[:size])


def test_image_reads_and_hashing_reject_truncation():
    from io import BytesIO
    from gbox.sfxt_inventory import XDVDFS
    image = XDVDFS.__new__(XDVDFS)
    image.f, image.base, image.size = BytesIO(b"abc"), 0, 3
    with pytest.raises(ValueError):
        image.read(0, 4)
    with pytest.raises(ValueError):
        image.read(0, -1)
    with pytest.raises(ValueError, match="hashing"):
        image.sha256(0, 4)
