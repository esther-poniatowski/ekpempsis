"""Publication-provider status adapters."""

from pathlib import Path
from typing import Protocol

from .model import Config
from .process import Runner


class StatusProvider(Protocol):
    """Report whether a pushed publication is available."""

    def status(self, config: Config) -> str:
        """Return the provider state for ``config``."""


class GitHubPagesProvider:
    """Read GitHub Pages state through the authenticated GitHub CLI."""

    def __init__(self, runner: Runner) -> None:
        self._runner = runner

    def status(self, config: Config) -> str:
        """Return the state reported by the GitHub Pages API."""

        result = self._runner.run(
            ["gh", "api", f"repos/{config.target.repository}/pages", "--jq", ".status"],
            Path.cwd(),
        )
        return result.stdout.strip()
