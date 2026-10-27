"""Git-backed fixtures for publication behavior."""

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest


def run(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, cwd=cwd, check=True, capture_output=True, text=True)


@dataclass
class PublicationFixture:
    root: Path
    checkout: Path
    remote: Path
    config: Path

    def route_push_to_bare_remote(self) -> None:
        run(
            "git",
            "remote",
            "set-url",
            "origin",
            "https://github.com/owner/site.git",
            cwd=self.checkout,
        )
        run(
            "git",
            "remote",
            "set-url",
            "--push",
            "origin",
            str(self.remote),
            cwd=self.checkout,
        )

    def remote_head(self) -> str | None:
        result = subprocess.run(
            ["git", "--git-dir", str(self.remote), "rev-parse", "--verify", "refs/heads/main"],
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def local_head(self) -> str | None:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=self.checkout,
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def write_config(self, extra: str = "") -> None:
        self.config.write_text(
            """version: 1
target:
  repository: owner/site
  checkout: deploy
  branch: main
  provider: github-pages
entrypoint: index.html
max_entrypoint_bytes: 30720
files:
  - source: landing/index.html
    target: index.html
  - source: landing/README.md
    target: README.md
    transform: strip-yaml-frontmatter
  - source: output/document.pdf
    target: document.pdf
"""
            + extra,
            encoding="utf-8",
        )


@pytest.fixture
def publication(tmp_path: Path) -> Iterator[PublicationFixture]:
    root = tmp_path / "consumer"
    checkout = root / "deploy"
    remote = tmp_path / "remote.git"
    (root / "landing").mkdir(parents=True)
    (root / "output").mkdir()
    (root / "landing" / "index.html").write_text(
        '<!doctype html><a href="#point">Point</a><a href="document.pdf">Document</a>'
        '<section id="point">Result</section>',
        encoding="utf-8",
    )
    (root / "landing" / "README.md").write_text(
        "---\nrole: section\n---\n\n# Landing page\n", encoding="utf-8"
    )
    (root / "output" / "document.pdf").write_bytes(b"%PDF fixture\n")
    run("git", "init", "-b", "main", cwd=root)
    run("git", "config", "user.email", "test@example.com", cwd=root)
    run("git", "config", "user.name", "Test", cwd=root)
    run("git", "init", "--bare", str(remote), cwd=tmp_path)
    checkout.mkdir()
    run("git", "init", "-b", "main", cwd=checkout)
    run("git", "config", "user.email", "test@example.com", cwd=checkout)
    run("git", "config", "user.name", "Test", cwd=checkout)
    run("git", "remote", "add", "origin", str(remote), cwd=checkout)
    fixture = PublicationFixture(root, checkout, remote, root / "ekpempsis.yml")
    fixture.write_config()
    yield fixture
