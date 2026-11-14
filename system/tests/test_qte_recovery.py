"""The post-QTE recovery: flash cover while held, then the operator's mine ring on release."""
from gbox.mercs.qte_escape import Recovery


def player(held):
    return {'ptr': 0x1000, 'generation': 3, 'hp': 900, 'state': 8 if held else 0, 'pos': [0., 0., 0.]}


def test_a_released_qte_requests_the_mine_ring_even_without_flash_cover():
    # The operator: "after surviving the QTE event ... drop landmines or mines or remote bombs around the area and
    # they flee from that area, detonating them". The cover flash may be unavailable (no flash resource, a bomb
    # already out); the recovery ring is requested anyway on release.
    clock = [100.0]
    fired = []

    def fire(expected, allowed):
        fired.append(expected)
        return {'state': 'unavailable', 'reason': 'no flash resource'}

    rec = Recovery(object(), submit=lambda fn: fn(), fire=fire, clock=lambda: clock[0])
    stats = {'round_evidence_id': 'round-1'}
    rec.observe({'player': player(True), 'enemies': []}, stats, 100.0, grants=1)
    assert stats['qte_escape_active'] is False
    rec.observe({'player': player(False), 'enemies': []}, stats, 100.2, grants=0)
    rec.observe({'player': player(False), 'enemies': []}, stats, 100.4, grants=0)
    assert stats['qte_escapes_observed'] == 1
    assert stats['qte_escape_mines_due'] == stats['qte_escape_episode']
    assert fired == [(0x1000, 3)]


def test_a_held_state_without_a_grant_never_lays_mines():
    rec = Recovery(object(), submit=lambda fn: fn(),
                   fire=lambda expected, allowed: {'state': 'confirmed', 'verified': True},
                   clock=lambda: 100.0)
    stats = {'round_evidence_id': 'round-1'}
    rec.observe({'player': player(True), 'enemies': []}, stats, 100.0, grants=0)
    rec.observe({'player': player(False), 'enemies': []}, stats, 100.2, grants=0)
    rec.observe({'player': player(False), 'enemies': []}, stats, 100.4, grants=0)
    assert stats.get('qte_escape_mines_due') is None
    assert not stats.get('qte_escapes_observed')
