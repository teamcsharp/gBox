"""Hermes never publishes game data to the public repository (gbox/hermes_payload_guard.py, 2026-10-21)."""
import io
import subprocess
import sys

import pytest

from gbox import hermes_payload_guard as G


def files(**kw):
    """name -> bytes for an in-memory inspector."""
    def inspect(path):
        data = kw.get(path)
        return (None, None) if data is None else (data[:G.HEAD_BYTES], len(data))
    return inspect


def test_source_docs_tests_and_gameplay_screenshots_are_published():
    ok = {'system/gbox/x.py': b'print(1)\n', 'system/docs/notes.md': b'# Notes\n',
          'system/tests/test_x.py': b'def test(): pass\n', 'system/docs/evidence/re5/round.jpg': b'\xff\xd8\xff\xe0',
          'system/clients/web/icon.png': b'\x89PNG\r\n', 'system/tests/fixtures/tiny.bin': b'\x01\x02\x03'}
    assert G.refusals(ok, files(**ok)) == []


@pytest.mark.parametrize('path,data,reason', [
    ('system/originals/Sonic 1 and 2.zip', b'PK\x03\x04rest', 'a zip archive'),
    ('system/start.dol', b'\x00\x00\x01\x00' + bytes(64), 'game data or binary (.dol)'),
    ('system/docs/native_evidence/kas00_geometry.obj', b'v 0 0 0\n', 'game data or binary (.obj)'),
    ('system/docs/mvc2_ryu.parts.png', b'\x89PNG\r\n', 'images go under docs/evidence'),
    ('system/gbox/data.txt', b'NES\x1a' + bytes(16), 'an NES ROM'),           # a ROM by content, whatever its name
    ('system/tests/fixtures/rom.bin', b'\x80\x37\x12\x40' + bytes(64), 'an N64 ROM'),
    ('system/tests/fixtures/big.bin', bytes(G.FIXTURE_MAX + 1), 'game data or binary (.bin)'),
    ('system/docs/huge.md', b'#' + bytes(G.MAX_BYTES), 'too large'),
], ids=lambda v: v if isinstance(v, str) and len(v) < 60 else '')
def test_game_data_binaries_and_extracted_assets_are_refused(path, data, reason):
    out = G.refusals([path], files(**{path: data}))
    assert len(out) == 1 and reason in out[0] and out[0].startswith(path)


def test_deleted_files_publish_nothing_and_the_worktree_inspector_reads_real_files(tmp_path):
    (tmp_path / 'system/gbox').mkdir(parents=True)
    (tmp_path / 'system/gbox/game.iso').write_bytes(bytes(0x8001) + b'CD001')
    assert G.refusals(['system/gbox/gone.zip'], G.worktree_inspector(tmp_path)) == []
    assert 'a disc image' in G.refusals(['system/gbox/game.iso'], G.worktree_inspector(tmp_path))[0]


def git(*args, cwd):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    origin, root = tmp_path / 'origin', tmp_path / 'repo'
    git('init', '--bare', str(origin), cwd=tmp_path)
    git('init', '-b', 'main', str(root), cwd=tmp_path)
    git('config', 'user.name', 'Test', cwd=root)
    git('config', 'user.email', 'test@example.invalid', cwd=root)
    (root / 'system/gbox').mkdir(parents=True)
    (root / 'system/gbox/a.py').write_text('A = 1\n')
    git('add', '.', cwd=root); git('commit', '-m', 'base', cwd=root)
    git('remote', 'add', 'origin', str(origin), cwd=root); git('push', '-u', 'origin', 'main', cwd=root)
    return root


def test_commit_inspection_and_the_pre_push_check(repo):
    git('checkout', '-b', 'hermes/request-1-1', cwd=repo)
    (repo / 'system/gbox/a.py').write_text('A = 2\n')
    git('commit', '-am', 'fine', cwd=repo)
    fine = git('rev-parse', 'HEAD', cwd=repo)
    (repo / 'system/originals').mkdir()
    (repo / 'system/originals/Sonic 1 and 2.zip').write_bytes(b'PK\x03\x04' + bytes(32))
    git('add', '.', cwd=repo); git('commit', '-m', 'rom', cwd=repo)
    bad = git('rev-parse', 'HEAD', cwd=repo)
    assert G.changed_files(repo, 'origin/main', bad) == ['system/gbox/a.py', 'system/originals/Sonic 1 and 2.zip']
    zeros = '0' * 40
    line = lambda sha: io.StringIO(f'refs/heads/x {sha} refs/heads/x {zeros}\n')
    assert G.pre_push_main(line(fine), repo) == 0
    assert G.pre_push_main(line(bad), repo) == 1
    assert G.pre_push_main(io.StringIO(f'(delete) {zeros} refs/heads/x {bad}\n'), repo) == 0


def test_installed_hook_refuses_a_real_push_of_game_data(repo):
    from pathlib import Path
    system = Path(G.__file__).resolve().parents[1]
    assert G.install_pre_push(repo, sys.executable, system) is True
    assert G.install_pre_push(repo, sys.executable, system) is False          # unchanged: not rewritten
    git('checkout', '-b', 'hermes/request-2-1', cwd=repo)
    (repo / 'system/gbox/start.dol').write_bytes(bytes(256))
    git('add', '.', cwd=repo); git('commit', '-m', 'exe', cwd=repo)
    pushed = subprocess.run(['git', 'push', 'origin', 'hermes/request-2-1'], cwd=repo, capture_output=True, text=True)
    assert pushed.returncode != 0 and 'start.dol' in pushed.stderr
    git('reset', '--hard', 'HEAD~1', cwd=repo)
    (repo / 'system/gbox/a.py').write_text('A = 3\n')
    git('commit', '-am', 'source only', cwd=repo)
    assert subprocess.run(['git', 'push', 'origin', 'hermes/request-2-1'], cwd=repo, capture_output=True).returncode == 0


def test_run_output_outside_the_work_folders_is_refused_on_push():
    junk = {'system/.checkpoint.json': b'{}', 'system/debug_probe.py': b'print(1)\n', 'tetris_nes_build.json': b'{}',
            'system/docs/notes.md': b'# ok\n', 'system/profiles/gamedata/x-ram.json': b'{}'}
    out = G.refusals(junk, files(**junk), G.HOMES)
    assert sorted(o.split(':')[0] for o in out) == ['system/.checkpoint.json', 'system/debug_probe.py', 'tetris_nes_build.json']
    assert all('outside' in o for o in out)
