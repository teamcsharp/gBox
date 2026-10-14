"""Validate operator-marked frames and explicitly labelled reference images."""
import base64
import binascii

from .session_images import as_png

MAX_BYTES = 4 << 20
MAX_PIXELS = 8_388_608


def annotation_frame(png: bytes) -> bytes:
    """Keep a whole high-resolution capture within the report attachment budget."""
    from io import BytesIO
    from PIL import Image
    with Image.open(BytesIO(png)) as image:
        if image.width * image.height <= MAX_PIXELS and len(png) <= MAX_BYTES:
            return png
        image.thumbnail((1600, 1600))
        while True:
            out = BytesIO()
            image.save(out, 'PNG')
            if len(out.getvalue()) <= MAX_BYTES:
                return out.getvalue()
            image.thumbnail((max(1, int(image.width * .8)), max(1, int(image.height * .8))))


def evidence_images(evidence: dict) -> tuple[str, list[dict]]:
    if not isinstance(evidence, dict):
        raise ValueError('evidence must contain a marked image and original frame')

    def decode(value):
        if not isinstance(value, str) or not value or len(value) > ((MAX_BYTES + 2) // 3) * 4:
            raise ValueError('Each report image must be at most 4 MB')
        try:
            raw = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError('Invalid report image encoding') from exc
        png = as_png(raw, max_bytes=MAX_BYTES, max_pixels=MAX_PIXELS)
        if len(png) > MAX_BYTES:
            raise ValueError('Converted report image exceeds 4 MB')
        return base64.b64encode(png).decode('ascii')

    marked = decode(evidence.get('image_b64'))
    original = decode(evidence.get('original_image_b64'))
    refs = evidence.get('reference_images', [])
    if not isinstance(refs, list) or len(refs) > 3:
        raise ValueError('Attach up to 3 reference images')
    attachments = [{'name': 'original-game-frame.png', 'type': 'image/png', 'b64': original},
                   {'name': 'annotated-game-frame.png', 'type': 'image/png', 'b64': marked}]
    for i, ref in enumerate(refs, 1):
        if not isinstance(ref, dict):
            raise ValueError('Invalid reference image')
        attachments.append({'name': f'character-reference-{i}.png', 'type': 'image/png', 'b64': decode(ref.get('b64'))})
    return marked, attachments
