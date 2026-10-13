"""Mod uploads use one .part per request, so a second machine pushing the same file can't break the first."""
from pathlib import Path

from fastapi.testclient import TestClient

from gbox.config import Config
from gbox.server import create_app


def test_upload_stores_and_leaves_no_part(tmp_path):
    cfg = Config(data_dir=tmp_path)
    with TestClient(create_app(cfg), headers={'Authorization': 'Bearer ' + cfg.token()}) as client:
        r = client.put('/api/modfiles/g/amy/file/disc1.iso', content=b'x' * 1000)
    assert r.status_code == 200 and r.json()['size'] == 1000
    d = Path(cfg.cache) / 'mods/g/amy'
    assert (d / 'disc1.iso').read_bytes() == b'x' * 1000
    assert not list(d.glob('*.part'))


def test_an_in_flight_upload_of_the_same_file_does_not_break_another(tmp_path):
    cfg = Config(data_dir=tmp_path)
    d = Path(cfg.cache) / 'mods/g/amy'
    d.mkdir(parents=True)
    other = d / 'disc1.iso.part'                  # what a concurrent upload of the same file used to share
    other.write_bytes(b'partial')
    with TestClient(create_app(cfg), headers={'Authorization': 'Bearer ' + cfg.token()}) as client:
        r = client.put('/api/modfiles/g/amy/file/disc1.iso', content=b'y' * 10)
    assert r.status_code == 200
    assert (d / 'disc1.iso').read_bytes() == b'y' * 10
    assert other.read_bytes() == b'partial'          # the other upload's file is untouched
