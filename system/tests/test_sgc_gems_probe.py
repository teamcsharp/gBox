"""Focused tests for the Sonic Gems Collection (USA) state-save probe."""
from gbox import sgc_gems_probe as probe


def _save():
    data = bytearray(probe.SAVE_SIZE)
    data[0:6] = probe.GAME_CODE.encode('ascii')
    data[0x06:0x08] = (0xFF02).to_bytes(2, 'big')
    data[0x08:0x18] = b'SONIC GEMSB_07\x00\x00'
    data[0x28:0x2c] = (0x0A1BF2F8).to_bytes(4, 'big')
    data[0x40:0x60] = b'SONIC GEMS COLLECTION'.ljust(32, b'\x00')
    data[0x60:0x80] = b' 8: VECTORMAN'.ljust(32, b'\x00')
    return bytes(data)


def test_header_fields_decode():
    head = probe.parse_header(_save())
    assert head['gamecode'] == 'G2XE8P'
    assert head['magic_word'] == 0xFF02
    assert head['banner'] == 'SONIC GEMSB_07'
    assert head['title'] == 'SONIC GEMS COLLECTION'
    assert head['comment'] == ' 8: VECTORMAN'
    assert head['timestamp'] == 0x0A1BF2F8


def test_only_this_revision_is_accepted():
    assert probe.looks_like_state_save(_save()) is True
    other = bytearray(_save())
    other[0:6] = b'GALE01'
    assert probe.looks_like_state_save(bytes(other)) is False
    assert probe.looks_like_state_save(_save()[:-1]) is False


def test_save_name_parsing():
    assert probe.parse_save_name('state_us__museum03.stm') == {
        'region': 'us', 'slot': 3, 'kind': 'stm'}
    assert probe.parse_save_name('state_jp__museum10.stg') == {
        'region': 'jp', 'slot': 10, 'kind': 'stg'}
    assert probe.parse_save_name('museum__museum01.adx') is None
    assert probe.parse_save_name('state_us__museum99.stm') is None
    assert probe.parse_save_name('state_us__museum.stm') is None


def test_slot_plan_groups_pairs():
    names = ['state_us__museum01.stm', 'state_us__museum01.stg',
             'state_us__museum02.stm', 'common__load.prs']
    slots = probe.plan_slots(names)
    assert [s['slot'] for s in slots] == [1, 2]
    assert set(slots[0]['files']) == {'stm', 'stg'}
    assert set(slots[1]['files']) == {'stm'}


def test_gate_is_honest_and_ungated():
    gate = probe.profile_gate()
    assert gate['verified'] is False
    assert gate['categories'] == list(probe.CATEGORIES)
    assert gate['blockers'] and gate['next']
    assert probe.DOL_SHA256 in gate['evidence']['executable']


def test_pinned_digests_are_full_sha256():
    for name, digest in probe.STATE_SAVE_SHA256.items():
        assert len(digest) == 64, name
        assert all(c in '0123456789abcdef' for c in digest), name
    assert probe.SLOT_COUNT == 10


def test_probe_has_no_write_path():
    """The probe is read-only: it must expose no write/apply API."""
    forbidden = ('write', 'apply', 'patch', 'unlock_all', 'save_bytes', 'open(', 'os.remove')
    for name in dir(probe):
        if name.startswith('_'):
            continue
        assert not any(tok in name.lower() for tok in forbidden), name
