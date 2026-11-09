"""Native slot composition keeps motion/control resources and resolves every material texture."""
from dataclasses import replace
import hashlib
import struct
import zlib

import pytest

from gbox import mt_arc, re5_player_archive as P
from tests.test_mtf_mrl import fixture as material_fixture


def entry(name, kind, raw):
    data = zlib.compress(raw)
    return mt_arc.Entry(name, kind, 0x40000000 | len(raw), len(data), 0, data)


def archive(character):
    mrl, model, _ = material_fixture()
    mrl = bytearray(mrl)
    paths = [rf"pawn\{character}\body_NM", rf"pawn\{character}\body_BM", r"system\texture\NullWhite"]
    for i, path in enumerate(paths):
        at = 40 + i * 88 + 24
        mrl[at:at + 64] = path.encode().ljust(64, b"\0")
    entries = [entry(P.MODEL_PATHS[character], P.MOD_CLASS, model),
               entry(P.MODEL_PATHS[character], P.MRL_CLASS, bytes(mrl)),
               entry(rf"pawn\{character}\motion", 123, b"LMT\0" + character.encode()),
               entry(P.MODEL_PATHS[character], 456, b"CHN\0" + character.encode())]
    entries += [entry(path, P.TEX_CLASS, b"TEX\0" + path.encode()) for path in paths[:2]]
    return mt_arc.build(mt_arc.Arc(7, entries))


@pytest.fixture
def pair(monkeypatch):
    target, donor = archive("chris"), archive("sheva")
    monkeypatch.setattr(P, "REQUIRED_ANIMATION_IDS", frozenset({0}))
    monkeypatch.setattr(P, "NATIVE_SHA256", {"chris": hashlib.sha256(target).hexdigest(),
                                           "sheva": hashlib.sha256(donor).hexdigest()})
    return target, donor


def edited(data, change, character, monkeypatch):
    arc = mt_arc.parse(data)
    change(arc)
    result = mt_arc.build(arc)
    monkeypatch.setitem(P.NATIVE_SHA256, character, hashlib.sha256(result).hexdigest())
    return result


def test_composes_lookup_names_and_preserves_all_other_target_resources(pair):
    target, donor = pair
    result, report = P.compose(target, donor)
    old, source, new = map(mt_arc.parse, (target, donor, result))
    assert len(new.entries) == len(old.entries) + 2
    for i in (0, 1):
        assert new.entries[i].name == P.MODEL_PATHS['chris']
        assert new.entries[i].data == source.entries[i].data
        assert new.entries[i].tag == source.entries[i].tag
    for a, b in zip(old.entries[2:], new.entries[2:]):
        assert (a.name, a.hash, a.tag, a.data) == (b.name, b.hash, b.tag, b.data)
    assert [e.data for e in new.entries[-2:]] == [e.data for e in source.entries[-2:]]
    assert report['gameplay_verified'] is False
    assert report['external_textures'] == [r'system\texture\NullWhite']
    assert report['target_motion_and_control_resources_preserved'] is True
    assert report['written_sha256'] == hashlib.sha256(result).hexdigest()
    assert P.compose(target, donor)[0] == result


@pytest.mark.parametrize('which', ['target', 'donor'])
def test_modified_original_is_rejected_before_parsing(pair, which, monkeypatch):
    target, donor = pair
    monkeypatch.setattr(mt_arc, 'parse', lambda *a: pytest.fail('unverified source parsed'))
    with pytest.raises(P.PlayerArchiveError, match='SHA256'):
        P.compose(target + (b'x' if which == 'target' else b''), donor + (b'x' if which == 'donor' else b''))


def test_other_native_pair_is_not_implicitly_supported(pair):
    with pytest.raises(P.PlayerArchiveError, match='only the measured'):
        P.compose(*pair, target='sheva', donor='chris')


@pytest.mark.parametrize('change,reason', [
    (lambda a: a.entries.pop(), 'missing'),
    (lambda a: a.entries.append(replace(a.entries[0])), 'duplicate resource'),
    (lambda a: setattr(a.entries[0], 'name', r'pawn\wrong\model'), 'missing expected'),
    (lambda a: setattr(a, 'version', 8), 'version 7'),
    (lambda a: setattr(a.entries[-1], 'tag', a.entries[-1].tag + 1), 'length'),
    (lambda a: setattr(a.entries[-1], 'data', a.entries[-1].data + b'trailing'), 'length'),
])
def test_missing_ambiguous_wrong_or_corrupt_dependencies_fail(pair, monkeypatch, change, reason):
    target, donor = pair
    donor = edited(donor, change, 'sheva', monkeypatch)
    with pytest.raises(P.PlayerArchiveError, match=reason):
        P.compose(target, donor)


def test_shared_texture_must_match_exactly_or_composition_refuses(pair, monkeypatch):
    target, donor = pair
    source = mt_arc.parse(donor).entries[-1]
    target = edited(target, lambda a: a.entries.append(replace(source)), 'chris', monkeypatch)
    _, report = P.compose(target, donor)
    assert report['reused_textures'] == [source.name]
    target = edited(target, lambda a: setattr(a.entries[-1], 'data', b'different'), 'chris', monkeypatch)
    with pytest.raises(P.PlayerArchiveError, match='collides'):
        P.compose(target, donor)


def test_unknown_external_texture_is_not_silently_assumed_available(pair, monkeypatch):
    target, donor = pair
    def change(a):
        raw = bytearray(zlib.decompress(a.entries[1].data))
        at = 40 + 2 * 88 + 24
        raw[at:at + 64] = b'system\\missing'.ljust(64, b'\0')
        a.entries[1] = entry(a.entries[1].name, P.MRL_CLASS, bytes(raw))
    donor = edited(donor, change, 'sheva', monkeypatch)
    with pytest.raises(P.PlayerArchiveError, match='missing'):
        P.compose(target, donor)


def test_donor_material_names_must_resolve_to_its_model(pair, monkeypatch):
    target, donor = pair
    def change(a):
        raw = bytearray(zlib.decompress(a.entries[1].data))
        material_offset = struct.unpack_from('<Q', raw, 32)[0]
        raw[material_offset + 8] ^= 1
        a.entries[1] = entry(a.entries[1].name, P.MRL_CLASS, bytes(raw))
    donor = edited(donor, change, 'sheva', monkeypatch)
    with pytest.raises(ValueError, match='no matching'):
        P.compose(target, donor)


def test_missing_common_body_animation_ids_are_rejected(pair, monkeypatch):
    monkeypatch.setattr(P, 'REQUIRED_ANIMATION_IDS', frozenset(range(24)))
    with pytest.raises(P.PlayerArchiveError, match='body animation IDs'):
        P.compose(*pair)
