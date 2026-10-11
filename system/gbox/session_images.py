"""Validate real session frames and normalize screenshot attachments to PNG."""
from __future__ import annotations

from io import BytesIO

from PIL import Image, UnidentifiedImageError


PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
MAX_FRAME_BYTES = 64 * 1024 * 1024
MAX_FRAME_PIXELS = 33_554_432


class SessionImageError(ValueError):
    """The captured bytes cannot be attached as a valid session image."""


def as_png(data: bytes, *, max_bytes: int = MAX_FRAME_BYTES,
           max_pixels: int = MAX_FRAME_PIXELS) -> bytes:
    """Return a fully decoded PNG, preserving valid PNG input byte for byte.

    Live workers commonly stream JPEG. Conversion preserves those decoded pixels;
    invalid or truncated frames never become placeholder screenshot artifacts.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise SessionImageError('session frame is not image bytes')
    data = bytes(data)
    if not data or len(data) > max_bytes:
        raise SessionImageError('session frame is empty or exceeds the image byte limit')
    expected = 'PNG' if data.startswith(PNG_SIGNATURE) else 'JPEG' if data.startswith(b'\xff\xd8\xff') else None
    if expected is None:
        raise SessionImageError('session frame must be a valid PNG or JPEG')
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != expected:
                raise SessionImageError('session frame format does not match its image header')
            if image.width <= 0 or image.height <= 0 or image.width * image.height > max_pixels:
                raise SessionImageError('session frame exceeds the decoded image pixel limit')
            image.verify()
        # Verification checks the container. Decoding also detects truncated or
        # corrupt pixel data before any artifact is advertised as image/png.
        with Image.open(BytesIO(data)) as image:
            image.load()
            if expected == 'PNG':
                return data
            if image.mode not in ('RGB', 'L'):
                image = image.convert('RGB')
            result = BytesIO()
            image.save(result, format='PNG')
            return result.getvalue()
    except SessionImageError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError,
            Image.DecompressionBombError) as exc:
        raise SessionImageError('session frame could not be decoded as a complete image') from exc
