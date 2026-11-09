"""Model transforms preserve paired MRL entries and can edit their own emitted archive again."""
import zlib

from gbox import mt_arc, mt_build, mt_model
from tests.test_mtf_author import make_target


def test_transform_updates_exact_mod_entry_and_preserves_wrapped_zlib():
    raw = make_target(2)
    entries = [mt_arc.Entry("same", 0, 0x40000000 | len(payload), 0, 0, zlib.compress(payload, 6))
               for payload in (b"MRL\0paired-resource", raw)]
    source = mt_arc.build(mt_arc.Arc(7, entries))
    original = mt_model.parse_mod(raw)
    output, receipt = mt_build.build_modified_arc(source, "same", 1,
                                                   lambda points: [(x + 1., y, z) for x, y, z in points])
    arc = mt_arc.parse(output)
    assert arc.entries[0].data == entries[0].data
    model = mt_model.parse_mod(zlib.decompress(arc.entries[1].data))
    assert arc.entries[1].data == zlib.compress(model.raw, 6)
    assert arc.entries[1].tag == 0x40000000 | len(model.raw)
    assert model.mesh_bytes(0) == original.mesh_bytes(0)
    assert model.bone_ids(1) == original.bone_ids(1)
    again, _ = mt_build.build_modified_arc(output, "same", 1, lambda points: points)
    assert again == output
    assert receipt["part"] == 1


def test_transform_preserves_legacy_raw_deflate_framing():
    raw = make_target(1)
    compressed = zlib.compress(raw, 6)[2:-4]
    source = mt_arc.build(mt_arc.Arc(7, [mt_arc.Entry("same", 0, len(raw), 0, 0, compressed)]))
    output, _ = mt_build.build_modified_arc(source, "same", 0, lambda points: points)
    assert zlib.decompress(mt_arc.parse(output).entries[0].data, -zlib.MAX_WBITS) == raw
    assert output == source
