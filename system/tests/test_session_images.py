from io import BytesIO

from PIL import Image
import pytest

from gbox.session_images import PNG_SIGNATURE, SessionImageError, as_png


def encoded(image, fmt):
    result = BytesIO()
    image.save(result, format=fmt)
    return result.getvalue()


@pytest.mark.parametrize('mode', ['RGB', 'L', 'CMYK'])
def test_jpeg_capture_becomes_a_real_png_with_identical_decoded_pixels(mode):
    image = Image.new('RGB', (12, 9), (31, 133, 220)).convert(mode)
    jpeg = encoded(image, 'JPEG')
    with Image.open(BytesIO(jpeg)) as source:
        source.load()
        expected = source.convert('RGB') if mode == 'CMYK' else source.copy()
    png = as_png(jpeg)
    assert png.startswith(PNG_SIGNATURE) and png != jpeg
    with Image.open(BytesIO(png)) as result:
        result.load()
        assert result.format == 'PNG' and result.size == expected.size
        assert result.mode == expected.mode and result.tobytes() == expected.tobytes()


def test_valid_png_is_unchanged_including_alpha():
    image = Image.new('RGBA', (5, 4), (12, 34, 56, 70))
    png = encoded(image, 'PNG')
    assert as_png(png) == png
    with Image.open(BytesIO(as_png(png))) as result:
        assert result.getpixel((0, 0)) == (12, 34, 56, 70)


@pytest.mark.parametrize('data', [b'', b'{}', b'\x89PNG\r\n\x1a\nfixture-frame',
                                 b'\xff\xd8\xffbroken', None, 'image/png'])
def test_bad_or_signature_only_frames_fail_with_a_controlled_error(data):
    with pytest.raises(SessionImageError):
        as_png(data)


@pytest.mark.parametrize('fmt', ['PNG', 'JPEG'])
def test_truncated_real_frame_cannot_be_attached(fmt):
    frame = encoded(Image.new('RGB', (20, 20), 'orange'), fmt)
    with pytest.raises(SessionImageError):
        as_png(frame[:len(frame) // 2])


def test_other_image_formats_are_not_mislabeled_png():
    with pytest.raises(SessionImageError):
        as_png(encoded(Image.new('RGB', (4, 4), 'red'), 'BMP'))


def test_frame_limits_are_checked_before_pixel_decode():
    jpeg = encoded(Image.new('RGB', (12, 9), 'blue'), 'JPEG')
    with pytest.raises(SessionImageError, match='byte limit'):
        as_png(jpeg, max_bytes=len(jpeg) - 1)
    with pytest.raises(SessionImageError, match='pixel limit'):
        as_png(jpeg, max_pixels=107)


def test_fresh_live_jpeg_is_attached_to_report_as_real_png(cfg):
    from fastapi.testclient import TestClient
    from gbox.server import create_app
    app = create_app(cfg)
    app.state.store.put('session', 'live-jpeg', {'session_id': 'live-jpeg', 'state': 'running'})
    client = TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})
    rid = client.post('/api/requests', json={'title': 'Native frame evidence'}).json()['id']
    jpeg = encoded(Image.new('RGB', (12, 9), (31, 133, 220)), 'JPEG')
    assert client.post('/api/sessions/live-jpeg/frame', content=jpeg).status_code == 200
    capture = client.post(f'/api/requests/{rid}/capture', json={
        'session_id': 'live-jpeg', 'text': 'Captured the actual native frame',
        'task_step': {'action': 'verify native gameplay', 'attempt': '1', 'status': 'finished'}})
    assert capture.status_code == 200, capture.text
    attachment = capture.json()['attachments'][0]
    assert attachment['type'] == 'image/png' and attachment['name'].endswith('.png')
    saved = client.get(f"/api/artifacts/{attachment['sha256']}")
    assert saved.headers['content-type'].startswith('image/png')
    assert saved.content == as_png(jpeg)
    with Image.open(BytesIO(saved.content)) as actual, Image.open(BytesIO(jpeg)) as source:
        assert actual.format == 'PNG' and actual.size == source.size
        assert actual.tobytes() == source.tobytes()


def test_invalid_live_frame_returns_409_without_a_fake_attachment(cfg):
    from fastapi.testclient import TestClient
    from gbox.server import create_app
    app = create_app(cfg)
    store = app.state.store
    store.put('session', 'bad-frame', {'session_id': 'bad-frame', 'state': 'running'})
    client = TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})
    rid = client.post('/api/requests', json={'title': 'Bad frame must remain uncaptured'}).json()['id']
    before = store.get('request', rid)
    artifacts_before = {item['sha256'] for item in store.all('artifact')}
    assert client.post('/api/sessions/bad-frame/frame', content=PNG_SIGNATURE + b'not-a-real-image').status_code == 200
    capture = client.post(f'/api/requests/{rid}/capture', json={'session_id': 'bad-frame'})
    assert capture.status_code == 409, capture.text
    assert store.get('request', rid)['messages'] == before['messages']
    assert {item['sha256'] for item in store.all('artifact')} == artifacts_before


def test_worker_fallback_jpeg_is_also_attached_as_png(cfg, monkeypatch):
    from fastapi.testclient import TestClient
    from gbox.server import create_app
    app = create_app(cfg)
    store = app.state.store
    store.put('session', 'worker-jpeg', {'session_id': 'worker-jpeg', 'state': 'running'})
    jpeg = encoded(Image.new('RGB', (12, 9), 'orange'), 'JPEG')
    frame = store.put_artifact(jpeg, 'actual-worker-frame.jpg', 'image/jpeg', {'source': 'worker-fixture'})
    original_get = store.get
    requested = []
    def completed_frame_job(kind, key):
        doc = original_get(kind, key)
        if kind == 'job' and doc and doc.get('tool') == 'get_frame':
            requested.append(doc['input']['session_id'])
            return doc | {'state': 'succeeded', 'output': {'sha256': frame.sha256, 'mean_luma': 100}}
        return doc
    monkeypatch.setattr(store, 'get', completed_frame_job)
    client = TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})
    rid = client.post('/api/requests', json={'title': 'Worker fallback image'}).json()['id']
    response = client.post(f'/api/requests/{rid}/capture', json={'session_id': 'worker-jpeg'})
    assert response.status_code == 200, response.text
    assert requested == ['worker-jpeg']
    attachment = response.json()['attachments'][0]
    assert attachment['type'] == 'image/png'
    assert store.read_artifact(attachment['sha256']) == as_png(jpeg)
