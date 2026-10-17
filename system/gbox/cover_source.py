"""Read an existing gBox image without making an authenticated HTTP loopback request."""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from . import cover_art


def local_image(url, *, store, config, media_file, character_file):
    """Only existing, path-checked image routes are usable as a cover source.

    Query strings (including browser credentials and thumbnail widths) are discarded.
    The caller supplies the same file resolvers used by the original media routes.
    """
    parsed = urlsplit(url)
    path = unquote(parsed.path)
    if parsed.scheme or parsed.netloc or not path.startswith('/api/') or re.search(r'[\\\x00-\x1f\x7f]', path):
        raise ValueError('choose an image from the gBox library')
    if any(part in {'.', '..'} for part in path.split('/')):
        raise ValueError('invalid image path')
    component = r'([A-Za-z0-9_][A-Za-z0-9_.~-]{0,159})'
    file = None
    if match := re.fullmatch(r'/api/artifacts/([a-f0-9]{64})', path):
        digest = match[1]
        meta = store.get('artifact', digest)
        if not meta or int(meta.get('size') or 0) > cover_art.MAX_BYTES:
            raise ValueError('image is missing or larger than 15 MB')
        data = store.read_artifact(digest)
    elif match := re.fullmatch('/api/media/' + component + r'/(boxart|snap|wheel|cartart|best|[a-z][a-z0-9_-]{0,39})', path):
        file = media_file(match[1], match[2])
    elif match := re.fullmatch('/api/characters/' + component + '/preview', path):
        file = character_file(match[1], 'preview.png')
    elif match := re.fullmatch('/api/characters/' + component + '/file/(.+)', path):
        file = character_file(match[1], match[2])
    elif match := re.fullmatch(r'/api/mods/built/([^/]+)/([^/]+)/image/(.+)', path):
        from .built_mods import image_path
        file = image_path(config, match[1], match[2], match[3])
    else:
        raise ValueError('this URL is not a gBox image source')
    if file is not None:
        with file.open('rb') as stream:
            data = stream.read(cover_art.MAX_BYTES + 1)
    if not data or len(data) > cover_art.MAX_BYTES or not cover_art.image_type(data):
        raise ValueError('choose a PNG, JPEG, GIF or WebP image up to 15 MB')
    return path, data
