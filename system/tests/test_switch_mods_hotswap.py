"""switch_mods op=hotswap: the hot-reload experiment's in-place, same-length swap (gbox.switch_mods.hotswap).

A hot swap changes a build's own file at the same path and the same length while the title runs: the emulator
re-reads it at its next load and no restart happens. A different length re-packs the layer and is a restart, so it is
refused; so is a swap while a round plays, and a file the build does not hold.
"""
import json
from pathlib import Path

import pytest

from gbox import switch_mods as SM
from gbox.config import Config

RE6 = "01002A000CD48000"
GID = "115f9cdbba115432"
CREATE = {"title_id": RE6, "game_title": "Resident Evil 6", "base": "Resident Evil 6.nsp"}
BODY = "arc/NX/uPl00LeonUsa.arc"


def build(tmp_path, files=None) -> tuple[Config, Path]:
    c = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    files = files or {BODY: b"A" * 32}
    res = SM.write_files(c, GID, "recovery-hot", {k: {"bytes": v} for k, v in files.items()}, create=CREATE)
    return c, Path(res["dir"])


def test_hotswap_overwrites_in_place_keeping_the_length_and_the_manifest(tmp_path):
    c, folder = build(tmp_path)
    before = SM.read_meta(folder)
    out = SM.hotswap(c, GID, "recovery-hot", {BODY: {"bytes": b"B" * 8}})
    data = (folder / "romfs" / BODY).read_bytes()
    assert len(data) == 32 and data[:8] == b"B" * 8 and data[8:] == b"\x00" * 24
    after = SM.read_meta(folder)
    assert out["files"] == 1 and out["build"] == "recovery-hot"
    assert after["files"] == before["files"]                       # the file list does not change
    assert after["hot_swaps"] == 1 and after["history"][-1]["reload"] is True
    assert after["history"][-1]["files"][0]["path"] == f"romfs/{BODY}"


def test_hotswap_refuses_a_round_in_progress(tmp_path):
    c, folder = build(tmp_path)
    original = (folder / "romfs" / BODY).read_bytes()
    with pytest.raises(ValueError, match="round is playing"):
        SM.hotswap(c, GID, "recovery-hot", {BODY: {"bytes": b"B"}}, in_round=True)
    assert (folder / "romfs" / BODY).read_bytes() == original


def test_hotswap_refuses_longer_bytes_and_files_the_build_does_not_hold(tmp_path):
    c, folder = build(tmp_path)
    with pytest.raises(ValueError, match="does not fit"):
        SM.hotswap(c, GID, "recovery-hot", {BODY: {"bytes": b"B" * 33}})
    with pytest.raises(ValueError, match="not a file"):
        SM.hotswap(c, GID, "recovery-hot", {"arc/NX/other.arc": {"bytes": b"B"}})
    with pytest.raises(ValueError, match="no build"):
        SM.hotswap(c, GID, "recovery-missing", {BODY: {"bytes": b"B"}})


def test_hotswap_accepts_a_shorter_payload_and_pads_it(tmp_path):
    c, folder = build(tmp_path)
    SM.hotswap(c, GID, "recovery-hot", {BODY: {"b64": "QUJD"}})     # "ABC"
    data = (folder / "romfs" / BODY).read_bytes()
    assert data[:3] == b"ABC" and data[3:] == b"\x00" * 29 and len(data) == 32
