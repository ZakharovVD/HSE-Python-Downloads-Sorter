import errno
import sqlite3
from pathlib import Path, PurePosixPath

from .config import validate_directory_name
from .filesystem import category_directory, exists, file_digest, fingerprint, move_without_overwrite
from .history import History
from .models import ConfigError, Fingerprint, HistoryError, Notice, Plan, Report


def movement_paths(history: History, record: sqlite3.Row) -> tuple[Path, Path]:
    paths = []
    for field, count in (("source", 1), ("target", 2)):
        value = record[field]
        if not isinstance(value, str):
            raise HistoryError("В истории найден неверный путь.")
        relative = PurePosixPath(value)
        if (
            relative.is_absolute()
            or relative.as_posix() != value
            or len(relative.parts) != count
            or any(part in (".", "..") for part in relative.parts)
            or len(Path(*relative.parts).parts) != count
            or Path(*relative.parts).is_absolute()
            or Path(*relative.parts).drive
        ):
            raise HistoryError(f"В истории найден небезопасный путь: {value!r}.")
        paths.append(history.root.joinpath(*relative.parts))
    checksum = record["checksum"]
    if not isinstance(checksum, str) or len(checksum) != 64 or set(checksum) - set("0123456789abcdef"):
        raise HistoryError("В истории найдена неверная контрольная сумма.")
    try:
        validate_directory_name(paths[1].parent.name)
    except ConfigError as error:
        raise HistoryError(f"Некорректная папка в истории: {error}") from error
    category_directory(history.root, paths[1].parent.name)
    return paths[0], paths[1]


def inspect_file(path: Path) -> tuple[Fingerprint | None, str | None]:
    if not exists(path):
        return None, None
    info = fingerprint(path)
    return info, file_digest(path, info)


def settle_move(history: History, record: sqlite3.Row, undo: bool = False) -> Notice:
    original, sorted_path = movement_paths(history, record)
    before, after = (sorted_path, original) if undo else (original, sorted_path)
    before_info, before_digest = inspect_file(before)
    after_info, after_digest = inspect_file(after)
    checksum = record["checksum"]
    completed_status = "undone" if undo else "moved"
    cancelled_status = "moved" if undo else "failed"
    if after_digest == checksum:
        if before_info is not None and before_info == after_info:
            if fingerprint(before) != before_info or fingerprint(after) != after_info:
                raise HistoryError(f"Файл меняется во время восстановления: {before!s}")
            before.unlink()
        elif before_digest == checksum:
            history.set_status(record["id"], cancelled_status)
            return Notice(before, "при восстановлении найдены две независимые копии; обе сохранены", error=True)
        history.set_status(record["id"], completed_status)
        return Notice(after, "восстановлена завершённая операция из журнала")
    if before_digest == checksum:
        history.set_status(record["id"], cancelled_status)
        return Notice(
            before,
            "незавершённая операция отменена; исходный файл сохранён",
            error=after_info is not None,
        )
    raise HistoryError(
        f"Не удалось восстановить запись {record['id']}: ожидаемое содержимое не найдено "
        f"в {str(before)!r} или {str(after)!r}. Новые перемещения остановлены. "
        "Проверьте эти файлы и восстановите ожидаемую копию, затем повторите команду."
    )


def recover_pending(history: History) -> list[Notice]:
    records = history.pending_moves()
    for record in records:
        movement_paths(history, record)
    notices = []
    for record in records:
        try:
            notices.append(settle_move(history, record, undo=record["status"] == "undo_pending"))
        except OSError as error:
            raise HistoryError(f"Не удалось восстановить запись {record['id']}: {error}") from error
    return notices


def perform_move(
    history: History, record: sqlite3.Row, expected: Fingerprint, report: Report, undo: bool = False
) -> None:
    original, sorted_path = movement_paths(history, record)
    source, target = (sorted_path, original) if undo else (original, sorted_path)
    completed_status = "undone" if undo else "moved"
    cancelled_status = "moved" if undo else "failed"
    if undo:
        history.set_status(record["id"], "undo_pending")
    try:
        move_without_overwrite(source, target, expected)
    except OSError as error:
        if isinstance(error, FileExistsError):
            history.set_status(record["id"], cancelled_status)
        else:
            try:
                report.notices.append(settle_move(history, record, undo=undo))
                if history.move_status(record["id"]) == completed_status:
                    report.completed.append(target)
            except OSError as recovery_error:
                raise HistoryError(f"Операция прервана, запись сохранена в журнале: {recovery_error}") from error
        report.notices.append(Notice(source, str(error), error=True))
    else:
        history.set_status(record["id"], completed_status)
        report.completed.append(target)


def apply_plan(plan: Plan, history: History) -> Report:
    report = Report(notices=recover_pending(history))
    run_id = None
    for move in plan.moves:
        try:
            if fingerprint(move.source) != move.fingerprint:
                raise OSError(errno.EBUSY, "Файл изменился после построения плана", str(move.source))
            category_directory(plan.root, move.destination.parent.name, create=True)
            if exists(move.destination):
                raise FileExistsError(errno.EEXIST, "Целевое имя занято после просмотра плана", str(move.destination))
            checksum = file_digest(move.source, move.fingerprint)
        except OSError as error:
            report.notices.append(Notice(move.source, str(error), error=True))
            continue
        if run_id is None:
            run_id = history.create_run()
        record = history.add_move(run_id, move.source, move.destination, checksum)
        perform_move(history, record, move.fingerprint, report)
    return report


def undo_moves(history: History, records: list[sqlite3.Row]) -> Report:
    paths = [movement_paths(history, record) for record in records]
    report = Report()
    for record, (original, sorted_path) in zip(records, paths):
        try:
            info = fingerprint(sorted_path)
            if file_digest(sorted_path, info) != record["checksum"]:
                raise OSError(errno.EBUSY, "Содержимое изменилось после сортировки", str(sorted_path))
            if exists(original):
                raise FileExistsError(errno.EEXIST, "Исходное имя уже занято", str(original))
        except OSError as error:
            report.notices.append(Notice(sorted_path, str(error), error=True))
            continue
        perform_move(history, record, info, report, undo=True)
    return report
