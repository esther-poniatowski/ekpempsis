"""Command-line interface for Ekpempsis."""

import argparse
import sys
from collections.abc import Sequence

from .application import Publisher
from .errors import EkpempsisError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ekpempsis")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("sync", "status"):
        command = commands.add_parser(name)
        command.add_argument("--config", required=True)
    publish = commands.add_parser("publish")
    publish.add_argument("--config", required=True)
    publish.add_argument(
        "--message",
        default="Publish the declared files",
        help="commit message used when synchronization changes the publication image",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run one command and present one diagnostic on failure."""

    arguments = _parser().parse_args(argv)
    publisher = Publisher()
    try:
        if arguments.command == "sync":
            config = publisher.sync(arguments.config)
            print(f"synchronized {len(config.files)} files; nothing committed or pushed")
        elif arguments.command == "publish":
            committed, state = publisher.publish(arguments.config, arguments.message)
            action = "committed and pushed" if committed else "pushed existing state"
            print(f"{action}; provider status: {state}")
        else:
            print(publisher.status(arguments.config))
    except EkpempsisError as error:
        print(f"ekpempsis: {error}", file=sys.stderr)
        raise SystemExit(1) from error
