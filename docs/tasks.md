# Tasks

``` {.python file=loom/task.py}
from __future__ import annotations
import asyncio
from contextlib import nullcontext
from copy import copy
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Optional, Union
from asyncio import create_subprocess_exec
from textwrap import indent

from .lazy import MissingDependency, Lazy, LazyDB, Phony
from .utility import stat
from .logging import logger
from .errors import UserError


@dataclass
class FailedTaskError(UserError):
    error_code: int
    stderr: str

    def __str__(self):
        return (
            f"process returned code {self.error_code}\n"
            f"standard error output: {self.stderr}"
        )


log = logger()


@dataclass
class Runner:
    command: str
    args: list[str]


DEFAULT_RUNNERS: dict[str, Runner] = {
    "Python": Runner("python", ["{script}"]),
    "Bash": Runner("bash", ["{script}"]),
}


def str_to_target(s: str) -> Path | Phony:
    if s[0] == '#':
        return Phony(s[1:])
    else:
        return Path(s)


@dataclass
class Task(Lazy[Path, None]):
    language: Optional[str] = None
    path: Optional[Path] = None
    script: Optional[str] = None
    stdin: Optional[Path] = None
    stdout: Optional[Path] = None

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
        if self.stdin and Path(self.stdin) not in self.dependencies:
            self.dependencies.append(Path(self.stdin))
        if self.path and Path(self.path) not in self.dependencies:
            self.dependencies.append(Path(self.path))
        if self.stdout and Path(self.stdout) not in self.targets:
            self.targets.append(Path(self.stdout))

    def validate(self):
        assert (self.path is None) or (self.script is None)
        if self.stdin is not None:
            assert Path(self.stdin) in self.dependencies
        if self.stdout is not None:
            assert Path(self.stdout) in self.targets

    def always_run(self) -> bool:
        return len(self.real_dependencies) == 0

    def needs_run(self) -> bool:
        if any(not path.exists() for path in self.targets):
            return True
        target_stats = [stat(p) for p in self.targets]
        dep_stats = [stat(p) for p in self.real_dependencies]
        if any(t < d for t in target_stats for d in dep_stats):
            return True
        return False

    async def run(self, cfg):
        log.debug(f"{self}")
        if not self.always_run() and not self.needs_run() and not cfg.force_run:
            return

        if self.language is None or (self.path is None and self.script is None):
            return

        runner = cfg.runners[self.language]
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

        args = [arg.format(script=path) for arg in runner.args]
        stdin = open(self.stdin, "r") if self.stdin is not None else None
        stdout = open(self.stdout, "w") if self.stdout is not None else None

        tgt_str = "(" + " ".join(str(t) for t in self.targets) + ")"
        log.info(f"{tgt_str} -> {runner.command} " + " ".join(args))
        async with cfg.throttle or nullcontext():
            proc = await create_subprocess_exec(
                runner.command,
                *args,
                stdin=stdin,
                stdout=stdout,
                stderr=asyncio.subprocess.PIPE,
            )
        stderr = await proc.stderr.read() if proc.stderr else b""
        await proc.wait()
        log.debug(f"return-code {proc.returncode}")

        if tmpfile is not None:
            tmpfile.close()

        if self.needs_run():
            raise FailedTaskError(proc.returncode or 0, stderr.decode())


@dataclass
class TaskDB(LazyDB[Path, Task]):
    runners: dict[str, Runner] = field(default_factory=lambda: copy(DEFAULT_RUNNERS))
    throttle: Optional[asyncio.Semaphore] = None
    force_run: bool = False

    async def run(self, t: Phony | Path, *args):
        log.debug(str(t))
        return await super().run(t, self, *args)

    def on_missing(self, t: Path):
        if not t.exists():
            raise MissingDependency()
        return Task([t], [])

    def target(self, target_path: Union[str, Path], deps: list[Path | Phony], **kwargs):
        task = Task([Path(target_path)], deps, **kwargs)
        self.add(task)

    def phony(self, name: str, deps: list[Path | Phony], **kwargs):
        task = Task([], deps, name=name, **kwargs)
        self.add(task)


@dataclass
class Pattern:
    """NYI. A `Pattern` can be used to generate `Rule`s from a template.
    This template will be expanded using Jinja."""

    targets: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    name: Optional[str] = None
    language: Optional[str] = None
    path: Optional[Path] = None
    script: Optional[str] = None
    stdout: Optional[str] = None
    stdin: Optional[str] = None

    def validate(self):
        assert (self.path is None) ^ (self.script is None)

    def call(self, args: dict[str, Any]) -> Task:
        targets: list[Path] = [
            Path(t.format(**args)) for t in self.targets
        ]
        deps: list[Path | Phony] = [
            str_to_target(d.format(**args)) for d in self.dependencies
        ]
        name = self.name.format(**args) if self.name else None
        lang = self.language
        if self.path is not None:
            script = self.path.read_text().format(**args)
        elif self.script is not None:
            script = self.script.format(**args)
        else:
            raise ValueError(
                "A `Pattern` needs to have either a `path` or `script` defined."
            )

        stdout = Path(self.stdout.format(**args)) if self.stdout is not None else None
        stdin = Path(self.stdin.format(**args)) if self.stdin is not None else None
        return Task(targets, deps, name, lang, script=script, stdout=stdout, stdin=stdin)
```
