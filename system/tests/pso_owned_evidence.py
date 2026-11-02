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
