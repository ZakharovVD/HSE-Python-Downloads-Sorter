import argparse
import sqlite3
import sys
from pathlib import Path

from . import __version__
from .config import DEFAULT_CONFIG, load_settings
from .duplicates import find_duplicates
from .filesystem import resolve_root
from .history import History, has_history
from .models import Notice, Plan, Report, Settings, SorterError
from .planner import build_plan
from .service import apply_plan, movement_paths, recover_pending, undo_moves


def positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Ожидается положительное целое число.") from error
    if number < 1:
        raise argparse.ArgumentTypeError("Число должно быть больше нуля.")
    return number


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Сортировщик папки «Загрузки».")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", title="команды")
    descriptions = {
        "plan": "показать план без изменения файлов",
        "sort": "показать план и выполнить сортировку после подтверждения",
        "undo": "отменить последнюю сортировку",
        "duplicates": "найти одинаковые файлы по содержимому",
        "history": "показать историю сортировок",
    }
    for name, description in descriptions.items():
        command = commands.add_parser(name, help=description, description=description)
        command.add_argument(
            "--source", type=Path, default=Path.home() / "Downloads", metavar="ПАПКА", help="по умолчанию ~/Downloads"
        )
        if name in ("plan", "sort", "duplicates"):
            command.add_argument(
                "--config", type=Path, default=DEFAULT_CONFIG, metavar="JSON", help="путь к конфигу правил"
            )
        if name in ("sort", "undo"):
            command.add_argument("--yes", action="store_true", help="явно подтвердить операцию без вопроса")
        if name == "history":
            command.add_argument("--limit", type=positive_integer, default=10, help="число последних запусков")
    return parser


def display_path(path: Path, root: Path) -> str:
    try:
        return repr(str(path.relative_to(root)))
    except ValueError:
        return repr(str(path))


def print_notices(notices: list[Notice], root: Path) -> None:
    for notice in notices:
        label = "Ошибка" if notice.error else "Примечание"
        print(f"  {label}: {display_path(notice.path, root)} — {notice.message}")


def print_plan(plan: Plan) -> None:
    print(f"Папка: {str(plan.root)!r}")
    for move in plan.moves:
        print(
            f"  {display_path(move.source, plan.root)} -> "
            f"{display_path(move.destination, plan.root)} ({move.reason})"
        )
    print_notices(plan.notices, plan.root)
    errors = sum(notice.error for notice in plan.notices)
    print(f"План: {len(plan.moves)} перемещений; пропусков: {len(plan.notices) - errors}; ошибок: {errors}.")


def print_report(report: Report, root: Path, action: str) -> int:
    print_notices(report.notices, root)
    for path in report.completed:
        print(f"  Готово: {display_path(path, root)}")
    errors = sum(notice.error for notice in report.notices)
    print(f"{action}: {len(report.completed)}; ошибок: {errors}.")
    return int(errors > 0)


def confirm(automatic: bool) -> bool:
    if automatic:
        return True
    try:
        answer = input("Для подтверждения введите «да» или «yes»: ").strip().casefold()
    except EOFError:
        answer = ""
    if answer in ("да", "yes"):
        return True
    print("Отменено пользователем.")
    return False


def run_history(root: Path, limit: int) -> int:
    if not has_history(root):
        print("Истории сортировок пока нет.")
        return 0
    with History(root) as history:
        records = history.summaries(limit)
        if not records:
            print("Истории сортировок пока нет.")
        for record in records:
            print(f"{record['created_at']} | запуск {record['id']}")
            print(
                f"  перемещено: {record['moved'] or 0}; отменено: {record['undone'] or 0}; "
                f"не завершено: {record['pending'] or 0}; ошибок перемещения: {record['failed'] or 0}"
            )
    return 0


def run_undo(root: Path, automatic: bool) -> int:
    if not has_history(root):
        print("Нет сортировки для отмены.")
        return 0
    with History(root) as history:
        notices = recover_pending(history)
        print_notices(notices, root)
        records = history.latest_moves()
        if not records:
            print("Нет сортировки для отмены.")
            return int(any(notice.error for notice in notices))
        print(f"Отмена запуска {records[0]['run_id']}:")
        for record in records:
            original, sorted_path = movement_paths(history, record)
            print(f"  {display_path(sorted_path, root)} -> {display_path(original, root)}")
        if not confirm(automatic):
            return 0
        result = print_report(undo_moves(history, records), root, "Возвращено файлов")
        return max(result, int(any(notice.error for notice in notices)))


def run_sort(root: Path, settings: Settings, config_path: Path, automatic: bool) -> int:
    with History(root) as history:
        notices = recover_pending(history)
        print_notices(notices, root)
        plan = build_plan(root, settings, excluded={config_path})
        print_plan(plan)
        errors = int(any(notice.error for notice in plan.notices + notices))
        if not plan.moves:
            return errors
        if not confirm(automatic):
            return 0
        result = print_report(apply_plan(plan, history), root, "Перемещено файлов")
        return max(result, errors)


def execute(arguments: argparse.Namespace) -> int:
    root = resolve_root(arguments.source)
    if arguments.command == "history":
        return run_history(root, arguments.limit)
    if arguments.command == "undo":
        return run_undo(root, arguments.yes)
    config_path = arguments.config.expanduser().resolve()
    settings = load_settings(config_path)
    if arguments.command == "duplicates":
        report = find_duplicates(root, settings, excluded={config_path})
        for number, group in enumerate(report.groups, start=1):
            print(f"Группа {number}:")
            for path in group:
                print(f"  {display_path(path, root)}")
        print_notices(report.notices, root)
        print(f"Проверено файлов: {report.scanned}; групп дубликатов: {len(report.groups)}.")
        return int(any(notice.error for notice in report.notices))
    if arguments.command == "sort":
        return run_sort(root, settings, config_path, arguments.yes)
    plan = build_plan(root, settings, excluded={config_path})
    print_plan(plan)
    return int(any(notice.error for notice in plan.notices))


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_help()
        return 0
    try:
        return execute(arguments)
    except (SorterError, OSError, sqlite3.Error) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nОперация прервана. Журнал будет проверен при следующей сортировке или отмене.", file=sys.stderr)
        return 130
