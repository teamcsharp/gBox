"""Native availability must agree with the writer's acceptance, not its reader roster."""
import pytest

from gbox import aki_wrestling as AKI, char_coverage as CC, cast_swap


@pytest.mark.parametrize('gid', ['061264c636cc284d', '2e8850a2a6c53375'])
def test_readable_unsupported_release_has_no_native_writer(gid):
    game = {'game_id': gid, 'title': AKI.GAME_IDS[gid], 'platform': 'n64'}
    # This path returns before accessing a context, donor or ROM: the actual
    # implementation cannot build for this release.
    refused = AKI.use(None, {}, game, None)
    assert refused['status'] == 'missing'
    assert CC.writer_for(game) is None
    assert CC.cast_slots(game) == []
    result = cast_swap.plan(game, [], '', 'by_role', '', 'player')
    assert 'no routed character writer' in result['message']


@pytest.mark.parametrize('gid', ['23a346e48b6368a6', *AKI.WORLD_TOUR, 'bca7ec4ecf71d164'])
def test_supported_native_releases_remain_available(gid):
    game = {'game_id': gid, 'title': AKI.GAME_IDS[gid], 'platform': 'n64'}
    writer = CC.writer_for(game)
    assert writer['writer'] == 'gbox.aki_wrestling'
    assert writer['routed'] is True
    assert writer['slots']


def test_available_ids_match_the_delegated_writer():
    from gbox import aki_wcw
    assert set(AKI.WRITER_GAME_IDS) == {'23a346e48b6368a6', *aki_wcw.GAME_IDS}
