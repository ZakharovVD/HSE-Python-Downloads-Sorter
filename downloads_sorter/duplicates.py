from collections import defaultdict
from pathlib import Path

from .filesystem import category_directory, file_digest
from .models import DuplicateReport, Fingerprint, Notice, Settings
from .planner import scan_files


def find_duplicates(root: Path, settings: Settings, excluded: set[Path] | None = None) -> DuplicateReport:
    report = DuplicateReport()
    files, notices = scan_files(root, settings, excluded or set(), describe_directories=False)
    report.notices.extend(notices)
    for name in settings.directory_names:
        try:
            directory = category_directory(root, name)
            if not directory.exists():
                continue
            found, notices = scan_files(directory, settings, excluded or set(), describe_directories=False)
            files.extend(found)
            report.notices.extend(notices)
        except OSError as error:
            report.notices.append(Notice(root / name, str(error), error=True))
    report.scanned = len(files)
    sizes: dict[int, list[tuple[Path, Fingerprint]]] = defaultdict(list)
    for path, info in files:
        sizes[info.size].append((path, info))
    for candidates in sizes.values():
        if len(candidates) < 2:
            continue
        hashes: dict[str, list[Path]] = defaultdict(list)
        for path, info in candidates:
            try:
                hashes[file_digest(path, info)].append(path)
            except OSError as error:
                report.notices.append(Notice(path, str(error), error=True))
        report.groups.extend(paths for paths in hashes.values() if len(paths) > 1)
    return report
