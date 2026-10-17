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
