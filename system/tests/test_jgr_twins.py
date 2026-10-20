"""Portable multi-group writer proofs; no game assets, Blender or emulator required."""
import struct
from types import SimpleNamespace

import pytest

from gbox import jgr, ninja


def _nodes(base, parents=None):
    parents = jgr.BODY_PARENTS if parents is None else parents
    nodes = [{"off": base + i * 52, "flags": 0, "model": 1,
              "trs": struct.pack("<3f3i3f", 0, 0, 0, 0, 0, 0, 1, 1, 1),
              "parent": None if p < 0 else p, "child": None, "sibling": None}
             for i, p in enumerate(parents)]
    for parent in range(len(nodes)):
        children = [i for i, n in enumerate(nodes) if n["parent"] == parent]
        if children:
            nodes[parent]["child"] = children[0]
        for first, second in zip(children, children[1:]):
            nodes[first]["sibling"] = second
    return nodes


def _world_points(tree):
    pts = []
    for tris in tree.tris.values():
        for tri in tris:
            for corner in tri:
                v = corner[2] if len(corner) > 2 and corner[2] else tree.vbuf.get(corner[0])
                pts.append(tuple(round(float(x), 4) for x in v["pos"]))
    return sorted(pts)


def _classification(monkeypatch):
    primary = _nodes(100)
    other = _nodes(2000)
    small = _nodes(4000, [-1, 0])
    trees = {100: primary, 2000: other, 4000: small, 5000: _nodes(5000)}
    monkeypatch.setattr(ninja, "tree_nodes", lambda data, root: trees[root])
    monkeypatch.setattr(jgr, "play_model_roots", lambda *args: list(trees))
    monkeypatch.setattr(jgr, "play_model", lambda data, root:
                        SimpleNamespace(tris={-1 if root == 5000 else 0: [(0, 1, 2)]}))
    return trees


def test_twins_require_a_textured_full_graph(monkeypatch):
    _classification(monkeypatch)
    assert list(jgr.body_twins(b"", b"", 0, 100)) == [2000]


@pytest.mark.parametrize("changed", ["rotation", "scale", "evaluation"])
def test_turned_or_scaled_twin_is_re_expressed_not_refused(monkeypatch, changed):
    # The spray-can bodies of Bis / Combo / the Love Shockers' leader turn or scale hand node 15 and differ in its
    # UNIT_ANG / UNIT_SCL eval bits; Gum's low-detail body rescales limbs. twin_transforms carries those.
    trees = _classification(monkeypatch)
    if changed == "rotation":
        trees[2000][3]["trs"] = struct.pack("<3f3i3f", 0, 0, 0, 0x1000, 0, 0, 1, 1, 1)
    elif changed == "scale":
        trees[2000][3]["trs"] = struct.pack("<3f3i3f", 0, 0, 0, 0, 0, 0, 2, 1, 1)
    else:
        trees[2000][3]["flags"] = 2
        trees[100][3]["trs"] = struct.pack("<3f3i3f", 0, 0, 0, 0x1000, 0, 0, 1, 1, 1)
    assert list(jgr.body_twins(b"", b"", 0, 100)) == [2000]
    moved = jgr.twin_transforms(trees[100], trees[2000])
    assert set(moved) == {3, 4}                         # the node and its child below it
    assert all(jgr._translation(m) is None for m in moved.values())


def test_twin_with_another_traversal_or_a_degenerate_node_is_refused(monkeypatch):
    trees = _classification(monkeypatch)
    trees[2000][3]["flags"] = 0x10                       # NJD_EVAL_BREAK: the twin stops traversing here
    with pytest.raises(ValueError, match="different native bind"):
        jgr.body_twins(b"", b"", 0, 100)
    trees[2000][3]["flags"] = 0
    trees[2000][3]["trs"] = struct.pack("<3f3i3f", 0, 0, 0, 0, 0, 0, 0, 1, 1)
    with pytest.raises(ValueError, match="degenerate"):
        jgr.twin_transforms(trees[100], trees[2000])


@pytest.mark.parametrize("node, moved", [(15, {15}), (13, {13, 14, 15})])
def test_translation_only_twin_gets_bind_preserving_offsets(monkeypatch, node, moved):
    # Beat's gameplay bodies (archive 04: 0x8da4, 0x2039c) differ from the max-triangle body only in hand
    # node 15's local position (#1151); a moved parent moves its whole chain.
    trees = _classification(monkeypatch)
    trees[2000][node]["trs"] = struct.pack("<3f3i3f", 0.25, -0.5, 0, 0, 0, 0, 1, 1, 1)
    assert list(jgr.body_twins(b"", b"", 0, 100)) == [2000]
    offsets = jgr.twin_offsets(trees[100], trees[2000])
    assert set(offsets) == moved
    for d in offsets.values():
        assert d == pytest.approx((-0.25, 0.5, 0.0))


def test_visibility_flag_can_differ_without_changing_bind_space(monkeypatch):
    trees = _classification(monkeypatch)
    trees[2000][3]["flags"] = 8
    assert list(jgr.body_twins(b"", b"", 0, 100)) == [2000]


def test_invalid_primary_graph_is_rejected(monkeypatch):
    trees = _classification(monkeypatch)
    trees[100][1]["parent"] = None
    with pytest.raises(ValueError, match="Primary JGR body"):
        jgr.body_twins(b"", b"", 0, 100)


def _binary_groups():
    out = bytearray(256)
    roots = []
    models = {}
    for i in range(20):
        verts = [[i, 0, 0], [i + 0.5, 0, 0], [i, 0.5, 0]]
        triangles = [((0, 1, 2), ((0, 0), (1, 0), (0, 1)))]
        models[i] = ninja.cnk_model_lists(verts, [[0, 0, 1]] * 3, triangles, 0, b"", base=i * 3)
    for _ in range(3):
        base = len(out)
        blob, root, _ = ninja.write_tree(_nodes(base), models, base)
        roots.append(root)
        out += blob
    # An independent accessory shares an original model, so that model and lists
    # must survive even though all body groups receive new model pointers.
    base = len(out)
    blob, root, _ = ninja.write_tree(_nodes(base, [-1]), {0: models[0]}, base)
    out += blob
    roots.append(root)
    shared_model = ninja.tree_nodes(out, roots[0])[0]["model"]
    struct.pack_into("<I", out, root + 4, shared_model)
    return bytes(out), roots


@pytest.mark.parametrize("variant", ["equivalent", "translated", "turned", "divergent", "shared_object"])
def test_writer_changes_all_equivalent_groups_and_preserves_shared_storage(monkeypatch, tmp_path, variant):
    from PIL import Image
    from gbox import gdrom, ninja_swap
    original, roots = _binary_groups()
    if variant != "equivalent":
        changed = bytearray(original)
        if variant == "translated":     # like archive 04's gameplay bodies: only hand node 15 sits elsewhere
            struct.pack_into("<f", changed, ninja.tree_nodes(original, roots[1])[15]["off"] + 8, 0.5)
        elif variant == "turned":       # the whole group turned: every node is re-expressed in its own frame
            struct.pack_into("<i", changed, roots[1] + 20, 0x2000)
        elif variant == "divergent":    # NJD_EVAL_BREAK on one node: the group traverses differently
            struct.pack_into("<I", changed, ninja.tree_nodes(original, roots[1])[3]["off"], 0x10)
        else:
            # The accessory traverses the selected body's live object nodes.
            # Protecting model storage alone cannot prevent its pointer rewrite.
            struct.pack_into("<I", changed, roots[-1] + 44, roots[0])
        original = bytes(changed)
    source = b"synthetic owned AFS fixture"
    monkeypatch.setattr(gdrom, "GDRom", lambda path: SimpleNamespace(read=lambda name: source))
    monkeypatch.setattr(jgr, "character_pair", lambda *args: (0, 1))
    monkeypatch.setattr(jgr, "entry_room", lambda *args: len(original) + 4096)
    monkeypatch.setattr(jgr, "entry_size", lambda *args: 16)
    monkeypatch.setattr(jgr, "play_bytes", lambda *args: original)
    monkeypatch.setattr(jgr, "body_root", lambda *args: roots[0])
    monkeypatch.setattr(jgr, "play_model_roots", lambda *args: roots)
    monkeypatch.setattr(jgr, "native_id_for_archive", lambda *args: 0)
    monkeypatch.setattr(jgr, "_material", lambda *args: (b"", 0x34, 0x4000, 0x12))
    monkeypatch.setattr(jgr, "ptex_textures", lambda *args: [{"bytes": b"x" * 16, "offset": 0}])
    monkeypatch.setattr(jgr, "group_texture_ids", lambda data, play, ptex, roots: (0, {r: 0 for r in roots}))
    monkeypatch.setattr(ninja, "pvr_like", lambda old, image: old)
    monkeypatch.setattr(ninja_swap, "target_from_nj", lambda *args: object())
    monkeypatch.setattr(jgr, "replace_entries", lambda old, entries: entries)

    fit_calls = []
    def fit(model, roles, target, work, name, budgets, blender, encode, size, scale, progress, protect=None):
        fit_calls.append(1)
        triangle = [((0, 1, 2), ((0, 0), (1, 0), (0, 1)))]
        geo = {i: ([[0, 0, 0], [0.25, 0, 0], [0, 0.25, 0]], [[0, 0, 1]] * 3, triangle)
               for i in range(1, 20)}
        return {"data": encode(geo), "atlas": Image.new("RGB", (8, 8)),
                "rigged": "fixture.gltf", "report": {"triangles": 19}}
    monkeypatch.setattr(ninja_swap, "fit", fit)
    if variant not in ("equivalent", "translated", "turned"):
        message = "different native bind" if variant == "divergent" else "shares an object node"
        with pytest.raises(ValueError, match=message):
            jgr.build_swap("fixture.gdi", tmp_path / "fixture.glb", {"hip": "x"}, tmp_path, "Donor", 4)
        assert not fit_calls
        return
    result = jgr.build_swap("fixture.gdi", tmp_path / "fixture.glb", {"hip": "x"}, tmp_path, "Donor", 4)
    rewritten = result["files"][jgr.PLAYER_AFS][0]
    for root in roots[:-1]:
        tree = jgr.play_model(rewritten, root)
        assert sum(len(tris) for tris in tree.tris.values()) == 19
        assert set(tree.tris) == {jgr.ATLAS_TEXTURE}
        old, new = ninja.tree_nodes(original, root), ninja.tree_nodes(rewritten, root)
        assert [n["trs"] for n in new] == [n["trs"] for n in old]
        assert [n["parent"] for n in new] == [n["parent"] for n in old]
    for start, end in ninja.tree_ranges(original, roots[-1]):
        assert rewritten[start:end] == original[start:end]
    assert result["report"]["body_groups"] == [hex(root) for root in roots[:-1]]
    assert result["report"]["runtime_verified"] is False
    points = [_world_points(jgr.play_model(rewritten, root)) for root in roots[:-1]]
    assert points[1] == points[0] == points[2]      # every group draws the donor in the same bind pose
    models = [[n["model"] for n in ninja.tree_nodes(rewritten, root)] for root in roots[:-1]]
    assert len({m for group in models for m in group}) == 60
    assert _native_relocation_errors(rewritten, roots) == []
    lists = [[struct.unpack_from('<II', rewritten, m) for m in group] for group in models]
    if variant == "translated":
        assert lists[1][15] != lists[0][15] and lists[1][:15] == lists[0][:15]
        assert result["report"]["bind_offsets"] == {hex(roots[1]): {"15": [-0.5, 0.0, 0.0]}}
    elif variant == "turned":
        assert all(a != b for a, b in zip(lists[0][1:], lists[1][1:])) and lists[2] == lists[0]
        assert set(result["report"]["bind_transforms"][hex(roots[1])]) == {str(j) for j in range(20)}
    else:
        assert lists[1] == lists[0] and result["report"]["bind_offsets"] == {}


def _patched_writer(monkeypatch, original, roots, geo):
    from PIL import Image
    from gbox import gdrom, ninja_swap
    monkeypatch.setattr(gdrom, "GDRom", lambda path: SimpleNamespace(read=lambda name: b"synthetic owned AFS"))
    monkeypatch.setattr(jgr, "character_pair", lambda *args: (0, 1))
    monkeypatch.setattr(jgr, "entry_room", lambda *args: len(original) + 4096)
    monkeypatch.setattr(jgr, "entry_size", lambda *args: 16)
    monkeypatch.setattr(jgr, "play_bytes", lambda *args: original)
    monkeypatch.setattr(jgr, "body_root", lambda *args: roots[0])
    monkeypatch.setattr(jgr, "play_model_roots", lambda *args: roots)
    monkeypatch.setattr(jgr, "native_id_for_archive", lambda *args: 0)
    monkeypatch.setattr(jgr, "_material", lambda *args: (b"", 0x34, 0x4000, 0x12))
    monkeypatch.setattr(jgr, "ptex_textures", lambda *args: [{"bytes": b"x" * 16, "offset": 0}])
    monkeypatch.setattr(jgr, "group_texture_ids", lambda data, play, ptex, roots: (0, {r: 0 for r in roots}))
    monkeypatch.setattr(ninja, "pvr_like", lambda old, image: old)
    monkeypatch.setattr(ninja_swap, "target_from_nj", lambda *args: object())
    monkeypatch.setattr(jgr, "replace_entries", lambda old, entries: entries)
    monkeypatch.setattr(ninja_swap, "fit", lambda model, roles, target, work, name, budgets, blender, encode, size,
                        scale, progress, protect=None: {"data": encode(geo), "atlas": Image.new("RGB", (8, 8)),
                                          "rigged": "fixture.gltf", "report": {}})


def _vertex_lists(buf, root):
    out = []
    for nd in ninja.tree_nodes(buf, root):
        if nd["model"]:
            vl = struct.unpack_from("<I", buf, nd["model"])[0]
            heads, o = [], vl
            while vl and buf[o] != 0xFF:
                head, base, count = struct.unpack_from("<IHH", buf, o)
                heads.append((head & 0xFF, base, count))
                o += 4 + (head >> 16) * 4
            out.append(heads)
    return out


def _native_relocation_errors(data, roots):
    """Transcribe US FUN_8c0c7278: pointers are changed in place on EVERY visit.

    Unlike our offline Ninja reader, the game does not deduplicate model records.
    List contents are not changed by this loader. Use an illustrative RAM base.
    """
    buf, base, errors = bytearray(data), 0x8C200000, []
    def read(off):
        return struct.unpack_from('<I', buf, off)[0]
    def relocate(off):
        value = (read(off) + base) & 0xFFFFFFFF
        struct.pack_into('<I', buf, off, value)
        return value - base
    def walk(node):
        while node:
            if read(node + 4):
                model = relocate(node + 4)
                for field in (model, model + 4):
                    if read(field):
                        target = relocate(field)
                        if not 0 <= target < len(buf):
                            errors.append((node, model, target))
            if read(node + 44):
                walk(relocate(node + 44))
            node = relocate(node + 48) if read(node + 48) else 0
    for root in roots:
        walk(root)
    return errors


def test_written_models_survive_native_in_place_relocation(monkeypatch, tmp_path):
    original, roots = _binary_groups()
    triangle = [((0, 1, 2), ((0, 0), (1, 0), (0, 1)))]
    geo = {i: ([[0, 0, 0], [0.25, 0, 0], [0, 0.25, 0]], [[0, 0, 1]] * 3, triangle)
           for i in range(1, 20)}
    _patched_writer(monkeypatch, original, roots, geo)
    result = jgr.build_swap('fixture.gdi', tmp_path / 'fixture.glb', {'hip': 'x'}, tmp_path, 'Donor', 4)
    rewritten = result['files'][jgr.PLAYER_AFS][0]
    assert _native_relocation_errors(rewritten, roots) == []


def test_new_vertices_stay_inside_every_groups_native_cache_span(monkeypatch, tmp_path):
    """#1156: on Beat, new slots 368-529 (stock body 0-354, low LOD 0-178) drew NO body in gameplay
    (#1153 live) although the cutscene renderer drew the same models. Every rewritten group must find
    each slot inside its own native span, and no original vertex chunk may run ahead of the new one."""
    original, roots = _binary_groups()
    span = min(max(jgr.play_model(original, r).vbuf) + 1 for r in roots[:-1])
    assert span == 60
    triangle = [((0, 1, 2), ((0, 0), (1, 0), (0, 1)))]
    geo = {i: ([[0, 0, 0], [0.25, 0, 0], [0, 0.25, 0]], [[0, 0, 1]] * 3, triangle) for i in range(1, 20)}
    _patched_writer(monkeypatch, original, roots, geo)
    result = jgr.build_swap("fixture.gdi", tmp_path / "fixture.glb", {"hip": "x"}, tmp_path, "Donor", 4)
    rewritten = result["files"][jgr.PLAYER_AFS][0]
    assert result["report"]["vertex_slots"] == span
    for root in roots[:-1]:
        tree = jgr.play_model(rewritten, root)
        assert sum(len(t) for t in tree.tris.values()) == 19
        assert max(tree.vbuf) < span
        lists = [heads for heads in _vertex_lists(rewritten, root) if heads]
        assert len(lists) == 19 and all(len(heads) == 1 and heads[0][0] == 0x29 for heads in lists)
        # the native per-node base is kept where it fits (node i natively starts at slot 3 * i)
        assert sorted(h[0][1] for h in lists) == [3 * i for i in range(1, 20)]


def test_node_larger_than_the_native_span_is_refused_for_a_smaller_budget(monkeypatch, tmp_path):
    original, roots = _binary_groups()
    big = [[k * 0.01, 0, 0] for k in range(61)]
    triangle = [((0, 1, 2), ((0, 0), (1, 0), (0, 1)))]
    _patched_writer(monkeypatch, original, roots, {1: (big, [[0, 0, 1]] * 61, triangle)})
    with pytest.raises(ValueError, match="61 vertices > 60 native vertex cache slots"):
        jgr.build_swap("fixture.gdi", tmp_path / "fixture.glb", {"hip": "x"}, tmp_path, "Donor", 4)


def test_span_clamped_writer_never_reuses_a_pre_1156_cached_build():
    # v3 builds (slots past the native span) drew no body in gameplay; `use` must not serve them again.
    assert jgr.CACHE_VERSION >= 7  # earlier versions share model records and corrupt pointers during native loading


def test_decimation_spares_the_head_and_arm_nodes():
    """#1889: a 1,384-triangle donor ends near 400 in JGR's hard body budget; head and arms collapse last."""
    from gbox import jgr
    role_node = {r: int(v[4:]) for r, v in jgr.BODY_ROLES.items()}
    for role in ("head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand"):
        assert role_node[role] in jgr.PROTECT_NODES
    for role in ("hip", "chest", "l_thigh", "r_shin", "l_foot"):
        assert role_node[role] not in jgr.PROTECT_NODES
