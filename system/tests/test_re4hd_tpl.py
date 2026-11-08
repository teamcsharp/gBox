"""The TPL image writer: replace a pack's own texture in place, and refuse anything that changes its size.

The tests that matter run against the real pack (skipped when the RomFS is not extracted here): a same-byte replacement must reproduce
the pack exactly, and a different length must be refused rather than corrupting the surrounding DAT slot.
"""
import struct
from pathlib import Path

import pytest

from gbox import re4hd_tex as T

PL08 = Path.home() / "gBox_alt" / "switch" / "romfs" / "010099A00BC1E000" / "bio4" / "em" / "pl08.udas"
needs_pack = pytest.mark.skipif(not PL08.is_file(), reason="the RE4 Switch RomFS is not extracted on this machine")
# Measured 2026-11-08: `pl08`'s TPL slots hold **descriptors only** - 9 records of 40 bytes in 608 bytes of slot, and zero `DDS `
# magics. The record's last u32 is an offset into a store that lives outside the slot (520, 528, 536... stride 8), not a byte count.
# So reading or replacing a payload through this container is not possible until that store is located; the writer below is correct
# for a container that *does* hold payloads and is what the store's own container will need.
needs_payload = pytest.mark.xfail(reason="the pack's TPL holds descriptors only; the image store is elsewhere (measured 2026-11-08)",
                                  strict=False)


def test_a_dds_that_is_not_a_dds_is_refused():
    with pytest.raises(T.TexError):
        T.tpl_replace_image(b"\x00" * 64, 0, b"not-a-dds")


def test_a_container_without_the_magic_is_refused():
    with pytest.raises(T.TexError):
        T.tpl_image_dds(b"\x00" * 64, 0)


@needs_pack
@needs_payload
def test_the_players_body_texture_is_a_tpl_image_with_an_id():
    data = PL08.read_bytes()
    slot, index, dds = T.tpl_image_for(data, 0)
    assert dds.startswith(b"DDS "), "the payload is a DDS surface"
    assert len(dds) > 1000, f"a body texture is not {len(dds)} bytes"
    assert slot >= 0 and index >= 0


@needs_pack
@needs_payload
def test_replacing_an_image_with_itself_reproduces_the_pack():
    data = PL08.read_bytes()
    _slot, _index, dds = T.tpl_image_for(data, 0)
    patched = T.tpl_replace_image(data, 0, dds)
    assert patched == data, "an identical replacement must not change one byte of the pack"


@needs_pack
@needs_payload
def test_a_payload_must_keep_its_length():
    data = PL08.read_bytes()
    _slot, _index, dds = T.tpl_image_for(data, 0)
    with pytest.raises(T.TexError) as raised:
        T.tpl_replace_image(data, 0, dds + b"\x00")
    assert "own size" in str(raised.value)


@needs_pack
def test_a_missing_texture_id_says_so():
    data = PL08.read_bytes()
    with pytest.raises(T.TexError) as raised:
        T.tpl_image_for(data, 0x7FFFFFFF)
    assert "no TPL image" in str(raised.value)
