"""Commit, push, and status boundary tests."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest
from conftest import PublicationFixture, run

from ekpempsis.application import Publisher
from ekpempsis.cli import main
from ekpempsis.errors import EkpempsisError, PublicationUnconfirmedError
from ekpempsis.model import Config
from ekpempsis.process import ProcessResult, Runner, SubprocessRunner


@dataclass
class FixedProvider:
    state: str
    calls: int = 0

    def status(self, config: Config) -> str:
        assert config.target.repository == "owner/site"
        self.calls += 1
        return self.state


@dataclass
class FailingProvider:
    calls: int = 0

    def status(self, config: Config) -> str:
        del config
        self.calls += 1
        raise EkpempsisError("planted provider failure")


class FailingRunner:
    def __init__(self, failure_prefix: tuple[str, ...]) -> None:
        self.failure_prefix = failure_prefix
        self.delegate: Runner = SubprocessRunner()

    def run(self, arguments: Sequence[str], cwd: Path) -> ProcessResult:
        if tuple(arguments[: len(self.failure_prefix)]) == self.failure_prefix:
            raise EkpempsisError(f"planted {' '.join(self.failure_prefix)} failure")
        return self.delegate.run(arguments, cwd)


@pytest.mark.parametrize("provider_state", ["building", "built", "errored"])
def test_publish_reaches_disposable_bare_remote_and_reports_state(
    publication: PublicationFixture, provider_state: str
) -> None:
    publication.route_push_to_bare_remote()
    provider = FixedProvider(provider_state)
    committed, state = Publisher(provider=provider).publish(
        publication.config, "Publish fixture"
    )
    assert committed is True
    assert state == provider_state
    assert provider.calls == 1
    assert publication.remote_head()


def test_publish_pushes_clean_checkout_ahead_of_remote(
    publication: PublicationFixture,
) -> None:
    publication.route_push_to_bare_remote()
    publisher = Publisher(provider=FixedProvider("built"))
    publisher.sync(publication.config)
    run(
        "git",
        "add",
        "--",
        "index.html",
        "README.md",
        "document.pdf",
        cwd=publication.checkout,
    )
    run("git", "commit", "-m", "Prepared publication", cwd=publication.checkout)
    local_head = run("git", "rev-parse", "HEAD", cwd=publication.checkout).stdout.strip()
    committed, state = publisher.publish(publication.config, "Unused message")
    assert committed is False
    assert state == "built"
    assert publication.remote_head() == local_head


def test_commit_failure_does_not_push_or_query_provider(
    publication: PublicationFixture,
) -> None:
    publication.route_push_to_bare_remote()
    provider = FixedProvider("built")
    publisher = Publisher(runner=FailingRunner(("git", "commit")), provider=provider)
    with pytest.raises(EkpempsisError, match="planted git commit failure"):
        publisher.publish(publication.config, "Publish fixture")
    assert publication.remote_head() is None
    assert provider.calls == 0


def test_push_failure_does_not_query_provider(publication: PublicationFixture) -> None:
    run(
        "git",
        "remote",
        "set-url",
        "origin",
        "https://github.com/owner/site.git",
        cwd=publication.checkout,
    )
    run(
        "git",
        "remote",
        "set-url",
        "--push",
        "origin",
        str(publication.root / "missing" / "remote.git"),
        cwd=publication.checkout,
    )
    provider = FixedProvider("built")
    with pytest.raises(EkpempsisError, match="git push"):
        Publisher(provider=provider).publish(publication.config, "Publish fixture")
    assert publication.remote_head() is None
    assert provider.calls == 0


@pytest.mark.parametrize(
    "failure",
    ["missing-source", "broken-anchor", "stale-output", "unrelated-change", "wrong-remote"],
)
def test_precondition_failure_never_commits_pushes_or_queries_provider(
    publication: PublicationFixture, failure: str
) -> None:
    if failure != "wrong-remote":
        publication.route_push_to_bare_remote()
    if failure == "missing-source":
        (publication.root / "output" / "document.pdf").unlink()
    elif failure == "broken-anchor":
        index = publication.root / "landing" / "index.html"
        index.write_text(
            index.read_text(encoding="utf-8").replace('id="point"', 'id="other"'),
            encoding="utf-8",
        )
    elif failure == "stale-output":
        (publication.checkout / "old.pdf").write_bytes(b"stale")
        run("git", "add", "old.pdf", cwd=publication.checkout)
        run("git", "commit", "-m", "Stale output", cwd=publication.checkout)
    elif failure == "unrelated-change":
        (publication.checkout / "notes.txt").write_text("private", encoding="utf-8")
    head_before = publication.local_head()
    provider = FixedProvider("built")
    with pytest.raises(EkpempsisError):
        Publisher(provider=provider).publish(publication.config, "Must not publish")
    assert publication.local_head() == head_before
    assert publication.remote_head() is None
    assert provider.calls == 0


def test_provider_failure_reports_that_push_succeeded(
    publication: PublicationFixture,
) -> None:
    publication.route_push_to_bare_remote()
    provider = FailingProvider()
    with pytest.raises(
        PublicationUnconfirmedError,
        match="pushed branch main, but provider availability is unconfirmed",
    ) as caught:
        Publisher(provider=provider).publish(publication.config, "Publish fixture")
    assert caught.value.pushed is True
    assert caught.value.branch == "main"
    assert publication.remote_head()
    assert provider.calls == 1


def test_cli_reports_partial_publication_outcome(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class UnconfirmedPublisher:
        def publish(self, path: str, message: str) -> tuple[bool, str]:
            del path, message
            raise PublicationUnconfirmedError("main", "planted provider failure")

    monkeypatch.setattr("ekpempsis.cli.Publisher", UnconfirmedPublisher)
    with pytest.raises(SystemExit, match="1"):
        main(["publish", "--config", "ekpempsis.yml"])
    assert capsys.readouterr().err == (
        "ekpempsis: pushed branch main, but provider availability is unconfirmed: "
        "planted provider failure\n"
    )


def test_status_uses_injected_provider_without_local_sources(
    publication: PublicationFixture,
) -> None:
    (publication.root / "output" / "document.pdf").unlink()
    provider = FixedProvider("building")
    assert Publisher(provider=provider).status(publication.config) == "building"
    assert provider.calls == 1
