from gbox import native_engineering as engineering, re_lab, re_seeds
from test_re_lab import Store


def test_every_stage_references_a_real_reusable_playbook():
    packet = engineering.plan('a' * 16)
    known = {p['id'] for p in re_seeds.PLAYBOOKS}
    assert set(packet['stages']) == {'inventory', 'analysis', 'reader', 'writer', 'runtime'}
    for entry in packet['stages'].values():
        assert set(entry['playbooks']) <= known
    assert 'normal gBox routes' in re_lab.playbook(Store(), 'native-reader-writer')['goal']


def test_writer_brief_keeps_integration_and_independent_roundtrip_requirements():
    text = engineering.prompt('a' * 16, stage='writer', fingerprint={'start_from': 'gbox.test_reader'})
    assert 'gbox.test_reader' in text
    assert 'byte-identical' in text and 'read it back independently' in text
    assert 'char_coverage.WRITERS' in text and 'characters_tool' in text
    assert 'runtime:' not in text  # current milestone stays bounded


def test_brief_is_not_readiness_and_cannot_mutate_shared_contract():
    packet = engineering.plan('a' * 16)
    assert 'no reader, writer or runtime support is inferred' in packet['scope']
    packet['stages']['writer']['checks'].clear()
    assert engineering.plan('b' * 16)['stages']['writer']['checks']


def test_native_playbook_reseeding_preserves_local_lessons():
    store = Store()
    re_lab.learn(store, 'native-reader-writer', 'Verify XEX execution-info offsets against owned bytes.', game='Too Human')
    old = store.get('playbook', 'native-reader-writer')
    old['seed_version'] = 0
    re_lab.seed_playbooks(store)
    assert store.get('playbook', 'native-reader-writer')['lessons'] == old['lessons']


def test_integration_files_exist_in_the_repository():
    from pathlib import Path
    root = Path(engineering.__file__).resolve().parents[1]
    assert all((root / name).exists() for name in engineering.plan('a' * 16)['integration'])
