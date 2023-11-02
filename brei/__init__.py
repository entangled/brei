# ~/~ begin <<docs/implementation.md#brei/__init__.py>>[init]
"""
Welcome to Brei's API documentation. There are two ways to use Brei: from the
command-line (in which case we refer to the homepage for documentation), or
straight from Python. The easiest function to work with is `brei()`, which
links to the command-line app one-to-one.

## Program
If you want to read the `Program` yourself, there are several ways to do so:

1. Use `Program.read()`. You give it a `Path` to a TOML or JSON file and a
section, this last bit giving a object path into the data. For instance:
`Program.read(Path("pyproject.toml"), "tool.brei")`.
2. Read your own data format into JSON compatible data, then
`construct(Program, data)`. The `construct` function uses the type annotations
in dataclasses to validate the input data.

After reading the data, you'll want to resolve all tasks, i.e. perform includes
and run any necessary task to resolve the targets of all other tasks.

    program = Program.read(Path("brei.toml"))
    db: TaskDB = await resolve_tasks(program)
    await db.run(Phony("all"))

There are three kinds of targets: `pathlib.Path`, `Phony` and `Variable`.

## API
"""

from .program import Program, resolve_tasks, TemplateCall
from .construct import construct
from .lazy import Lazy, LazyDB
from .task import Task, TaskDB, Phony, Variable, TaskProxy, Template
from .runner import Runner
from .cli import brei

__all__ = [
    "brei",

    "Lazy", "LazyDB", "Phony", "Program", "Runner", "Task", "TaskDB",
    "TaskProxy", "Template", "TemplateCall", "Variable", "construct",
    "resolve_tasks",
]
# ~/~ end
