from dataclasses import dataclass, field
from pathlib import Path

STATE_DIRECTORY = ".sorter-state"


class SorterError(Exception):
    pass


class ConfigError(SorterError):
    pass


class HistoryError(SorterError):
    pass


@dataclass(frozen=True)
class Category:
    name: str
    keywords: tuple[str, ...]
    extensions: tuple[str, ...]


@dataclass(frozen=True)
class Settings:
    categories: tuple[Category, ...]
    fallback_category: str
    skip_extensions: tuple[str, ...]

    @property
    def directory_names(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys([category.name for category in self.categories] + [self.fallback_category]))


@dataclass(frozen=True)
class Fingerprint:
    device: int
    inode: int
    size: int
    modified_ns: int


@dataclass(frozen=True)
class PlannedMove:
    source: Path
    destination: Path
    reason: str
    fingerprint: Fingerprint


@dataclass(frozen=True)
class Notice:
    path: Path
    message: str
    error: bool = False


@dataclass
class Plan:
    root: Path
    moves: list[PlannedMove] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)


@dataclass
class Report:
    completed: list[Path] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)


@dataclass
class DuplicateReport:
    groups: list[list[Path]] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)
    scanned: int = 0
