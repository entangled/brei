# ~/~ begin <<docs/index.md#loom/cli.py>>[init]
from argparse import ArgumentParser
from pathlib import Path
import re
from typing import Optional
import argh  # type: ignore
import asyncio
from loom.lazy import Phony

from loom.utility import read_from_file
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


@argh.arg(
    "path",
    help="Loom TOML or JSON file, use a `[...]` suffix to indicate a subsection.",
)
@argh.arg("targets", nargs="+", help="names of tasks to run")
@argh.arg("-B", "--force-run", help="rebuild all dependencies")
@argh.arg("-j", "--jobs", help="limit number of concurrent jobs")
def loom(
    path: str, targets: list[str], force_run: bool = False, jobs: Optional[int] = None
):
    """Build one of the configured targets."""
    if m := re.match(path, r"([^\[\]]+)\[([^\[\]\s]+)\]"):
        input_path = Path(m.group(1))
        section = m.group(2)
    else:
        input_path = Path(path)
        section = None

    program = read_from_file(Program, input_path, section)
    asyncio.run(main(program, targets, force_run, jobs))


def cli():
    parser = ArgumentParser(formatter_class=RichHelpFormatter)
    argh.set_default_command(parser, loom)
    argh.dispatch(parser)


if __name__ == "__main__":
    cli()
# ~/~ end
