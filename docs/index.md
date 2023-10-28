# Welcome to Brei
Brei is a small workflow system in Python. The primary reason for creating Brei is to replace GNU Make, in order to be compatible on systems that are naturally deprived of this wonder of human ingenuity. Design goals are:

- Programmable workflows from TOML description
- Ease of use
- Ease of installation
- Stay minimal: don't give in to feature bloat.

## How it works
You give Brei a list of tasks that may depend on one another. Brei will run these when input files are newer than the target. Execution is lazy and in parallel.

### Tasks
Tasks are the elemental units of work in Brei. A task is the single execution of a given script, and can be indicated to depend on previous tasks by explicitly listing targets and dependencies.

``` {.toml file=examples/tasks.toml}
[[task]]
creates = ["hello.txt"]
runner = "Bash"
script = "echo 'Hello, World!' > hello.txt"

[[task]]
name = "all"
requires = ["hello.txt"]

[[task]]
name = "clean"
script = "rm hello.txt"
```

This defines to named tasks `all` and `clean`, where `all` depends on the creation of a file `hello.txt`. Giving a `name` to a task is similar to creating a 'phony' target in Make.

### Patterns: Rot13
We can use patterns to create reusable items. Variables follow Python's `string.Template` syntax (similar to many scripting languages), `${var_name}` substitutes for the contents of the `var_name` variable. Use two dollar signs `$$` to make a `$` literal.

``` {.toml file=examples/rot13.toml}
[template.echo]
stdout = "${stdout}"
runner = "Bash"
script = "echo ${text}"

[pattern.rot13]
stdout = "${stdout}"
stdin = "${stdin}"
runner = "Bash"
script = "tr a-zA-Z n-za-mN-ZA-M"

[[call]]
template = "echo"
  [call.args]
  stdout = "secret1.txt"
  text = "Uryyb, Jbeyq!"

[[call]]
template = "rot13"
  [call.args]
  stdin = "secret.txt"
  stdout = "msg.txt"

[[task]]
name = "all"
requires = ["msg.txt"]
```

### Variables: Writing output to flexible target
For many science applications its desirable to know which version of a software generated some output. You may write the output of a command to the contents of a variable, by using `"var(name)"` as a target.

``` {.toml file=examples/versioned_output.toml}
[environment]
data_dir = "./data"
output_dir = "./output/${commit}"

[[task]]
runner = "Bash"
stdout = "var(commit)"
script = "git rev-parse HEAD"

[[task]]
creates = ["${output_dir}/data.h5"]
requires = ["${data_dir}/input.h5", "#prepare"]
runner = "Python"
path = "scripts/run.py"

[[task]]
name = "prepare"
runner = "Bash"
script = "mkdir -p ${output_dir}"

[[task]]
name = "all"
requires = ["${output_dir}/data.h5"]
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
[template.echo]
runner = "Bash"
stdout = "${stdout}"
script = "echo '${text}'"
```

``` {.toml file=examples/hello-includes.toml}
include = [
    "./echo.toml"
]

[[call]]
template = "echo"
  [call.args]
  stdout = "hello.txt"
  text = "Hello, World!"

[[task]]
name = "all"
requires = ["hello.txt"]
```

It is even possible to include files that still need to be generated. The following generates a file with ten tasks, includes that file and runs those tasks.

``` {.toml file=examples/include-gen.toml}
include = [
    "./gen.json"
]

[[task]]
stdout = "./gen.json"
runner = "Python"
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
requires = ["#write-outs"]
```

### Remarks
A lot of the above examples use Bash for brevity. If you need your workflows also execute on a Windows machine, it is advised to write scripts in Python.

``` {.python file=brei/__init__.py}
from .program import Program, resolve_tasks
from .task import Task, TaskDB

__all__ = ["Program", "resolve_tasks", "Task", "TaskDB"]
```


``` {.python file=brei/logging.py}
import logging


def logger():
    return logging.getLogger("brei")


logging.basicConfig(level=logging.INFO)
logger().level = logging.INFO
```

``` {.python file=brei/cli.py}
from argparse import ArgumentParser
from pathlib import Path
import re
import tomllib
from typing import Optional
import argh  # type: ignore
import asyncio

from .errors import HelpfulUserError
from .lazy import Phony

from .utility import construct, read_from_file
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
    await asyncio.gather(*(db.run(Phony(t), db=db) for t in target_strs))


@argh.arg("targets", nargs="+", help="names of tasks to run")
@argh.arg(
    "-i",
    "--input-file",
    help="Brei TOML or JSON file, use a `[...]` suffix to indicate a subsection.",
)
@argh.arg("-B", "--force-run", help="rebuild all dependencies")
@argh.arg("-j", "--jobs", help="limit number of concurrent jobs")
def loom(
    targets: list[str],
    *,
    input_file: Optional[str] = None,
    force_run: bool = False,
    jobs: Optional[int] = None,
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

    asyncio.run(main(program, targets, force_run, jobs))


def cli():
    parser = ArgumentParser(formatter_class=RichHelpFormatter)
    argh.set_default_command(parser, loom)
    argh.dispatch(parser)


if __name__ == "__main__":
    cli()
```
