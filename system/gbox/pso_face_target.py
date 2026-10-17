"""A face-editor target from actual draw geometry under a click, never an inferred identity."""
from pathlib import Path
import numpy as np

from .registry import Unsupported


def capture(ad, sid, point, ctx):
    from . import scene_capture as SC, characters as C, pick_tool as P
    x, y = P.picture_xy(point['x'], point['y'], point.get('window_aspect', 4 / 3))
    if not 0 <= x <= 1 or not 0 <= y <= 1:
        raise ValueError('Point inside the game picture, outside its letterboxing')
    folder = Path(ctx.config.runtime) / 'pso-face-picks' / sid / ctx.job_id
    result = None
    try:
        result = SC.capture_session(ad, folder, frames=1, progress=ctx.progress)
        if not result.get('scene_draws'):
            raise Unsupported('This frame contains no captured 3D geometry; no person was selected')
        cut = C.cut_scene(folder / 'scene.glb', x, y)
        if not cut['nodes'] or len(cut['nodes']) > 128:
            raise Unsupported('The selected draw group is empty or too large for a character face editor')
        model = C.subset_glb(folder / 'scene.glb', cut['nodes'], folder / 'person.glb', 'Selected game draw')
        if model.stat().st_size > 32 * 2**20:
            raise Unsupported('The selected mesh exceeds the 32 MiB character inspection limit')
        textures = P.glb_textures(folder / 'scene.glb', cut['nodes'], limit=32)
        if not textures:
            raise Unsupported('No native base-colour textures were captured for the selected draw')
        gl, _ = P._glb_json(folder / 'scene.glb')
        for texture in textures:
            material_names = []
            for node in cut['nodes']:
                nd = gl['nodes'][node]
                for primitive in gl['meshes'][nd['mesh']]['primitives']:
                    index = primitive.get('material')
                    if index is None:
                        continue
                    material = gl['materials'][index]
                    ti = material.get('pbrMetallicRoughness', {}).get('baseColorTexture', {}).get('index')
                    if ti is None:
                        continue
                    image = gl['images'][gl['textures'][ti]['source']]
                    name = image.get('name') or 'image' + str(gl['textures'][ti]['source'])
                    if name == texture['name']:
                        material_names.append(material.get('name') or 'material_' + str(index))
            texture['materials'] = sorted(set(material_names))
        return {'model_path': model, 'textures': textures,
                'evidence': {'kind': 'captured_draw', 'point': [x, y], 'nodes': cut['nodes'],
                             'seed': cut['seed'], 'depth': cut['depth'],
                             'notice': 'Actual selected draw geometry at capture time. This is a static mesh, not a verified actor identity.'}}
    finally:
        if result and result.get('resume_on_leave'):
            ad.resume()


def texture_binding(chunk, textures):
    """Require native decoded texels to match a captured texture, not a visual guess."""
    from . import pso_gc as G
    native = G.gvr_decode(chunk)
    matches = []
    for texture in textures:
        if (texture['w'], texture['h']) != (native.shape[1], native.shape[0]):
            continue
        pixels = np.frombuffer(texture['rgba'], np.uint8).reshape(native.shape)
        # GX and GPU decoders can round interpolated CMPR channels by one unit.
        # Do not admit an unrelated image just because it has a similar average colour.
        error = np.abs(pixels.astype(np.int16) - native.astype(np.int16))
        if int(error.max()) <= 2 and float(error.mean()) <= .75:
            matches.append({'texture': texture['name'], 'materials': texture.get('materials', []),
                            'max_channel_error': int(error.max()), 'mean_channel_error': float(error.mean())})
    return matches
