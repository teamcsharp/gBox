"""RE6 PS3 backend registration: verified RPCS3 launch, still non-playable."""
from gbox import mercmode as M


def test_re6_ps3_backend_registered_nonplayable():
    re6 = M.TITLES['re6']
    # Playability must remain False until a witnessed Mercenaries round.
    assert re6['playable'] is False
    # The legacy game_ids tuple still points at the Xbox 360 placeholder.
    assert '0871eee3b68cdea3' in re6['game_ids']
    # The new PS3 backend carries the catalog id and verified revision evidence.
    ps3 = re6['backends']['ps3']
    assert ps3['adapter'] == 'rpcs3'
    assert ps3['game_id'] == '6fc93ff62e4eb868'
    assert ps3['title_id'] == 'BLUS30855'
    assert ps3['app_ver'] == '01.00'
    assert ps3['verified'] is True
    assert len(ps3['eboot_sha256']) == 64
    assert re6['backends']['xbox360']['verified'] is False
