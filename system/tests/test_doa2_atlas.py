"""RGBA/UV sampling and geometry-preservation tests independent of the packer."""
import unittest

import numpy as np

from gbox.doa2_atlas import AtlasCapacityError, atlas_primitives, native_capacities


def primitive(texture=None, uv=None, color=(255, 255, 255, 255), wrap=(10497, 10497)):
    return {'pos': np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0]]),
            'nrm': np.array([[0., 0, 1]] * 3),
            'uv': np.asarray(uv if uv is not None else [[0, 0], [1, 0], [0, 1]], float),
            'tris': np.array([[0, 1, 2]], np.int64),
            'J': np.array([[2, 0, 0, 0], [3, 0, 0, 0], [4, 0, 0, 0]], np.int64),
            'W': np.array([[1., 0, 0, 0]] * 3), 'tex': texture, 'color': color,
            'wrap': wrap, 'name': 'preserved mesh name', 'prop': True}


def capacity(size=32, classes=('opaque', 'binary', 'graded'), index=0):
    return {'index': index, 'width': size, 'height': size, 'alpha_classes': classes}


def pattern(size=4, alpha=255):
    result = np.empty((size, size, 4), np.uint8)
    for y in range(size):
        for x in range(size):
            result[y, x] = (x * 255 // max(1, size - 1), y * 255 // max(1, size - 1),
                            (x + y) * 127 // max(1, size - 1), alpha)
    return result


def sample(image, uv, modes=(10497, 10497)):
    """Independent normalized bilinear sampler at pixel centers."""
    image = np.asarray(image, float)
    height, width = image.shape[:2]
    q = np.asarray(uv, float) * (width, height) - .5
    base = np.floor(q).astype(int)
    frac = q - base

    def index(v, n, mode):
        if mode == 10497:
            return v % n
        if mode == 33071:
            return min(n - 1, max(0, v))
        v %= 2 * n
        return v if v < n else 2 * n - 1 - v

    result = np.zeros(4)
    for y in (0, 1):
        for x in (0, 1):
            weight = (frac[0] if x else 1 - frac[0]) * (frac[1] if y else 1 - frac[1])
            result += weight * image[index(base[1] + y, height, modes[1]),
                                     index(base[0] + x, width, modes[0])]
    return result


class AtlasTests(unittest.TestCase):
    def test_rgba_color_factor_is_baked_exactly_once(self):
        texture = pattern(alpha=128)
        source = primitive(texture, uv=[[.125, .125], [.875, .125], [.125, .875]],
                           color=(128, 255, 64, 128))
        result = atlas_primitives([source], [capacity()])
        output = result['primitives'][0]
        baked = np.rint(texture.astype(float) * np.array(source['color']) / 255).astype(np.uint8)
        for old_uv, new_uv in zip(source['uv'], output['uv']):
            np.testing.assert_allclose(sample(baked, old_uv), sample(output['tex'], new_uv, output['wrap']), atol=1e-10)
        self.assertEqual(output['color'], (255, 255, 255, 255))
        self.assertEqual(result['report']['materials'][0]['alpha'], 'graded')

    def test_repeat_crossings_are_continuous_without_uv_clamp(self):
        source = primitive(pattern(), uv=[[-.4, -.8], [1.2, -.2], [.3, 1.4]])
        output = atlas_primitives([source], [capacity()])['primitives'][0]
        for a in np.linspace(0, 1, 9):
            for b in np.linspace(0, 1 - a, 7):
                weights = np.array([a, b, 1 - a - b])
                np.testing.assert_allclose(sample(source['tex'], weights @ source['uv']),
                                           sample(output['tex'], weights @ output['uv'], output['wrap']), atol=1e-10)
        self.assertEqual(output['wrap'], (33071, 33071))

    def test_clamp_and_mirror_sampling_are_baked_with_alpha_intact(self):
        texture = pattern(alpha=96)
        for modes in [(33071, 33071), (33648, 10497), (10497, 33648), (33648, 33071)]:
            with self.subTest(modes=modes):
                source = primitive(texture, uv=[[-.8, -.5], [1.4, .4], [.1, 1.2]], wrap=modes)
                output = atlas_primitives([source], [capacity()])['primitives'][0]
                for weights in ([1, 0, 0], [0, 1, 0], [0, 0, 1], [.2, .3, .5]):
                    np.testing.assert_allclose(sample(texture, np.asarray(weights) @ source['uv'], modes),
                                               sample(output['tex'], np.asarray(weights) @ output['uv'], output['wrap']), atol=1e-10)

    def test_source_geometry_skin_and_triangles_are_unchanged(self):
        source = primitive(pattern())
        snapshots = {k: source[k].copy() for k in ('pos', 'nrm', 'uv', 'tris', 'J', 'W', 'tex')}
        result = atlas_primitives([source], [capacity()])
        output = result['primitives'][0]
        for key in ('pos', 'nrm', 'tris', 'J', 'W'):
            self.assertIs(output[key], source[key])
            np.testing.assert_array_equal(source[key], snapshots[key])
        np.testing.assert_array_equal(source['uv'], snapshots['uv'])
        np.testing.assert_array_equal(source['tex'], snapshots['tex'])
        self.assertEqual(output['name'], source['name'])
        self.assertTrue(output['prop'])
        self.assertEqual(result['report']['source_triangles'], result['report']['output_triangles'])

    def test_multiple_images_share_page_without_color_or_alpha_bleed(self):
        red, green = pattern(), pattern()
        red[:] = (255, 0, 0, 255)
        green[:] = (0, 255, 0, 255)
        result = atlas_primitives([primitive(red), primitive(green)], [capacity()])
        self.assertEqual(len(result['pages']), 1)
        for output, color in zip(result['primitives'], [(255, 0, 0, 255), (0, 255, 0, 255)]):
            for uv in output['uv']:
                np.testing.assert_allclose(sample(output['tex'], uv, output['wrap']), color, atol=1e-10)

    def test_alpha_classes_stay_on_separate_compatible_pages(self):
        binary = pattern()
        binary[:2, :, 3] = 0
        source = [primitive(pattern()), primitive(binary), primitive(pattern(alpha=100))]
        capacities = [capacity(classes=('opaque',), index=0), capacity(classes=('binary',), index=1),
                      capacity(classes=('graded',), index=2)]
        result = atlas_primitives(source, capacities)
        self.assertEqual(len(result['pages']), 3)
        self.assertEqual({p['alpha'] for p in result['report']['pages']}, {'opaque', 'binary', 'graded'})
        for output, original in zip(result['primitives'], source):
            for a, b in zip(output['uv'], original['uv']):
                np.testing.assert_allclose(sample(output['tex'], a, output['wrap']), sample(original['tex'], b), atol=1e-10)

    def test_alpha_is_never_silently_assigned_to_rgb_capacity(self):
        with self.assertRaises(AtlasCapacityError):
            atlas_primitives([primitive(pattern(alpha=128))], [capacity(classes=('opaque',))], allow_downscale=True)

    def test_identical_baked_materials_are_deduplicated(self):
        source = [primitive(pattern()), primitive(pattern().copy())]
        result = atlas_primitives(source, [capacity()])
        self.assertEqual(result['report']['source_materials'], 1)
        self.assertEqual(result['report']['materials'][0]['primitives'], [0, 1])
        self.assertIs(result['primitives'][0]['tex'], result['primitives'][1]['tex'])

    def test_flat_material_color_including_alpha_is_preserved(self):
        source = primitive(None, color=(24, 48, 96, 64))
        output = atlas_primitives([source], [capacity()])['primitives'][0]
        for uv in output['uv']:
            np.testing.assert_allclose(sample(output['tex'], uv, output['wrap']), source['color'], atol=1e-10)

    def test_tiny_uv_excursions_cost_pixels_instead_of_whole_tiles(self):
        source = primitive(pattern(16), uv=[[-1e-6, -1e-6], [1.000001, 0], [0, 1.000001]])
        result = atlas_primitives([source], [capacity(32)])
        record = result['report']['materials'][0]
        self.assertEqual(record['rect'][2:], [18, 18])
        self.assertFalse(record['resized'])
        for old_uv, new_uv in zip(source['uv'], result['primitives'][0]['uv']):
            np.testing.assert_allclose(sample(source['tex'], old_uv),
                                       sample(result['pages'][0], new_uv, (33071, 33071)), atol=1e-10)

    def test_full_page_preserves_original_uvs_and_sampler(self):
        for modes in [(10497, 10497), (33071, 10497), (33648, 33071)]:
            source = primitive(pattern(8), uv=[[-100, -.7], [100, .3], [0, 10]], wrap=modes)
            result = atlas_primitives([source], [capacity(8)])
            output = result['primitives'][0]
            np.testing.assert_array_equal(output['uv'], source['uv'])
            np.testing.assert_array_equal(np.asarray(output['tex']), source['tex'])
            self.assertEqual(output['wrap'], modes)
            self.assertEqual(result['report']['materials'][0]['mode'], 'native_sampler')

    def test_repeat_limit_does_not_silently_clamp_unsupported_domain(self):
        source = primitive(pattern(8), uv=[[0, 0], [100, 0], [0, 1]])
        with self.assertRaises(AtlasCapacityError):
            atlas_primitives([source], [capacity(32)], max_repeat=16)

    def test_resolution_is_preserved_when_it_fits(self):
        result = atlas_primitives([primitive(pattern(16))], [capacity(32)], allow_downscale=True)
        self.assertEqual(result['report']['resized_materials'], 0)
        self.assertEqual(result['report']['scale_attempt'], 1)

    def test_downsampling_requires_opt_in_and_reports_dimensions(self):
        source = [primitive(pattern(16)), primitive(np.flip(pattern(16), axis=1).copy())]
        with self.assertRaises(AtlasCapacityError):
            atlas_primitives(source, [capacity(32)])
        result = atlas_primitives(source, [capacity(32)], allow_downscale=True)
        self.assertEqual(result['report']['resized_materials'], 2)
        self.assertTrue(all(r['resized'] and tuple(r['source_size']) == (16, 16)
                            and max(r['tile_size']) < 16 for r in result['report']['materials']))
        self.assertEqual(result['report']['output_triangles'], 2)

    def test_binary_downsampling_preserves_binary_alpha_class(self):
        a = pattern(16)
        a[::2, :, 3] = 0
        b = np.flip(a, axis=1).copy()
        result = atlas_primitives([primitive(a), primitive(b)], [capacity(32, ('binary',))], allow_downscale=True)
        self.assertTrue(set(np.unique(np.asarray(result['pages'][0])[..., 3])) <= {0, 255})

    def test_bucket_resizing_preserves_large_detail_when_small_tiles_need_merging(self):
        source = [primitive(pattern(128))]
        source += [primitive(np.roll(pattern(16), i, axis=1)) for i in range(4)]
        result = atlas_primitives(source, [capacity(128, index=0), capacity(32, index=1)], allow_downscale=True)
        records = result['report']['materials']
        self.assertEqual(records[0]['tile_size'], (128, 128))
        self.assertFalse(records[0]['resized'])
        self.assertEqual(result['report']['resized_materials'], 4)
        self.assertEqual(result['report']['resize_scope'], 'small_64')

    def test_equal_images_with_different_samplers_keep_both_semantics(self):
        source = [primitive(pattern(), uv=[[-.5, 0], [1.5, 0], [0, 1]], wrap=(10497, 10497)),
                  primitive(pattern(), uv=[[-.5, 0], [1.5, 0], [0, 1]], wrap=(33071, 10497))]
        result = atlas_primitives(source, [capacity()])
        self.assertEqual(result['report']['source_materials'], 2)
        for original, output in zip(source, result['primitives']):
            for old_uv, new_uv in zip(original['uv'], output['uv']):
                np.testing.assert_allclose(sample(original['tex'], old_uv, original['wrap']),
                                           sample(output['tex'], new_uv, output['wrap']), atol=1e-10)

    def test_unused_vertices_do_not_inflate_the_sampled_uv_domain(self):
        source = primitive(pattern())
        for key in ('pos', 'nrm', 'J', 'W'):
            source[key] = np.concatenate((source[key], source[key][:1]))
        source['uv'] = np.concatenate((source['uv'], [[1000, 1000]]))
        result = atlas_primitives([source], [capacity()])
        self.assertEqual(result['report']['materials'][0]['repeat_domain'], [[0, 0], [1, 1]])
        self.assertEqual(len(result['primitives'][0]['pos']), 4)

    def test_invalid_geometry_and_materials_fail(self):
        cases = []
        source = primitive(pattern()); source['uv'][0, 0] = np.nan; cases.append(source)
        source = primitive(pattern()); source['tris'][0, 0] = 99; cases.append(source)
        source = primitive(pattern()); source['color'] = (255, 255, 255, -1); cases.append(source)
        source = primitive(pattern()); source['wrap'] = ('mystery', 'repeat'); cases.append(source)
        source = primitive(pattern()); source['J'] = source['J'][:2]; cases.append(source)
        for i, source in enumerate(cases):
            with self.subTest(case=i), self.assertRaises(ValueError):
                atlas_primitives([source], [capacity()])

    def test_invalid_capacities_and_options_fail(self):
        for caps, kwargs in [([capacity(30)], {}), ([capacity(), capacity()], {}),
                             ([capacity(classes=('rgb-only',))], {}), ([capacity()], {'gutter': 0}),
                             ([capacity()], {'max_repeat': 0})]:
            with self.subTest(capacity=caps, kwargs=kwargs), self.assertRaises(ValueError):
                atlas_primitives([primitive(pattern())], caps, **kwargs)

    def test_native_capacity_conversion_is_explicit_and_nonmutating(self):
        import struct
        header = bytearray(80)
        struct.pack_into('<4I', header, 0, 0x80000008, 1 << 25, 1 << 19, 1 << 27)
        struct.pack_into('<2i', header, 32, 0, 1)
        archive = {'textures': [(8 | 8 << 16, 1 | 1 << 8, 0)],
                   'models': [{'id': 0, 'meshes': [{'header': bytes(header)}]}]}
        original = list(archive['textures'])
        plain = native_capacities(archive, bytes(128))
        self.assertEqual(plain[0]['alpha_classes'], ['opaque'])
        converted = native_capacities(archive, bytes(128), synthesize_headers=True, retype_argb4444=True)
        self.assertEqual(converted[0]['alpha_classes'], ['opaque', 'binary', 'graded'])
        self.assertEqual(archive['textures'], original)
        self.assertEqual(native_capacities(archive, bytes(128), excluded_slots=[0]), [])
        with self.assertRaises(ValueError):
            native_capacities(archive, bytes(128), retype_argb4444=True)


if __name__ == '__main__':
    unittest.main()
