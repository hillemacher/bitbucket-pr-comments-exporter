"""Private, atomic output writes using only the standard library."""
from __future__ import annotations

import errno
import os
from pathlib import Path
import stat
import tempfile


def _private_parents(path: Path) -> None:
    if path.is_dir():
        return
    try:
        path.mkdir(mode=0o700)
    except FileNotFoundError:
        _private_parents(path.parent)
        path.mkdir(mode=0o700)


def write_private(path: Path, value: str) -> None:
    """Replace a regular file atomically; never follow a final symlink.

    New directories are private; existing directory permissions are preserved.
    On POSIX the new file is 0600 even when replacing a permissive file.
    Windows users must additionally protect the output directory with its ACL.
    """
    _private_parents(path.parent)
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISREG(mode):
            raise OSError(errno.EINVAL, 'Output must be a regular file, not a symlink or special file')
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
