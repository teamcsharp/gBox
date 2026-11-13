import struct

import pytest

from gbox.mercs.titles import re5_switch_mods as SM, re5_switch as R
from tests.test_re5_switch_mods import Adapter, put_slot
from tests.test_re5_switch_parity import parity_guest, block_at, put_block, ids, GENERIC


@pytest.fixture(autouse=True)
def fresh_state():
    SM.ORIG.clear()
    yield
    SM.ORIG.clear()


def test_automine_toggle_is_independent_of_supply_and_does_not_touch_game_memory():
    ad = Adapter(parity_guest())
    g = SM.RE5Switch(ad)
    ad.writes.clear()
    assert g.state.get('automine', True) is True
    assert SM.automine(g, False)['verified']
    assert SM.mine_settings(ad)['automine'] is False
    g.state['mine_loadout'] = False
    assert SM.automine(g, True)['automine'] is True
    assert SM.mine_settings(ad) == {'enabled': False, 'interval_s': 30.0, 'only': False, 'automine': True}
    assert not ad.writes
    with pytest.raises(ValueError):
        SM.automine(g, 1)


def test_driver_prepares_every_costume_before_a_player_exists_and_rechecks_without_writes():
    guest=parity_guest(player=False);ad=Adapter(guest)
    original={i:guest.rd(block_at(i),SM.TEMPLATE_REC*SM.TEMPLATE_RECS) for i in SM.MERC_DESC}
    result=SM.maintain(ad,{},enabled=False,prepare_mines=True,clock=lambda:0)
    assert result['verified'] and result['mine_supply']['status']=='ready_next_round'
    assert result['mine_supply']['template_blocks']==54
    assert SM.mine_settings(ad)=={'enabled':True,'interval_s':30.0,'only':False}
    for i in SM.MERC_DESC:
        block=guest.rd(block_at(i),SM.TEMPLATE_REC*SM.TEMPLATE_RECS)
        assert SM._quick_mine(block)
        # Every original gun, healing item and knife remains, even grenade-free Safari.
        before=[struct.unpack_from('<I',original[i],k*SM.TEMPLATE_REC)[0] for k in range(12)]
        assert all(item in ids(guest,i) for item in before if item and item not in (0x106,0x107,0x108))
    assert SM.maintain(ad,{},enabled=False,prepare_mines=True,clock=lambda:3)['writes']==0


def test_direct_mines_on_initializes_all_templates_without_prior_weapon_loadout():
    guest=parity_guest();ad=Adapter(guest)
    result=SM.mines(SM.RE5Switch(ad),30,True)
    assert result['verified'] and result['mine_loadout']['template_blocks']==54
    assert all(SM._quick_mine(guest.rd(block_at(i),SM.TEMPLATE_REC*12)) for i in SM.MERC_DESC)


def test_existing_nonquick_native_mine_is_moved_and_off_restores_original_exactly():
    guest=parity_guest();ad=Adapter(guest)
    put_block(guest,block_at(16),{**GENERIC,2:(SM.MINE_ID,2,0)})
    before=guest.rd(block_at(16),SM.TEMPLATE_REC*12)
    SM.mines(SM.RE5Switch(ad),30,True)
    after=guest.rd(block_at(16),len(before))
    assert SM._quick_mine(after) and ids(guest,16)[3]==0x102
    assert struct.unpack_from('<I',after,3*SM.TEMPLATE_REC+SM.REC_GRID)[0]==3  # equipped gun stays quick
    SM.mines(SM.RE5Switch(ad),30,False)
    assert guest.rd(block_at(16),len(before))==before
    writes=len(ad.writes)
    assert SM.run(ad,'mine_loadout',on=True)['mine_loadout'] is False  # profile cannot override explicit off
    result=SM.maintain(ad,{},enabled=False,prepare_mines=True,clock=lambda:10)
    assert result['mine_supply']['status']=='disabled' and len(ad.writes)==writes
    assert SM.mine_settings(ad)['enabled'] is False


def test_no_usable_quick_grid_reports_incomplete_coverage_instead_of_claiming_ready():
    guest=parity_guest();ad=Adapter(guest)
    rows={k:(0x102,-1,1) for k in range(12)}
    put_block(guest,block_at(16),rows)
    before=guest.rd(block_at(16),SM.TEMPLATE_REC*12)
    result=SM.maintain(ad,{},enabled=False,prepare_mines=True,clock=lambda:0)
    assert not result['verified'] and result['mine_supply']['status']=='template_coverage_incomplete'
    assert result['mine_supply']['missing_blocks'] and guest.rd(block_at(16),len(before))==before


@pytest.mark.parametrize('count,obj,expected',[(1,0x123456,5),(4,0x123456,5),(5,0x123456,5),
                                            (0,0x123456,0),(1,0,1)])
def test_live_refill_only_touches_positive_native_stack_count_and_capacity(count,obj,expected):
    guest=parity_guest();ad=Adapter(guest)
    SM.mines(SM.RE5Switch(ad),30,True)
    addr=put_slot(guest,2,SM.MINE_ID,count,1,obj=obj)
    before=guest.rd(addr,R.INV_SLOT);ad.writes.clear()
    result=SM.maintain(ad,R.snapshot(guest),clock=lambda:0)
    after=guest.rd(addr,R.INV_SLOT)
    assert struct.unpack_from('<i',after,R.INV_ROUNDS)[0]==expected
    assert after[:R.INV_ROUNDS]==before[:R.INV_ROUNDS] and after[R.INV_CAP+4:]==before[R.INV_CAP+4:]
    assert all(at==addr+R.INV_ROUNDS and len(data)==8 for at,data in ad.writes)
    assert result['mine_supply']['status']==('ready' if count>0 and obj else 'missing_live_stack_next_round')


def test_stale_or_outside_player_inventory_record_is_never_revived():
    guest=parity_guest();ad=Adapter(guest)
    SM.mines(SM.RE5Switch(ad),30,True)
    addr=put_slot(guest,2,SM.MINE_ID,1,1);snap=R.snapshot(guest)
    guest.put(addr+R.INV_ID,struct.pack('<I',0x106));ad.writes.clear()
    assert SM.maintain(ad,snap)['mine_supply']['status']=='missing_live_stack_next_round'
    assert not ad.writes
    guest.put(addr+R.INV_ID,struct.pack('<I',SM.MINE_ID))
    snap['player']['ptr']+=R.INV_SLOT*R.INV_SLOTS
    SM.maintain(ad,snap)
    assert not ad.writes


def test_driver_can_report_missing_live_stack_while_preparing_next_native_round():
    guest=parity_guest();ad=Adapter(guest)
    result=SM.maintain(ad,R.snapshot(guest),prepare_mines=True,clock=lambda:0)
    assert result['verified'] and result['mine_supply']['status']=='missing_live_stack_next_round'
    assert not any(at>=R.snapshot(guest)['player']['ptr'] for at,data in ad.writes)


def test_explicit_loadout_off_survives_profile_defaults_and_explicit_tool_on_can_restore():
    guest=parity_guest();ad=Adapter(guest)
    SM.maintain(ad,{},enabled=False,prepare_mines=True,clock=lambda:0)
    assert SM.tool_run(ad,'mine_loadout',on=False)['verified']
    writes=len(ad.writes)
    assert SM.run(ad,'mine_loadout',on=True)['mine_loadout'] is False
    assert SM.maintain(ad,{},enabled=False,prepare_mines=True,clock=lambda:3)['mine_supply']['status']=='disabled'
    assert len(ad.writes)==writes
    assert SM.tool_run(ad,'mines',30,True)['verified']
    assert SM.mine_settings(ad)['enabled'] is True


def test_invalid_template_descriptor_preparation_never_falls_back_to_partial_writes():
    guest=parity_guest();ad=Adapter(guest)
    from tests.test_re5_switch import BASE
    guest.put(BASE+SM.DESC_TABLE+SM.DESC_STRIDE*67+16,struct.pack('<Q',11))
    result=SM.maintain(ad,{},enabled=False,prepare_mines=True,clock=lambda:0)
    assert not result['verified'] and result['mine_supply']['status']=='prepare_failed'
    assert not ad.writes and 'tpl_orig' not in SM.ORIG[id(ad)]


def test_empty_records_with_duplicate_default_grid_never_overlap_a_live_item():
    guest=parity_guest();ad=Adapter(guest)
    put_block(guest,block_at(16),{0:(0x201,50,0),3:(0x102,-1,1),9:(0x101,-1,0),11:(0x100,-1,0)})
    for k in (1,2,4,5,6,7,8):
        guest.put(block_at(16)+k*SM.TEMPLATE_REC+SM.REC_GRID,struct.pack('<I',0))
    before=guest.rd(block_at(16),SM.TEMPLATE_REC*12)
    result=SM.mines(SM.RE5Switch(ad),30,True)
    assert result['verified']
    after=guest.rd(block_at(16),len(before))
    assert SM._quick_mine(after)
    for k in (0,3,9,11):
        assert after[k*SM.TEMPLATE_REC:(k+1)*SM.TEMPLATE_REC]==before[k*SM.TEMPLATE_REC:(k+1)*SM.TEMPLATE_REC]


def test_mine_probe_is_one_read_only_sample_of_the_bomb_from_the_games_memory():
    guest=parity_guest();ad=Adapter(guest)
    SM.mines(SM.RE5Switch(ad),30,True)
    put_slot(guest,2,SM.MINE_ID,5,1,obj=0x123456)
    ad.writes.clear()
    res=SM.tool_run(ad,'mine_probe')
    assert res['op']=='mine_probe' and res['verified'] and 'status' not in res   # small: no status block rides along
    assert res['mine']=={'id':SM.MINE_ID,'rounds':5,'cap':5,'grid':1,'hand':False,'slot':2}
    assert res['mine_loadout'] and res['mine_settings']=={'enabled':True,'interval_s':30.0,'only':False}
    assert res['player']['pos'] and res['ground_mines']==[] and res['foes']['alive']>=0
    assert not ad.writes                                                        # a probe never writes


def test_mine_probe_without_a_player_says_so_instead_of_failing():
    guest=parity_guest(player=False);ad=Adapter(guest)
    res=SM.tool_run(ad,'mine_probe')
    assert res['verified'] and res['player'] is None and res['mine'] is None and res['ground_mines']==[]
