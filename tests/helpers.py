from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from downloads_sorter.models import Category, Settings


class FolderTestCase(TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory(prefix="downloads-sorter-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.settings = Settings(
            categories=(
                Category("Учёба", ("лекция", "семинар"), ()),
                Category("Документы", (), (".pdf", ".txt")),
                Category("Изображения", (), (".jpg", ".png")),
                Category("Архивы", (), (".zip", ".tar.gz")),
            ),
            fallback_category="Прочее",
            skip_extensions=(".part", ".crdownload", ".tmp"),
        )

    def make_file(self, name: str, content: bytes = b"content") -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def make_symlink(self, name: str, target: Path, directory: bool = False) -> Path:
        link = self.root / name
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Символические ссылки недоступны в окружении: {error}")
        return link

    def tree_snapshot(self) -> dict[str, bytes | str | None]:
        result = {}
        for path in self.root.rglob("*"):
            if path.is_symlink():
                content = str(path.readlink())
            else:
                content = path.read_bytes() if path.is_file() else None
            result[path.relative_to(self.root).as_posix()] = content
        return result
