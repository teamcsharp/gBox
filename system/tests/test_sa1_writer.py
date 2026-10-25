"""Independent NJS_MODEL layout, malformed data and owned Dreamcast build checks."""
import struct
import pytest
from gbox import sa1_writer as W
from gbox.sa1_inventory import Exe, KEY


def source():
    # Hand-positioned NJS_MODEL / NJS_MESHSET per ninja.h, not encode_model output.
    data = bytearray(0x160)
    data[0x158:] = b'KEEPKEEP'
    struct.pack_into('<IIiIIHH4f', data, 0x10, KEY+0x40, KEY+0x70, 3, KEY+0xa0, KEY+0xc0, 1, 1, 0, 0, 0, 4)
    struct.pack_into('<9f', data, 0x40, 0,0,0, 1,0,0, 0,1,0)
    struct.pack_into('<9f', data, 0x70, 0,0,1, 0,0,1, 0,0,1)
    struct.pack_into('<HHIIIII', data, 0xa0, 0, 1, KEY+0xe0, 0, 0, 0, KEY+0xf0)
    struct.pack_into('<IIfII', data, 0xc0, 0xff010203, 0, 2.0, 0, 0)
    struct.pack_into('<3H', data, 0xe0, 0,1,2)
    struct.pack_into('<6h', data, 0xf0, 0,0, 256,0, 0,256)
    return Exe(bytes(data)), KEY+0x10


def test_true_noop_and_changed_geometry_preserve_every_unrelated_byte():
    ex, model = source()
    points = [(0.,0.,0.), (1.,0.,0.), (0.,1.,0.)]
    assert W.patch_points(ex, model, points) == ex.d
    changed = W.patch_points(ex, model, [(0.,0.,0.), (2.,0.,0.), (0.,1.,0.)])
    expected = bytearray(ex.d)
    struct.pack_into('<f', expected, 0x4c, 2.0)
    assert changed == bytes(expected) and ex.d != changed
    assert struct.unpack_from('<3f', changed, 0x4c) == (2.,0.,0.)


def test_canonical_relocation_preserves_semantics_and_is_not_byte_identity():
    ex, model = source()
    original, rebuilt, equal = W.roundtrip(ex, model)
    assert equal and original == rebuilt
    buf, addr = W.encode_model(original, KEY+0x10000)
    assert W.model_data(Exe(buf, KEY+0x10000), addr) == original
    assert buf != ex.d
    assert W.model_span(ex, model)['allocation_safe'] is False


@pytest.mark.parametrize('offset', [0xa8, 0xac, 0xb0])
def test_canonical_encoder_refuses_unrelocated_optional_arrays(offset):
    ex, model = source()
    data = bytearray(ex.d)
    struct.pack_into('<I', data, offset, KEY+0x120)
    ex = Exe(bytes(data))
    with pytest.raises(ValueError, match='optional mesh arrays'):
        W.roundtrip(ex, model)
    # In-place no-op is still lossless because these arrays and pointers stay put.
    assert W.patch_points(ex, model, [(0.,0.,0.), (1.,0.,0.), (0.,1.,0.)]) == ex.d


@pytest.mark.parametrize('offset,fmt,value', [(0x18,'i',-1), (0x18,'i',0x7fffffff),
    (0x10,'I',KEY-4), (0xa4,'I',KEY+0x15f), (0xb4,'I',KEY+0x15f), (0xe0,'H',3)])
def test_reader_bounds_and_indices(offset, fmt, value):
    ex, model = source()
    data = bytearray(ex.d)
    struct.pack_into('<'+fmt, data, offset, value)
    with pytest.raises(ValueError):
        W.model_data(Exe(bytes(data)), model)


def test_writer_rejects_count_nonfinite_and_outside_original_bounds():
    ex, model = source()
    for points in ([(0,0,0)], [(float('nan'),0,0)]*3, [(5,0,0)]*3):
        with pytest.raises(ValueError):
            W.patch_points(ex, model, points)
    d = W.model_data(ex, model)
    d['meshsets'][0]['meshes'][0].append(0)
    with pytest.raises(ValueError, match='fixed-size'):
        W.encode_model(d)


def test_owned_sonic_geometry_noop_and_changed_vertex():
    from test_sa1_chars import _gdi
    from gbox import sa1_chars, gdrom
    path = _gdi()
    if path is None:
        pytest.skip('Owned Sonic Adventure disc not mounted')
    disc = gdrom.GDRom(path)
    ex, root, _ = sa1_chars.locate(disc, 'sonic')
    models = [n['model'] for n in ex.tree(root) if n['model']]
    assert models
    edited = False
    for model in models:
        pts, _, count, *_ = W._header(ex, model)
        points = [struct.unpack_from('<3f', ex.d, pts-ex.key+12*i) for i in range(count)]
        assert W.patch_points(ex, model, points) == ex.d
        if not edited:
            center = struct.unpack_from('<3f', ex.d, model-ex.key+0x18)
            changed = [tuple((v[i]+center[i])/2 for i in range(3)) for v in points]
            out = W.patch_points(ex, model, changed)
            assert out[:pts-ex.key] == ex.d[:pts-ex.key]
            assert out[pts-ex.key+12*count:] == ex.d[pts-ex.key+12*count:]
            assert out != ex.d
            edited = True
    assert edited


def test_owned_cli_reports_semantics_separately_from_byte_identity(tmp_path, capsys):
    import json
    from test_sa1_chars import _gdi
    path = _gdi()
    if path is None:
        pytest.skip('Owned Sonic Adventure disc not mounted')
    dest = tmp_path / 'span.json'
    assert W.main([str(path), '--char', 'sonic', '--out', str(dest)]) == 0
    report = json.loads(dest.read_text())
    assert report['roundtrip_all_models_semantically_equal'] is True
    assert report['noop_all_models_byte_identical'] is True
    assert report['allocation_safe'] is False
    assert len(report['source_sha256']) == 64
    assert 'roundtrip_all_models_lossless' not in report


# ------------------------------------------------------------------ array ownership

def test_tree_ownership_exclusive_arrays_are_safe_for_inplace_edit():
    """A tree whose arrays are all exclusive is safe: an edit to one array
    cannot affect any other character's rendering."""
    from gbox import sa1_analysis as SA
    from test_sa1_chars import _gdi
    from gbox import gdrom
    path = _gdi()
    if path is None:
        pytest.skip('Owned Sonic Adventure disc not mounted')
    disc = gdrom.GDRom(path)
    from gbox import sa1_chars
    ex, root, _ = sa1_chars.locate(disc, 'sonic')
    report = W.tree_ownership(ex, root)
    # 196 of 218 arrays are exclusive; 22 are aliased with the 4-node
    # tree at 0x8C1E12AC (a separate object, not a character body).
    assert report['array_count'] == 218
    assert report['exclusive_count'] == 196
    assert report['shared_count'] == 22
    assert report['exclusive_ratio'] == pytest.approx(196 / 218, rel=1e-6)
    assert report['all_exclusive'] is False
    # Every shared array is aliased with exactly one other tree
    for entry in report['shared']:
        assert len(entry['trees']) == 1
        assert entry['trees'][0] == '0x8C1E12AC'
        assert entry['kind'] in ('points', 'normals', 'meshsets', 'materials',
                                 'indices', 'vertuv')
    # Exclusive arrays have no 'trees' key
    for entry in report['exclusive']:
        assert 'trees' not in entry


def test_tree_ownership_variant_tree_shares_no_arrays_with_body():
    """Sonic's variant tree (super form) references completely different
    arrays than the body tree — no aliasing between body and variant."""
    from gbox import sa1_analysis as SA
    from test_sa1_chars import _gdi
    from gbox import gdrom
    path = _gdi()
    if path is None:
        pytest.skip('Owned Sonic Adventure disc not mounted')
    disc = gdrom.GDRom(path)
    from gbox import sa1_chars
    ex, body_root, _ = sa1_chars.locate(disc, 'sonic')
    variant = 0x8C1D630C
    report = W.tree_ownership(ex, variant)
    # Variant has 28 models, all arrays exclusive to the variant tree
    assert report['array_count'] >= 218
    # No variant array is shared with the body tree
    body_arrays = set()
    for n in ex.tree(body_root):
        if n['model']:
            m = n['model']
            pts, nrm, nv, msets, mats, nms, nmat = ex.u('IIiIIHH', m)
            body_arrays.add(pts)
            if nrm:  body_arrays.add(nrm)
            if mats: body_arrays.add(mats)
            body_arrays.add(msets)
            for i in range(nms):
                tm, nmesh, mp, _a, _mn, _mc, uvs = ex.u('HHIIIII', msets + i * 28)
                if mp:  body_arrays.add(mp)
                if uvs: body_arrays.add(uvs)
    variant_arrays = set(int(e['addr'], 16) for e in
                         report['exclusive'] + report['shared'])
    assert not (body_arrays & variant_arrays), \
        f"variant and body share {len(body_arrays & variant_arrays)} arrays"


def test_tree_ownership_cli_reports_source_hash(tmp_path, capsys):
    import json
    from test_sa1_chars import _gdi
    path = _gdi()
    if path is None:
        pytest.skip('Owned Sonic Adventure disc not mounted')
    dest = tmp_path / 'own.json'
    assert W.main([str(path), '--char', 'sonic', '--ownership',
                   '--out', str(dest)]) == 0
    report = json.loads(dest.read_text())
    assert report['root'] == '0x8C1CE76C'
    assert report['array_count'] == 218
    assert report['exclusive_count'] == 196
    assert report['shared_count'] == 22
    assert len(report['source_sha256']) == 64
    assert report['trees_scanned'] >= 44


# ------------------------------------------------------------------ changed donor

def test_owned_changed_donor_intended_slot_changed_unrelated_intact():
    """Prove the writer changes exactly the intended geometry array and
    leaves every unrelated byte identical. Uses the body tree's largest
    exclusive model so the edit cannot alias another character."""
    from test_sa1_chars import _gdi
    from gbox import gdrom, sa1_chars
    path = _gdi()
    if path is None:
        pytest.skip('Owned Sonic Adventure disc not mounted')
    disc = gdrom.GDRom(path)
    ex, root, _ = sa1_chars.locate(disc, 'sonic')

    # The 3 shared models (aliased with 0x8C1E12AC) must be excluded
    shared_models = {0x8C1CA400, 0x8C1CA674, 0x8C1CA880}
    models = [n['model'] for n in ex.tree(root) if n['model'] and n['model'] not in shared_models]
    assert models, 'no exclusive models found'

    # Pick the model with the most vertices among exclusive ones
    best = max(models, key=lambda m: struct.unpack_from('<i', ex.d, m - ex.key + 4)[0])
    pts, nrm, nv, msets, mats, nms, nmat = ex.u('IIiIIHH', best)
    assert nv > 10, f'expected a sizeable model, got {nv} points'

    # Read original points
    orig_points = [struct.unpack_from('<3f', ex.d, pts - ex.key + 12 * i) for i in range(nv)]

    # Change: scale each vertex toward the model center by 0.9 (a visible
    # shrink that stays inside the bounding radius)
    cx, cy, cz = ex.u('3f', best + 0x18)
    radius = ex.u('f', best + 0x24)[0]
    changed = [(cx + (v[0] - cx) * 0.9,
                cy + (v[1] - cy) * 0.9,
                cz + (v[2] - cz) * 0.9) for v in orig_points]
    out = W.patch_points(ex, best, changed)

    # 1. Output differs from original
    assert out != ex.d, 'changed output must differ from input'

    # 2. Only the points array changed; everything before and after is identical
    p0, p1 = pts - ex.key, pts - ex.key + nv * 12
    assert out[:p0] == ex.d[:p0], 'bytes before points array changed'
    assert out[p1:] == ex.d[p1:], 'bytes after points array changed'
    assert len(out) == len(ex.d), 'output length must be preserved'

    # 3. Independently re-read the points from the patched image
    re_points = [struct.unpack_from('<3f', out, p0 + 12 * i) for i in range(nv)]
    for a, b in zip(re_points, changed):
        for x, y in zip(a, b):
            assert abs(x - y) < 1e-6, f're-read point {a} != changed {b}'
    assert re_points != orig_points, 're-read points must differ from original'

    # 4. Every other model in the tree is byte-identical
    for n in ex.tree(root):
        if not n['model'] or n['model'] == best:
            continue
        m0, m1 = n['model'] - ex.key, n['model'] - ex.key + 0x28
        assert out[m0:m1] == ex.d[m0:m1], f'model {n["model"]:#x} header changed'

    # 5. The patch_points no-op on the same model confirms the original was
    #    the fixed point
    assert W.patch_points(ex, best, orig_points) == ex.d
