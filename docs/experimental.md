## Lazy tasks
We use Python's `asyncio` to implement a system of **lazy tasks**. Results of those tasks are memoized.
Suppose we have some decorated functions:

``` {.python #lazy-example-functions}
@lazy
async def gather(*args):
    return list(args)

@lazy
async def sleep(t):
    await asyncio.sleep(t)

@lazy
async def add(a, b):
    return a + b
```

Lazy tasks don't do anything until `run()`.

``` {.python #lazy-spec}
async with timer() as t:
    p = gather(sleep(0.1), sleep(0.1), sleep(0.1), sleep(0.1))
assert t.elapsed and t.elapsed < 0.01
async with timer() as t:
    await p
assert t.elapsed and t.elapsed > 0.1 and t.elapsed < 0.2
```

We can do dynamic programming.

``` {.python #lazy-spec}
fib_cache = { }
@lazy
async def fib(i):
    if i < 2:
        return 1
    if i not in fib_cache:
        fib_cache[i] = add(fib(i-2), fib(i-1))
    return fib_cache[i]

assert await fib(20) == Ok(10946);
```

Now we have lazy programming inside a kind of `lazy` monad. There is the `pure` function is `T -> Lazy[T]`:

``` {.python #lazy-spec}
for x in "abc":
    v = pure(x)
    for _ in range(10):
        assert (await v) == Ok(x)
```

Lazy routines automatically perform tail-call elimination. Without that, this would trigger a `RecursionError`.

``` {.python #lazy-spec}
@lazy
async def factorial(n, total=1):
    if n == 0:
        return total
    else:
        return factorial(n - 1, n * total)

assert (await factorial(1000)).value > 1
```

:::details
### Unit testing

``` {.python file=test/experimental/test_func_lazy.py}
import pytest
import asyncio

from brei.experimental import lazy
from brei.experimental.lazy import lazy, pure
from brei.result import Ok
from brei.async_timer import timer

<<lazy-example-functions>>

@pytest.mark.asyncio
async def test_lazy():
    <<lazy-spec>>
```
:::

:::details
### Implementation

``` {.python file=brei/experimental/lazy.py}
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
import asyncio
import functools
from typing import Any, TypeGuard
from ..result import DependencyFailure, Result, Ok, TaskFailure


@dataclass
class Lazy[T]:
    _thunk: Callable[[], Coroutine[None, None, Result[T]]]

    def __await__(self):
        return self._trampoline().__await__()

    def __hash__(self):
        return hash(id(self))

    async def _trampoline(self):
        while True:
            x = await self._thunk()
            match x:
                case Ok(Lazy() as l):
                    self._thunk = l._thunk
                case _:
                    return x


def pure[T](value: T) -> Lazy[T]:
    async def _pure() -> Result[T]:
        return Ok(value)
    return Lazy(_pure)


def ensure_lazy[T](v: Lazy[T] | T) -> Lazy[T]:
    if isinstance(v, Lazy):
        return v
    else:
        return pure(v)


def none_failed(rs: list[Result[Any]]) -> TypeGuard[list[Ok[Any]]]:
    return all(rs)


def lazy[T](coroutine: Callable[..., Coroutine[None, None, T]]) -> Callable[..., Lazy[T]]:
    """Transform a coroutine function `Any... -> T` into a `Lazy` function. The
    `Lazy[T]` is an awaitable for `Result[T]`.

    The wrapped function creates a closure with a lock and a result. The lock
    ensures that only one consuming thread performs the actual computation. Other
    threads have to wait until the computation has finished.

    All arguments to the function call are awaited in parallel. If any of them
    fail, we propagate these failures to the parent call.

    If the decorated function returns another `Lazy`, then the result is also
    awaited (trampoline fashion).
    """
    @functools.wraps(coroutine)
    def run(*args) -> Lazy[T]:
        lock = asyncio.Lock()
        result: Result[T] | None = None

        async def arun() -> Result[T]:
            nonlocal result
            async with lock:
                if result is None:
                    arg_values = await asyncio.gather(*map(ensure_lazy, args))
                    if none_failed(arg_values):
                        try:
                            result = Ok(await coroutine(*(r.value for r in arg_values)))

                        except TaskFailure as f:
                            result = f

                    else:
                        fails: dict[int, Any] = {k: f for k, f in enumerate(arg_values) if not f}
                        result = DependencyFailure(fails)

            return result

        return Lazy(arun)

    return run


@lazy
async def gather(*args):
    return list(args)
```
:::

## Task

``` {.python file=brei/experimental/task_database.py}
from __future__ import annotations
from copy import copy
import shlex

from typing import Any, TextIO
from dataclasses import dataclass, field
from pathlib import Path
from contextlib import contextmanager, nullcontext
from tempfile import NamedTemporaryFile
from asyncio.subprocess import create_subprocess_exec

import re
import asyncio

from ..result import MissingFailure
from ..errors import CyclicWorkflowError
from ..utility import stat
from ..logging import logger

from .lazy import Lazy, lazy, pure


log = logger()


@dataclass
class Phony:
    name: str

    def __str__(self):
        return f"#{self.name}"

    def __hash__(self):
        return hash(str(self))


@dataclass
class Variable:
    name: str

    def __hash__(self):
        return hash(str(self))

    def __str__(self):
        return f"var({self.name})"


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
class Task:
    creates: list[Path | Phony | Variable] = field(default_factory=list)
    requires: list[Path | Phony | Variable] = field(default_factory=list)
    name: str | None = None
    runner: str | None = None
    path: Path | None = None
    script: str | None = None
    stdin: Path | Variable | None = None
    stdout: Path | Variable | None = None
    description: str | None = None
    force: bool = False

    @property
    def target_paths(self):
        return (p for p in self.creates if isinstance(p, Path))

    @property
    def dependency_paths(self):
        return (p for p in self.requires if isinstance(p, Path))

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

    @lazy
    async def run(self, cfg, db: TaskDatabase, visited: dict[Phony | Variable | Path, None]):
        if not self.always_run() and not self.needs_run() and not cfg.force_run:
            tgts = " ".join(f"`{t}`" for t in self.target_paths)
            log.info(f"Targets {tgts} already up-to-date.")
            return

        log.debug(f"{self}")
        if (self.path is None and self.script is None):
            return

        targets = " ".join(f"`{t}`" for t in self.creates)
        short_note = self.description or (f"#{self.name}" if self.name else None) \
            or f"creating {targets}"
        log.info(f"[green]{short_note}[/]", extra={'markup': True})

        stdin: TextIO | int | None = None
        match self.stdin:
            case Variable(x):
                stdin = asyncio.subprocess.PIPE
                input_data = await db.get(self.stdin, visited)
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
                    async with cfg.throttle or nullcontext():
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
                        log.info(f"[gold1]{short_note}[/] %s", stderr_data.decode().rstrip(), extra={"markup": True})

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
                log.info(f"[gold1]{short_note}[/] %s", stderr_data.decode().rstrip(), extra={"markup": True})

        else:
            return

        if self.needs_run():
            raise TaskFailure("Task didn't achieve goals.")

        return stdout_data.decode().strip() if stdout_data else None

class MissingDependency(Exception):
    pass


@dataclass
class TaskDatabase[Id, R]:
    index: dict[Id, Lazy[R]] = field(default_factory=dict)

    def get(self, task_id: Id, visited: dict[Id, None] | None = None) -> Lazy[R]:
        visited = copy(visited) or dict()
        if task_id in visited:
            raise CyclicWorkflowError(list(visited.keys()))
        visited[task_id] = None

        if task_id not in self.index:
            try:
                return self.on_missing(task_id)
            except MissingDependency:
                raise MissingFailure(task_id)
        else:
            return self.index[task_id]

    def on_missing(self, _: Id) -> Lazy[R]:
        raise MissingDependency()

    def __setitem__(self, k: Id, v: Lazy[R]):
        self.index[k] = v

    def __getitem__(self, k: Id) -> Lazy[R]:
        return self.get(k)
```

