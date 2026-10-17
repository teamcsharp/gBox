"""The stock SC2 FIFO desync workaround follows the disc header, not a filename.

Only argv preparation runs: no emulator, game input, global settings or real
memory cards are opened by these tests.
"""
from pathlib import Path
import struct
import zlib

import pytest

from gbox import adapters, cheats
from gbox.config import Config


def disc(path: Path, serial: bytes):
    header = serial + bytes(0x8000 - len(serial))
    if path.suffix == '.gcz':
        first = zlib.compress(header)
        path.write_bytes(struct.pack('<IIQQII', 0xB10BC001, 0, len(first), len(header) * 2,
                                     len(header), 2) + struct.pack('<QQII', 0, len(first), 0, 0) + first)
    else:
        path.write_bytes(header)
    return str(path)


def prepare(tmp_path, monkeypatch, cls):
    adapter = cls(Config(data_dir=tmp_path / 'data'), 'gamecube')
    if cls is adapters.DolphinWinAdapter:
        exe = tmp_path / 'Dolphin-x64/gBox Dolphin.exe'
        exe.parent.mkdir()
        exe.write_bytes(b'not executed')
        monkeypatch.setattr(adapter, '_exe', lambda: exe)
        monkeypatch.setattr(adapter, '_claim_lane', lambda: 'F13')
        user = exe.parent / 'User'
        monkeypatch.setattr(adapters, '_audio_selection', lambda *args: {'chosen': {'none': True}})
    else:
        user = adapter.config.runtime / 'dolphin-user'
    monkeypatch.setattr(cheats, 'gecko_codes', lambda *args: [])
    (user / 'Config').mkdir(parents=True)
    (user / 'GameSettings').mkdir()
    global_ini = user / 'Config/Dolphin.ini'
    other_ini = user / 'GameSettings/GBIE08.ini'
    global_ini.write_bytes(b'[Core]\r\nCPUThread = True\r\n[General]\r\nCustom = keep\r\n')
    other_ini.write_bytes(b'[Core]\nCPUThread = True\n[Video_Settings]\nCustom = keep\n')
    return adapter, global_ini, other_ini


@pytest.mark.parametrize('cls', [adapters.DolphinAdapter, adapters.DolphinWinAdapter])
@pytest.mark.parametrize('extension', ['.iso', '.gcz'])
def test_stock_and_renamed_mod_discs_use_single_core_before_spawn(tmp_path, monkeypatch, cls, extension):
    adapter, global_ini, other_ini = prepare(tmp_path, monkeypatch, cls)
    saved = {path: path.read_bytes() for path in (global_ini, other_ini)}
    # A rebuilt disc can have any name. Its six-byte native header is authoritative.
    rom = disc(tmp_path / ('renamed_sonic_build' + extension), b'GRSEAF')
    argv = adapter._argv(rom)
    cpu = [value for value in argv if value.startswith('Dolphin.Core.CPUThread=')]
    assert cpu == ['Dolphin.Core.CPUThread=False']
    assert argv[-2:] == ['-e', rom]
    assert all(path.read_bytes() == data for path, data in saved.items())


@pytest.mark.parametrize('cls', [adapters.DolphinAdapter, adapters.DolphinWinAdapter])
@pytest.mark.parametrize('serial', [b'GMSE01', b'GRSPAF'])
def test_other_disc_ids_keep_their_existing_launch_defaults(tmp_path, monkeypatch, cls, serial):
    adapter, global_ini, other_ini = prepare(tmp_path, monkeypatch, cls)
    saved = {path: path.read_bytes() for path in (global_ini, other_ini)}
    # Even an SC2 filename must not force a workaround for an unverified revision.
    argv = adapter._argv(disc(tmp_path / 'Soul Calibur II (USA).iso', serial))
    cpu = [value for value in argv if value.startswith('Dolphin.Core.CPUThread=')]
    assert cpu == (['Dolphin.Core.CPUThread=True'] if cls is adapters.DolphinWinAdapter else [])
    assert all(path.read_bytes() == data for path, data in saved.items())
