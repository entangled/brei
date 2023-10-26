# ~/~ begin <<docs/tasks.md#loom/task.py>>[init]
from __future__ import annotations
import asyncio
from contextlib import contextmanager, nullcontext
from copy import copy
from dataclasses import dataclass, field
from pathlib import Path
import re
import string
from tempfile import NamedTemporaryFile
from typing import Any, Optional, Union
from asyncio import create_subprocess_exec
from textwrap import indent

from .lazy import MissingDependency, Lazy, LazyDB, Phony
from .utility import stat
from .logging import logger
from .errors import FailedTaskError
from .template_strings import gather_args, substitute


log = logger()


@dataclass()
class Variable:
    name: str

    def __hash__(self):
        return hash(f"var({self.name})")


@dataclass
class Runner:
    command: str
    args: list[str]


DEFAULT_RUNNERS: dict[str, Runner] = {
    "Python": Runner("python", ["${script}"]),
    "Bash": Runner("bash", ["${script}"]),
}


def str_to_target(s: str) -> Path | Phony | Variable:
    if s[0] == '#':
        return Phony(s[1:])
    elif (m := re.match(r"var\(([^\s\(\)]+)\)", s)):
        return Variable(m.group(1))
    else:
        return Path(s)


@dataclass
class Task(Lazy[Path | Phony | Variable, str | None]):
    name: Optional[str] = None
    language: Optional[str] = None
    path: Optional[Path] = None
    script: Optional[str] = None
    stdin: Optional[Path | Variable] = None
    stdout: Optional[Path | Variable] = None

    @property
    def target_paths(self):
        return (p for p in self.targets if isinstance(p, Path))

    @property
    def dependency_paths(self):
        return (p for p in self.dependencies if isinstance(p, Path))

    def __str__(self):
        tgts = ", ".join(str(t) for t in self.targets)
        deps = ", ".join(str(t) for t in self.dependencies)
        if self.script is not None:
            src = indent(self.script, prefix=" ▎ ", predicate=lambda _: True)
        elif self.path is not None:
            src = str(self.path)
        else:
            src = " - "
        name = f"{self.name}: " if self.name else ""
        return name + f"[{tgts}] <- [{deps}]\n" + src

    def __post_init__(self):
        if self.name is not None:
            self.targets.append(Phony(self.name))
        if self.stdin and self.stdin not in self.dependencies:
            self.dependencies.append(self.stdin)
        if self.path and self.path not in self.dependencies:
            self.dependencies.append(self.path)
        if self.stdout and self.stdout not in self.targets:
            self.targets.append(self.stdout)

    def always_run(self) -> bool:
        return len(self.real_dependencies) == 0

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


    async def run(self, cfg):
        log.debug(f"{self}")
        if not self.always_run() and not self.needs_run() and not cfg.force_run:
            return

        if self.language is None or (self.path is None and self.script is None):
            return

        runner = cfg.runners[self.language]

        match self.stdin:
            case Variable(x):
                stdin = asyncio.subprocess.PIPE
                input_data = cfg.environment[x].encode()
            case x if isinstance(x, Path):
                stdin = open(x, "r")
                input_data = None
            case _:
                stdin = None
                input_data = None

        with self.get_script_path() as path, self.get_stdout() as stdout:
            args = [string.Template(arg).substitute(script=path) for arg in runner.args]
            async with cfg.throttle or nullcontext():
                proc = await create_subprocess_exec(
                    runner.command,
                    *args,
                    stdin=stdin,
                    stdout=stdout,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_data, stderr_data = await proc.communicate(input_data)

        if stderr_data:
            log.info(stderr_data.decode())

        log.debug(f"return-code {proc.returncode}")

        if self.needs_run():
            raise FailedTaskError(proc.returncode or 0, stderr_data.decode())

        return stdout_data.decode().strip() if stdout_data else None


@dataclass
class TaskProxy:
    targets: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    name: Optional[str] = None
    language: Optional[str] = None
    path: Optional[str] = None
    script: Optional[str] = None
    stdin: Optional[str] = None
    stdout: Optional[str] = None

    @property
    def all_targets(self):
        return self.targets + ([self.stdout] if self.stdout else []) + ([f"#{self.name}"] if self.name else [])

    @property
    def all_dependencies(self):
        return self.dependencies + ([self.stdin] if self.stdin else []) + ([self.path] if self.path else [])


@dataclass
class TemplateVariable(Lazy[Variable, str]):
    template: str

    def __post_init__(self):
        self.dependencies += [Variable(arg) for arg in gather_args(self.template)]

    async def run(self, ctx) -> str:
        return substitute(self.template, ctx.environment)


@dataclass
class TemplateTask(Lazy[Path | Phony | Variable, Task]):
    template: TaskProxy

    def __post_init__(self):
        assert not gather_args(self.template.targets)
        self.targets += [str_to_target(t) for t in self.template.all_targets]
        self.dependencies += [Variable(arg) for arg in gather_args(self.template)]

    async def run(self, ctx):
        proxy = substitute(self.template, ctx.environment)
        tgts = [str_to_target(t) for t in proxy.all_targets]
        deps = [str_to_target(t) for t in proxy.all_dependencies]
        path = Path(proxy.path) if proxy.path else None
        stdin = str_to_target(proxy.stdin) if proxy.stdin else None
        stdout = str_to_target(proxy.stdout) if proxy.stdout else None
        assert not isinstance(stdin, Phony) and not isinstance(stdout, Phony)
        task = Task(tgts, deps, proxy.name, proxy.language, path, proxy.script, stdin, stdout)
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
        await asyncio.gather(*(self.run(Variable(v), self) for v in vars))
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


class Pattern(TaskProxy):
    def call(self, args: dict[str, Any]) -> TaskProxy:
        return substitute(self, args)
# ~/~ end
