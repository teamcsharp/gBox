from gbox.mercs.titles import re5_switch as R
from test_re5_bonus_scan_budget import Memory


def census_memory(n):
    m = Memory()
    start = m.chain(R.ENEMY_LINE, n, bonus=False)
    for i in range(n):
        m.put(start+i*0x3000+R.E_HP, '<h', 100)
    return m, start


def finish(m, identity='one'):
    for i in range(100):
        result = R.unit_enemies_alive(m, m.base, i*.03, identity=identity)
        if m._re5_enemy_census['status'] == 'complete':
            return result
    raise AssertionError('census did not finish')


def test_census_never_traverses_whole_enemy_list_on_one_tick(monkeypatch):
    monkeypatch.setattr(R,'enemy_class',lambda m,u:'uEm10')
    m, _ = census_memory(100)
    assert R.unit_enemies_alive(m,m.base,0,identity='one') is None
    assert m._re5_enemy_census['nodes'] <= R.CENSUS_NODES
    assert finish(m) == 100
    # Separate memory/life cannot inherit the old count or cursor.
    assert R.unit_enemies_alive(m,m.base,4,identity='two') is None
    other, _ = census_memory(1)
    assert finish(other) == 1


def test_transport_budget_stops_between_operations(monkeypatch):
    monkeypatch.setattr(R,'enemy_class',lambda m,u:'uEm10')
    m, _ = census_memory(100)
    m.delay = .0007
    monkeypatch.setattr(R.time,'perf_counter',lambda:m.clock)
    R.unit_enemies_alive(m,m.base,0)
    assert m._re5_enemy_census['nodes'] == 1
    assert m.reads <= 4


def test_cycle_and_unknown_class_cannot_publish_partial_count(monkeypatch):
    monkeypatch.setattr(R,'enemy_class',lambda m,u:'uEm10')
    m, p = census_memory(2)
    m.put(p+0x3000+R.UNIT_NEXT,'<Q',p)
    assert R.unit_enemies_alive(m,m.base,0) is None
    assert m._re5_enemy_census['status'] == 'incomplete'
    m, p = census_memory(2)
    monkeypatch.setattr(R,'enemy_class',lambda m,u:'uEm10' if u==p else None)
    assert R.unit_enemies_alive(m,m.base,0) is None
    assert m._re5_enemy_census['n'] is None
