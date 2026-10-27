"""Construct, validate, and install one publication image."""

import os
import re
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from .errors import EkpempsisError
from .model import Config, FileMapping

_FRONTMATTER = re.compile(br"\A---\r?\n.*?\r?\n---\r?\n(?:\r?\n)?", re.DOTALL)
_ALLOWED_EXTERNAL_SCHEMES = {"http", "https", "mailto"}


class _HTMLReferences(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.identifiers: set[str] = set()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        for name, value in attrs:
            if value is None:
                continue
            if name in {"id", "name"}:
                self.identifiers.add(value)
            elif name in {"href", "src"}:
                self.references.append(value)


def _write_mapping(mapping: FileMapping, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = mapping.source.read_bytes()
    if mapping.transform == "strip-yaml-frontmatter":
        data = _FRONTMATTER.sub(b"", data, count=1)
    destination.write_bytes(data)
    shutil.copymode(mapping.source, destination, follow_symlinks=False)


@contextmanager
def candidate_image(config: Config) -> Iterator[Path]:
    """Yield a complete candidate image in a temporary directory."""

    with tempfile.TemporaryDirectory(prefix="ekpempsis-") as temporary:
        root = Path(temporary)
        try:
            for mapping in config.files:
                _write_mapping(mapping, root / Path(*mapping.target.parts))
        except OSError as error:
            raise EkpempsisError(f"could not construct publication image: {error}") from error
        yield root


def _parse_html(path: Path) -> _HTMLReferences:
    parser = _HTMLReferences()
    try:
        parser.feed(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, OSError) as error:
        raise EkpempsisError(f"cannot parse HTML target {path.name}: {error}") from error
    return parser


def _local_target(current: PurePosixPath, reference: str) -> tuple[PurePosixPath, str]:
    split = urlsplit(reference)
    if split.scheme:
        if split.scheme.lower() not in _ALLOWED_EXTERNAL_SCHEMES:
            raise EkpempsisError(f"unsupported URI scheme in {current}: {reference}")
        return PurePosixPath(), ""
    if split.netloc:
        raise EkpempsisError(f"scheme-relative URI is not admitted in {current}: {reference}")
    decoded = unquote(split.path)
    if decoded.startswith("/"):
        raise EkpempsisError(f"local reference escapes the publication root in {current}: {reference}")
    raw = current.parent / decoded if decoded else current
    parts: list[str] = []
    for part in raw.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise EkpempsisError(
                    f"local reference escapes the publication root in {current}: {reference}"
                )
            parts.pop()
        else:
            parts.append(part)
    return PurePosixPath(*parts), unquote(split.fragment)


def validate_image(config: Config, image_root: Path) -> None:
    """Validate size, local references, and fragments in a candidate image."""

    entrypoint = image_root / Path(*config.entrypoint.parts)
    if config.max_entrypoint_bytes is not None:
        size = entrypoint.stat().st_size
        if size > config.max_entrypoint_bytes:
            raise EkpempsisError(
                f"entrypoint is {size} bytes; maximum is {config.max_entrypoint_bytes} bytes"
            )

    parsed: dict[PurePosixPath, _HTMLReferences] = {}
    for target_text in config.targets:
        relative = PurePosixPath(target_text)
        if relative.suffix.lower() in {".html", ".htm"}:
            parsed[relative] = _parse_html(image_root / Path(*relative.parts))

    for current, document in parsed.items():
        for reference in document.references:
            target, fragment = _local_target(current, reference)
            if not target.parts:
                continue
            target_path = image_root / Path(*target.parts)
            if not target_path.is_file():
                raise EkpempsisError(f"broken local reference in {current}: {reference}")
            if fragment:
                target_document = parsed.get(target)
                if target_document is None or fragment not in target_document.identifiers:
                    raise EkpempsisError(f"broken fragment in {current}: {reference}")


def install_image(config: Config, image_root: Path) -> None:
    """Replace declared targets and restore their prior bytes if installation fails."""

    checkout = config.target.checkout
    checkout_root = checkout.resolve()
    for target_text in config.targets:
        target = PurePosixPath(target_text)
        relative_parent = Path(*target.parts).parent
        cursor = checkout
        for part in relative_parent.parts:
            cursor /= part
            if cursor.is_symlink():
                raise EkpempsisError(f"target parent is a symlink: {target}")
        try:
            (checkout / relative_parent).resolve().relative_to(checkout_root)
        except ValueError as error:
            raise EkpempsisError(
                f"target parent escapes the publication checkout: {target}"
            ) from error

    with tempfile.TemporaryDirectory(prefix="ekpempsis-backup-") as temporary:
        backup = Path(temporary)
        existing: set[PurePosixPath] = set()
        installed: list[PurePosixPath] = []
        temporary_targets: list[Path] = []
        for target_text in config.targets:
            target = PurePosixPath(target_text)
            current = checkout / Path(*target.parts)
            if current.exists():
                existing.add(target)
                saved = backup / Path(*target.parts)
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(current, saved)
        try:
            for target_text in config.targets:
                target = PurePosixPath(target_text)
                source = image_root / Path(*target.parts)
                destination = checkout / Path(*target.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                descriptor, temporary_name = tempfile.mkstemp(
                    dir=destination.parent,
                    prefix=f".{destination.name}.ekpempsis-",
                )
                os.close(descriptor)
                temporary_target = Path(temporary_name)
                temporary_targets.append(temporary_target)
                shutil.copy2(source, temporary_target)
                os.replace(temporary_target, destination)
                temporary_targets.remove(temporary_target)
                installed.append(target)
        except OSError as error:
            for target in reversed(installed):
                destination = checkout / Path(*target.parts)
                saved = backup / Path(*target.parts)
                if target in existing:
                    shutil.copy2(saved, destination)
                else:
                    destination.unlink(missing_ok=True)
            raise EkpempsisError(f"could not install publication image: {error}") from error
        finally:
            for temporary_target in temporary_targets:
                temporary_target.unlink(missing_ok=True)
