"""Git preconditions and publication operations."""

import re
from collections.abc import Iterable
from pathlib import Path

from .errors import EkpempsisError
from .model import Config
from .process import Runner


def _git(
    runner: Runner,
    checkout: Path,
    *arguments: str,
    preserve_output: bool = False,
) -> str:
    output = runner.run(["git", *arguments], checkout).stdout
    return output if preserve_output else output.strip()


def _remote_identity(url: str) -> str:
    value = url.strip()
    match = re.fullmatch(r"git@github\.com:(.+?)(?:\.git)?", value)
    if match:
        return match.group(1)
    match = re.fullmatch(r"https?://github\.com/(.+?)(?:\.git)?/?", value)
    if match:
        return match.group(1)
    return value.removesuffix(".git")


def verify_checkout(config: Config, runner: Runner) -> None:
    """Verify checkout identity, exact tracked set, and unrelated worktree state."""

    checkout = config.target.checkout
    if not checkout.is_dir():
        raise EkpempsisError(f"publication checkout does not exist: {checkout}")
    root = Path(_git(runner, checkout, "rev-parse", "--show-toplevel")).resolve()
    if root != checkout.resolve():
        raise EkpempsisError(f"publication checkout is not a Git worktree root: {checkout}")
    branch = _git(runner, checkout, "branch", "--show-current")
    if branch != config.target.branch:
        raise EkpempsisError(
            f"publication checkout is on {branch or 'detached HEAD'}, expected {config.target.branch}"
        )
    origin = _remote_identity(_git(runner, checkout, "remote", "get-url", "origin"))
    if origin.casefold() != config.target.repository.casefold():
        raise EkpempsisError(
            f"publication checkout origin is {origin}, expected {config.target.repository}"
        )

    declared = set(config.targets)
    tracked = set(
        filter(
            None,
            _git(runner, checkout, "ls-files", "-z", preserve_output=True).split("\0"),
        )
    )
    stale = sorted(tracked - declared)
    if stale:
        raise EkpempsisError(f"stale tracked publication target(s): {', '.join(stale)}")

    status = _git(
        runner,
        checkout,
        "status",
        "--porcelain=v1",
        "-z",
        "--no-renames",
        "--untracked-files=all",
        preserve_output=True,
    )
    records = [record for record in status.split("\0") if record]
    unrelated: list[str] = []
    for record in records:
        path = record[3:]
        if path not in declared:
            unrelated.append(path)
    if unrelated:
        raise EkpempsisError(f"unrelated checkout change(s): {', '.join(sorted(unrelated))}")


def commit_image(config: Config, runner: Runner, message: str) -> bool:
    """Commit declared changes and return whether a commit was created."""

    checkout = config.target.checkout
    targets = list(config.targets)
    _git(runner, checkout, "add", "--", *targets)
    staged = set(
        filter(
            None,
            _git(
                runner,
                checkout,
                "diff",
                "--cached",
                "--name-only",
                "-z",
                preserve_output=True,
            ).split("\0"),
        )
    )
    unexpected = sorted(staged - set(targets))
    if unexpected:
        raise EkpempsisError(f"refusing to commit undeclared path(s): {', '.join(unexpected)}")
    if not staged:
        return False
    _git(runner, checkout, "commit", "-m", message)
    return True


def push(config: Config, runner: Runner) -> None:
    """Push the configured branch without force."""

    _git(
        runner,
        config.target.checkout,
        "push",
        "--set-upstream",
        "origin",
        config.target.branch,
    )


def iter_tracked(config: Config, runner: Runner) -> Iterable[str]:
    """Return tracked paths for diagnostics and tests."""

    output = _git(
        runner,
        config.target.checkout,
        "ls-files",
        "-z",
        preserve_output=True,
    )
    return tuple(filter(None, output.split("\0")))
