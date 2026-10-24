import json
from copy import deepcopy
from pathlib import Path

from downloads_sorter.config import load_settings
from downloads_sorter.models import ConfigError

from tests.helpers import FolderTestCase


class ConfigTests(FolderTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.data = {
            "categories": [{"name": "Учёба", "keywords": ["ЛЕКЦИЯ"], "extensions": [".PDF"]}],
            "fallback_category": "Прочее",
            "skip_extensions": [".PART"],
        }

    def write_config(self, data: object) -> Path:
        return self.make_file("rules.json", json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def test_valid_config_normalizes_matching_rules(self) -> None:
        settings = load_settings(self.write_config(self.data))
        self.assertEqual(settings.categories[0].name, "Учёба")
        self.assertEqual(settings.categories[0].keywords, ("лекция",))
        self.assertEqual(settings.categories[0].extensions, (".pdf",))
        self.assertEqual(settings.skip_extensions, (".part",))

    def test_incorrect_schema_is_rejected(self) -> None:
        invalid = [None, [], {}, {**self.data, "typo": True}, {**self.data, "categories": {}}]
        for field, value in (("keywords", "лекция"), ("keywords", [""]), ("extensions", ["pdf"])):
            data = deepcopy(self.data)
            data["categories"][0][field] = value
            invalid.append(data)
        for data in invalid:
            with self.subTest(data=data):
                with self.assertRaises(ConfigError):
                    load_settings(self.write_config(data))

    def test_unsafe_category_names_are_rejected(self) -> None:
        names = ("", ".", "..", "../outside", "/tmp/outside", "a/b", "a\\b", ".sorter-state", "CON", "name ")
        for name in names:
            with self.subTest(name=name):
                data = deepcopy(self.data)
                data["categories"][0]["name"] = name
                with self.assertRaises(ConfigError):
                    load_settings(self.write_config(data))
