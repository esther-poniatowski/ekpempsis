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
    """Identify the publication checkout and its remote state.

    ``path`` names the folder of the checkout that the configuration owns. Without it, the
    configuration owns the whole checkout; with it, several configurations can publish into one
    repository, each in its own folder.
    """

    repository: str
    checkout: Path
    branch: str
    provider: ProviderName
    path: PurePosixPath | None = None


@dataclass(frozen=True)
class Config:
    """Declare one exact publication image."""

    path: Path
    repository_root: Path
    target: Target
    entrypoint: PurePosixPath
    files: tuple[FileMapping, ...]
    max_entrypoint_bytes: int | None = None

    def in_checkout(self, path: PurePosixPath) -> PurePosixPath:
        """Return a path of the publication image as a path of the checkout."""

        return self.target.path / path if self.target.path is not None else path

    def owns(self, checkout_path: str) -> bool:
        """Return whether a checkout path lies in the folder that the configuration owns."""

        if self.target.path is None:
            return True
        return self.target.path in PurePosixPath(checkout_path).parents

    @property
    def targets(self) -> tuple[str, ...]:
        """Return declared target paths of the checkout, in configuration order."""

        return tuple(self.in_checkout(mapping.target).as_posix() for mapping in self.files)
