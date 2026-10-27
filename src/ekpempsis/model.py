"""Typed values shared by configuration, synchronization, and publication."""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

Transform = Literal["strip-yaml-frontmatter"]
ProviderName = Literal["github-pages"]


@dataclass(frozen=True)
class FileMapping:
    """Map one repository source to one path in the publication image."""

    source: Path
    target: PurePosixPath
    transform: Transform | None = None


@dataclass(frozen=True)
class Target:
    """Identify the publication checkout and its remote state."""

    repository: str
    checkout: Path
    branch: str
    provider: ProviderName


@dataclass(frozen=True)
class Config:
    """Declare one exact publication image."""

    path: Path
    repository_root: Path
    target: Target
    entrypoint: PurePosixPath
    files: tuple[FileMapping, ...]
    max_entrypoint_bytes: int | None = None

    @property
    def targets(self) -> tuple[str, ...]:
        """Return declared target paths in configuration order."""

        return tuple(mapping.target.as_posix() for mapping in self.files)
