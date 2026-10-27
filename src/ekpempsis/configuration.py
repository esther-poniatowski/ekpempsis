"""Load the closed, versioned YAML configuration."""

import re
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn, cast

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

from .errors import EkpempsisError
from .model import Config, FileMapping, ProviderName, Target, Transform
from .process import Runner, SubprocessRunner

_TOP_KEYS = {"version", "target", "entrypoint", "files", "max_entrypoint_bytes"}
_TARGET_KEYS = {"repository", "checkout", "branch", "provider"}
_FILE_KEYS = {"source", "target", "transform"}
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class _UniqueKeyLoader(yaml.SafeLoader):
    """Load safe YAML while rejecting every duplicate mapping key."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: MappingNode, deep: bool = False
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as error:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from error
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _fail(location: str, message: str) -> NoReturn:
    raise EkpempsisError(f"{location}: {message}")


def _mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        _fail(location, "expected a mapping with string keys")
    return cast(Mapping[str, Any], value)


def _closed(value: Mapping[str, Any], admitted: set[str], location: str) -> None:
    unknown = sorted(set(value) - admitted)
    if unknown:
        _fail(location, f"unknown field(s): {', '.join(unknown)}")


def _string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(location, "expected a non-empty string")
    return value


def _relative(value: Any, location: str) -> PurePosixPath:
    text = _string(value, location)
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or not path.parts
        or path.as_posix() != text
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        _fail(location, "expected a normalized relative path without '.' or '..'")
    return path


def _repository_root(config_path: Path, runner: Runner) -> Path:
    result = runner.run(["git", "rev-parse", "--show-toplevel"], config_path.parent)
    root = Path(result.stdout.strip()).resolve()
    try:
        config_path.resolve().relative_to(root)
    except ValueError:
        _fail("configuration", "file is outside the consumer repository")
    return root


def load_config(
    path: str | Path,
    runner: Runner | None = None,
    *,
    require_sources: bool = True,
) -> Config:
    """Load and validate an Ekpempsis configuration."""

    config_path = Path(path).resolve()
    if not config_path.is_file():
        raise EkpempsisError(f"configuration does not exist: {config_path}")
    try:
        loaded = yaml.load(config_path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise EkpempsisError(f"cannot parse {config_path}: {error}") from error
    data = _mapping(loaded, "configuration")
    _closed(data, _TOP_KEYS, "configuration")
    if data.get("version") != 1:
        _fail("version", "only version 1 is supported")

    target_data = _mapping(data.get("target"), "target")
    _closed(target_data, _TARGET_KEYS, "target")
    repository = _string(target_data.get("repository"), "target.repository")
    if not _REPOSITORY.fullmatch(repository):
        _fail("target.repository", "expected owner/repository")
    checkout_path = _relative(target_data.get("checkout"), "target.checkout")
    branch = _string(target_data.get("branch"), "target.branch")
    provider_value = _string(target_data.get("provider"), "target.provider")
    if provider_value != "github-pages":
        _fail("target.provider", "admitted value is github-pages")
    provider = cast(ProviderName, provider_value)

    files_value = data.get("files")
    if not isinstance(files_value, Sequence) or isinstance(files_value, (str, bytes)) or not files_value:
        _fail("files", "expected a non-empty sequence")
    raw_files = files_value
    mappings: list[tuple[PurePosixPath, PurePosixPath, Transform | None]] = []
    targets: set[PurePosixPath] = set()
    for index, raw in enumerate(raw_files):
        location = f"files[{index}]"
        item = _mapping(raw, location)
        _closed(item, _FILE_KEYS, location)
        source = _relative(item.get("source"), f"{location}.source")
        target_path = _relative(item.get("target"), f"{location}.target")
        if target_path in targets:
            _fail(f"{location}.target", f"duplicate target {target_path}")
        collision = next(
            (
                existing
                for existing in targets
                if existing in target_path.parents or target_path in existing.parents
            ),
            None,
        )
        if collision is not None:
            _fail(f"{location}.target", f"target hierarchy collides with {collision}")
        targets.add(target_path)
        transform_value = item.get("transform")
        if transform_value is not None and transform_value != "strip-yaml-frontmatter":
            _fail(f"{location}.transform", "admitted value is strip-yaml-frontmatter")
        mappings.append((source, target_path, cast(Transform | None, transform_value)))

    entrypoint = _relative(data.get("entrypoint"), "entrypoint")
    if entrypoint not in targets:
        _fail("entrypoint", "must name one declared target")
    max_bytes = data.get("max_entrypoint_bytes")
    if max_bytes is not None and (not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0):
        _fail("max_entrypoint_bytes", "expected a positive integer")

    active_runner = runner or SubprocessRunner()
    root = _repository_root(config_path, active_runner)
    checkout = (root / Path(*checkout_path.parts)).resolve()
    try:
        checkout.relative_to(root)
    except ValueError:
        _fail("target.checkout", "resolved path escapes the consumer repository")

    resolved: list[FileMapping] = []
    for index, (source_relative, target_path, transform) in enumerate(mappings):
        source_path = (root / Path(*source_relative.parts)).resolve()
        try:
            source_path.relative_to(root)
        except ValueError:
            _fail(f"files[{index}].source", "resolved source escapes the consumer repository")
        if require_sources and not source_path.is_file():
            _fail(f"files[{index}].source", f"source does not exist: {source_relative}")
        resolved.append(FileMapping(source_path, target_path, transform))

    return Config(
        path=config_path,
        repository_root=root,
        target=Target(repository, checkout, branch, provider),
        entrypoint=entrypoint,
        files=tuple(resolved),
        max_entrypoint_bytes=max_bytes,
    )
