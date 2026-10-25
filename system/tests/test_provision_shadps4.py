"""Portable installation verifies its input and never overwrites another runtime."""
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

_spec = importlib.util.spec_from_file_location('provision_shadps4', Path(__file__).parents[1] / 'scripts/provision_shadps4.py')
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)


def archive(tmp_path, monkeypatch, files=None):
    src = tmp_path / 'official-fixture.zip'
    with zipfile.ZipFile(src, 'w') as out:
        for name, data in (files or {'shadPS4.exe': b'fixture executable', 'lib.dll': b'fixture library'}).items():
            out.writestr(name, data)
    monkeypatch.setattr(P, 'ARCHIVE_SIZE', src.stat().st_size)
    monkeypatch.setattr(P, 'ARCHIVE_SHA256', hashlib.sha256(src.read_bytes()).hexdigest())
    return src


def test_verified_archive_installs_with_per_file_receipt_without_launch(tmp_path, monkeypatch):
    src = archive(tmp_path, monkeypatch)
    result = P.provision(tmp_path / 'runtime', src)
    assert result['launched'] is False
    manifest = json.loads(Path(result['manifest']).read_text())
    assert manifest['archive_sha256'] == P.ARCHIVE_SHA256
    assert manifest['files']['shadPS4.exe'] == hashlib.sha256(b'fixture executable').hexdigest()
    assert Path(result['executable']).read_bytes() == b'fixture executable'


def test_changed_archive_and_existing_install_are_refused(tmp_path, monkeypatch):
    src = archive(tmp_path, monkeypatch)
    original = src.read_bytes()
    src.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with pytest.raises(ValueError, match='SHA-256'):
        P.provision(tmp_path / 'bad', src)
    assert not (tmp_path / 'bad').exists()
    folder = tmp_path / 'existing'
    folder.mkdir()
    (folder / 'personal-config.toml').write_text('keep')
    with pytest.raises(FileExistsError):
        P.provision(folder, src)
    assert (folder / 'personal-config.toml').read_text() == 'keep'


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'C:/absolute', 'nested/../../escape', 'bad. /file'])
def test_archive_paths_cannot_escape_installation(tmp_path, monkeypatch, name):
    src = archive(tmp_path, monkeypatch, {'shadPS4.exe': b'fixture', name: b'escape'})
    with pytest.raises(ValueError, match='Unsafe archive member'):
        P.provision(tmp_path / 'runtime', src)
    assert not (tmp_path / 'runtime').exists()


def test_archive_without_core_is_not_published(tmp_path, monkeypatch):
    src = archive(tmp_path, monkeypatch, {'launcher.exe': b'wrong program'})
    with pytest.raises(ValueError, match='shadPS4.exe'):
        P.provision(tmp_path / 'runtime', src)
    assert not (tmp_path / 'runtime').exists()
