import struct

from gbox.mercs.titles import re5_switch as R


class Memory:
    base, su = 0x3c00000000, 0x5d00000000
    def __init__(self):
        self.data = {}
        self.reads = 0
        self.clock = 0.
        self.delay = 0.
        self.put(self.base + R.S_UNIT, '<Q', self.su)

    def put(self, addr, fmt, *values):
        for i,v in enumerate(struct.pack(fmt, *values)):
            self.data[addr+i] = v

    def rd(self, addr, count):
        self.reads += 1
        self.clock += self.delay
        return bytes(self.data.get(addr+i, 0) for i in range(count))

    def chain(self, line, count, *, bonus=True):
        start = self.su + 0x1000000 * (line+1)
        self.put(self.su + R.UNIT_LINES + R.LINE_STRIDE*line, '<Q', start)
        for k in range(count):
            p = start+k*0x3000
            self.put(p, '<Q', self.base+R.BONUS_VT if bonus and k == count-1 else self.base+0x100)
            self.put(p+R.UNIT_NEXT, '<Q', p+0x3000 if k<count-1 else 0)
        if bonus:
            p = start+(count-1)*0x3000
            self.put(p+R.E_POS, '<3f', line*100, 0, 100)
            self.put(p+R.E_HP, '<h', 60)
        return start


def finish(m, now=0, identity='life-a'):
    for k in range(200):
        result = R.time_bonuses(m, m.base, now+k*.033, identity=identity)
        if m._re5_bonus_scan['status'] == 'complete':
            return result
    raise AssertionError('scan failed to finish')


def test_large_multiline_census_is_sliced_and_never_publishes_partial_absence(monkeypatch):
    m = Memory(); m.chain(0, 150); m.chain(20, 100)
    monkeypatch.setattr(R.time, 'perf_counter', lambda:m.clock)
    assert R.time_bonuses(m, m.base, now=0, identity='life-a') is None
    assert m._re5_bonus_scan['work'] <= 64 and m.reads <= 70
    full = finish(m)
    assert len(full) == 2
    assert R.time_bonuses(m, m.base, now=10, identity='life-a') is full
    assert m._re5_bonus_scan['status'] == 'scanning'


def test_one_slow_read_yields_and_new_life_cannot_inherit_previous_census(monkeypatch):
    m = Memory(); m.chain(0, 100)
    monkeypatch.setattr(R.time, 'perf_counter', lambda:m.clock)
    full = finish(m)
    m.delay = .02
    before = m.reads
    assert R.time_bonuses(m, m.base, now=10, identity='life-a') is full
    assert m.reads-before <= 2  # header transport plus one indivisible scan operation
    assert R.time_bonuses(m, m.base, now=11, identity='life-b') is None
    assert m._re5_bonus_scan['identity'][-1] == 'life-b'


def test_cycle_marks_census_unknown_and_keeps_previous_complete_evidence(monkeypatch):
    m = Memory(); start = m.chain(0, 1)
    monkeypatch.setattr(R.time, 'perf_counter', lambda:m.clock)
    full = finish(m)
    m.put(start+R.UNIT_NEXT, '<Q', start)
    assert R.time_bonuses(m, m.base, now=10, identity='life-a') == full
    assert m._re5_bonus_scan['status'] == 'incomplete'
    assert m._re5_bonus_scan['list'] == full
    assert 'cycle' in m._re5_bonus_scan['error']


def test_bad_early_line_does_not_starve_later_discoveries(monkeypatch):
    m = Memory(); start = m.chain(0, 1, bonus=False); m.chain(20, 1)
    m.put(start+R.UNIT_NEXT, '<Q', start)
    monkeypatch.setattr(R.time, 'perf_counter', lambda:0)
    found = R.time_bonuses(m, m.base, now=0)
    assert len(found) == 1 and found[0]['pos'][0] == 2000
    assert m._re5_bonus_scan['status'] == 'incomplete'


def test_distinct_memory_views_never_share_native_statue_addresses(monkeypatch):
    first, second = Memory(), Memory()
    first.chain(0, 1)
    monkeypatch.setattr(R.time, 'perf_counter', lambda:0)
    assert len(finish(first)) == 1
    assert finish(second) == []
