"""Native ring receipts must not bypass the title's final movement decision."""
import pytest

from gbox.mercs import engine, grenade_ring, lessons

TITLES = ('010099A00BC1E000', '010018100CD46000', '01002A000CD48000')


def play(tmp_path, monkeypatch, title, *, receipt=None, stale=False, blocked=False):
    monkeypatch.setattr(lessons, 'ROOT', tmp_path / 'mercs' / 'lessons')
    index, sent, decisions, rings = [-1], [], [], []
    stats = {'ring_blast_until': 1000.} if stale else {}
    movements = [set(), {'lright'}, {'lleft', 'lup'}] if blocked else [{'lup', 'b'}, {'lright'}, {'lleft', 'lup'}]

    class Brain:
        def tick(self, snap):
            decisions.append(index[0])
            return {'hold': movements[index[0]]}
        def prompt_ok(self, *args): return True
        def save(self): pass
        def plan(self): return {}

    class Driver:
        frame = None
        def snapshot(self, memory):
            return {'player': {'ptr': 10, 'generation': 1, 'hp': 1000, 'pos': (0., 0., 0.)}}
        def screen(self, memory, snap): return 'playing'
        def progress(self, snap): return {'timer': 100., 'kills': 0, 'score': 0}
        def prompt_source(self, *args): return lambda: None
        def prompt_keys(self, key): return []

    def ring(snap, stats, now, hold):
        rings.append(index[0])
        if index[0] != 0 or receipt is None:
            return {'fired': False}
        # A synchronous native caller can release keys, but its return must not
        # prevent the already guarded title decision from being sent this tick.
        hold(set())
        return {'fired': receipt.get('state') == 'confirmed', 'receipt': receipt}

    monkeypatch.setattr(grenade_ring, 'control', lambda *a, **kw: ring)

    def stopped():
        index[0] += 1
        return index[0] >= len(movements)

    def send(rows):
        sent.append((index[0], rows))
        return {'sent': len(rows)}

    result = engine.play_round({'map_id': title}, object(), send, stopped, stats,
        brain=Brain(), driver=Driver(), clock=lambda: index[0] * .1,
        sleep=lambda delay: None, learn_dir=tmp_path)
    applied, held = {}, set()
    for tick, rows in sent:
        for row in rows:
            held.add(row['key']) if row['down'] else held.discard(row['key'])
        applied[tick] = set(held)
    assert result == 'stopped' and decisions == rings == [0, 1, 2]
    for tick, expected in enumerate(movements):
        assert applied.get(tick, set()) == expected
    assert all(not (row['key'] == 'ldown' and row['down']) for _, rows in sent for row in rows)
    assert not stats.get('ring_blast_backsteps')
    return stats


@pytest.mark.parametrize('title', TITLES)
@pytest.mark.parametrize('stale', [False, True])
def test_nonflash_completion_submits_guarded_action_same_tick_without_backstep(tmp_path, monkeypatch, title, stale):
    stats = play(tmp_path, monkeypatch, title, receipt={'state': 'confirmed', 'kind': 'nitrogen'}, stale=stale)
    assert stats['ring_driver_actions_retained'] == 1
    assert stats['ring_movement_policy'] == 'title driver action retained; no engine escape asserted'


@pytest.mark.parametrize('title', TITLES)
def test_legacy_blast_timer_cannot_rewrite_inputs_when_no_new_ring_fires(tmp_path, monkeypatch, title):
    stats = play(tmp_path, monkeypatch, title, stale=True)
    assert not stats.get('ring_driver_actions_retained')


@pytest.mark.parametrize('receipt', [{'state': 'confirmed', 'kind': 'flash'},
                                    {'state': 'uncertain', 'kind': 'hand'}])
def test_flash_and_uncertain_receipts_keep_driver_control_without_fake_completion(tmp_path, monkeypatch, receipt):
    stats = play(tmp_path, monkeypatch, TITLES[1], receipt=receipt, stale=True)
    assert not stats.get('ring_driver_actions_retained')


def test_no_verified_escape_remains_neutral_after_native_damaging_ring(tmp_path, monkeypatch):
    play(tmp_path, monkeypatch, TITLES[1], receipt={'state': 'confirmed', 'kind': 'hand'}, stale=True, blocked=True)
