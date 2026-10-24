import errno
from pathlib import Path
from unittest.mock import patch

from downloads_sorter.history import History, has_history
from downloads_sorter.planner import build_plan
from downloads_sorter.service import apply_plan, undo_moves

from tests.helpers import FolderTestCase


class ServiceTests(FolderTestCase):
    def test_sort_and_undo_preserve_contents_and_persist_history(self) -> None:
        lecture = self.make_file("лекция.pdf", b"lecture")
        report_file = self.make_file("report.pdf", b"new report")
        existing = self.make_file("Документы/report.pdf", b"existing report")
        with History(self.root) as history:
            result = apply_plan(build_plan(self.root, self.settings), history)
            self.assertEqual(len(result.completed), 2)
            self.assertFalse(any(notice.error for notice in result.notices))
        self.assertFalse(lecture.exists())
        self.assertFalse(report_file.exists())
        self.assertEqual((self.root / "Учёба/лекция.pdf").read_bytes(), b"lecture")
        self.assertEqual((self.root / "Документы/report (1).pdf").read_bytes(), b"new report")
        self.assertTrue(has_history(self.root))
        with History(self.root) as history:
            self.assertEqual(len(history.latest_moves()), 2)
            result = undo_moves(history, history.latest_moves())
            self.assertEqual(len(result.completed), 2)
            self.assertFalse(history.latest_moves())
        self.assertEqual(lecture.read_bytes(), b"lecture")
        self.assertEqual(report_file.read_bytes(), b"new report")
        self.assertEqual(existing.read_bytes(), b"existing report")

    def test_file_changed_after_preview_is_not_moved(self) -> None:
        source = self.make_file("report.pdf", b"original")
        plan = build_plan(self.root, self.settings)
        source.write_bytes(b"changed after preview")
        with History(self.root) as history:
            result = apply_plan(plan, history)
            self.assertFalse(result.completed)
            self.assertTrue(any(notice.error for notice in result.notices))
            self.assertFalse(history.summaries(10))
        self.assertEqual(source.read_bytes(), b"changed after preview")

    def test_partial_undo_skips_changed_file_and_can_be_retried(self) -> None:
        first = self.make_file("first.pdf", b"first original")
        second = self.make_file("second.pdf", b"second original")
        with History(self.root) as history:
            apply_plan(build_plan(self.root, self.settings), history)
            changed = self.root / "Документы/first.pdf"
            changed.write_bytes(b"modified by user")
            result = undo_moves(history, history.latest_moves())
            self.assertEqual(result.completed, [second])
            self.assertTrue(any(notice.error for notice in result.notices))
            self.assertFalse(first.exists())
            self.assertEqual(changed.read_bytes(), b"modified by user")
            self.assertEqual(len(history.latest_moves()), 1)
            changed.write_bytes(b"first original")
            retry = undo_moves(history, history.latest_moves())
            self.assertEqual(retry.completed, [first])
            self.assertFalse(history.latest_moves())
        self.assertEqual(first.read_bytes(), b"first original")
        self.assertEqual(second.read_bytes(), b"second original")

    def test_undo_does_not_overwrite_occupied_original_name(self) -> None:
        source = self.make_file("report.pdf", b"sorted content")
        with History(self.root) as history:
            apply_plan(build_plan(self.root, self.settings), history)
            source.write_bytes(b"new unrelated file")
            result = undo_moves(history, history.latest_moves())
            self.assertFalse(result.completed)
            self.assertTrue(any(notice.error for notice in result.notices))
            self.assertEqual(len(history.latest_moves()), 1)
        self.assertEqual(source.read_bytes(), b"new unrelated file")
        self.assertEqual((self.root / "Документы/report.pdf").read_bytes(), b"sorted content")

    def test_access_error_rolls_back_second_name_and_other_files_are_processed(self) -> None:
        denied = self.make_file("denied.pdf", b"preserve")
        other = self.make_file("other.pdf", b"move")
        original_unlink = Path.unlink

        def unlink_with_access_error(path: Path, *args, **kwargs) -> None:
            if path == denied:
                raise PermissionError(errno.EACCES, "Нет доступа", str(path))
            original_unlink(path, *args, **kwargs)

        with History(self.root) as history:
            plan = build_plan(self.root, self.settings)
            with patch.object(Path, "unlink", unlink_with_access_error):
                result = apply_plan(plan, history)
            self.assertEqual(result.completed, [self.root / "Документы/other.pdf"])
            self.assertTrue(any(notice.error for notice in result.notices))
            self.assertFalse(history.pending_moves())
        self.assertEqual(denied.read_bytes(), b"preserve")
        self.assertFalse((self.root / "Документы/denied.pdf").exists())
        self.assertFalse(other.exists())
