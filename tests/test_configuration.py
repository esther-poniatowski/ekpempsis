"""Configuration contract tests."""

from pathlib import Path

import pytest
from conftest import PublicationFixture

from ekpempsis.configuration import load_config
from ekpempsis.errors import EkpempsisError


def test_configuration_rejects_unknown_field(publication: PublicationFixture) -> None:
    publication.write_config("unexpected: true\n")
    with pytest.raises(EkpempsisError, match="unknown field"):
        load_config(publication.config)


@pytest.mark.parametrize(
    "old, duplicate",
    [
        ("version: 1", "version: 1\nversion: 1"),
        ("  branch: main", "  branch: main\n  branch: main"),
        (
            "    transform: strip-yaml-frontmatter",
            "    transform: strip-yaml-frontmatter\n    transform: strip-yaml-frontmatter",
        ),
    ],
)
def test_configuration_rejects_duplicate_yaml_keys(
    publication: PublicationFixture, old: str, duplicate: str
) -> None:
    publication.config.write_text(
        publication.config.read_text(encoding="utf-8").replace(old, duplicate, 1),
        encoding="utf-8",
    )
    with pytest.raises(EkpempsisError, match="duplicate key"):
        load_config(publication.config)


def test_configuration_rejects_duplicate_target(publication: PublicationFixture) -> None:
    text = publication.config.read_text(encoding="utf-8")
    publication.config.write_text(
        text + "  - source: output/document.pdf\n    target: document.pdf\n",
        encoding="utf-8",
    )
    with pytest.raises(EkpempsisError, match="duplicate target"):
        load_config(publication.config)


def test_configuration_rejects_target_hierarchy_collision(
    publication: PublicationFixture,
) -> None:
    text = publication.config.read_text(encoding="utf-8")
    publication.config.write_text(
        text.replace("target: README.md", "target: assets")
        + "  - source: output/document.pdf\n    target: assets/document.pdf\n",
        encoding="utf-8",
    )
    with pytest.raises(EkpempsisError, match="target hierarchy collides"):
        load_config(publication.config)


def test_configuration_rejects_source_symlink_escape(
    publication: PublicationFixture, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.html"
    outside.write_text("outside", encoding="utf-8")
    source = publication.root / "landing" / "index.html"
    source.unlink()
    source.symlink_to(outside)
    with pytest.raises(EkpempsisError, match="escapes the consumer repository"):
        load_config(publication.config)


def test_configuration_rejects_path_escape(publication: PublicationFixture) -> None:
    publication.config.write_text(
        publication.config.read_text(encoding="utf-8").replace(
            "target: document.pdf", "target: ../document.pdf"
        ),
        encoding="utf-8",
    )
    with pytest.raises(EkpempsisError, match="normalized relative path"):
        load_config(publication.config)


@pytest.mark.parametrize("invalid", [".", "assets//document.pdf"])
def test_configuration_rejects_non_normalized_target(
    publication: PublicationFixture, invalid: str
) -> None:
    publication.config.write_text(
        publication.config.read_text(encoding="utf-8").replace(
            "target: document.pdf", f"target: {invalid}"
        ),
        encoding="utf-8",
    )
    with pytest.raises(EkpempsisError, match="normalized relative path"):
        load_config(publication.config)


def test_configuration_rejects_missing_source(publication: PublicationFixture) -> None:
    (publication.root / "output" / "document.pdf").unlink()
    with pytest.raises(EkpempsisError, match="source does not exist"):
        load_config(publication.config)
