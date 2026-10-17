import copy
import io
import json
import os
from pathlib import Path
import struct

import numpy as np
from PIL import Image
import pytest

from gbox import re5ps3_write as W
from gbox.re5ps3_arc import Arc, sha
from gbox.re5ps3_models import Model, Texture, export_glb, export_archive
from test_re5ps3_models import model, texture, glb


def edited_glb(path, edit):
    raw = path.read_bytes()
    size = struct.unpack_from('<I', raw, 12)[0]
    doc = json.loads(raw[20:20 + size])
    binary = bytearray(raw[28 + size:])
    edit(doc, binary)
    header = json.dumps(doc, separators=(',', ':'), allow_nan=True).encode()
    header += b' ' * (-len(header) % 4)
    return struct.pack('<3I', 0x46546c67, 2, 28 + len(header) + len(binary)) + \
        struct.pack('<2I', len(header), 0x4e4f534a) + header + struct.pack('<2I', len(binary), 0x004e4942) + binary


def attr_offset(doc, name, primitive=0):
    p = doc['meshes'][0]['primitives'][primitive]
    a = doc['accessors'][p['attributes'][name]]
    v = doc['bufferViews'][a['bufferView']]
    return v['byteOffset'] + a.get('byteOffset', 0)


@pytest.mark.parametrize('eight', [False, True])
def test_native_noop_preserves_every_byte_even_nonstandard_weight_sums(eight, tmp_path):
    data = bytearray(model(eight))
    vertex = struct.unpack_from('>I', data, 60)[0]
    data[vertex + (16 if eight else 12)] -= 1  # Accepted native sum 254; retain original byte quantization.
    data = bytes(data)
    source = Model(data)
    path = tmp_path / 'model.glb'
    export_glb(source, {'pawn\\test\\body': texture()}, path)
    actual, receipt = W.model_from_glb(data, path.read_bytes(), expected_sha256=sha(data))
    assert actual == data and receipt['noop_identical'] and receipt['changed_bytes'] == 0


def test_native_vertex_edits_preserve_unknown_bytes_topology_and_rig():
    data = model(True); source = Model(data)
    mesh = source.meshes[0]
    positions = mesh['positions'].copy(); positions[0] += [.25, .5, .75]
    normals = mesh['normals'].copy(); normals[1] = [0, 1, 0]
    uv = mesh['uv'].copy(); uv[2] = [.125, .875]
    weights = mesh['weights'].copy(); weights[0] = [1, 0, 0, 0, 0, 0, 0, 0]
    joints = mesh['joints'].copy(); joints[0, 0] = 0
    actual, receipt = W.patch_model(data, {0: dict(positions=positions, normals=normals, uv=uv,
                                                 weights=weights, joints=joints)}, expected_sha256=sha(data))
    got = Model(actual).meshes[0]
    assert np.allclose(got['positions'], positions, atol=2 / 32767)
    assert np.allclose(got['normals'][1], [0, 1, 0], atol=.004)
    assert np.array_equal(got['uv'], uv)
    assert got['joints'][0, 0] == 0 and got['weights'][0, 0] == 1
    assert np.array_equal(got['triangles'], mesh['triangles'])
    vertex = struct.unpack_from('>I', data, 60)[0]
    writable = {vertex + i * 32 + at for i in range(3) for at in [*range(6), *range(8, 24), *range(24, 27), *range(28, 32)]}
    assert all(i in writable for i, (old, new) in enumerate(zip(data, actual)) if old != new)
    assert 0 < receipt['changed_bytes'] < len(writable)


def test_shared_native_lod_mask_reports_every_affected_view():
    data = bytearray(model())
    mesh_at = struct.unpack_from('>I', data, 56)[0]
    data[mesh_at + 5] = 255
    data = bytes(data)
    positions = Model(data).meshes[0]['positions'].copy()
    positions[0, 0] += .25
    actual, receipt = W.patch_model(data, {0: {'positions': positions}}, expected_sha256=sha(data))
    assert receipt['changes'] == [{'mesh': 0, 'fields': ['positions'], 'native_lod_mask': 255}]
    assert receipt['affected_lod_masks'] == [1, 2, 4]
    assert Model(actual).meshes[0]['lod'] == 255


def test_native_alias_cannot_silently_edit_an_unselected_lod():
    data = bytearray(model())
    mesh_at = struct.unpack_from('>I', data, 56)[0]
    # Two valid descriptors share the primary vertices but have separate index
    # ranges and LOD masks. Reading is valid; bounded writing must reject it.
    data[mesh_at + 52:mesh_at + 52] = data[mesh_at:mesh_at + 52]
    struct.pack_into('>H', data, 8, 2)
    struct.pack_into('>2I', data, 12, 6, 8)
    for at in (60, 64, 68):
        struct.pack_into('>I', data, at, struct.unpack_from('>I', data, at)[0] + 52)
    data[mesh_at + 52 + 5] = 2
    struct.pack_into('>I', data, mesh_at + 52 + 28, 3)
    data += struct.pack('>3H', 0, 1, 2)
    data = bytes(data)
    source = Model(data)
    assert len(source.meshes) == 2 and source.meshes[1]['lod'] == 2
    assert np.array_equal(source.meshes[0]['positions'], source.meshes[1]['positions'])
    positions = source.meshes[0]['positions'].copy(); positions[0, 0] = 1
    with pytest.raises(ValueError, match='overlapping native vertex spans'):
        W.patch_model(data, {0: {'positions': positions}}, expected_sha256=sha(data))


@pytest.mark.parametrize('field,value,match', [
    ('positions', [[1e308, 0, 0]] * 3, 'positions'),
    ('positions', [[float('nan'), 0, 0]] * 3, 'non-finite'),
    ('uv', [[1e30, 0]] * 3, 'half-float'),
    ('normals', [[0, 0, 0]] * 3, 'zero-length'),
    ('joints', [[200, 0, 0, 0]] * 3, 'joint IDs'),
    ('weights', [[.3, .3, .3, .3]] * 3, 'sum to one'),
    ('weights', [[.5, .5, 0, 0]] * 3, 'influence count'),
    ('triangles', [[0, 2, 1]], 'unsupported MOD edit'),
])
def test_invalid_native_patch_rejected(field, value, match):
    data = model()
    with pytest.raises(ValueError, match=match):
        W.patch_model(data, {0: {field: value}}, expected_sha256=sha(data))


def test_edited_glb_updates_native_positions_and_rejects_rig_topology_and_nonfinite(tmp_path):
    data = model(); source = Model(data)
    path = tmp_path / 'model.glb'
    export_glb(source, {'pawn\\test\\body': texture()}, path)
    def move(doc, blob):
        struct.pack_into('<f', blob, attr_offset(doc, 'POSITION'), .01)
    edited = edited_glb(path, move)
    actual, _ = W.model_from_glb(data, edited, expected_sha256=sha(data))
    assert Model(actual).meshes[0]['positions'][0, 0] == pytest.approx(1, abs=2/32767)
    def wrong_topology(doc, blob):
        a = doc['accessors'][doc['meshes'][0]['primitives'][0]['indices']]
        struct.pack_into('<I', blob, doc['bufferViews'][a['bufferView']]['byteOffset'], 1)
    def wrong_rig(doc, blob):
        doc['nodes'][2]['matrix'][12] = 1
    def nan_position(doc, blob):
        struct.pack_into('<f', blob, attr_offset(doc, 'POSITION'), float('nan'))
    def wrong_source(doc, blob):
        doc['extras']['source_sha256'] = '0' * 64
    def oversized_accessor(doc, blob):
        doc['accessors'][0]['count'] = 9000000
    def animated(doc, blob):
        doc['animations'] = [{'name': 'unsupported animation'}]
    for bad in (wrong_topology, wrong_rig, nan_position, wrong_source, oversized_accessor, animated):
        with pytest.raises(ValueError):
            W.model_from_glb(data, edited_glb(path, bad), expected_sha256=sha(data))


def tex_mips(kind='DXT5'):
    # Three independent, known red BC blocks. Offsets deliberately leave gaps
    # that a writer must preserve, as well as a non-mip trailer.
    base = texture(kind)
    block = base[40:]
    head = bytearray(base[:36]); head[8] = 3
    struct.pack_into('>HH', head, 10, 8, 8)
    head += struct.pack('>3I', 52, 52 + len(block)*4 + 7, 52 + len(block)*5 + 10)
    return bytes(head) + b'GAP!' + block * 4 + b'unknown' + block + b'pad' + block + b'trailer'


@pytest.mark.parametrize('kind', ['DXT1', 'DXT5'])
def test_texture_noop_and_changed_full_mip_chain_preserve_headers(kind):
    data = tex_mips(kind); source = Texture(data)
    actual, receipt = W.replace_texture(data, source.image(), expected_sha256=sha(data))
    assert actual == data and receipt['noop_identical']
    image = Image.new('RGBA', (8, 8), (0, 255, 0, 255))
    actual, receipt = W.replace_texture(data, image, expected_sha256=sha(data))
    output = Texture(actual)
    allowed = {i for at, size in zip(source.offsets, source.sizes) for i in range(at, at + size)}
    assert all(i in allowed for i, (a, b) in enumerate(zip(data, actual)) if a != b)
    assert receipt['mips'] == 3 and len(receipt['compression_error']) == 3
    for level in range(3):
        pixels = np.asarray(output.image(level))
        assert np.max(np.abs(pixels.astype(int) - [0, 255, 0, 255])) <= 1


def test_texture_rejects_dimensions_and_unrepresentable_dxt1_alpha():
    data = texture()
    with pytest.raises(ValueError, match='dimensions'):
        W.replace_texture(data, Image.new('RGBA', (8, 8)), expected_sha256=sha(data))
    with pytest.raises(ValueError, match='binary alpha'):
        W.replace_texture(data, Image.new('RGBA', (4, 4), (0, 0, 255, 100)), expected_sha256=sha(data))


def test_binary_dxt1_alpha_and_dxt5_alpha_are_retained_or_explicitly_rejected():
    for kind, alpha in [('DXT1', 0), ('DXT5', 80)]:
        data = texture(kind)
        image = Image.new('RGBA', (4, 4), (0, 0, 255, alpha))
        try:
            actual, _ = W.replace_texture(data, image, expected_sha256=sha(data))
        except ValueError as error:
            # An encoder incapable of BC1 cutout alpha must never silently drop it.
            assert kind == 'DXT1' and 'binary alpha' in str(error)
        else:
            got = np.asarray(Texture(actual).image())
            assert np.max(np.abs(got[:, :, 3].astype(int) - alpha)) <= 1


def test_worker_handoff_exposes_bounded_writer_cli(monkeypatch, capsys):
    import shlex
    import sys
    from gbox.native_engineering import plan, prompt
    title = plan('e7ca89bbeb67360d', stage='writer')['title_work']
    command = title['native_write_command']
    args = shlex.split(command)
    assert args[:3] == ['python', '-m', 'gbox.re5ps3_write']
    assert args[args.index('--member') + 1] == r'pawn\pl\pl00\model\pl0000'
    assert command in prompt('e7ca89bbeb67360d', stage='writer')
    assert 'transactional multi-resource' in title['validated_scope']
    batch = title['native_multi_write_command']
    assert batch in prompt('e7ca89bbeb67360d', stage='writer')
    assert shlex.split(batch)[-4:] == ['--edits-json', 'edits.json', '--out', 'NEW_CHRIS.arc']
    monkeypatch.setattr(sys, 'argv', [args[2], '--help'])
    with pytest.raises(SystemExit) as stopped:
        W.main()
    assert stopped.value.code == 0
    assert '--texture-png' in capsys.readouterr().out


def test_publication_is_exclusive_and_cleans_failed_staging(tmp_path, monkeypatch):
    target = tmp_path / 'output.arc'
    target.write_bytes(b'existing')
    with pytest.raises(FileExistsError):
        W._publish_archive(b'new', target)
    assert target.read_bytes() == b'existing'
    assert list(tmp_path.iterdir()) == [target]
    fresh = tmp_path / 'fresh.arc'
    def unavailable(*args):
        raise OSError('hard-link publication unavailable')
    monkeypatch.setattr(W.os, 'link', unavailable)
    with pytest.raises(OSError, match='publication unavailable'):
        W._publish_archive(b'complete output', fresh)
    assert not fresh.exists() and list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize('doc,match', [
    ({'version': 2, 'edits': []}, 'version 1'),
    ({'version': True, 'edits': []}, 'version 1'),
    ({'version': 1, 'edits': []}, '1..79'),
    ({'version': 1, 'edits': [{}] * 80}, '1..79'),
    ({'version': 1, 'edits': [{'member': 'a', 'geometry_glb': '../outside.glb'}]}, 'escapes'),
    ({'version': 1, 'edits': [{'member': 'a', 'geometry_glb': 'a.glb', 'texture_png': 'a.png'}]}, 'one geometry'),
])
def test_manifest_rejects_ambiguous_schema_and_outside_files(tmp_path, doc, match):
    manifest = tmp_path / 'edits.json'
    manifest.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match=match):
        W.read_edit_manifest(manifest)


@pytest.mark.parametrize('tag', ['uPl00ChrisNormal', 'uPl01ShebaNormal'])
def test_owned_transaction_combines_resources_deterministically_or_creates_nothing(tmp_path, tag, monkeypatch, capsys):
    import sys
    root = Path(os.environ.get('GBOX_RE5_EVIDENCE', str(Path.home() / 'gbox-pr-audit-20261017/re-export-evidence')))
    paths = list(root.glob(f're5/**/{tag}.arc'))
    if not paths:
        pytest.skip('owned RE5 PS3 archive evidence unavailable')
    assert len(paths) == 1
    original = paths[0].read_bytes(); archive = Arc(original)
    native_entry = next(e for e in archive.entries if archive.read(e)[:4] == b'\0DOM')
    native = archive.read(native_entry)
    model_path = tmp_path / 'model.glb'
    export_archive(archive, native_entry.name, model_path)
    original_glb = model_path.read_bytes()
    def move(doc, blob):
        at = attr_offset(doc, 'POSITION')
        struct.pack_into('<f', blob, at, struct.unpack_from('<f', blob, at)[0] + .0001)
    changed_glb = edited_glb(model_path, move)
    model_path.write_bytes(changed_glb)
    tex_entries = [e for e in archive.entries if archive.read(e)[:4] == b'\0XET'][:2]
    noop = tmp_path / 'noop-batch.arc'
    noop_receipt = W.write_archive_edits(original, [
        {'member': native_entry.name, 'geometry_glb': original_glb},
        {'member': tex_entries[0].name, 'texture_image': Texture(archive.read(tex_entries[0])).image()},
    ], noop, expected_sha256=sha(original))
    assert noop.read_bytes() == original and noop_receipt['noop_identical']
    edits = [{'member': native_entry.name, 'geometry_glb': changed_glb}]
    manifest_edits = [{'member': native_entry.name, 'geometry_glb': model_path.name}]
    expected = {native_entry.key: W.model_from_glb(native, changed_glb, expected_sha256=sha(native))[0]}
    for index, entry in enumerate(tex_entries):
        raw = archive.read(entry); tex = Texture(raw)
        im = Image.new('RGBA', (tex.width, tex.height), (0, 255 if index == 0 else 0, 255, 255))
        png = tmp_path / f'texture{index}.png'; im.save(png)
        edits.append({'member': entry.name, 'texture_image': im})
        manifest_edits.append({'member': entry.name, 'texture_png': png.name})
        expected[entry.key] = W.replace_texture(raw, im, expected_sha256=sha(raw))[0]
    manifest = tmp_path / 'edits.json'
    manifest.write_text(json.dumps({'version': 1, 'edits': manifest_edits}))
    output = tmp_path / 'combined.arc'
    monkeypatch.setattr(sys, 'argv', ['gbox.re5ps3_write', str(paths[0]), '--edits-json', str(manifest),
                                    '--expected-sha256', sha(original), '--out', str(output)])
    W.main()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['edited_members_verified'] == 3
    assert receipt['unchanged_members_verified'] == len(archive.entries) - 3
    assert {e['edit_source']['format'] for e in receipt['edits']} == {'glb', 'rgba8'}
    assert next(e for e in receipt['edits'] if e['edit_source']['format'] == 'glb')['edit_source']['sha256'] == sha(changed_glb)
    actual = Arc(output.read_bytes())
    for entry in archive.entries:
        raw = archive.read(entry)
        got = actual.read(actual.find(*entry.key))
        assert got == expected.get(entry.key, raw)
        assert (got != raw) == (entry.key in expected)
    reverse = tmp_path / 'reversed.arc'
    W.write_archive_edits(original, list(reversed(edits)), reverse, expected_sha256=sha(original))
    assert reverse.read_bytes() == output.read_bytes()
    for malformed, match in [
        (edits + [edits[0]], 'duplicate'),
        (edits + [{'member': tex_entries[0].name, 'texture_image': Image.new('RGBA', (1, 1))}], 'duplicate'),
        (edits[:-1] + [{'member': tex_entries[1].name, 'texture_image': Image.new('RGBA', (1, 1))}], 'dimensions'),
        (edits[:-1] + [{'member': 'missing', 'texture_image': edits[1]['texture_image']}], 'exact native'),
        ([], 'nonempty'),
    ]:
        bad = tmp_path / 'bad.arc'
        before = sorted(p.name for p in tmp_path.iterdir())
        with pytest.raises(ValueError, match=match):
            W.write_archive_edits(original, malformed, bad, expected_sha256=sha(original))
        assert not bad.exists() and sorted(p.name for p in tmp_path.iterdir()) == before
    assert paths[0].read_bytes() == original


def test_owned_model_and_texture_arc_roundtrips_and_independent_readback(tmp_path):
    root = Path(os.environ.get('GBOX_RE5_EVIDENCE', str(Path.home() / 'gbox-pr-audit-20261017/re-export-evidence')))
    paths = sorted(root.glob('re5/**/*.arc'))
    if not paths:
        pytest.skip('owned RE5 PS3 archive evidence unavailable')
    assert len(paths) == 2
    for path in paths:
        data = path.read_bytes(); archive = Arc(data)
        model_name = r'pawn\pl\pl00\model\pl0000' if path.name.startswith('uPl00') else r'pawn\pl\pl01\model\pl0100'
        native_entry = next(e for e in archive.entries if e.name == model_name and archive.read(e)[:4] == b'\0DOM')
        native = archive.read(native_entry)
        out = tmp_path / (path.stem + '.glb')
        export_archive(archive, model_name, out)
        noop = tmp_path / (path.stem + '-noop.arc')
        W.write_archive(data, model_name, noop, expected_sha256=sha(data), geometry_glb=out.read_bytes())
        assert noop.read_bytes() == data
        for lod in (2, 4):
            lod_out = tmp_path / (path.stem + f'-lod{lod}.glb')
            export_archive(archive, model_name, lod_out, lod=lod)
            lod_native, _ = W.model_from_glb(native, lod_out.read_bytes(), expected_sha256=sha(native))
            assert lod_native == native
        def move(doc, blob):
            at = attr_offset(doc, 'POSITION')
            old = struct.unpack_from('<f', blob, at)[0]
            struct.pack_into('<f', blob, at, old + .0001)
        changed_glb = edited_glb(out, move)
        changed_path = tmp_path / (path.stem + '-geometry.arc')
        receipt = W.write_archive(data, model_name, changed_path, expected_sha256=sha(data), geometry_glb=changed_glb)
        checked = Arc(changed_path.read_bytes())
        changed_native = checked.read(checked.find(*native_entry.key))
        assert changed_native != native and receipt['native_edit']['changed_bytes'] > 0
        old_model, new_model = Model(native), Model(changed_native)
        native_index = glb(out)[0]['meshes'][0]['primitives'][0]['extras']['index']
        mask = old_model.meshes[native_index]['lod']
        assert receipt['native_edit']['changes'][0]['native_lod_mask'] == mask
        assert receipt['native_edit']['affected_lod_masks'] == [m for m in (1, 2, 4) if mask & m]
        assert new_model.meshes[native_index]['positions'][0, 0] == pytest.approx(
            old_model.meshes[native_index]['positions'][0, 0] + .01,
            abs=float((old_model.bbox_max[0] - old_model.bbox_min[0]) / 32767))
        for e in archive.entries:
            if e.key != native_entry.key:
                assert checked.read(checked.find(*e.key)) == archive.read(e)
        tex_entry = next(e for e in archive.entries if archive.read(e)[:4] == b'\0XET')
        tex = Texture(archive.read(tex_entry))
        image = Image.new('RGBA', (tex.width, tex.height), (0, 255, 0, 255))
        tex_path = tmp_path / (path.stem + '-texture.arc')
        W.write_archive(data, tex_entry.name, tex_path, expected_sha256=sha(data), texture_image=image)
        tex_arc = Arc(tex_path.read_bytes())
        written = Texture(tex_arc.read(tex_arc.find(*tex_entry.key)))
        assert np.max(np.abs(np.asarray(written.image()).astype(int) - [0, 255, 0, 255])) <= 1
        assert path.read_bytes() == data
        with pytest.raises(FileExistsError):
            W.write_archive(data, model_name, noop, expected_sha256=sha(data), geometry_glb=out.read_bytes())
        bad = tmp_path / 'bad.arc'
        with pytest.raises(ValueError, match='exact owned'):
            W.write_archive(data, model_name, bad, expected_sha256='0'*64, geometry_glb=out.read_bytes())
        assert not bad.exists()
        def nonfinite(doc, blob):
            struct.pack_into('<f', blob, attr_offset(doc, 'POSITION'), float('inf'))
        with pytest.raises(ValueError, match='non-finite'):
            W.write_archive(data, model_name, bad, expected_sha256=sha(data), geometry_glb=edited_glb(out, nonfinite))
        assert not bad.exists()
        with pytest.raises(ValueError, match='dimensions'):
            W.write_archive(data, tex_entry.name, bad, expected_sha256=sha(data), texture_image=Image.new('RGBA', (1, 1)))
        assert not bad.exists()
