from downloads_sorter.duplicates import find_duplicates

from tests.helpers import FolderTestCase


class DuplicateTests(FolderTestCase):
    def test_identical_contents_are_found_across_categories_without_changes(self) -> None:
        first = self.make_file("first.jpg", b"same")
        second = self.make_file("Изображения/other.png", b"same")
        self.make_file("different.jpg", b"diff")
        self.make_file("larger.jpg", b"same plus more")
        before = self.tree_snapshot()
        result = find_duplicates(self.root, self.settings)
        self.assertEqual({frozenset(group) for group in result.groups}, {frozenset((first, second))})
        self.assertEqual(result.scanned, 4)
        self.assertEqual(self.tree_snapshot(), before)
        self.assertFalse((self.root / ".sorter-state").exists())
