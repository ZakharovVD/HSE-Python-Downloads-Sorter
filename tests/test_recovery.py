import os

from downloads_sorter.filesystem import file_digest
from downloads_sorter.history import History
from downloads_sorter.service import recover_pending

from tests.helpers import FolderTestCase


class RecoveryTests(FolderTestCase):
    def test_sort_recovers_each_interruption_phase(self) -> None:
        for phase in ("before_link", "after_link", "after_unlink"):
            with self.subTest(phase=phase):
                folder = self.root / phase
                source = self.make_file(f"{phase}/report.pdf", b"recover")
                target = folder / "Документы/report.pdf"
                target.parent.mkdir()
                with History(folder) as history:
                    record = history.add_move(history.create_run(), source, target, file_digest(source))
                    if phase != "before_link":
                        os.link(source, target)
                    if phase == "after_unlink":
                        source.unlink()
                with History(folder) as history:
                    notices = recover_pending(history)
                    self.assertFalse(history.pending_moves())
                    self.assertFalse(any(notice.error for notice in notices))
                    expected = "failed" if phase == "before_link" else "moved"
                    self.assertEqual(history.move_status(record["id"]), expected)
                if phase == "before_link":
                    self.assertEqual(source.read_bytes(), b"recover")
                    self.assertFalse(target.exists())
                else:
                    self.assertEqual(target.read_bytes(), b"recover")
                    self.assertFalse(source.exists())

    def test_undo_recovers_each_interruption_phase(self) -> None:
        for phase in ("before_link", "after_link", "after_unlink"):
            with self.subTest(phase=phase):
                folder = self.root / phase
                source = self.make_file(f"{phase}/report.pdf", b"recover undo")
                target = folder / "Документы/report.pdf"
                target.parent.mkdir()
                with History(folder) as history:
                    record = history.add_move(history.create_run(), source, target, file_digest(source))
                    os.link(source, target)
                    source.unlink()
                    history.set_status(record["id"], "undo_pending")
                    if phase != "before_link":
                        os.link(target, source)
                    if phase == "after_unlink":
                        target.unlink()
                with History(folder) as history:
                    recover_pending(history)
                    self.assertFalse(history.pending_moves())
                    expected = "moved" if phase == "before_link" else "undone"
                    self.assertEqual(history.move_status(record["id"]), expected)
                restored = target if phase == "before_link" else source
                removed = source if phase == "before_link" else target
                self.assertEqual(restored.read_bytes(), b"recover undo")
                self.assertFalse(removed.exists())
