"""Regression tests for the Armored Core V unlock evidence module."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('acv_evidence', ROOT / 'gbox' / 'acv_evidence.py')
acv_evidence = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(acv_evidence)

REQUIRED = {'characters', 'hidden_characters', 'modes', 'levels', 'stages', 'costumes', 'items', 'extras'}


def test_inventory_covers_every_required_category():
    assert set(acv_evidence.inventory()) == REQUIRED
    assert set(acv_evidence.CATEGORIES) == REQUIRED


def test_every_category_records_a_status_and_evidence():
    for category, row in acv_evidence.inventory().items():
        assert row['status'] in ('unlocked', 'not_present', 'unknown'), category
        assert isinstance(row['evidence'], str) and row['evidence'].strip(), category
        assert isinstance(row['entries'], list), category


def test_absent_categories_enumerate_nothing():
    for category, row in acv_evidence.inventory().items():
        if row['status'] == 'not_present':
            assert row['entries'] == [], category


def test_unlocked_categories_enumerate_every_entry():
    for category, row in acv_evidence.inventory().items():
        if row['status'] == 'unlocked':
            assert row['entries'], category
            assert all(isinstance(x, str) and x.strip() for x in row['entries']), category


def test_revision_guard_accepts_only_the_owned_executable():
    assert acv_evidence.assert_revision(acv_evidence.ACV_XEX_SHA256) == acv_evidence.ACV_XEX_SHA256
    for bad in ('0' * 64, acv_evidence.ACV_ELF_SHA256, acv_evidence.ACV_ISO_SHA256, ''):
        try:
            acv_evidence.assert_revision(bad)
        except ValueError:
            continue
        raise AssertionError('revision guard accepted ' + repr(bad))


def test_inventory_is_a_copy_and_cannot_be_mutated_in_place():
    inv = acv_evidence.inventory()
    inv['characters']['status'] = 'unlocked'
    assert acv_evidence.inventory()['characters']['status'] == 'not_present'


def test_profile_body_refuses_an_inventory_with_unknown_categories():
    pending = acv_evidence.unresolved()
    if pending:
        try:
            acv_evidence.profile_body()
        except ValueError as exc:
            assert 'unresolved' in str(exc)
            for category in pending:
                assert category in str(exc)
        else:
            raise AssertionError('profile body accepted an unresolved inventory')
    else:
        body = acv_evidence.profile_body()
        assert body['inventory_complete'] is True
        assert body['executable_sha256'] == acv_evidence.ACV_XEX_SHA256


def test_lock_surface_and_greyout_sets_are_disjoint():
    assert not set(acv_evidence.LOCK_SURFACE) & set(acv_evidence.OFFLINE_GREYOUT)
    assert acv_evidence.LOCK_SURFACE and acv_evidence.OFFLINE_GREYOUT
