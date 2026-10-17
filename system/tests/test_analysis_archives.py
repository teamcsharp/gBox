import io
import subprocess
import tarfile
import pytest
from gbox import rom_archives as A
from gbox.formats.disc import listing


@pytest.mark.parametrize('suffix,mode', [('.tar', 'w'), ('.tar.gz', 'w:gz'), ('.tar.bz2', 'w:bz2'), ('.tar.xz', 'w:xz')])
def test_tar_analysis_and_preparation(tmp_path, cfg, suffix, mode):
    src = tmp_path / ('game' + suffix)
    with tarfile.open(src, mode) as archive:
        item = tarfile.TarInfo('game/default.xbe'); item.size = 8
        archive.addfile(item, io.BytesIO(b'XBEHtest'))
    result = listing(src)
    assert result.executable == b'XBEHtest'
    assert A.prepare(src, cfg, 'game/default.xbe').read_bytes() == b'XBEHtest'


def test_real_7z_fingerprint(tmp_path):
    try:
        exe = A.seven_zip()
    except RuntimeError:
        pytest.skip('7-Zip not installed')
    (tmp_path / 'default.xbe').write_bytes(b'XBEH' + b'hello' * 100)
    src = tmp_path / 'game.7z'
    subprocess.run([exe, 'a', str(src), 'default.xbe'], cwd=tmp_path, check=True, capture_output=True)
    result = listing(src)
    assert result.executable.startswith(b'XBEH')
    assert result.files[0]['head'].startswith(b'XBEH')


def test_tar_rejects_link_and_traversal(tmp_path):
    for name, kind in [('bad', tarfile.SYMTYPE), ('../escape', tarfile.REGTYPE)]:
        src = tmp_path / 'bad.tar'
        with tarfile.open(src, 'w') as archive:
            item = tarfile.TarInfo(name); item.type = kind; item.linkname = '/outside'
            archive.addfile(item)
        with pytest.raises(ValueError):
            A.members(src)
