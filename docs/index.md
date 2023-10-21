# Welcome to Loom
Loom is a small build system in Python.

Loom executes workflows in Asyncio, through lazy evaluation and memoization.
The `Lazy` class contains a `asyncio.lock` and a `Result` object. When multiple
tasks ask for the result of the same dependent task, the lock makes sure a
computation is perforemed only once. Once the lock is free, all future requests
immediately return the memoized result.

      .------.        .------. 
     |  Lazy  | -->  |  Task  |
      `------'        `------' 

      .--------.        .--------. 
     |  LazyDB  | -->  |  TaskDB  |
      `--------'        `--------' 



``` {.python file=loom/__init__.py}
from .program import Program, resolve_tasks
from .task import Task, TaskDB, Target

__all__ = ["Program", "resolve_tasks", "Task", "TaskDB", "Target"]
```


``` {.python file=loom/logging.py}
import logging


def logger():
    return logging.getLogger("loom")

```

``` {.python file=loom/cli.py}
from argparse import ArgumentParser
from pathlib import Path
import re
from typing import Optional
import argh  # type: ignore
import asyncio

from loom.utility import read_from_file
from rich_argparse import RichHelpFormatter

from .program import Program, resolve_tasks
from .target import Target
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
    jobs = [db.run(Target.from_str(t)) for t in target_strs]
    await asyncio.gather(*jobs)


@argh.arg(
    "path",
    help="Loom TOML or JSON file, use a `[...]` suffix to indicate a subsection.",
)
@argh.arg("targets", nargs="*", help="name of targets to run", default="phony(all)")
@argh.arg("-B", "--force-run", help="rebuild all dependencies")
@argh.arg("-j", "--jobs", help="limit number of concurrent jobs")
def loom(
    path: str, targets: list[str], force_run: bool = False, jobs: Optional[int] = None
):
    """Build one of the configured targets."""
    if not targets:
        targets = ["phony(all)"]

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
```
