"""Opt-in local evidence reader. No game assets are distributed with these tests."""
from pathlib import Path, PurePosixPath
import os
import pytest

class OwnedEvidencePath:
    def __init__(self, relative): self.relative=PurePosixPath(relative)
    def __truediv__(self, value): return OwnedEvidencePath(self.relative / value)
    @property
    def parent(self): return OwnedEvidencePath(self.relative.parent)
    @property
    def parents(self): return [OwnedEvidencePath(p) for p in self.relative.parents]
    def resolve(self): return self
    def _file(self):
        root=os.environ.get('GBOX_PSO_OWNED_EVIDENCE')
        if not root:
            pytest.skip('Owned-disc/capture evidence is opt-in: set GBOX_PSO_OWNED_EVIDENCE to the external pso-live-20261101 directory', allow_module_level=True)
        path=Path(root)/str(self.relative)
        if not path.is_file():
            pytest.skip('Optional owned-disc/capture evidence is absent: '+str(self.relative), allow_module_level=True)
        return path
    def read_text(self, *args, **kwargs): return self._file().read_text(*args, **kwargs)
    def read_bytes(self): return self._file().read_bytes()

def original_test_path(relative): return OwnedEvidencePath(relative)


def owned_dol_read(address, length):
    """Read an exact owned executable section; never distribute executable bytes."""
    import hashlib
    import struct
    data = original_test_path('../pso-live/PsoV3.dol').read_bytes()
    assert hashlib.sha256(data).hexdigest() == '1f80fb82b41c05b26b6d0545b1ba9c0aa60b52e6589cf32fbb2ffe644692a61a'
    for count, offsets, addresses, sizes in ((7, 0, 0x48, 0x90), (11, 0x1c, 0x64, 0xac)):
        for index in range(count):
            offset, start, size = (struct.unpack_from('>I', data, field + 4*index)[0]
                                   for field in (offsets, addresses, sizes))
            if size and start <= address and address + length <= start + size:
                return data[offset + address - start:offset + address - start + length]
    raise ValueError('Owned DOL address outside section')
