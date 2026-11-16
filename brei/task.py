# ~/~ begin <<docs/tasks.md#brei/task.py>>[init]
from __future__ import annotations
import asyncio
from collections import defaultdict
from contextlib import contextmanager, nullcontext
from copy import copy
from dataclasses import dataclass, field
from pathlib import Path
import re
import string
import json
from tempfile import NamedTemporaryFile
from typing import Any, DefaultDict, Optional
from asyncio import create_subprocess_exec
from textwrap import indent
import shlex
import hashlib

from .errors import HelpfulUserError
from .result import TaskFailure
from .lazy import MissingDependency, Lazy, LazyDB, Phony
from .utility import stat
from .logging import logger
from .template_strings import gather_args, substitute
from .runner import Runner, DEFAULT_RUNNERS

from msgspec import Struct, field as struct_field


log = logger()


@dataclass
class Variable:
    name: str

    def __hash__(self):
        return hash(f"var({self.name})")

    def __str__(self):
        return f"var({self.name})"


# `listvar(name)` as `stdout` stores the output, split into lines, as a list.
# `splice(name)` as an element of a list inserts the elements of that list.
LIST_VARIABLE = re.compile(r"listvar\(([^\s\(\)]+)\)")
SPLICE = re.compile(r"splice\(([^\s\(\)]+)\)")


def splice_name(s: str) -> str | None:
    """The name of the list variable in `splice(name)`, or `None`."""
    return m.group(1) if (m := SPLICE.fullmatch(s)) else None


def str_to_target(s: str) -> Path | Phony | Variable:
    if s[0] == "#":
        return Phony(s[1:])
    elif m := re.match(r"var\(([^\s\(\)]+)\)", s):
        return Variable(m.group(1))
    elif m := LIST_VARIABLE.fullmatch(s):
        return Variable(m.group(1))
    else:
        return Path(s)


def is_oneliner(s: str) -> bool:
    return len(s.splitlines()) == 1


@dataclass
class Task(Lazy[Path | Phony | Variable, str | list[str] | None]):
    name: Optional[str] = None
    runner: Optional[str] = None
    path: Optional[Path] = None
    script: Optional[str] = None
    stdin: Optional[Path | Variable] = None
    stdout: Optional[Path | Variable] = None
    description: Optional[str] = None
    force: bool = False
    list_output: bool = False

    @property
    def target_paths(self):
        return (p for p in self.creates if isinstance(p, Path))

    @property
    def dependency_paths(self):
        return (p for p in self.requires if isinstance(p, Path))

    @property
    def digest(self) -> str | None:
        if self.script is None:
            return None
        return hashlib.md5(self.script.encode()).hexdigest()

    def __str__(self):
        tgts = ", ".join(str(t) for t in self.creates)
        deps = ", ".join(str(t) for t in self.requires)
        if self.script is not None:
            src = indent(self.script, prefix=" ▎ ", predicate=lambda _: True)
        elif self.path is not None:
            src = str(self.path)
        else:
            src = " - "
        name = f"{self.name}: " if self.name else ""
        return name + f"[{tgts}] <- [{deps}]\n" + src

    def __post_init__(self):
        if self.name and Phony(self.name) not in self.creates:
            self.creates.append(Phony(self.name))
        if self.stdin and self.stdin not in self.requires:
            self.requires.append(self.stdin)
        if self.path and self.path not in self.requires:
            self.requires.append(self.path)
        if self.stdout and self.stdout not in self.creates:
            self.creates.append(self.stdout)

    def always_run(self) -> bool:
        return self.force or len(list(self.target_paths)) == 0

    def needs_run(self, db: TaskDB) -> bool:
        if any(not p.exists() for p in self.target_paths):
            return True
        target_stats = [stat(p) for p in self.target_paths]
        dep_stats = [stat(p) for p in self.dependency_paths]
        if any(t < d for t in target_stats for d in dep_stats):
            return True
        if any(self.digest != db.history.get(p, None) for p in self.target_paths):
            return True
        return False

    @contextmanager
    def get_script_path(self):
        if self.path is not None:
            tmpfile = None
            path = self.path
        elif self.script is not None:
            # On Windows, a file can't be opened by another process while we
            # still have it open, so we close it before running the script.
            with NamedTemporaryFile("w", delete=False) as tmpfile:
                tmpfile.write(self.script)
            path = Path(tmpfile.name)
        else:
            raise ValueError("A `Rule` can have either `path` or `script` defined.")

        try:
            yield path
        finally:
            if tmpfile is not None:
                path.unlink(missing_ok=True)

    @contextmanager
    def get_stdin(self, db: TaskDB):
        """Yields the `stdin` argument for the subprocess, and the data to
        send to it."""
        match self.stdin:
            case Variable(x):
                yield asyncio.subprocess.PIPE, db.environment[x].encode()
            case x if isinstance(x, Path):
                with open(x, "r") as stdin:
                    yield stdin, None
            case _:
                yield None, None

    @contextmanager
    def get_stdout(self):
        match self.stdout:
            case Variable(x):
                yield asyncio.subprocess.PIPE
            case x if isinstance(x, Path):
                with open(x, "w") as stdout:
                    yield stdout
            case _:
                yield None

    @contextmanager
    def get_commands(self, db: TaskDB):
        """Yields the list of commands to run. Without a runner, each line
        of the script is a command; with a runner, the script is written to a
        file (if needed) and passed to the runner."""
        if self.runner is None:
            assert self.script is not None
            if not is_oneliner(self.script):
                assert self.stdin is None
            yield [shlex.split(line) for line in self.script.splitlines()]
            return

        runner = db.runners[self.runner]
        with self.get_script_path() as path:
            args = [string.Template(arg).substitute(script=path) for arg in runner.args]
            yield [[runner.command, *args]]

    def check_return_code(self, returncode: int | None, db: TaskDB):
        """A failing command fails the task. Its targets may be written
        partially, so we forget them, and they are built again next time."""
        if returncode == 0:
            return
        for p in self.target_paths:
            db.history.pop(p, None)
        raise TaskFailure(f"Command failed with exit code {returncode}.")

    async def _exec(self, db: TaskDB, short_note: str, command: list[str],
                    stdin, input_data: bytes | None, stdout) -> bytes:
        """Run a single command, returning its standard output if it was captured."""
        async with db.throttle or nullcontext():
            proc = await create_subprocess_exec(
                *command,
                stdin=stdin,
                stdout=stdout,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_data, stderr_data = await proc.communicate(input_data)
            log.debug(f"return-code {proc.returncode}")
        if stderr_data:
            log.info(f"[gold1]{short_note}[/] %s", stderr_data.decode().rstrip(), extra={"markup": True})
        self.check_return_code(proc.returncode, db)
        return stdout_data or b""

    async def run(self, *, db: TaskDB):
        if not self.always_run() and not self.needs_run(db) and not db.force_run:
            tgts = " ".join(f"`{t}`" for t in self.target_paths)
            log.debug(f"Targets {tgts} already up-to-date.")
            return

        log.debug(f"{self}")
        if self.runner is None and self.script is None:
            return

        targets = " ".join(f"`{t}`" for t in self.creates)
        short_note = self.description or (f"#{self.name}" if self.name else None) \
            or f"creating {targets}"
        log.info(f"[green]{short_note}[/]", extra={'markup': True})

        stdout_data = b""
        with self.get_commands(db) as commands, \
                self.get_stdin(db) as (stdin, input_data), \
                self.get_stdout() as stdout:
            for command in commands:
                stdout_data += await self._exec(db, short_note, command, stdin, input_data, stdout)

        for p in self.target_paths:
            db.history[p] = self.digest

        if self.needs_run(db):
            raise TaskFailure("Task didn't achieve goals.")

        if self.list_output:
            return [line for line in stdout_data.decode().splitlines() if line]
        return stdout_data.decode().strip() if stdout_data else None


class TaskProxy(Struct, forbid_unknown_fields=True):
    """Input to create an actual Task.

    An actual `Task` has no template variables remaining and untyped strings
    are replaced with `Path` `Variable` or `Phony` objects.
    """
    creates: list[str] = struct_field(default_factory=list)
    requires: list[str] = struct_field(default_factory=list)
    name: Optional[str] = None
    runner: Optional[str] = None
    path: Optional[str] = None
    script: Optional[str] = None
    stdin: Optional[str] = None
    stdout: Optional[str] = None
    description: Optional[str] = None
    force: bool = False

    @property
    def all_targets(self):
        return (
            self.creates
            + ([self.stdout] if self.stdout else [])
            + ([f"#{self.name}"] if self.name else [])
        )

    @property
    def all_dependencies(self):
        return (
            self.requires
            + ([self.stdin] if self.stdin else [])
            + ([self.path] if self.path else [])
        )


@dataclass
class TemplateVariable(Lazy[Variable, str]):
    template: str

    def __post_init__(self):
        self.requires += [Variable(arg) for arg in gather_args(self.template)]

    async def run(self, *, db) -> str:
        return substitute(self.template, db.environment)


@dataclass
class TemplateTask(Lazy[Path | Phony | Variable, Task]):
    template: TaskProxy

    def __post_init__(self):
        assert not gather_args(self.template.creates)
        check_list_syntax(self.template)
        self.creates += [str_to_target(t) for t in self.template.all_targets]
        self.requires += [Variable(arg) for arg in gather_args(self.template)]
        self.requires += [Variable(n) for t in self.template.requires if (n := splice_name(t))]

    async def run(self, *, db):
        proxy = substitute(self.template, db.environment)
        tgts = [str_to_target(t) for t in proxy.all_targets]
        deps = [str_to_target(t) for t in db.splice(proxy.all_dependencies)]
        path = Path(proxy.path) if proxy.path else None
        stdin = str_to_target(proxy.stdin) if proxy.stdin else None
        stdout = str_to_target(proxy.stdout) if proxy.stdout else None
        assert not isinstance(stdin, Phony) and not isinstance(stdout, Phony)
        task = Task(
            tgts,
            deps,
            proxy.name,
            proxy.runner,
            path,
            proxy.script,
            stdin,
            stdout,
            proxy.description,
            proxy.force,
            list_output=proxy.stdout is not None and LIST_VARIABLE.fullmatch(proxy.stdout) is not None,
        )
        return task


def check_list_syntax(proxy: TaskProxy):
    """`listvar(name)` can only be used as `stdout`, `splice(name)` only in
    `requires`."""
    for t in [*proxy.creates, *proxy.all_dependencies]:
        if LIST_VARIABLE.fullmatch(t):
            raise HelpfulUserError(f"`{t}` can only be used as `stdout` of a task.")
    for t in [*proxy.all_targets, *(x for x in (proxy.stdin, proxy.path) if x)]:
        if SPLICE.fullmatch(t):
            raise HelpfulUserError(f"`{t}` can only be used in `requires` or template call arguments.")


@dataclass
class TaskDB(LazyDB[Path | Variable | Phony, Task | TemplateTask | TemplateVariable]):
    runners: dict[str, Runner] = field(default_factory=lambda: copy(DEFAULT_RUNNERS))
    throttle: Optional[asyncio.Semaphore] = None
    force_run: bool = False
    history_path: Path | None = None
    history: dict[Path, str | None] = field(default_factory=dict)

    @contextmanager
    def persistent_history(self):
        if not self.history_path:
            yield
        else:
            self.read_history(self.history_path)
            yield
            self.write_history(self.history_path)

    def read_history(self, history_path: Path):
        if not history_path.exists():
            return

        with open(history_path, "r") as f_in:
            data = json.load(f_in)
            for k, v in data.items():
                self.history[Path(k)] = v

    def write_history(self, history_path: Path):
        with open(history_path, "w") as f_out:
            json.dump({str(k): v for k, v in self.history.items()}, f_out, indent=2)

    def on_missing(self, t: Path | Phony | Variable):
        if isinstance(t, Path) and t.exists():
            return Task([t], [])
        raise MissingDependency()

    def is_resolvable(self, s: Any) -> bool:
        return all(v in self.index for v in map(Variable, gather_args(s)))

    async def resolve_object(self, s: Any) -> Any:
        vars = gather_args(s)
        await asyncio.gather(*(self.run(Variable(v), db=self) for v in vars))
        result = substitute(s, self.environment)
        log.debug(f"substituting {s} => {result}")
        return result

    @property
    def environment(self):
        return Environment(self)

    def list_variable(self, name: str) -> list[str]:
        """The value of list variable `name`, which should be computed already."""
        if Variable(name) not in self.index:
            raise HelpfulUserError(f"List variable `{name}` is not defined.")
        value = self.index[Variable(name)].result
        if not isinstance(value, list):
            raise HelpfulUserError(
                f"`splice({name})` needs a list variable; use `listvar({name})` as `stdout`.")
        return value

    def splice(self, items: list[str]) -> list[str]:
        """Replace each `splice(name)` in `items` with the elements of the list
        variable `name`."""
        result: list[str] = []
        for item in items:
            name = splice_name(item)
            result.extend(self.list_variable(name) if name else [item])
        return result


class Environment:
    def __init__(self, db):
        self.db = db

    def __contains__(self, k: str):
        return Variable(k) in self.db.index

    def items(self):
        return (k.name for k in self.db.index if isinstance(k, Variable))

    def __getitem__(self, k: str):
        value = self.db.index[Variable(k)].result
        if isinstance(value, list):
            raise HelpfulUserError(
                f"`{k}` is a list variable, it can only be used as `splice({k})`.")
        return value
# ~/~ end
