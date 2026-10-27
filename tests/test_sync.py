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
