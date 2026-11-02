"""Old valid metadata must not authorize overwriting a warmed V3 address."""
from pathlib import Path
import struct
import pytest
from gbox import pso_gc_live as G
from gbox.registry import Unsupported
from test_pso_gc_live import RAM

FIX=Path(__file__).resolve().parent

@pytest.mark.parametrize('legacy',[1,2])
def test_unhooked_v3_with_retained_legacy_metadata_refuses_before_writes(legacy):
    ram=RAM()
    ram.put(G.OLD_CAVE,(FIX/f'dispatcher-v{legacy}.bin').read_bytes())
    ram.put(G.OLD_HEADER,f'GBPSOGC{legacy}'.encode()+struct.pack('>II',G.ORIGINAL_UPDATE,G.VT_UPDATE))
    ram.word(G.OLD_NEXT,G.ID_BASE+1)
    ram.word(G.OLD_SURVIVAL,1 if legacy==2 else 0)
    ram.put(G.CAVE,(FIX/'dispatcher-v3.bin').read_bytes())
    ram.put(G.HEADER,b'GBPSOGC3'+struct.pack('>II',G.ORIGINAL_UPDATE,G.VT_UPDATE))
    ram.word(G.VT_UPDATE,G.ORIGINAL_UPDATE)
    with pytest.raises(Unsupported):G.GC(ram).hook()
    assert not ram.writes
