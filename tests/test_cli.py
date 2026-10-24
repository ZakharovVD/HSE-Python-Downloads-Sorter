import os
import subprocess
import sys
from pathlib import Path

from tests.helpers import FolderTestCase

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CliTests(FolderTestCase):
    def run_cli(self, command: str, *arguments: str, answer: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "downloads_sorter", command, "--source", str(self.root), *arguments],
            input=answer,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"},
            timeout=10,
        )

    def test_cli_plan_sort_history_duplicates_and_undo(self) -> None:
        lecture = self.make_file("лекция.pdf", b"lecture")
        first = self.make_file("first.jpg", b"picture")
        second = self.make_file("second.png", b"picture")
        before = self.tree_snapshot()
        result = self.run_cli("plan")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.tree_snapshot(), before)
        result = self.run_cli("sort", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(lecture.exists())
        self.assertEqual((self.root / "Учёба/лекция.pdf").read_bytes(), b"lecture")
        result = self.run_cli("history")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("перемещено: 3", result.stdout)
        result = self.run_cli("duplicates")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("групп дубликатов: 1", result.stdout)
        result = self.run_cli("undo", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(lecture.read_bytes(), b"lecture")
        self.assertEqual(first.read_bytes(), b"picture")
        self.assertEqual(second.read_bytes(), b"picture")

    def test_sort_requires_confirmation(self) -> None:
        source = self.make_file("report.pdf", b"keep")
        result = self.run_cli("sort", answer="нет\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(source.read_bytes(), b"keep")
        self.assertFalse((self.root / "Документы/report.pdf").exists())

    def test_invalid_config_is_reported_without_traceback_or_file_changes(self) -> None:
        source = self.make_file("report.pdf", b"keep")
        config = self.make_file("rules.json", b"{bad json")
        before = self.tree_snapshot()
        result = self.run_cli("sort", "--yes", "--config", str(config))
        self.assertEqual(result.returncode, 1)
        self.assertIn("Ошибка", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.tree_snapshot(), before)
        self.assertEqual(source.read_bytes(), b"keep")
