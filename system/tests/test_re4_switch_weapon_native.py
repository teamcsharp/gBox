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


def test_zero_object_item_can_refresh_from_coherent_owned_native_selection():
    ad = Ad(); _armoury(ad, held=0x21); ctl = ad.native
    obj = E.active(ctl)['object']
    ad.write_memory(obj + R.OBJ_ITEM, b'\0\0')
    ad.write_memory(obj + 0x3F8, struct.pack('<Q', ctl.player))
    result = ctl.equip_primary(0x2A)
    assert result['verified'] and result['weapon_object_item'] == 0x2A


@pytest.mark.parametrize('fault', ['owner', 'class', 'selection', 'same_class'])
def test_zero_object_item_never_licenses_an_unidentified_weapon_write(fault):
    ad = Ad(); _armoury(ad, held=0x21); ctl = ad.native
    obj = E.active(ctl)['object']
    ad.write_memory(obj + R.OBJ_ITEM, b'\0\0')
    ad.write_memory(obj + 0x3F8, struct.pack('<Q', ctl.player if fault != 'owner' else 0))
    if fault == 'class':
        ad.write_memory(BASE + W.GAME_OBJ + W.G_CLASS, b'\xff\0')
    if fault == 'selection':
        ad.write_memory(BASE + W.ITEM_MGR + W.M_EQUIPPED_ID, struct.pack('<H', 0x27))
    ad.writes.clear()
    with pytest.raises(Unavailable, match='coherent recovery'):
        ctl.equip_primary(0x21 if fault == 'same_class' else 0x2A)
    assert not ad.writes and not ctl.calls


def asset_guest(character=5):
    ad = Ad(); _armoury(ad); ctl = ad.native
    ad.write_memory(BASE + W.GAME_OBJ + W.G_CHARACTER, bytes([character]))
    for got, table in E.ASSET_TABLES.values():
        ad.put(BASE + got, struct.pack('<Q', BASE + table))
        ad.put(BASE + table, bytes(8 * W.N_CLASSES))
    # Verified campaign shotgun resource IDs from this executable's data table.
    row = bytes.fromhex('4500460000000000')
    ad.write_memory(BASE + E.ASSET_TABLES[0][1] + 7 * 8, row)
    ad.writes.clear()
    return ad, ctl, row


def test_wesker_shotgun_loads_resources_before_native_refresh_and_verifies_object():
    ad, ctl, resource = asset_guest()
    refresh = ctl.call
    def call(off, *args, **kw):
        if off == E.REFRESH:
            # The actual native loader returns early when this entry is empty.
            assert ctl.rd(BASE + E.ASSET_TABLES[5][1] + 7 * 8, 8) == resource
        return refresh(off, *args, **kw)
    ctl.call = call
    result = ctl.equip_primary(0x2C)
    assert result['verified'] and result['assets']['source'] == 'native_campaign_fallback'
    assert E.active(ctl)['item'] == 0x2C


@pytest.mark.parametrize('fault', ['pointer', 'partial_row', 'missing_campaign'])
def test_unidentified_asset_data_never_publishes_a_native_equip(fault):
    ad, ctl, resource = asset_guest()
    got, table = E.ASSET_TABLES[5]
    if fault == 'pointer':
        ad.write_memory(BASE + got, struct.pack('<Q', BASE + table + 8))
    elif fault == 'partial_row':
        ad.write_memory(BASE + table + 7 * 8 + 2, b'\x01\0')
    else:
        ad.write_memory(BASE + E.ASSET_TABLES[0][1] + 7 * 8, bytes(8))
    ad.writes.clear()
    with pytest.raises(Unavailable, match='resource'):
        ctl.equip_primary(0x2C)
    assert not ad.writes and not ctl.calls


def test_existing_character_resources_are_preserved():
    ad, ctl, _ = asset_guest()
    at = BASE + E.ASSET_TABLES[5][1] + 7 * 8
    original = bytes.fromhex('fc00fd0000000000')
    ad.write_memory(at, original); ad.writes.clear()
    result = E.prepare_assets(ctl, {'class': 7, 'variant': 0})
    assert result['source'] == 'native_character' and not ad.writes


@pytest.mark.parametrize('character,cls,variant,want', [(5,10,0,5), (5,19,0,4),
    (4,19,0,23), (2,19,0,19), (0,10,2,32), (0,9,1,21), (5,7,0,7)])
def test_character_asset_remapping_matches_native_loader(character, cls, variant, want):
    assert E.asset_index(character, cls, variant) == want


def uncertain_equip():
    ad = Ad(); _armoury(ad); ctl = ad.native
    real = ctl.call
    ctl.call = lambda off, *args, **kw: real(off, *args, **kw) if off == E.SELECT else None
    with pytest.raises(Uncertain):
        ctl.equip_primary(0x2A)
    ctl.call = real
    return ad, ctl


def test_original_failure_is_retained_on_later_attempts():
    ad, ctl = uncertain_equip()
    receipt = dict(ctl.weapon_uncertain)
    with pytest.raises(Uncertain, match='first failure at refresh_returned'):
        ctl.equip_primary(0x2C)
    assert ctl.weapon_uncertain == receipt


@pytest.mark.parametrize('quiet', [False, True])
def test_late_native_object_requires_quiescent_dispatch_before_reconciliation(quiet):
    ad, ctl = uncertain_equip()
    ctl.equipment_quiescent = lambda: quiet
    obj = E.active(ctl)['object']
    ad.write_memory(obj + R.OBJ_ITEM, struct.pack('<H', 0x2A))
    ad.write_memory(BASE + W.GAME_OBJ + W.G_CLASS, bytes((W.CLASS_OF[0x2A], 0)))
    before = len(ctl.calls)
    if quiet:
        result = ctl.equip_primary(0x2C)
        assert result['verified']
        assert ctl.weapon_resolution['resolved'] == 'late_object'
    else:
        with pytest.raises(Uncertain):
            ctl.equip_primary(0x2C)
        assert len(ctl.calls) == before


@pytest.mark.parametrize('new_life,quiet', [(False,True),(True,False),(True,True)])
def test_valid_new_life_can_retire_old_failed_equipment_without_replay(new_life, quiet):
    ad, ctl = uncertain_equip()
    # The engine has reset the new round to its native handgun.
    ad.write_memory(ITEM, struct.pack('<H', 0x27))
    ad.write_memory(BASE + W.ITEM_MGR + W.M_EQUIPPED_ID, struct.pack('<H', 0x27))
    ad.write_memory(BASE + W.GAME_OBJ + W.G_CLASS, bytes((W.CLASS_OF[0x27], 0)))
    ctl.ready = lambda: (ctl.player, 8 if new_life else 7)
    ctl.equipment_quiescent = lambda: quiet
    before = len(ctl.calls)
    if new_life and quiet:
        assert ctl.equip_primary(0x2C)['verified']
        assert ctl.weapon_resolution['resolved'] == 'new_native_life'
        assert [c[0] for c in ctl.calls[before:]] == [E.SELECT, E.REFRESH]
    else:
        with pytest.raises(Uncertain):
            ctl.equip_primary(0x2C)
        assert len(ctl.calls) == before


def test_zero_current_object_is_unknown_for_controls_status():
    ad = Ad(); _armoury(ad); ctl = ad.native
    obj = E.active(ctl)['object']
    ad.write_memory(obj + R.OBJ_ITEM, bytes(2))
    assert E.current_weapon(ctl) is None


def native_round(ctl, phases=('results', 'intro', 'playing'), start=10.):
    for i, phase in enumerate(phases):
        E.observe_round(ctl, dict(mercenaries=True, phase=phase, kills=0, score=0,
            in_control=phase == 'playing', clock_running=phase == 'playing', clock=120., stage=2, mode=1), start+i)


def restore_native_handgun(ad, ctl):
    ad.write_memory(ITEM, struct.pack('<H', 0x27))
    ad.write_memory(BASE + W.ITEM_MGR + W.M_EQUIPPED_ID, struct.pack('<H', 0x27))
    ad.write_memory(BASE + W.GAME_OBJ + W.G_CLASS, bytes((W.CLASS_OF[0x27], 0)))
    ctl.equipment_quiescent = lambda: True


def test_reused_player_slot_can_recover_only_after_complete_native_round_boundary():
    ad, ctl = uncertain_equip()
    original = dict(ctl.weapon_uncertain)
    restore_native_handgun(ad, ctl)
    native_round(ctl)
    before = len(ctl.calls)
    assert ctl.equip_primary(0x2C)['verified']
    assert ctl.weapon_resolution['resolved'] == 'new_native_round'
    assert ctl.weapon_resolution['error'] == original['error']
    assert ctl.weapon_resolution['item'] == 0x2A  # history is not rewritten as the new shotgun
    assert ctl.weapon_resolution['boundary']['selection'] == (2, 1)
    assert [c[0] for c in ctl.calls[before:]] == [E.SELECT, E.REFRESH]


@pytest.mark.parametrize('phases', [('playing',), ('results','playing'), ('intro','playing'),
    ('playing','intro','playing'), ('results','playing','intro','playing'), ('case','intro','playing')])
def test_incomplete_or_out_of_order_boundary_cannot_unlock_equipment(phases):
    ad, ctl = uncertain_equip(); restore_native_handgun(ad, ctl)
    native_round(ctl, phases)
    before = len(ctl.calls)
    with pytest.raises(Uncertain):
        ctl.equip_primary(0x2C)
    assert len(ctl.calls) == before


@pytest.mark.parametrize('fault', ['busy', 'incoherent', 'pending', 'legacy'])
def test_round_boundary_does_not_bypass_native_completion_or_actual_identity(fault):
    ad, ctl = uncertain_equip(); restore_native_handgun(ad, ctl)
    native_round(ctl)
    if fault == 'busy': ctl.equipment_quiescent = lambda: False
    if fault == 'incoherent': ad.write_memory(E.active(ctl)['object'] + R.OBJ_ITEM, bytes(2))
    if fault == 'pending': ctl.weapon_uncertain['stage'] = 'refresh_pending'
    if fault == 'legacy': ctl.weapon_uncertain.pop('native_round')
    before = len(ctl.calls)
    with pytest.raises(Uncertain): ctl.equip_primary(0x2C)
    assert len(ctl.calls) == before


def test_boundary_credit_cannot_resolve_a_new_failure_in_the_same_round():
    ad, ctl = uncertain_equip(); restore_native_handgun(ad, ctl); native_round(ctl)
    real = ctl.call
    ctl.call = lambda off, *args, **kw: real(off, *args, **kw) if off == E.SELECT else None
    with pytest.raises(Uncertain): ctl.equip_primary(0x2C)
    restore_native_handgun(ad, ctl)
    before = len(ctl.calls)
    with pytest.raises(Uncertain): ctl.equip_primary(0x2A)
    assert ctl.weapon_uncertain['native_round'] == 1 and len(ctl.calls) == before


@pytest.mark.parametrize('fault', ['old_intro','reordered','nonzero','selection','not_mercs'])
def test_invalid_native_observations_cannot_create_a_boundary(fault):
    from types import SimpleNamespace
    ctl = SimpleNamespace()
    game = dict(mercenaries=True, phase='results', kills=0, score=0, stage=2, mode=1,
                clock=120., clock_running=True, in_control=True)
    E.observe_round(ctl, game, 1.)
    E.observe_round(ctl, dict(game, phase='intro', kills=1 if fault == 'nonzero' else 0,
                            mercenaries=fault != 'not_mercs'), .5 if fault == 'reordered' else 2.)
    E.observe_round(ctl, dict(game, phase='playing', stage=0 if fault == 'selection' else 2),
                    40. if fault == 'old_intro' else 3.)
    assert ctl.weapon_round_witness['generation'] == 0


def test_late_refresh_cannot_attribute_its_failure_to_the_following_round():
    ad = Ad(); _armoury(ad); ctl = ad.native
    real = ctl.call
    def call(off, *args, **kw):
        result = real(off, *args, **kw)
        if off == E.REFRESH: native_round(ctl)
        return result
    ctl.call = call
    with pytest.raises(Unavailable, match='changed'):
        ctl.equip_primary(0x2A)
    assert ctl.weapon_uncertain['native_round'] == 0
    assert ctl.weapon_round_witness['generation'] == 1
