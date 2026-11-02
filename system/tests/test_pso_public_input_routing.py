"""Public input keeps controller identity through the actual Dolphin emitters."""
from types import SimpleNamespace

import pytest

from gbox import adapters, tools
from gbox.desktop_input_lease import MARKER, attach


@pytest.fixture
def routed(monkeypatch):
    calls = []
    monkeypatch.setattr(adapters, 'win_send_keys', lambda pid, rows, **kwargs:
                        calls.append((rows, kwargs)) or {'sent': len(rows)})
    ad = adapters.DolphinWinAdapter.__new__(adapters.DolphinWinAdapter)
    ad.proc, ad.coop_players = SimpleNamespace(pid=123), 2
    lease = attach(ad, 'input-routing-test')
    return tools._SessionPadSender(ad), ad, lease, calls


def test_mixed_players_keep_chronological_order_and_independent_buttons(routed):
    sender, _, lease, calls = routed
    sender.send([{'key': 'a', 'player': 1}, {'key': 'a', 'player': 2},
                 {'key': 'a', 'player': 1, 'down': False},
                 {'key': 'a', 'player': 2, 'down': False}], polite=True)
    assert [[row['key'] for row in rows] for rows, _ in calls] == [['a'], ['D'], ['a'], ['D']]
    assert all(kwargs == {'polite': True} for _, kwargs in calls)
    assert not sender.held and not lease.local


def test_p2_down_up_batch_is_one_scoped_delivery(routed):
    sender, _, _, calls = routed
    sender.send([{'key': 'up', 'player': 2}, {'key': 'up', 'player': 2, 'down': False}])
    assert len(calls) == 1
    assert calls[0][0] == [{'key': 'NUMPAD8', 'down': True}, {'key': 'NUMPAD8', 'down': False}]


@pytest.mark.parametrize('bad', [3, True, '2'])
def test_all_ports_are_validated_before_any_press(routed, bad):
    sender, _, _, calls = routed
    with pytest.raises(ValueError, match='controller port'):
        sender.send([{'key': 'a'}, {'key': 'a', 'player': bad}])
    assert calls == []


def test_unconnected_second_pad_never_falls_through_to_p1(routed):
    sender, ad, _, calls = routed
    ad.coop_players = 1
    with pytest.raises(ValueError, match='unavailable'):
        sender.send([{'key': 'a', 'player': 2}])
    assert calls == []


def test_failed_dispatch_releases_prior_and_uncertain_holds_on_both_ports(routed, monkeypatch):
    sender, _, lease, calls = routed
    sender.send([{'key': 'up', 'player': 1}])
    def partial(pid, rows, **kwargs):
        calls.append((rows, kwargs))
        return {'sent': 0} if any(row['down'] for row in rows) else {'sent': len(rows)}
    monkeypatch.setattr(adapters, 'win_send_keys', partial)
    with pytest.raises(RuntimeError, match='not fully delivered'):
        sender.send([{'key': 'up', 'player': 2}])
    assert calls[-2][0] == [{'key': 'up', 'down': False}]
    assert calls[-1][0] == [{'key': 'NUMPAD8', 'down': False}]
    assert not sender.held and not lease.local


def test_clear_preserves_another_lease_owners_p2_hold(routed):
    sender, ad, lease, calls = routed
    ad.send_input_player([{'key': 'a', 'down': True}], player=2)
    sender.send([{'key': 'a', 'player': 2, MARKER: 'input-routing-test'}])
    sender.clear()
    assert calls[-1][0] == [{'key': 'D', 'down': True}]
    assert not lease.remote and lease.local


def test_takeover_release_keeps_p2_port_and_leaves_unrelated_p1_hold(routed):
    sender, _, lease, calls = routed
    sender.send([{'key': 'a', 'player': 1, 'src': 'player'},
                 {'key': 'a', 'player': 2, 'src': 'autoplay'}])
    sender.relay_release([{'key': 'a', 'down': False}])
    assert calls[-1][0] == [{'key': 'D', 'down': False}]
    assert any(player == 1 for player, _ in lease.local)
    assert not any(player == 2 for player, _ in lease.local)


def test_other_adapters_keep_original_dispatch_and_polite_behavior(monkeypatch):
    direct, polite = [], []
    ad = SimpleNamespace(name='other', send_input=lambda rows: direct.append(rows))
    sender = tools._SessionPadSender(ad)
    events = [{'key': 'a', 'player': 4}]
    monkeypatch.setattr(tools, '_polite_send', lambda adapter, rows: polite.append((adapter, rows)))
    sender.send(events)
    sender.send(events, polite=True)
    sender.clear()
    assert direct == [events] and polite == [(ad, events)]


@pytest.mark.parametrize('receipt', [None, False, {}, {'error': 'failed'}, {'ok': False},
                                    {'blocked': True}, {'sent': True}, {'sent': 1, 'stopped': True}])
def test_unconfirmed_receipt_clears_uncertain_holds(routed, monkeypatch, receipt):
    sender, _, _, calls = routed
    def unconfirmed(pid, rows, **kwargs):
        calls.append((rows, kwargs))
        return receipt if any(row['down'] for row in rows) else {'sent': len(rows)}
    monkeypatch.setattr(adapters, 'win_send_keys', unconfirmed)
    with pytest.raises(RuntimeError, match='not fully delivered'):
        sender.send([{'key': 'a', 'player': 2}])
    assert calls[-1][0] == [{'key': 'D', 'down': False}]
    assert not sender.held


def test_linux_scoped_demo_uses_supported_signature():
    ad = adapters.DolphinAdapter.__new__(adapters.DolphinAdapter)
    ad.coop_players = 2
    sent = []
    ad._xdo = lambda *args: sent.append(args)
    attach(ad, 'linux-routing-test')
    sender = tools._SessionPadSender(ad)
    sender.send([{'key': 'a', 'player': 2}, {'key': 'a', 'player': 2, 'down': False}], polite=True)
    assert sent == [('keydown', 'F6', 'sleep', '0.06', 'keyup', 'F6')]


def test_legitimate_axis_ownership_expansion_acknowledges_logical_request(routed):
    sender, _, lease, calls = routed
    sender.send([{'key': 'lup', 'player': 2, MARKER: 'input-routing-test'}])
    result = sender.send([{'key': 'ldown', 'player': 2}])
    assert calls[-1][0] == [{'key': 'NUMPAD8', 'down': False}, {'key': 'NUMPAD2', 'down': True}]
    assert result == [{'sent': 2, 'logical_sent': 1}]
    assert lease.remote and lease.local
    sender.send([{'key': 'ldown', 'player': 2, 'down': False}])
    assert calls[-1][0] == [{'key': 'NUMPAD2', 'down': False}, {'key': 'NUMPAD8', 'down': True}]
    sender.clear()
    assert not lease.local and not lease.remote


def test_partial_axis_expansion_is_not_mistaken_for_full_logical_delivery(routed, monkeypatch):
    sender, _, lease, calls = routed
    sender.send([{'key': 'lup', 'player': 2, MARKER: 'input-routing-test'}])
    def partial(pid, rows, **kwargs):
        calls.append((rows, kwargs))
        return {'sent': 1} if any(row['down'] for row in rows) else {'sent': len(rows)}
    monkeypatch.setattr(adapters, 'win_send_keys', partial)
    with pytest.raises(RuntimeError, match='not fully delivered'):
        sender.send([{'key': 'ldown', 'player': 2}])
    assert not sender.held and not lease.local and not lease.remote
