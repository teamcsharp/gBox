import numpy as np

from gbox.gta_stories_models import pack_atlases


def test_opaque_and_masked_materials_sharing_a_texture_keep_their_alpha_rules():
    texture = np.full((4, 4, 4), [80, 90, 100, 0], dtype=np.uint8)
    prim = {'pos': np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]]),
            'tris': np.array([[0, 1, 2]]), 'uv': np.full((3, 2), 0.5),
            'tex': texture, 'color': (255, 255, 255, 255)}
    atlases, mappings = pack_atlases([prim, {**prim, 'alpha_mode': 'MASK'}], [(16, 16)])
    alpha = []
    for atlas, uv in mappings:
        x, y = np.floor(uv[0, 0] * 16).astype(int)
        alpha.append(atlases[atlas][y, x, 3])
    assert alpha == [255, 0]
    assert (texture[..., 3] == 0).all()
