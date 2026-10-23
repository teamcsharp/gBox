from pathlib import Path
p=Path('system/tests/test_re5_mercs.py');s=p.read_text()
helper='''def provide_open_navigation(monkeypatch):
    from gbox.mercs.titles.re5_nav import NavMesh
    mesh = NavMesh([(-5000.,0.,-5000.), (5000.,0.,-5000.), (5000.,0.,5000.), (-5000.,0.,5000.)],
                   [(0,1,2), (0,2,3)], [[(1,2,1.)], [(0,0,1.)]])
    original = R.snapshot
    def snapshot(memory):
        return dict(original(memory), nav=mesh)
    monkeypatch.setattr(R, "snapshot", snapshot)


'''
s=s.replace('def test_a_time_bonus_is_taken_with_its_prompt(monkeypatch):',helper+'def test_a_time_bonus_is_taken_with_its_prompt(monkeypatch):')
for name in ('test_a_time_bonus_is_taken_with_its_prompt','test_bonuses_anywhere_are_walked_to_nearest_first_and_the_clock_jumps_are_counted',
             'test_gathers_every_bonus_first_then_stands_and_breaks_for_a_late_one','test_distant_unsighted_front_candidate_does_not_starve_time_bonus_navigation',
             'test_a_time_bonus_beats_a_visible_majini_further_off','test_a_time_bonus_is_taken_even_when_the_strategy_would_keep_the_combo'):
    s=s.replace(f'def {name}(monkeypatch):',f'def {name}(monkeypatch):\n    provide_open_navigation(monkeypatch)')
s=s.replace('assert any(abs(w[1] + 150.0) < 1 for w in route)', 'assert any(isinstance(w, R.re5_nav.Traversal) and w[1] == -300. for w in route)')
s=s.replace('ladder = next(w for w in route if abs(w[1] + 150.0) < 1)', 'ladder = next(w.portal for w in route if isinstance(w, R.re5_nav.Traversal))')
s=s.replace('assert bot.stats["stuck"] == 2 and bot.stats["routes_blocked"] == 1', 'assert bot.stats["stuck"] == 2 and bot.stats["route_replans"] == 1')
s=s.replace('p = {"pos": (20., 80., 50.),', 'p = {"pos": (20., 50., 50.),')
s=s.replace('    assert bot.stats["routes_blocked"] == 1 and bot.bonus_skip[7] > t', '    assert bot.stats["stuck"] == 0\n    assert bot.stats["route"] == "waiting for stage navigation; no blind straight-line pursuit"')
p.write_text(s)
print('Updated route fixtures to provide mapped floors and assert explicit action-link behavior')
