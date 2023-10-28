# Welcome to Loom
Loom is a small workflow system in Python. The primary reason for creating Loom is to replace GNU Make, in order to be compatible on systems that are naturally deprived of this wonder of human ingenuity. Design goals are:

- Programmable workflows from TOML description
- Ease of use
- Ease of installation
- Stay minimal: don't give in to feature bloat.

## How it works
You give Loom a list of tasks that may depend on one another. Loom will run these when input files are newer than the target. Execution is lazy and in parallel.

### Tasks
Tasks are the elemental units of work in Loom. A task is the single execution of a given script, and can be indicated to depend on previous tasks by explicitly listing targets and dependencies.

``` {.toml file=examples/tasks.toml}
[[task]]
targets = ["hello.txt"]
language = "Bash"
script = "echo 'Hello, World!' > hello.txt"

[[task]]
name = "all"
dependencies = ["hello.txt"]

[[task]]
name = "clean"
script = "rm hello.txt"
```

This defines to named tasks `all` and `clean`, where `all` depends on the creation of a file `hello.txt`. Giving a `name` to a task is similar to creating a 'phony' target in Make.

### Patterns: Rot13
We can use patterns to create reusable items. Variables follow Python's `string.Template` syntax (similar to many scripting languages), `${var_name}` substitutes for the contents of the `var_name` variable. Use two dollar signs `$$` to make a `$` literal.

``` {.toml file=examples/rot13.toml}
[pattern.echo]
stdout = "${stdout}"
language = "Bash"
script = "echo ${text}"

[pattern.rot13]
stdout = "${stdout}"
stdin = "${stdin}"
language = "Bash"
script = "tr a-zA-Z n-za-mN-ZA-M"

[[call]]
pattern = "echo"
  [call.args]
  stdout = "secret1.txt"
  text = "Uryyb, Jbeyq!"

[[call]]
pattern = "rot13"
  [call.args]
  stdin = "secret.txt"
  stdout = "msg.txt"

[[task]]
name = "all"
dependencies = ["msg.txt"]
```

### Example 3: Writing output to flexible target
For many science applications its desirable to know which version of a software generated some output. You may write the output of a command to the contents of a variable, by using `"var(name)"` as a target.

``` {.toml file=examples/versioned_output.toml}
[environment]
data_dir = "./data"
output_dir = "./output/${commit}"

[[task]]
language = "Bash"
stdout = "var(commit)"
script = "git rev-parse HEAD"

[[task]]
targets = ["${output_dir}/data.h5"]
dependencies = ["${data_dir}/input.h5", "#prepare"]
language = "Python"
path = "scripts/run.py"

[[task]]
name = "prepare"
language = "Bash"
script = "mkdir -p ${output_dir}"

[[task]]
name = "all"
dependencies = ["${output_dir}/data.h5"]
```

Also note the following:

- Instead of listing a `script` you can give a `path` to an existing script.
- Named (phony) targets are referenced with a hash symbol `#`.
- Tasks with no targets are always run.
- The `[environment]` item lists global variables.
- All string substitution is done lazily.

### Includes
You can include parts of a workflow from other files, both TOML and JSON.

``` {.toml file=examples/echo.toml}
[pattern.echo]
language = "Bash"
stdout = "${stdout}"
script = "echo '${text}'"
```

``` {.toml file=examples/hello-includes.toml}
include = [
    "./echo.toml"
]

[[call]]
pattern = "echo"
  [call.args]
  stdout = "hello.txt"
  text = "Hello, World!"

[[task]]
name = "all"
dependencies = ["hello.txt"]
```

It is even possible to include files that still need to be generated.

``` {.toml file=examples/include-gen.toml}
include = [
    "./gen.json"
]

[[task]]
stdout = "./gen.json"
language = "Python"
script = """
import json
tasks = [
    {"stdout": f"out{i}.dat",
     "script": f"echo '{i}'",
     "language": "Bash"} for i in range(10)
]
tasks.append({"name": "write-outs", "dependencies": [
    f"out{i}.dat" for i in range(10)
]})
print(json.dumps(tasks))
"""

[[task]]
name = "all"
dependencies = ["#write-outs"]
```

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
from .task import Task, TaskDB

__all__ = ["Program", "resolve_tasks", "Task", "TaskDB"]
```


``` {.python file=loom/logging.py}
import logging


def logger():
    return logging.getLogger("loom")


logging.basicConfig(level=logging.INFO)
logger().level = logging.INFO
```

``` {.python file=loom/cli.py}
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
```