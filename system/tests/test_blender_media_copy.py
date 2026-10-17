"""Image/sprite paste uses native Blender objects, and never forwards a client URL/token."""
import base64
import io
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from gbox import blender_copy as bc


@pytest.mark.parametrize('url', [
    'https://evil.example/api/assets/x/file', '//evil.example/api/assets/x/file',
    '/api/assets/x/file?token=secret', '/api/assets/x/file#frag',
    '/api/characters/a/file/../secret', '/api/characters/a/file/%2e%2e/secret',
    '/api/characters/a/file/foo%5csecret', '/api/jobs',
])
def test_asset_source_rejects_hosts_credentials_and_traversal(url):
    with pytest.raises(ValueError):
        bc.asset_source(url)


def test_asset_source_accepts_only_known_files():
    for path in ['/api/assets/asset-1/file', '/api/characters/sonic/file/walk/clip.mp4',
                 '/api/characters/sonic/model', '/api/artifacts/' + 'a' * 64]:
        assert bc.asset_source(path) == path


def test_still_copy_is_rgba_first_frame_and_reused(tmp_path):
    src = tmp_path / 'animation.gif'
    Image.new('RGBA', (8, 4), (255, 0, 0, 255)).save(src, save_all=True,
        append_images=[Image.new('RGBA', (8, 4), (0, 255, 0, 255))], duration=100, loop=0)
    path = bc.prepare_image(src, 'image_plane', tmp_path / 'media')
    assert path == bc.prepare_image(src, 'image_empty', tmp_path / 'media')
    with Image.open(path) as im:
        assert im.format == 'PNG' and im.mode == 'RGBA' and im.size == (8, 4)
        assert im.getpixel((0, 0)) == (255, 0, 0, 255)
    with pytest.raises(ValueError, match='requires an MP4'):
        bc.prepare_image(src, 'movie_plane', tmp_path / 'media')


def test_image_job_dispatches_mode_and_keeps_auth_out_of_source(tmp_path, monkeypatch):
    im = io.BytesIO(); Image.new('RGBA', (8, 4)).save(im, format='PNG')
    calls = []
    monkeypatch.setattr(bc, 'to_blender', lambda path, nodes, mode: calls.append((path, mode)) or {'objects': 1})
    ctx = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path))
    result = bc.blender_copy(bc.CopyIn(image_b64=base64.b64encode(im.getvalue()).decode(), paste_as='image_empty'), ctx)['result']
    assert calls[0][1] == 'image_empty' and calls[0][0].is_file()
    assert result['source'] == '' and result['media_path'].endswith('.png')
    with pytest.raises(ValueError, match='requires image_plane'):
        bc.blender_copy(bc.CopyIn(image_b64='x'), ctx)


def test_library_model_copy_fetches_bundled_gltf_artifact(tmp_path, monkeypatch):
    import httpx
    calls = []
    def post(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'sha256': 'b' * 64})
    monkeypatch.setattr(httpx, 'post', post)
    monkeypatch.setattr(bc, '_fetch', lambda ctx, url, suffix: calls.append(url) or tmp_path / 'model.glb')
    monkeypatch.setattr(bc, 'to_blender', lambda *args: {'objects': 1})
    ctx = SimpleNamespace(server='http://gbox.test', headers={})
    result = bc.blender_copy(bc.CopyIn(asset_url='/api/assets/model/file'), ctx)['result']
    assert calls == ['http://gbox.test/api/assets/model/copy', '/api/artifacts/' + 'b' * 64]
    assert result['source'] == calls[1]


@pytest.mark.skipif(not os.environ.get('GBOX_TEST_BLENDER'), reason='set GBOX_TEST_BLENDER for isolated real Blender verification')
@pytest.mark.parametrize('mode', ['image_plane', 'image_empty', 'movie_plane'])
def test_real_blender_copybuffer_contains_pasteable_media(tmp_path, monkeypatch, mode):
    """No operator clipboard: background Blender writes ONLY inside this test's temp directory."""
    exe = os.environ['GBOX_TEST_BLENDER']
    src = tmp_path / 'sprite.png'
    Image.new('RGBA', (16, 8), (200, 30, 70, 140)).save(src)
    if mode == 'movie_plane':
        movie = tmp_path / 'clip.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(src), '-t', '0.3',
                        '-pix_fmt', 'yuv420p', '-y', str(movie)], check=True, capture_output=True)
        src = movie
    monkeypatch.setattr(bc, 'find_blender', lambda: exe)
    monkeypatch.setattr(bc, 'running_blenders', lambda: [])
    monkeypatch.setattr(bc, 'probe_tempdir', lambda _: {})
    monkeypatch.setattr(bc, 'candidate_dirs', lambda *_: [tmp_path])
    result = bc.to_blender(src, paste_as=mode)
    assert result['objects'] == 1 and result['copybuffers'] == [str(tmp_path / bc.COPYBUFFER)]
    check = tmp_path / 'check.py'
    check.write_text('''import bpy, json, sys
path, mode = sys.argv[sys.argv.index("--")+1:]
with bpy.data.libraries.load(path) as (available, loaded):
    loaded.objects = available.objects
obj, = loaded.objects
assert obj["gbox_paste_as"] == mode
if mode == "image_empty":
    assert obj.type == "EMPTY" and obj.empty_display_type == "IMAGE"
    assert obj.data.packed_file
    assert abs(obj.data.pixels[3] - 140/255) < 0.005
else:
    assert obj.type == "MESH" and len(obj.data.polygons) == 1
    assert abs(obj.dimensions.x / obj.dimensions.y - 2) < 0.001
    tex = next(n for n in obj.data.materials[0].node_tree.nodes if n.type == "TEX_IMAGE")
    assert tex.interpolation == "Closest"
    if mode == "movie_plane":
        from pathlib import Path
        assert tex.image.source == "MOVIE" and Path(tex.image.filepath).is_file()
        assert tex.image_user.use_auto_refresh and tex.image_user.use_cyclic
        assert tex.image_user.frame_duration > 1
    else:
        assert tex.image.packed_file
        assert abs(tex.image.pixels[3] - 140/255) < 0.005
        assert obj.data.uv_layers.active is not None
print("MEDIA_PASTE_VERIFIED")
''', encoding='utf-8')
    verified = subprocess.run([exe, '-b', '--factory-startup', '--python', str(check), '--',
        result['copybuffer'], mode], capture_output=True, text=True, timeout=90)
    assert 'MEDIA_PASTE_VERIFIED' in verified.stdout, verified.stdout + verified.stderr
