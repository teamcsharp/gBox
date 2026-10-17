"""Cheap image evidence for a persistent near-black presentation; no game controls."""
from PIL import Image


def measure(image):
    thumb = image.convert('L').resize((64, 48), Image.Resampling.BOX)
    hist = thumb.histogram()
    count = sum(hist)
    mean = sum(value * n for value, n in enumerate(hist)) / count
    fraction = sum(hist[:9]) / count
    return {'mean_luma': round(mean, 2), 'near_black_fraction': round(fraction, 4),
            'near_black': mean <= 3 and fraction >= .999}


def update(measurement, prior, now):
    since = prior.get('dark_since') if measurement['near_black'] else None
    if measurement['near_black'] and since is None:
        since = now
    # A fade or startup frame is evidence, not a failed game. Require repeated
    # captures spanning 90 seconds, rather than treating one dark image as failure.
    persistent = since is not None and now - since >= 90
    return measurement | {'sampled_at': now, 'dark_since': since, 'persistent': persistent}
