"""#1106: preserve actual-slot reporting without weakening completed-container evidence.

A command acknowledgement proves dispatch, not a completed native save or load.
Only fresh, complete native bytes identify the checkpoint to export.
"""
import struct

import pytest

from gbox import adapters
from gbox.config import Config, HOST_OS, EmulatorConfig


def make_adapter(tmp_path):
    config = Config(runtime_dirs={HOST_OS: str(tmp_path)})
    ad = adapters.RetroArchAdapter(EmulatorConfig(adapter="retroarch", executable="x", core="y"), config=config)
    ad.log_path = tmp_path / "native.log"
    ad.log_path.write_text("older native output\n")
    (tmp_path / "states").mkdir()
    return ad


def checkpoint():
    data = b"complete non-Flycast native core state"
    return (b"RASTATE\x01MEM " + struct.pack("<I", len(data)) + data
            + bytes((-len(data)) % 8) + b"END " + bytes(4))


@pytest.mark.parametrize("actual", [0, 89, -1])
def test_one_save_reports_actual_native_file_without_retrying_the_moment(tmp_path, actual):
    ad = make_adapter(tmp_path)
    ad._slot = lambda requested: requested
    suffix = str(actual) if actual else ""
    native = tmp_path / "states" / f"mygame.state{suffix}"
    (tmp_path / "states" / "othergame.state91").write_bytes(b"wrong game")
    commands = []

    def command(text):
        commands.append(text)
        native.write_bytes(checkpoint())
        with ad.log_path.open("a") as log:
            log.write(f'[State] Saving state "{native}"\n')

    ad.cmd = command
    result = ad.save_state(91)
    assert commands == ["SAVE_STATE"]  # no load probe or repeated saves of later moments
    assert result["slot"] == ad.slot == actual
    assert result["requested_slot"] == 91 and result["slot_verified"] is False
    assert result["verified"] is True and result["path"] == str(native)
    assert native.read_bytes() == checkpoint() and "warning" in result


def test_ack_without_native_write_cannot_verify_a_saved_checkpoint(tmp_path, monkeypatch):
    ad = make_adapter(tmp_path)
    ad._slot = lambda requested: requested
    commands = []
    ad.cmd = lambda text: commands.append(text) or "SAVE_STATE_SLOT 91"
    ticks = iter([0, 0, 13])
    monkeypatch.setattr(adapters.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(adapters.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="did not produce a verified save file"):
        ad.save_state(91)
    assert commands == ["SAVE_STATE"]


def test_load_dispatch_does_not_claim_native_restoration(tmp_path):
    ad = make_adapter(tmp_path)
    ad._slot = lambda requested: requested
    commands = []
    ad.cmd = lambda text: commands.append(text) or "LOAD_STATE_SLOT 91"
    result = ad.load_state(91)
    assert commands == ["LOAD_STATE"] and result["slot"] == 91
    assert result.get("verified") is not True and result.get("loaded") is not True
