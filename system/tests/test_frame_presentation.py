from PIL import Image

from gbox.frame_presentation import measure, update


def test_loading_fade_is_not_a_persistent_failure_and_nonblack_content_resets_it():
    black = measure(Image.new('RGB', (640, 480), 'black'))
    initial = update(black, {}, 100)
    assert initial['near_black'] and not initial['persistent']
    assert not update(black, initial, 189)['persistent']
    assert update(black, initial, 190)['persistent']
    dim = measure(Image.new('RGB', (640, 480), (14, 12, 14)))
    changed = update(dim, initial, 200)
    assert not changed['near_black'] and not changed['persistent'] and changed['dark_since'] is None
    assert update(black, changed, 230)['dark_since'] == 230


def test_letterboxing_and_small_visible_content_are_not_a_completely_black_screen():
    image = Image.new('RGB', (640, 480), 'black')
    image.paste('white', (200, 200, 230, 230))
    assert not measure(image)['near_black']
