from gbox import jgr_swap as J


def test_player_archive_coverage_cannot_claim_the_entire_world_is_replaced():
    scope=J.replacement_scope()
    assert scope['complete_world_replacement'] is False
    assert any('police' in row for row in scope['missing'])
    assert any('gang' in row for row in scope['missing'])
    assert any('Professor K' in row for row in scope['missing'])
    assert any('character-select' in row for row in scope['missing'])
    assert any('cinematic' in row for row in scope['missing'])
