"""Assisted rank provenance and an engine that can observe without taking control."""
import json
from types import SimpleNamespace

import pytest

from gbox.mercs import engine, lessons, tactical
from gbox.mercs.notebook import Notebook, reflect
from gbox.mercs.training import HumanObserver, RoundAssistance, participant


def evidence(classification='unmodified', verified=True, effects=()):
    return {'classification': classification, 'verified': verified, 'effects': list(effects)}


def test_assistance_cannot_be_removed_at_results():
    measured = RoundAssistance()
    measured.observe(evidence('mod_assisted', True, ['extra_time_per_kill']))
    measured.observe(evidence())
    assert measured.summary()['classification'] == 'mod_assisted'
    assert measured.summary()['effects'] == ['extra_time_per_kill']


def test_unknown_history_never_becomes_clean_by_unchecking_mods():
    measured = RoundAssistance()
    measured.observe(None)
    measured.observe(evidence())
    assert measured.summary()['classification'] == 'unknown'
    assert measured.summary()['verified'] is False


@pytest.mark.parametrize('malformed', [{}, {'verified': True}, evidence('invented', True)])
def test_unrecognized_rule_evidence_cannot_certify_original_rules(malformed):
    measured = RoundAssistance()
    measured.observe(malformed)
    measured.observe(evidence())
    assert measured.summary()['classification'] == 'unknown'


def test_known_assistance_is_visible_even_without_a_complete_stock_verifier():
    measured = RoundAssistance()
    measured.observe(evidence('mod_assisted', False, ['fire_rate']))
    assert measured.summary()['classification'] == 'mod_assisted'
    assert measured.summary()['verified'] is False


def test_old_s_rank_does_not_qualify_for_unmodified_mastery(tmp_path):
    book = Notebook(tmp_path, 'BLUS30491')
    old = book.finish('map', 'mercenaries', 'Chris', 'completed', {'result_rank': 'S', 'score': 60000})
    assert old['observed']['s_rank_verified'] is True
    assert old['observed']['unmodified_s_rank_verified'] is False
    assert old['observed']['assistance']['classification'] == 'unknown'
    assert book.guide()['stages']['mercenaries/map']['unknown_rules_rounds'] == 1


@pytest.mark.parametrize('context,qualifies', [
    (evidence('mod_assisted', True, ['infinite_ammunition']), False),
    (evidence('unmodified', False), False),
    (evidence('unknown', False), False),
    (evidence(), True),
])
def test_clean_qualification_requires_positive_rule_evidence(tmp_path, context, qualifies):
    book = Notebook(tmp_path, 'BLUS30491')
    run = book.finish('map', 'reunion', 'Chris', 'completed', {'result_rank': 'S', 'assistance': context})
    assert run['observed']['unmodified_s_rank_verified'] is qualifies
    assert reflect('completed', {'result_rank': 'S', 'assistance': context})['acceptance']['unmodified_s_rank'] is qualifies


def test_participant_identity_never_inferred_from_an_unverified_position():
    assert participant({'pos': [1, 2, 3]}, 1, 'human', source='test') is None
    assert participant({'ptr': 0x30001000, 'pos': [1, float('nan'), 3]}, 1, 'human', source='test') is None
    recorded = participant({'ptr': 0x30001000, 'pos': [1, 2, 3], 'hp': 500}, 1, 'human', source='native_slot')
    assert recorded['control'] == 'human' and recorded['actor'] == 0x30001000
    assert recorded['provenance']['inputs_observed'] is False


def test_tactical_frame_keeps_both_players_and_rules_separate():
    player = {'ptr': 0x30001000, 'pos': [1, 2, 3], 'hp': 500, 'hp_max': 1000}
    p1 = participant(player, 1, 'human', source='native_slot')
    p2 = participant(dict(player, ptr=0x30002000, pos=[100, 2, 300]), 2, 'bot', source='native_slot')
    frame = tactical.Tracker('BLUS30491').frame({'player': player, 'players': [p1, p2],
                                              'assistance': evidence('mod_assisted', False, ['fire_rate'])})
    assert [p['control'] for p in frame['players']] == ['human', 'bot']
    assert frame['players'][1]['pos'] == [100, 2, 300]
    assert frame['assistance']['classification'] == 'mod_assisted'


def test_observation_engine_never_constructs_brain_or_prompts_or_sends_buttons(tmp_path):
    lessons.configure(tmp_path)
    class Driver:
        def snapshot(self, memory):
            return {'player': {'ptr': 0x30001000, 'pos': (0, 0, 0), 'hp': 500, 'hp_max': 1000},
                    'timer': 100., 'kills': 1, 'score': 300, 'mercenaries_mode': 'mercenaries',
                    'character_index': 0, 'prompt': 'mash:circle'}
        def screen(self, memory, snap):
            return 'playing'
        def brain(self, *args, **kwargs):
            pytest.fail('Observation must not construct a gameplay brain')
        def prompt_source(self, *args):
            pytest.fail('Observation must not create a prompt presser')
        def prompt_keys(self, button):
            pytest.fail('Observation must not answer a human QTE')
        def progress(self, snap):
            return {key: snap[key] for key in ('timer', 'kills', 'score')}
    count, stats, sent = [0], {}, []
    def stopped():
        count[0] += 1
        return count[0] > 5
    result = engine.play_round({'map_id': 'BLUS30491'}, SimpleNamespace(), sent.extend, stopped, stats,
                               driver=Driver(), observe_only=True, sleep=lambda _: None, clock=lambda: count[0])
    assert result == 'stopped'
    assert sent == []
    assert stats['character'] == 'Chris (BSAA)'
    assert stats['assistance_classification'] == 'unknown'
    with Notebook(tmp_path/'mercs', 'BLUS30491').connect() as db:
        rows = db.execute('select data from rounds').fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0][0])['unmodified_s_rank_verified'] is False


def test_human_observer_detects_a_retry_without_replaying_inputs():
    stats = {}
    observer = HumanObserver(stats)
    snap = {'player': {'ptr': 0x30001000}, 'kills': 30}
    observer.observe_round(snap, 'playing', 10)
    observer.observe_round(dict(snap, kills=31), 'playing', 11)
    assert observer._round_started == 10
    observer.observe_round(dict(snap, kills=0), 'playing', 12)
    assert observer._round_started == 12
    assert observer.tick(snap) == {'hold': set()}
