# Tasks

``` {.python file=brei/runner.py}
from dataclasses import dataclass


@dataclass
class Runner:
    command: str
    args: list[str]


DEFAULT_RUNNERS: dict[str, Runner] = {
    "python": Runner("python", ["${script}"]),
    "bash": Runner("bash", ["${script}"]),
}
```

``` {.python file=brei/task.py}
from __future__ import annotations
import asyncio
from contextlib import contextmanager, nullcontext
from copy import copy
from dataclasses import dataclass, field
from pathlib import Path
import re
import string
from tempfile import NamedTemporaryFile
from typing import IO, Any, BinaryIO, Optional, TextIO
from asyncio import create_subprocess_exec
from textwrap import indent
import shlex

from .result import TaskFailure
from .lazy import MissingDependency, Lazy, LazyDB, Phony
from .utility import stat
from .logging import logger
from .errors import FailedTaskError, HelpfulUserError
from .template_strings import gather_args, substitute
from .runner import Runner, DEFAULT_RUNNERS


log = logger()


@dataclass
class Variable:
    name: str

    def __hash__(self):
        return hash(f"var({self.name})")


def str_to_target(s: str) -> Path | Phony | Variable:
    if s[0] == "#":
        return Phony(s[1:])
    elif m := re.match(r"var\(([^\s\(\)]+)\)", s):
        return Variable(m.group(1))
    else:
        return Path(s)


def is_oneliner(s: str) -> bool:
    return len(s.splitlines()) == 1


@dataclass
class Task(Lazy[Path | Phony | Variable, str | None]):
    name: Optional[str] = None
    runner: Optional[str] = None
    path: Optional[Path] = None
    script: Optional[str] = None
    stdin: Optional[Path | Variable] = None
    stdout: Optional[Path | Variable] = None
    description: Optional[str] = None

    @property
    def target_paths(self):
        return (p for p in self.creates if isinstance(p, Path))

    @property
    def dependency_paths(self):
        return (p for p in self.requires if isinstance(p, Path))

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
        return len(self.real_requirements) == 0 or len(list(self.target_paths)) == 0

    def needs_run(self) -> bool:
        if any(not p.exists() for p in self.target_paths):
            return True
        target_stats = [stat(p) for p in self.target_paths]
        dep_stats = [stat(p) for p in self.dependency_paths]
        if any(t < d for t in target_stats for d in dep_stats):
            return True
        return False

    @contextmanager
    def get_script_path(self):
        if self.path is not None:
            tmpfile = None
            path = self.path
        elif self.script is not None:
            tmpfile = NamedTemporaryFile("w")
            tmpfile.write(self.script)
            tmpfile.flush()
            path = Path(tmpfile.name)
        else:
            raise ValueError("A `Rule` can have either `path` or `script` defined.")

        yield path

        if tmpfile is not None:
            tmpfile.close()

    @contextmanager
    def get_stdout(self):
        match self.stdout:
            case Variable(x):
                yield asyncio.subprocess.PIPE
            case x if isinstance(x, Path):
                stdout = open(x, "w")
                yield stdout
                stdout.close()
            case _:
                yield None

    async def run(self, *, db: TaskDB):
        if not self.always_run() and not self.needs_run() and not db.force_run:
            tgts = " ".join(f"`{t}`" for t in self.target_paths)
            log.info(f"Targets {tgts} already up-to-date.")
            return

        targets = " ".join(f"`{t}`" for t in self.creates)
        short_note = self.description or f"#{self.name}" or f"creating {targets}"
        log.info(f"run: [green]{short_note}[/]", extra={'markup': True})
        log.debug(f"{self}")
        if (self.path is None and self.script is None):
            return

        stdin: TextIO | int | None = None
        match self.stdin:
            case Variable(x):
                stdin = asyncio.subprocess.PIPE
                input_data = db.environment[x].encode()
            case x if isinstance(x, Path):
                stdin = open(x, "r")
                input_data = None
            case _:
                stdin = None
                input_data = None

        if self.runner is None and self.script is not None:
            if not is_oneliner(self.script):
                assert self.stdin is None
            with self.get_stdout() as stdout:
                stdout_data = b""
                for line in self.script.splitlines():
                    async with db.throttle or nullcontext():
                        proc = await create_subprocess_exec(
                            *shlex.split(line),
                            stdin=stdin,
                            stdout=stdout,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        stdout_data_part, stderr_data = await proc.communicate(input_data)
                        log.debug(f"return-code {proc.returncode}")
                    if stdout_data_part:
                        stdout_data += stdout_data_part
                    if stderr_data:
                        log.info(stderr_data.decode())

        elif self.runner is not None:
            with self.get_script_path() as path, self.get_stdout() as stdout:
                runner = db.runners[self.runner]
                args = [string.Template(arg).substitute(script=path) for arg in runner.args]
                async with db.throttle or nullcontext():
                    proc = await create_subprocess_exec(
                        runner.command,
                        *args,
                        stdin=stdin,
                        stdout=stdout,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout_data, stderr_data = await proc.communicate(input_data)
                    log.debug(f"return-code {proc.returncode}")

            if stderr_data:
                log.info(stderr_data.decode())

        else:
            return

        if self.needs_run():
            raise TaskFailure("Task didn't achieve goals.")

        return stdout_data.decode().strip() if stdout_data else None


@dataclass
class TaskProxy:
    creates: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    name: Optional[str] = None
    runner: Optional[str] = None
    path: Optional[str] = None
    script: Optional[str] = None
    stdin: Optional[str] = None
    stdout: Optional[str] = None
    description: Optional[str] = None

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
        self.creates += [str_to_target(t) for t in self.template.all_targets]
        self.requires += [Variable(arg) for arg in gather_args(self.template)]

    async def run(self, *, db):
        proxy = substitute(self.template, db.environment)
        tgts = [str_to_target(t) for t in proxy.all_targets]
        deps = [str_to_target(t) for t in proxy.all_dependencies]
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
        )
        return task


@dataclass
class TaskDB(LazyDB[Path | Variable | Phony, Task | TemplateTask | TemplateVariable]):
    runners: dict[str, Runner] = field(default_factory=lambda: copy(DEFAULT_RUNNERS))
    throttle: Optional[asyncio.Semaphore] = None
    force_run: bool = False

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


class Environment:
    def __init__(self, db):
        self.db = db

    def __contains__(self, k: str):
        return Variable(k) in self.db.index

    def items(self):
        return (k.name for k in self.db.index if isinstance(k, Variable))

    def __getitem__(self, k: str):
        return self.db.index[Variable(k)].result


class Template(TaskProxy):
    def call(self, args: dict[str, Any]) -> TaskProxy:
        return substitute(self, args)
```
