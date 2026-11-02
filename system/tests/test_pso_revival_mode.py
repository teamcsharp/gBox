"""Regress the observed HP-positive-but-no-movement revival failure."""
from pathlib import Path
import struct

import pytest
from gbox import pso_gc_extras as E, pso_gc_live as G
from gbox.registry import Unsupported
from test_pso_gc_extras import memory


def test_manual_native_revival_retains_control_mode_and_native_hp_result():
    ram = memory()
    ram.put(ram.player + 0x324, struct.pack('>H', 1))
    ram.put(ram.player + 0x32c, bytes(2))
    native = E.Extras(ram)
    calls_seen = []

    def call(calls):
        calls_seen.extend(calls)
        assert calls == [(E.REVIVE, ram.player)]
        # The stock revive routine may restore half HP. Control-mode mutation
        # must never be used to force a full-HP branch.
        assert native.u16(ram.player + 0x324) == 1
        ram.put(ram.player + 0x32c, struct.pack('>H', 16))
        return [0]

    native.call = call
    result = native.revive()
    assert result['verified'] and result['hp'] == 16
    assert native.u16(ram.player + 0x324) == 1
    assert calls_seen == [(E.REVIVE, ram.player)]
    assert not ram.writes


def test_already_alive_does_not_repair_unknown_actor_state_or_call_revive():
    ram = memory()
    ram.put(ram.player + 0x324, struct.pack('>H', 3))
    ram.put(ram.player + 0x32c, struct.pack('>H', 33))
    native = E.Extras(ram)
    native.call = lambda calls: pytest.fail('No unsolicited actor-state repair')
    assert native.revive()['verified']
    assert native.u16(ram.player + 0x324) == 3
    assert not ram.writes


@pytest.mark.parametrize('active', [False, True])
def test_old_v3_dispatcher_requires_fresh_emulator_and_is_never_overwritten(active):
    ram = memory()
    old = (Path(__file__).parent / 'dispatcher-v3.bin').read_bytes()
    ram.put(G.CAVE, old)
    ram.put(G.HEADER, b'GBPSOGC3' + struct.pack('>II', G.ORIGINAL_UPDATE, G.VT_UPDATE))
    ram.word(G.VT_UPDATE, G.CAVE if active else G.ORIGINAL_UPDATE)
    ram.word(G.NEXT_ID, G.ID_BASE + 7)
    ram.word(G.SURVIVAL, 1)
    before = ram.read_memory(G.QUEUE, G.END - G.QUEUE)
    with pytest.raises(Unsupported):
        E.Extras(ram).hook()
    assert ram.read_memory(G.QUEUE, G.END - G.QUEUE) == before
    assert not ram.writes


def test_new_cold_hook_identifies_fixed_dispatcher():
    ram = memory()
    E.Extras(ram).hook()
    assert ram.read_memory(G.HEADER, 8) == b'GBPSOGC4'
    assert ram.read_memory(G.CAVE, len(G.CODE)) == G.CODE


@pytest.mark.parametrize('version', [1, 2])
def test_unhooked_v3_cannot_be_mistaken_for_retained_older_migration(version):
    ram = memory()
    fixture = Path(__file__).parent
    ram.put(G.OLD_CAVE, (fixture / f'dispatcher-v{version}.bin').read_bytes())
    ram.put(G.OLD_HEADER, f'GBPSOGC{version}'.encode() + struct.pack('>II', G.ORIGINAL_UPDATE, G.VT_UPDATE))
    ram.word(G.OLD_NEXT, G.ID_BASE + 9)
    ram.word(G.OLD_SURVIVAL, int(version == 2))
    ram.put(G.CAVE, (fixture / 'dispatcher-v3.bin').read_bytes())
    ram.put(G.HEADER, b'GBPSOGC3' + struct.pack('>II', G.ORIGINAL_UPDATE, G.VT_UPDATE))
    ram.word(G.VT_UPDATE, G.ORIGINAL_UPDATE)
    with pytest.raises(Unsupported, match='fresh emulator session'):
        E.Extras(ram).hook()
    assert not ram.writes
