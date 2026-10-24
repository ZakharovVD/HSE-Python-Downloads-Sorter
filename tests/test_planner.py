from dataclasses import replace

from downloads_sorter.planner import build_plan

from tests.helpers import FolderTestCase


class PlannerTests(FolderTestCase):
    def test_keywords_take_priority_over_earlier_extension_rules(self) -> None:
        source = self.make_file("ЛЕКЦИЯ.PDF")
        settings = replace(self.settings, categories=(self.settings.categories[1], self.settings.categories[0]))
        plan = build_plan(self.root, settings)
        self.assertEqual(plan.moves[0].source, source)
        self.assertEqual(plan.moves[0].destination, self.root / "Учёба" / source.name)

    def test_conflicts_preserve_extensions_and_existing_files(self) -> None:
        cases = (
            ("report.pdf", "Документы", "report (2).pdf", "report (1).pdf"),
            ("bundle.tar.gz", "Архивы", "bundle (1).tar.gz", None),
            ("notes", "Прочее", "notes (1)", None),
        )
        for filename, category, expected, occupied in cases:
            with self.subTest(filename=filename):
                self.make_file(filename, b"new")
                self.make_file(f"{category}/{filename}", b"existing")
                if occupied is not None:
                    self.make_file(f"{category}/{occupied}", b"existing suffix")
                before = self.tree_snapshot()
                move = next(move for move in build_plan(self.root, self.settings).moves if move.source.name == filename)
                self.assertEqual(move.destination.name, expected)
                self.assertEqual(self.tree_snapshot(), before)

    def test_temporary_hidden_nested_and_config_files_are_skipped(self) -> None:
        self.make_file("good.pdf")
        self.make_file("unfinished.PART")
        self.make_file("browser.crdownload")
        self.make_file(".hidden.pdf")
        self.make_file("nested/lecture.pdf")
        config = self.make_file("rules.json")
        plan = build_plan(self.root, self.settings, excluded={config})
        self.assertEqual([move.source.name for move in plan.moves], ["good.pdf"])
        self.assertEqual(len(plan.notices), 5)
        self.assertFalse(any(notice.error for notice in plan.notices))

    def test_category_cannot_be_a_file_or_symlink(self) -> None:
        source = self.make_file("report.pdf")
        category = self.make_file("Документы")
        plan = build_plan(self.root, self.settings)
        self.assertTrue(any(notice.path == source and notice.error for notice in plan.notices))
        category.unlink()
        outside = self.root / "outside"
        outside.mkdir()
        self.make_symlink("Документы", outside, directory=True)
        plan = build_plan(self.root, self.settings)
        self.assertTrue(any(notice.path == source and notice.error for notice in plan.notices))
        self.assertFalse(list(outside.iterdir()))
