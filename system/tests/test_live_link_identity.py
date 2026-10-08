import base64
from types import SimpleNamespace

import pytest

from gbox.live_link import _swap32, apply_hotswap


@pytest.mark.parametrize('convert', [lambda data: data, _swap32])
def test_shared_prefix_cannot_authorize_overwriting_another_build(convert):
    old = b'\0' * 512 + b'A' * 512
    new = b'\0' * 512 + b'C' * 512
    loaded = b'\0' * 512 + b'B' * 512
    ram = b'X' * 1024 + convert(loaded) + b'X' * 1024
    adapter = SimpleNamespace(read_memory=lambda address, size: ram)
    encode = lambda data: base64.b64encode(data).decode()
    patch = {'seg4_old': encode(old), 'seg4_new': encode(new),
             'seg17_old': encode(b'D' * 1024), 'seg17_new': encode(b'E' * 1024), 'dl_map': []}
    with pytest.raises(RuntimeError, match="current model data isn't"):
        apply_hotswap(adapter, patch, SimpleNamespace())


@pytest.mark.parametrize('convert', [lambda data: data, _swap32])
def test_already_loaded_requires_the_complete_new_segment(convert):
    old = b'O' * 1024
    new = b'N' * 1024
    encode = lambda data: base64.b64encode(data).decode()
    patch = {'seg4_old': encode(old), 'seg4_new': encode(new),
             'seg17_old': encode(b'D' * 1024), 'seg17_new': encode(b'E' * 1024), 'dl_map': []}
    adapter = SimpleNamespace(read_memory=lambda address, size: b'X' * 1024 + convert(new))
    assert apply_hotswap(adapter, patch, SimpleNamespace())['already'] is True
