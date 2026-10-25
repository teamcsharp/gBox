"""What Hermes may publish to the public repository: source, tests, docs and gameplay screenshots - never game data.

2026-10-21: four hermes/* branches on the public teamcsharp/gBox carried a ROM ("Sonic 1 and 2.zip"), a game executable
(Metal Arms start.dol), extracted sprite sheets and a game mesh (a DOA3 .obj). They reached GitHub through direct pushes
from task worktrees and came back for review as recovery PRs. This check runs in publish_task_changes, before the
outcome reconciler reopens stranded commits as a PR, and in the Hermes repository's pre-push hook.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import subprocess
from typing import Callable, Iterable

# Disc and ROM images, archives, executables, game archives, extracted assets and media. ".md" is Markdown here, so
# Mega Drive ROMs are only refused by their other names and by content.
GAME_DATA = frozenset({
    '.zip', '.7z', '.rar', '.gz', '.tgz', '.xz', '.bz2', '.tar', '.iso', '.gcz', '.rvz', '.wbfs', '.wad', '.chd',
    '.cso', '.cue', '.img', '.mdf', '.nrg', '.ecm', '.z64', '.n64', '.v64', '.sfc', '.smc', '.nes', '.fds', '.gba',
    '.gb', '.gbc', '.nds', '.3ds', '.cia', '.xci', '.nsp', '.pkg', '.gen', '.smd', '.32x', '.sms', '.gg', '.pce',
    '.ws', '.wsc', '.ngp', '.lnx', '.a26', '.vb', '.gcm', '.dol', '.elf', '.self', '.sprx', '.prx', '.xbe', '.xex',
    '.exe', '.dll', '.so', '.dylib', '.rel', '.bin', '.afs', '.xpr', '.pak', '.arc', '.cpk', '.awb', '.acb', '.adx',
    '.hca', '.at3', '.at9', '.xma', '.bnk', '.wem', '.pac', '.mdl', '.mot', '.tpl', '.gvr', '.pvr', '.dds', '.obj',
    '.glb', '.gltf', '.fbx', '.dae', '.blend', '.wav', '.mp3', '.ogg', '.flac', '.mp4', '.mkv', '.avi', '.webm',
})
IMAGES = frozenset({'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'})
IMAGE_HOMES = ('system/docs/evidence/', 'system/clients/')     # gameplay screenshots / the app's own UI pictures
FIXTURE_HOME = 'system/tests/fixtures/'
FIXTURE_MAX = 64 * 1024                                       # small synthetic test inputs only
MAX_BYTES = 8 * 1024 * 1024
MAGIC = (
    (0, b'\x7fELF', 'an ELF executable'), (0, b'MZ', 'a Windows executable'), (0, b'SCE\x00', 'a PS3 executable'),
    (0, b'XBEH', 'an Xbox executable'), (0, b'NES\x1a', 'an NES ROM'), (0, b'\x80\x37\x12\x40', 'an N64 ROM'),
    (0, b'\x37\x80\x40\x12', 'an N64 ROM'), (0x1C, b'\xc2\x33\x9f\x3d', 'a GameCube disc'),
    (0x18, b'\x5d\x1c\x9e\xa3', 'a Wii disc'), (0x8001, b'CD001', 'a disc image'), (0, b'PK\x03\x04', 'a zip archive'),
    (0, b'7z\xbc\xaf\x27\x1c', 'a 7z archive'), (0, b'Rar!', 'a rar archive'), (0, b'AFS\x00', 'a CRI AFS archive'),
    (0, b'XPR0', 'an Xbox packed resource'), (0, b'CPK ', 'a CRI CPK archive'),
)
HEAD_BYTES = 0x8010

Inspect = Callable[[str], 'tuple[bytes | None, int | None]']


# Where Hermes work lives. Run output (checkpoints, manifests, debug scripts) at the repository or system root is not
# work: it was pushed from task worktrees straight into system/ until the pre-push hook refused it.
HOMES = ('system/gbox/', 'system/tests/', 'system/clients/', 'system/docs/', 'system/hermes/', 'system/profiles/',
         'system/scripts/', 'system/adapters/')
# Tracked project metadata outside those directories. Exact membership only:
# these are files, never filename prefixes or additional writable directories.
PROJECT_FILES = frozenset({'system/gbox.toml', 'system/LICENSES-THIRD-PARTY.md'})


def refusals(files: Iterable[str], inspect: Inspect | None = None, homes: tuple[str, ...] | None = None) -> list[str]:
    """One reason per file that must never be published. `inspect(path)` -> (first HEAD_BYTES bytes, size), or
    (None, None) for a deleted or unreadable file (nothing to publish). `homes`:
    allowed folders, alongside the exact PROJECT_FILES; every admitted file still undergoes payload checks."""
    out = []
    for name in files:
        path = str(name).replace('\\', '/')
        suffix = PurePosixPath(path).suffix.lower()
        head, size = inspect(path) if inspect else (None, None)
        if inspect and head is None and size is None:
            continue
        if homes and not (path.startswith(homes) or path in PROJECT_FILES):
            out.append(f'{path}: outside the source, test, docs, profiles and client folders (run output stays in the workspace)')
            continue
        fixture = path.startswith(FIXTURE_HOME) and size is not None and size <= FIXTURE_MAX
        kind = next((what for at, magic, what in MAGIC if head and head[at:at + len(magic)] == magic), None)
        if kind:
            out.append(f'{path}: {kind}')
        elif suffix in GAME_DATA and not fixture:
            out.append(f'{path}: game data or binary ({suffix})')
        elif suffix in IMAGES and not path.startswith(IMAGE_HOMES):
            folder = path.rsplit('/', 1)[0] if '/' in path else '.'
            out.append(f'{path}: images go under docs/evidence (gameplay screenshots) or clients (UI), not {folder}/')
        elif size is not None and size > MAX_BYTES:
            out.append(f'{path}: {size // (1024 * 1024)} MiB is too large for the repository')
    return out


def worktree_inspector(root: Path) -> Inspect:
    """Read files from a checkout."""
    def inspect(path):
        p = Path(root) / path
        try:
            with p.open('rb') as f:
                return f.read(HEAD_BYTES), p.stat().st_size
        except OSError:
            return None, None
    return inspect


def commit_inspector(root: Path, sha: str) -> Inspect:
    """Read files as they are in a commit (the reconciler and the pre-push hook)."""
    def inspect(path):
        spec = f'{sha}:{path}'
        size = subprocess.run(['git', 'cat-file', '-s', spec], cwd=root, capture_output=True, text=True)
        if size.returncode:
            return None, None
        blob = subprocess.run(['git', 'cat-file', 'blob', spec], cwd=root, capture_output=True)
        return blob.stdout[:HEAD_BYTES], int(size.stdout.strip())
    return inspect


def changed_files(root: Path, base: str, sha: str) -> list[str]:
    """Paths added or changed between base and sha (deleted paths are not published)."""
    out = subprocess.run(['git', 'diff', '--name-only', '--diff-filter=ACMRT', f'{base}...{sha}'], cwd=root,
                         capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


PRE_PUSH = '''#!/bin/sh
# gBox: refuse pushing game data or binaries from Hermes task worktrees (gbox/hermes_payload_guard.py).
exec "{python}" -c "import sys; sys.path.insert(0, {system!r}); from gbox.hermes_payload_guard import pre_push_main; sys.exit(pre_push_main())" "$@"
'''


def pre_push_main(stdin=None, root: Path | None = None) -> int:
    """git pre-push: each stdin line is '<local ref> <local sha> <remote ref> <remote sha>'. Non-zero refuses the push."""
    import sys
    root = Path(root or '.')
    bad = []
    for line in (stdin or sys.stdin).read().splitlines():
        parts = line.split()
        if len(parts) != 4 or set(parts[1]) == {'0'}:
            continue                                   # a deleted ref publishes nothing
        local, remote = parts[1], parts[3]
        base = 'origin/main' if set(remote) == {'0'} else remote
        bad += refusals(changed_files(root, base, local), commit_inspector(root, local), HOMES)
    if bad:
        print('gBox refused this push: game data and binaries are never published to the public repository:',
              *bad[:20], sep='\n  ', file=sys.stderr)
        return 1
    return 0


def install_pre_push(repo: Path, python: str, system: Path) -> bool:
    """Install the hook in the repository's common hooks directory (shared by every task worktree). True if written."""
    hooks = Path(repo) / '.git' / 'hooks'
    # forward slashes: the hook is a POSIX shell script (Git Bash on Windows) and the path lands in a Python literal
    text = PRE_PUSH.format(python=Path(python).as_posix(), system=Path(system).as_posix())
    target = hooks / 'pre-push'
    try:
        if target.read_text(encoding='utf-8') == text:
            return False
    except OSError:
        pass
    hooks.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8')
    target.chmod(0o755)
    return True
