"""Transactional synchronization and validation tests."""

import os
from pathlib import Path

import pytest
from conftest import PublicationFixture, run

from ekpempsis.application import Publisher
from ekpempsis.errors import EkpempsisError


def _accept_local_remote(publication: PublicationFixture) -> None:
    run(
        "git",
        "remote",
        "set-url",
        "origin",
        "https://github.com/owner/site.git",
        cwd=publication.checkout,
    )


def test_sync_is_deterministic_and_strips_frontmatter(publication: PublicationFixture) -> None:
    _accept_local_remote(publication)
    publisher = Publisher()
    publisher.sync(publication.config)
    first = {path.name: path.read_bytes() for path in publication.checkout.iterdir() if path.is_file()}
    publisher.sync(publication.config)
    second = {path.name: path.read_bytes() for path in publication.checkout.iterdir() if path.is_file()}
    assert first == second
    assert first["README.md"] == b"# Landing page\n"
    assert first["document.pdf"] == b"%PDF fixture\n"


def test_sync_accepts_unstaged_changes_to_declared_targets(
    publication: PublicationFixture,
) -> None:
    _accept_local_remote(publication)
    publisher = Publisher()
    publisher.sync(publication.config)
    run("git", "add", "--", "index.html", "README.md", "document.pdf", cwd=publication.checkout)
    run("git", "commit", "-m", "Accepted publication", cwd=publication.checkout)
    (publication.checkout / "index.html").write_text("local drift", encoding="utf-8")

    status = run("git", "status", "--porcelain=v1", cwd=publication.checkout).stdout
    assert status.startswith(" M index.html")
    publisher.sync(publication.config)

    assert (publication.checkout / "index.html").read_bytes() == (
        publication.root / "landing" / "index.html"
    ).read_bytes()


@pytest.mark.parametrize(
    ("old_reference", "new_reference", "message"),
    [
        ('href="document.pdf"', 'href="missing"', "broken local reference"),
        ('href="#point"', 'href="#missing"', "broken fragment"),
    ],
)
def test_validation_failure_leaves_checkout_unchanged(
    publication: PublicationFixture, old_reference: str, new_reference: str, message: str
) -> None:
    _accept_local_remote(publication)
    existing = publication.checkout / "index.html"
    existing.write_text("accepted", encoding="utf-8")
    source = publication.root / "landing" / "index.html"
    source.write_text(
        source.read_text(encoding="utf-8").replace(old_reference, new_reference),
        encoding="utf-8",
    )
    with pytest.raises(EkpempsisError, match=message):
        Publisher().sync(publication.config)
    assert existing.read_text(encoding="utf-8") == "accepted"
    assert not (publication.checkout / "README.md").exists()


def test_stale_tracked_output_blocks_sync(publication: PublicationFixture) -> None:
    _accept_local_remote(publication)
    stale = publication.checkout / "old.pdf"
    stale.write_bytes(b"old")
    run("git", "add", "old.pdf", cwd=publication.checkout)
    run("git", "commit", "-m", "stale", cwd=publication.checkout)
    with pytest.raises(EkpempsisError, match="stale tracked"):
        Publisher().sync(publication.config)
    assert stale.read_bytes() == b"old"


def test_wrong_remote_blocks_sync(publication: PublicationFixture) -> None:
    with pytest.raises(EkpempsisError, match="origin is"):
        Publisher().sync(publication.config)


def test_unrelated_dirty_file_blocks_sync(publication: PublicationFixture) -> None:
    _accept_local_remote(publication)
    (publication.checkout / "notes.txt").write_text("private", encoding="utf-8")
    with pytest.raises(EkpempsisError, match="unrelated checkout change"):
        Publisher().sync(publication.config)


def test_staged_rename_is_reported_as_an_unrelated_target(
    publication: PublicationFixture,
) -> None:
    _accept_local_remote(publication)
    publisher = Publisher()
    publisher.sync(publication.config)
    run("git", "add", "--", "index.html", "README.md", "document.pdf", cwd=publication.checkout)
    run("git", "commit", "-m", "Accepted publication", cwd=publication.checkout)
    run("git", "mv", "index.html", "renamed.html", cwd=publication.checkout)

    with pytest.raises(EkpempsisError, match="renamed.html"):
        publisher.sync(publication.config)


def test_symlinked_target_parent_blocks_sync(
    publication: PublicationFixture, tmp_path: Path
) -> None:
    _accept_local_remote(publication)
    outside = tmp_path / "outside"
    outside.mkdir()
    (publication.checkout / "assets").symlink_to(outside, target_is_directory=True)
    (publication.checkout / ".git" / "info" / "exclude").write_text(
        "assets\n", encoding="utf-8"
    )
    publication.config.write_text(
        publication.config.read_text(encoding="utf-8").replace(
            "target: document.pdf", "target: assets/document.pdf"
        ),
        encoding="utf-8",
    )
    index = publication.root / "landing" / "index.html"
    index.write_text(
        index.read_text(encoding="utf-8").replace("document.pdf", "assets/document.pdf"),
        encoding="utf-8",
    )
    with pytest.raises(EkpempsisError, match="target parent is a symlink"):
        Publisher().sync(publication.config)
    assert not (outside / "document.pdf").exists()


def test_install_failure_rolls_back_every_replaced_target(
    publication: PublicationFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    _accept_local_remote(publication)
    publisher = Publisher()
    publisher.sync(publication.config)
    before = {
        path.name: path.read_bytes()
        for path in publication.checkout.iterdir()
        if path.is_file()
    }
    (publication.root / "landing" / "index.html").write_text(
        '<!doctype html><a href="document.pdf">Changed</a>', encoding="utf-8"
    )
    real_replace = os.replace
    calls = 0

    def fail_second_replace(source: str | Path, destination: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("planted replacement failure")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_second_replace)
    with pytest.raises(EkpempsisError, match="planted replacement failure"):
        publisher.sync(publication.config)
    after = {
        path.name: path.read_bytes()
        for path in publication.checkout.iterdir()
        if path.is_file()
    }
    assert after == before
    assert not list(publication.checkout.glob(".*.ekpempsis-*"))


def _scope(publication: PublicationFixture, path: str = "events/workshop") -> None:
    publication.write_config()
    text = publication.config.read_text(encoding="utf-8")
    publication.config.write_text(
        text.replace("  provider: github-pages\n", f"  provider: github-pages\n  path: {path}\n"),
        encoding="utf-8",
    )


def test_owned_path_installs_into_its_folder_and_ignores_other_owners(
    publication: PublicationFixture,
) -> None:
    _accept_local_remote(publication)
    _scope(publication)
    other = publication.checkout / "events" / "other" / "index.html"
    other.parent.mkdir(parents=True)
    other.write_text("another owner", encoding="utf-8")
    run("git", "add", "--", "events/other/index.html", cwd=publication.checkout)
    run("git", "commit", "-m", "Another owner", cwd=publication.checkout)
    other.write_text("another owner, edited", encoding="utf-8")

    Publisher().sync(publication.config)

    owned = publication.checkout / "events" / "workshop"
    assert sorted(path.name for path in owned.iterdir()) == ["README.md", "document.pdf", "index.html"]
    assert not (publication.checkout / "index.html").exists()
    assert other.read_text(encoding="utf-8") == "another owner, edited"


def test_owned_path_rejects_an_undeclared_file_inside_its_folder(
    publication: PublicationFixture,
) -> None:
    _accept_local_remote(publication)
    _scope(publication)
    stale = publication.checkout / "events" / "workshop" / "old.html"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")
    run("git", "add", "--", "events/workshop/old.html", cwd=publication.checkout)
    run("git", "commit", "-m", "Stale page", cwd=publication.checkout)

    with pytest.raises(EkpempsisError, match="stale tracked publication target"):
        Publisher().sync(publication.config)


def test_owned_path_rejects_a_reference_that_leaves_its_folder(
    publication: PublicationFixture,
) -> None:
    _accept_local_remote(publication)
    _scope(publication)
    index = publication.root / "landing" / "index.html"
    index.write_text(
        index.read_text(encoding="utf-8").replace('href="document.pdf"', 'href="../other/index.html"'),
        encoding="utf-8",
    )

    with pytest.raises(EkpempsisError, match="leaves the owned target path"):
        Publisher().sync(publication.config)
