import io

from PIL import Image

from gbox.remote_desktop import crop_jpeg, frame_for_view


def test_app_view_crops_desktop_to_window():
    source = Image.new("RGB", (400, 200), "red")
    source.paste(Image.new("RGB", (200, 100), "blue"), (100, 50))
    data = io.BytesIO()
    source.save(data, format="JPEG")
    cropped = crop_jpeg(data.getvalue(), (0.25, 0.25, 0.5, 0.5))
    with Image.open(io.BytesIO(cropped)) as image:
        assert image.size == (200, 100)
        assert image.getpixel((100, 50))[2] > 200


def test_app_view_does_not_expose_desktop_without_window():
    assert crop_jpeg(b"unused", None) is None
    assert crop_jpeg(b"unused", (0, 0, 2, 1)) is None
    assert frame_for_view(b"desktop pixels", "app", None) is None
    assert frame_for_view(b"desktop pixels", "desktop", None) == b"desktop pixels"
