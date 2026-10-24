import stat
import unicodedata
from pathlib import Path

from .filesystem import category_directory, snapshot
from .models import Fingerprint, Notice, Plan, PlannedMove, Settings


def name_key(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def scan_files(
    directory: Path,
    settings: Settings,
    excluded: set[Path],
    describe_directories: bool = True,
) -> tuple[list[tuple[Path, Fingerprint]], list[Notice]]:
    files = []
    notices = []
    for path in sorted(directory.iterdir(), key=lambda item: name_key(item.name)):
        try:
            info = path.lstat()
            if path in excluded:
                notices.append(Notice(path, "файл конфигурации"))
            elif stat.S_ISLNK(info.st_mode):
                notices.append(Notice(path, "символическая ссылка"))
            elif path.name.startswith("."):
                notices.append(Notice(path, "скрытый файл или служебная папка"))
            elif stat.S_ISDIR(info.st_mode):
                if describe_directories:
                    notices.append(Notice(path, "вложенная папка"))
            elif not stat.S_ISREG(info.st_mode):
                notices.append(Notice(path, "не является обычным файлом"))
            elif any(path.name.casefold().endswith(extension) for extension in settings.skip_extensions):
                notices.append(Notice(path, "незавершённая загрузка или временный файл"))
            else:
                files.append((path, snapshot(info)))
        except OSError as error:
            notices.append(Notice(path, str(error), error=True))
    return files, notices


def choose_category(filename: str, settings: Settings) -> tuple[str, str]:
    lowered = filename.casefold()
    for category in settings.categories:
        for keyword in category.keywords:
            if keyword in lowered:
                return category.name, f"ключевое слово {keyword!r}"
    for category in settings.categories:
        for extension in category.extensions:
            if lowered.endswith(extension):
                return category.name, f"расширение {extension}"
    return settings.fallback_category, "правила не найдены"


def free_name(filename: str, occupied: set[str], settings: Settings) -> str:
    if name_key(filename) not in occupied:
        return filename
    extensions = {
        extension
        for category in settings.categories
        for extension in category.extensions
        if filename.casefold().endswith(extension)
    }
    suffix = filename[-len(max(extensions, key=len)) :] if extensions else Path(filename).suffix
    stem = filename[: -len(suffix)] if suffix else filename
    number = 1
    while name_key(candidate := f"{stem} ({number}){suffix}") in occupied:
        number += 1
    return candidate


def build_plan(root: Path, settings: Settings, excluded: set[Path] | None = None) -> Plan:
    plan = Plan(root)
    files, plan.notices = scan_files(root, settings, excluded or set())
    reservations: dict[str, set[str]] = {}
    for source, file_snapshot in files:
        category, reason = choose_category(source.name, settings)
        try:
            directory = category_directory(root, category)
            if category not in reservations:
                reservations[category] = (
                    {name_key(path.name) for path in directory.iterdir()} if directory.exists() else set()
                )
            filename = free_name(source.name, reservations[category], settings)
            reservations[category].add(name_key(filename))
            plan.moves.append(PlannedMove(source, directory / filename, reason, file_snapshot))
        except OSError as error:
            plan.notices.append(Notice(source, str(error), error=True))
    return plan
