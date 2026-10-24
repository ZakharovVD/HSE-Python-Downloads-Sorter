import errno
import hashlib
import os
import stat
from pathlib import Path

from .models import STATE_DIRECTORY, Fingerprint, SorterError

HASH_CHUNK_SIZE = 1024 * 1024


def resolve_root(path: Path) -> Path:
    root = path.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise SorterError(f"Ожидалась папка: {root}")
    return root


def exists(path: Path) -> bool:
    return os.path.lexists(path)


def snapshot(info: os.stat_result) -> Fingerprint:
    if not stat.S_ISREG(info.st_mode):
        raise OSError(errno.EINVAL, "Ожидался обычный файл, а не папка или ссылка")
    return Fingerprint(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def fingerprint(path: Path) -> Fingerprint:
    return snapshot(path.lstat())


def file_digest(path: Path, expected: Fingerprint | None = None) -> str:
    before = fingerprint(path)
    if expected is not None and before != expected:
        raise OSError(errno.EBUSY, "Файл изменился после построения плана", str(path))
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        if snapshot(os.fstat(stream.fileno())) != before:
            raise OSError(errno.EBUSY, "Файл был заменён перед чтением", str(path))
        digest = hashlib.sha256()
        while chunk := stream.read(HASH_CHUNK_SIZE):
            digest.update(chunk)
        if snapshot(os.fstat(stream.fileno())) != before or fingerprint(path) != before:
            raise OSError(errno.EBUSY, "Файл изменился во время чтения", str(path))
    return digest.hexdigest()


def require_directory(path: Path) -> None:
    if not stat.S_ISDIR(path.lstat().st_mode):
        raise OSError(errno.ENOTDIR, "Ожидалась папка без символической ссылки", str(path))


def category_directory(root: Path, name: str, create: bool = False) -> Path:
    directory = root / name
    if create:
        directory.mkdir(exist_ok=True)
    if exists(directory):
        require_directory(directory)
    elif create:
        raise FileNotFoundError(errno.ENOENT, "Папка назначения отсутствует", str(directory))
    return directory


def state_directory(root: Path, create: bool = False) -> Path:
    return category_directory(root, STATE_DIRECTORY, create=create)


def move_without_overwrite(source: Path, destination: Path, expected: Fingerprint) -> None:
    require_directory(source.parent)
    require_directory(destination.parent)
    if fingerprint(source) != expected:
        raise OSError(errno.EBUSY, "Исходный файл изменился перед перемещением", str(source))
    os.link(source, destination, follow_symlinks=False)
    try:
        if fingerprint(source) != expected or fingerprint(destination) != expected:
            raise OSError(errno.EBUSY, "Файл изменился во время перемещения", str(source))
        source.unlink()
    except OSError as error:
        try:
            if exists(source) and exists(destination):
                current = fingerprint(source)
                if (
                    current == fingerprint(destination)
                    and current.device == expected.device
                    and current.inode == expected.inode
                ):
                    destination.unlink()
        except OSError as rollback_error:
            raise OSError(
                rollback_error.errno,
                f"Ошибка перемещения: {error}; не удалось убрать созданное второе имя: {rollback_error}",
            ) from error
        raise
