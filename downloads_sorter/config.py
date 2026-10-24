import json
from pathlib import Path

from .models import STATE_DIRECTORY, Category, ConfigError, Settings

DEFAULT_CONFIG = Path(__file__).with_name("rules.json")
INVALID_NAME_CHARACTERS = set('/\\<>:"|?*')
WINDOWS_RESERVED_NAMES = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)
}


def validate_directory_name(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ConfigError("Имя категории должно быть непустой строкой без пробелов по краям.")
    if (
        value.startswith(".")
        or value.endswith(".")
        or any(character in INVALID_NAME_CHARACTERS or ord(character) < 32 for character in value)
        or value.split(".")[0].casefold() in WINDOWS_RESERVED_NAMES
        or value.casefold() == STATE_DIRECTORY.casefold()
    ):
        raise ConfigError(f"Недопустимое имя папки категории: {value!r}.")
    return value


def require_fields(value: object, fields: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{label}: ожидается JSON-объект.")
    missing = fields - value.keys()
    unknown = value.keys() - fields
    if missing:
        raise ConfigError(f"{label}: отсутствуют поля {', '.join(sorted(missing))}.")
    if unknown:
        raise ConfigError(f"{label}: неизвестные поля {', '.join(sorted(unknown))}.")
    return value


def read_strings(value: object, label: str, extensions: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ConfigError(f"{label}: ожидается список строк.")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or item != item.strip():
            raise ConfigError(f"{label}: элементы должны быть непустыми строками без пробелов по краям.")
        if extensions and (
            not item.startswith(".")
            or len(item) < 2
            or item.endswith(".")
            or any(character in INVALID_NAME_CHARACTERS or character.isspace() for character in item)
            or any(ord(character) < 32 for character in item)
        ):
            raise ConfigError(f"{label}: неверное расширение {item!r}; пример правильного: '.pdf'.")
        result.append(item.casefold())
    return tuple(dict.fromkeys(result))


def load_settings(path: Path) -> Settings:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigError(f"Не удалось прочитать конфиг {path}: {error}") from error
    data = require_fields(data, {"categories", "fallback_category", "skip_extensions"}, "Конфиг")
    if not isinstance(data["categories"], list):
        raise ConfigError("categories: ожидается список категорий.")
    categories = []
    names = set()
    for index, value in enumerate(data["categories"], start=1):
        value = require_fields(value, {"name", "keywords", "extensions"}, f"Категория {index}")
        name = validate_directory_name(value["name"])
        if name.casefold() in names:
            raise ConfigError(f"Категория {name!r} повторяется.")
        names.add(name.casefold())
        categories.append(
            Category(
                name,
                read_strings(value["keywords"], f"{name}: keywords"),
                read_strings(value["extensions"], f"{name}: extensions", extensions=True),
            )
        )
    fallback = validate_directory_name(data["fallback_category"])
    for category in categories:
        if category.name.casefold() == fallback.casefold() and category.name != fallback:
            raise ConfigError("Резервная категория должна совпадать с существующей также по регистру.")
    return Settings(
        tuple(categories),
        fallback,
        read_strings(data["skip_extensions"], "skip_extensions", extensions=True),
    )
