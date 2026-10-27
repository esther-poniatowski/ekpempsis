"""Coordinate configuration, image construction, Git, and provider status."""

from pathlib import Path

from .configuration import load_config
from .errors import PublicationUnconfirmedError
from .git import commit_image, push, verify_checkout
from .image import candidate_image, install_image, validate_image
from .model import Config
from .process import Runner, SubprocessRunner
from .providers import GitHubPagesProvider, StatusProvider


class Publisher:
    """Serve the three public operations over injectable external boundaries."""

    def __init__(self, runner: Runner | None = None, provider: StatusProvider | None = None) -> None:
        self.runner = runner or SubprocessRunner()
        self.provider = provider or GitHubPagesProvider(self.runner)

    def load(self, path: str | Path) -> Config:
        """Load one configuration through the active process boundary."""

        return load_config(path, self.runner)

    def sync_config(self, config: Config) -> None:
        """Validate and install a complete publication image without Git mutation."""

        verify_checkout(config, self.runner)
        with candidate_image(config) as image_root:
            validate_image(config, image_root)
            install_image(config, image_root)

    def sync(self, path: str | Path) -> Config:
        """Load, validate, and install one publication image."""

        config = self.load(path)
        self.sync_config(config)
        return config

    def publish(self, path: str | Path, message: str) -> tuple[bool, str]:
        """Synchronize, commit declared changes, push, and report provider state."""

        config = self.load(path)
        self.sync_config(config)
        committed = commit_image(config, self.runner, message)
        push(config, self.runner)
        try:
            state = self.provider.status(config)
        except Exception as error:
            raise PublicationUnconfirmedError(config.target.branch, str(error)) from error
        return committed, state

    def status(self, path: str | Path) -> str:
        """Return the publication provider state without changing local or remote state."""

        return self.provider.status(load_config(path, self.runner, require_sources=False))
