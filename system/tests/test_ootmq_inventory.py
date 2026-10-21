"""Owned-build inventory pins for Ocarina of Time Master Quest retail (NZLP, PAL GameCube disc).

The catalog entry "Legend of Zelda, The - Ocarina of Time - Master Quest (Europe) (GameCube Edition)"
(platform n64, core parallel_n64) is the 32 MiB NZLP retail ROM from the PAL Master Quest GameCube disc.
Its zip member is stored v64 despite the .z64 name, so the big-endian normalize step matters. The ROM
shares the gc-eu dmadata/code layout (dmadata 0x7170), which gbox.oot_writer resolves via md5 pin.
"""
import json
from pathlib import Path

import pytest

from gbox import oot_writer as OW

OWNED = Path.home() / "gBox_alt/gbox-cache/ff72441b33ff806b/source.zip"
MD5 = "1618403427e4344a57833043db5ce3c3"


def test_md5_pins_the_mq_retail_build():
    assert OW.MD5[MD5] == "gc-eu-mq"
    assert OW.VERSIONS["gc-eu-mq"]["dma"] == 0x7170
    assert OW.VERSIONS["gc-eu-mq"] == OW.VERSIONS["gc-eu"]       # same layout, own name


@pytest.mark.skipif(not OWNED.is_file(), reason="owned OoT MQ retail ROM not cached on this host")
def test_owned_mq_retail_inventory():
    from gbox import oot_inventory as OI
    m = OI.inventory(OWNED)
    s, h = m["source"], m["header"]
    assert s["sha256"] == "a01fff9024ba2bcdc4f07d7fa3b8520f80ecc6e4af6a41520bce3b7e5abe613b"
    assert s["member_byte_order"] == "v64 (halfword-swapped)"    # .z64-named member is stored v64
    assert s["normalized_md5"] == MD5
    assert s["normalized_sha256"] == "ed392a890d5fab1c4d6863c69a40df6ca966f568160f2b2a9a73e5d02a6e93c2"
    assert s["rom_size"] == 33554432
    assert s["version"] == "gc-eu-mq" and s["version_by_md5"]
    assert s["build_label"].startswith("Master Quest retail")
    assert h["game_code"] == "NZLP" and h["entry"] == "80000400"
    assert m["launch"]["crc_valid"] and m["launch"]["core"].startswith("parallel_n64")
    L = m["layout"]
    assert L["dmadata"] == "0x7170" and L["files"] == 1510 and L["yaz0_files"] == 1456
    assert L["code"]["dma_index"] == 28 and L["code"]["vram"] == "0x80010F00" and L["code"]["size"] == 1057328
    assert L["gObjectTable"] == "code+0xE4F58" and L["gActorOverlayTable"] == "code+0xD4480"
    assert m["summary"]["objects"] == 380 and m["summary"]["skeletal_objects"] == 155
    assert m["summary"]["skeletons"] == 181 and m["summary"]["animation_headers"] == 968
    for age, off, dma in (("adult", "0x377F4", 502), ("child", "0x2CF6C", 503)):
        link = m["link"][age]
        assert link["skeleton"]["offset"] == off and link["skeleton"]["limbs"] == 21
        assert link["skeleton"]["lod"] and link["dma_index"] == dma
        assert link["found_by_scan"] and link["writer_offset_ok"]   # oot_swap can write both slots
    assert m["link"]["shared"]["link_animetion"]["dma_index"] == 6
    assert m["link"]["shared"]["ovl_player_actor"]["dma_index"] == 34


@pytest.mark.skipif(not OWNED.is_file(), reason="owned OoT MQ retail ROM not cached on this host")
def test_owned_mq_retail_manifest_is_serializable():
    from gbox import oot_inventory as OI
    json.dumps(OI.inventory(OWNED))
