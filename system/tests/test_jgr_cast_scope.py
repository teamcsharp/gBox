from gbox import jgr_swap as J


def test_player_archive_coverage_cannot_claim_the_entire_world_is_replaced():
    scope=J.replacement_scope()
    assert scope['complete_world_replacement'] is False
    assert any('police' in row for row in scope['missing'])
    assert any('gang' in row for row in scope['missing'])
    assert any('Professor K' in row for row in scope['missing'])
    assert any('character-select' in row for row in scope['missing'])
    assert any('cinematic' in row for row in scope['missing'])


def test_scope_records_verified_enemy_afs_inventory_and_next_step():
    ev=J.replacement_scope()['evidence']['enemy_afs']
    assert ev['entries']==2*ev['model_pairs']==54
    assert 'round-trip' in J.replacement_scope()['next_step']
