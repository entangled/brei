# ~/~ begin <<docs/implementation.md#brei/cli.py>>[init]
from argparse import ArgumentParser
from pathlib import Path
import re
import sys
import textwrap
import tomllib
from typing import Optional, Any
import argh  # type: ignore
import asyncio
from rich.console import Console

from rich_argparse import RichHelpFormatter
from rich.table import Table

from .runner import DEFAULT_RUNNERS
from .errors import HelpfulUserError, UserError
from .lazy import Phony
from .utility import construct, read_from_file
from .program import Program, resolve_tasks
from .logging import logger, configure_logger
from .version import __version__
from .result import Result

log = logger()


async def main(
    program: Program, target_strs: list[str], force_run: bool, throttle: Optional[int]
):
    db = await resolve_tasks(program, history_path=Path(".brei_history"))
    if throttle:
        db.throttle = asyncio.Semaphore(throttle)
    db.force_run = force_run

    with db.persistent_history():
        results: list[Result[Any]] = await asyncio.gather(*(db.run(Phony(t), db=db) for t in target_strs))

    if not all(results):
        log.error("Some jobs have failed:")
        for r in results:
            if not r:
                msg = textwrap.indent(str(r), "| ")
                log.error(msg)


@argh.arg("targets", nargs="*", help="names of tasks to run")
@argh.arg(
    "-i",
    "--input-file",
    help="Brei TOML or JSON file, use a `[...]` suffix to indicate a subsection.",
)
@argh.arg("-B", "--force-run", help="rebuild all dependencies")
@argh.arg("-j", "--jobs", help="limit number of concurrent jobs")
@argh.arg("-v", "--version", help="print version number and exit")
@argh.arg("--list-runners", help="show default configured runners")
@argh.arg("--debug", help="more verbose logging")
def brei(
    targets: list[str],
    *,
    input_file: Optional[str] = None,
    force_run: bool = False,
    jobs: Optional[int] = None,
    version: bool = False,
    list_runners: bool = False,
    debug: bool = False
):
    """Build one of the configured targets."""
    if version:
        print(f"Brei {__version__}, Copyright (c) 2023 Netherlands eScience Center.")
        print("Licensed under the Apache License, Version 2.0.")
        sys.exit(0)

    if list_runners:
        t = Table(title="Default Runners", header_style="italic green", show_edge=False)
        t.add_column("runner", style="bold yellow")
        t.add_column("executable")
        t.add_column("arguments")
        for r, c in DEFAULT_RUNNERS.items():
            t.add_row(r, c.command, f"{c.args}")
        console = Console()
        console.print(t)
        sys.exit(0)

    if input_file is not None:
        if m := re.match(r"([^\[\]]+)\[([^\[\]\s]+)\]", input_file):
            input_path = Path(m.group(1))
            section = m.group(2)
        else:
            input_path = Path(input_file)
            section = None

        program = read_from_file(Program, input_path, section)

    elif Path("brei.toml").exists():
        program = read_from_file(Program, Path("brei.toml"))

    elif Path("pyproject.toml").exists():
        with open("pyproject.toml", "rb") as f_in:
            data = tomllib.load(f_in)
        try:
            for s in ["tool", "brei"]:
                data = data[s]
        except KeyError as e:
            raise HelpfulUserError(
                f"With out the `-f` argument, Brei looks for `brei.toml` first, then for "
                f"a `[tool.brei]` section in `pyproject.toml`. A `pyproject.toml` file was "
                f"found, but contained no `[tool.brei]` section."
            ) from e

        program = construct(Program, data)
    else:
        raise HelpfulUserError(
            "No input file given, no `loom.toml` found and no `pyproject.toml` found."
        )

    jobs = int(jobs) if jobs else None
    configure_logger(debug)
    try:
        asyncio.run(main(program, targets, force_run, jobs))
    except UserError as e:
        log.error(f"Failed: {e}")


def cli():
    parser = ArgumentParser(formatter_class=RichHelpFormatter)
    argh.set_default_command(parser, brei)
    argh.dispatch(parser)


if __name__ == "__main__":
    cli()
# ~/~ end
