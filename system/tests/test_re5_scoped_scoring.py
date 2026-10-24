"""Shared Mercenaries scores cannot manufacture a solo rank or P2 character."""
from types import SimpleNamespace

from gbox.mercs.titles import re5_ps3 as R


def snapshot(**scope):
    return {'player':{'ptr':0x30400000},'score':65000,'kills':150,'combo':17,'timer':120.,
            'mercenaries_phase':3,'stage_index':0,**scope}


class ForbiddenRoster:
    @property
    def round(self):raise AssertionError('global roster cannot label a shared/Player 2 run')
    def observe(self,*_args):raise AssertionError('global roster must not receive team totals')
    def started(self):raise AssertionError('global roster cannot select a Player 2 costume')


def test_p2_and_native_duo_progress_clear_stale_solo_labels_without_touching_roster(monkeypatch):
    monkeypatch.setattr(R,'ROSTER',ForbiddenRoster())
    for fields in ({'control_player':2},{'scoring_players':2},{'control_player':1,'scoring_players':2}):
        stats={'rank':'S','completed_score_rank':'SS','character':'Chris BSAA'}
        stats.update(R.RE5PS3().progress(snapshot(**fields)))
        assert stats['score']==65000 and stats['kills']==150 and stats['stage_index']==0
        assert stats['rank'] is None and stats['completed_score_rank'] is None
        assert stats['character']=='unknown' and not stats['character_cursor_verified']
        assert stats['score_scope']==stats['kills_scope']==stats['combo_scope']=='team'
        assert stats.get('result_rank') is None


def test_terminal_p2_and_duo_results_preserve_team_totals_but_remove_solo_estimate(monkeypatch):
    monkeypatch.setattr(R,'ROSTER',ForbiddenRoster())
    for fields in ({'control_player':2},{'scoring_players':2}):
        stats={'score':60000,'kills':149,'rank':'S','completed_score_rank':'S',
               'completed_score_rank_source':'terminal_ram_score_and_solo_thresholds','character':'Chris BSAA'}
        brain=SimpleNamespace(stats=stats,round_active=True,round_end=None,_round_player=0x30400000)
        R.Bot._observe_result(brain,snapshot(**fields))
        assert stats['score']==65000 and stats['kills']==150 and stats['finished_naturally']
        assert not any(key in stats for key in ('rank','completed_score_rank','completed_score_rank_source'))
        assert stats['character']=='unknown' and stats['scoring_scope']=='team'
        assert 'result_rank' not in stats and 'rank_verified' not in stats


def test_default_solo_progress_and_terminal_derived_thresholds_are_preserved(monkeypatch):
    monkeypatch.setattr(R,'ROSTER',R.Roster())
    for fields in ({},{'control_player':1,'scoring_players':1}):
        progress=R.RE5PS3().progress(snapshot(**fields))
        assert progress['rank']=='S' and progress['character']!='unknown'
        brain=SimpleNamespace(stats={},round_active=True,round_end=None,_round_player=0x30400000)
        R.Bot._observe_result(brain,snapshot(**fields))
        assert brain.stats['completed_score_rank']=='S'
        assert brain.stats['completed_score_rank_source']=='terminal_ram_score_and_solo_thresholds'
        assert 'result_rank' not in brain.stats


def test_unattributed_team_damage_does_not_turn_into_zero_percent_individual_accuracy():
    brain = SimpleNamespace(stats={}, _round_started=1., _round_ended_at=None,
        _round_combo=10, _round_baseline={},
        combat=SimpleNamespace(damage_unattributed=True, round_counts={'shots':5, 'hits':0}))
    R.Bot._evaluate_round(brain, snapshot(control_player=2), 10.)
    evaluation = brain.stats['round_evaluation']
    assert 'observed_hit_fraction' not in evaluation['derived']
    assert 'round_hits' in evaluation['missing']
    assert evaluation['score_scope'] == 'team'
    assert evaluation['damage_attribution'] == 'unattributed_multiple_players'
