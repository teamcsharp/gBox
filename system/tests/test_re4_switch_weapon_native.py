import struct
import pytest
from test_re4_switch_mods import Ad, _armoury, BASE, ITEM
from gbox.mercs.titles import re4_switch as R, re4_weapons as W
from gbox.mercs.titles import re4_switch_weapon_native as E
from gbox.mercs.titles.re4_switch_native import Unavailable, Uncertain


@pytest.mark.parametrize('item', [0x2C, 0x2A, 0x37, 0x35, 0x41, 0x2F])
def test_refresh_constructs_selected_weapon_after_stale_data_only_swap(item):
    ad = Ad(); _armoury(ad, held=0x27)
    ctl = ad.native
    # Reproduce the live failure: inventory/class claim the new weapon, while
    # the actual object is still a pistol.
    ad.write_memory(ITEM, struct.pack('<H', item))
    ad.write_memory(BASE + W.GAME_OBJ + W.G_CLASS, bytes((W.CLASS_OF[item], 0)))
    result = ctl.equip_primary(item)
    assert result['verified'] and E.active(ctl)['item'] == item
    assert [c[0] for c in ctl.calls] == [E.SELECT, E.REFRESH]


def test_wrong_signature_cancels_without_inventory_mutation():
    ad = Ad(); _armoury(ad); ctl = ad.native
    ad.write_memory(BASE + E.REFRESH, b'X')
    ad.writes.clear()
    with pytest.raises(Unavailable, match='signature'):
        ctl.equip_primary(0x2A)
    assert not ad.writes and not ctl.calls


def test_unconfirmed_actual_object_cannot_report_success_or_replay():
    ad = Ad(); _armoury(ad); ctl = ad.native
    real = ctl.call
    ctl.call = lambda off, *args, **kw: real(off, *args, **kw) if off == E.SELECT else None
    with pytest.raises(Uncertain, match='object'):
        ctl.equip_primary(0x2A)
    before = len(ad.writes)
    with pytest.raises(Uncertain, match='unresolved'):
        ctl.equip_primary(0x2C)
    assert len(ad.writes) == before


def test_operator_cancelled_request_writes_nothing():
    ad = Ad(); _armoury(ad); ctl = ad.native
    with pytest.raises(Unavailable, match='cancelled'):
        ctl.equip_primary(0x2A, allowed=lambda: False)
    assert not ad.writes and not ctl.calls
