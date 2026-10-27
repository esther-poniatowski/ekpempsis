"""Checked subprocess execution."""

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .errors import EkpempsisError


@dataclass(frozen=True)
class ProcessResult:
    """Hold the observable result of a command."""

    stdout: str
    stderr: str
    returncode: int


class Runner(Protocol):
    """Execute a command without a shell."""

    def run(self, arguments: Sequence[str], cwd: Path) -> ProcessResult:
        """Run ``arguments`` in ``cwd`` and return all output."""


class SubprocessRunner:
    """Run commands through ``subprocess`` without shell interpretation."""

    def run(self, arguments: Sequence[str], cwd: Path) -> ProcessResult:
        """Run a command and raise one diagnostic when it fails."""

        completed = subprocess.run(
            list(arguments),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
        result = ProcessResult(completed.stdout, completed.stderr, completed.returncode)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic"
            raise EkpempsisError(f"command failed ({' '.join(arguments)}): {detail}")
        return result
