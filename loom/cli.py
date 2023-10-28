# ~/~ begin <<docs/index.md#loom/cli.py>>[init]
from argparse import ArgumentParser
from pathlib import Path
import re
import tomllib
from typing import Optional
import argh  # type: ignore
import asyncio
from loom.errors import HelpfulUserError
from loom.lazy import Phony

from loom.utility import construct, read_from_file
from rich_argparse import RichHelpFormatter

from .program import Program, resolve_tasks
from .logging import logger

log = logger()


async def main(
    program: Program, target_strs: list[str], force_run: bool, throttle: Optional[int]
):
    db = await resolve_tasks(program)
    for t in db.tasks:
        log.debug(str(t))
    if throttle:
        db.throttle = asyncio.Semaphore(throttle)
    db.force_run = force_run
    await asyncio.gather(*(db.run(Phony(t), db) for t in target_strs))


@argh.arg("targets", nargs="+", help="names of tasks to run")
@argh.arg(
    "-f", "--input-file",
    help="Loom TOML or JSON file, use a `[...]` suffix to indicate a subsection.",
)
@argh.arg("-B", "--force-run", help="rebuild all dependencies")
@argh.arg("-j", "--jobs", help="limit number of concurrent jobs")
def loom(
    targets: list[str],
    input_file: Optional[str] = None,
    *,
    force_run: bool = False,
    jobs: Optional[int] = None
):
    """Build one of the configured targets."""
    if input_file is not None:
        if m := re.match(input_file, r"([^\[\]]+)\[([^\[\]\s]+)\]"):
            input_path = Path(m.group(1))
            section = m.group(2)
        else:
            input_path = Path(input_file)
            section = None

        program = read_from_file(Program, input_path, section)

    elif Path("loom.toml").exists():
        program = read_from_file(Program, Path("loom.toml"))

    elif Path("pyproject.toml").exists():
        section = "tool.loom"
        with open("pyproject.toml", "rb") as f_in:
            data = tomllib.load(f_in)
        try:
            for s in ["tool", "loom"]:
                data = data[s]
        except KeyError as e:
            raise HelpfulUserError(
                f"With out the `-f` argument, Loom looks for `loom.toml` first, then for "
                f"a `[tool.loom]` section in `pyproject.toml`. A `pyproject.toml` file was "
                f"found, but contained no `[tool.loom]` section."
            ) from e

        program = construct(Program, data)
    else:
        raise HelpfulUserError(
            "No input file given, no `loom.toml` found and no `pyproject.toml` found."
        )

    asyncio.run(main(program, targets, force_run, jobs))


def cli():
    parser = ArgumentParser(formatter_class=RichHelpFormatter)
    argh.set_default_command(parser, loom)
    argh.dispatch(parser)


if __name__ == "__main__":
    cli()
# ~/~ end
