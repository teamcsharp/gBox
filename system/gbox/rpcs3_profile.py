"""Linux RPCS3 profile ownership, without removing RPCS3's persistent lock file.

RPCS3 opens cache/rpcs3/RPCS3.buf and takes flock(LOCK_EX | LOCK_NB).
The filename remains after normal exit; unlinking it can bypass a live lock.
The separate gBox lease serializes our preparation and emulator lifetime. The
native lock probe catches an older worker or an independently started RPCS3;
RPCS3 itself remains authoritative for external launch races after the probe.
Upstream: RPCS3/rpcs3 3fc0b099, rpcs3/rpcs3.cpp run_rpcs3 and
Utilities/File.cpp fs::file::file (fs::rewrite + fs::lock).
"""
import os
from pathlib import Path
import stat


class ProfileBusy(RuntimeError):
    pass


def _exclusive(fd):
    import fcntl
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _open(path, create=False):
    flags = (os.O_WRONLY | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NOFOLLOW', 0)
             | getattr(os, 'O_NONBLOCK', 0))  # A substituted FIFO must not hang before the regular-file check.
    if create:
        flags |= os.O_CREAT
    fd = os.open(path, flags, 0o600)
    try:
        _stable(fd, path)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _stable(fd, path):
    opened = os.fstat(fd)
    try:
        current = path.lstat()
    except FileNotFoundError as exc:
        raise ProfileBusy(f'RPCS3 profile lock changed during verification: {path}') from exc
    if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
        raise ProfileBusy(f'RPCS3 profile lock is not a stable regular file: {path}')


def native_available(cache_home):
    """Probe the actual launch environment's .buf, without creating/truncating it."""
    path = Path(cache_home) / 'rpcs3' / 'RPCS3.buf'
    try:
        fd = _open(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ProfileBusy(f'Cannot verify RPCS3 profile access: {path}: {exc}') from exc
    try:
        _exclusive(fd)
        _stable(fd, path)
    except OSError as exc:
        raise ProfileBusy(f'RPCS3 profile is busy or its lock cannot be verified: {path}. '
                          'Stop its existing session before starting another; the lock file was left intact.') from exc
    finally:
        os.close(fd)


class Lease:
    def __init__(self, home, cache_home):
        self.fd = None
        self.home, self.cache_home = Path(home), cache_home

    def acquire(self):
        if self.fd is not None:
            raise ProfileBusy('This RPCS3 adapter already owns a profile')
        self.home.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = _open(self.home / '.gbox-profile.lock', create=True)
            _exclusive(self.fd)
            _stable(self.fd, self.home / '.gbox-profile.lock')
            native_available(self.cache_home)
        except (OSError, ProfileBusy) as exc:
            self.close()
            raise ProfileBusy(f'RPCS3 profile is unavailable; another launch/session may own it: {exc}') from exc
        return self

    def close(self):
        if self.fd is not None:
            fd, self.fd = self.fd, None
            os.close(fd)

    def __del__(self):
        self.close()
