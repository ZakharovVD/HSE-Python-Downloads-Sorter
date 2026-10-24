import shutil
import sqlite3
import sys
from pathlib import Path
from tempfile import mkdtemp

from downloads_sorter.config import DEFAULT_CONFIG, load_settings
from downloads_sorter.history import History
from downloads_sorter.models import STATE_DIRECTORY, SorterError
from downloads_sorter.planner import build_plan
from downloads_sorter.service import apply_plan


def main() -> int:
    try:
        runs = Path(__file__).resolve().parent / "runs"
        runs.mkdir(exist_ok=True)
        folder = Path(mkdtemp(prefix="run-", dir=runs)) / "downloads"
        print("Копирую загрузки...", flush=True)
        shutil.copytree(
            Path.home() / "Downloads", folder, symlinks=True, ignore=shutil.ignore_patterns(STATE_DIRECTORY)
        )
        plan = build_plan(folder, load_settings(DEFAULT_CONFIG))
        with History(folder) as history:
            result = apply_plan(plan, history)
        completed = set(result.completed)
        moves_file = folder.parent / "moved_files.txt"
        with moves_file.open("w", encoding="utf-8") as stream:
            for move in plan.moves:
                if move.destination in completed:
                    stream.write(f"{move.source.name!r} -> {str(move.destination.relative_to(folder))!r}\n")
    except (OSError, sqlite3.Error, SorterError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1

    print(f"Копия: {folder}")
    print(f"Перемещено файлов: {len(result.completed)}")
    print(f"Список перемещений: {moves_file}")
    unmoved = [notice for notice in plan.notices if notice.error or not notice.path.is_dir()]
    unmoved.extend(notice for notice in result.notices if notice.error)
    if unmoved:
        print("Не перемещены:")
        for notice in unmoved:
            print(f"  {str(notice.path.relative_to(folder))!r}: {notice.message}")
    else:
        print("Все файлы перемещены.")
    return int(any(notice.error for notice in unmoved))


if __name__ == "__main__":
    sys.exit(main())
