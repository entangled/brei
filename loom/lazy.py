# ~/~ begin <<docs/lazy.md#loom/lazy.py>>[init]
from __future__ import annotations
from dataclasses import dataclass, field, fields
from typing import Generic, Iterable, Optional, Self, TypeVar, cast
import asyncio

from .errors import HelpfulUserError
from .utility import FromStr
from .logging import logger
from .result import Failure, Result, Ok, DependencyFailure, TaskFailure, MissingFailure

T = TypeVar("T")
R = TypeVar("R")

log = logger()


@dataclass
class Phony(FromStr):
    name: str

    @classmethod
    def from_str(cls, s: str) -> Phony:
        if s[0] == "#":
            return Phony(s[1:])
        raise ValueError("A phony target should start with a `#` character.")

    def __str__(self):
        return f"#{self.name}"

    def __hash__(self):
        return hash(str(self))


@dataclass
class Lazy(Generic[T, R]):
    """Base class for tasks that are tagged with type `T` (usually `str` or
    `Path`) and representing values of type `R`.

    To implement a specific task, you need to implement the asynchronous
    `run` method, which should return a value of `R` or throw `TaskFailure`.

    Attributes:
        targets: list of target identifiers, for instance paths that are
            generated by running a particular task.
        dependencies: list of dependency identifiers. All of these need to
            be realized before the task can run.
        result (property): value of the result, once the task was run. This
            throws an exception if accessed before the task is complete.
    """

    creates: list[T]
    requires: list[T]

    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _result: Optional[Result[R]] = field(default=None, init=False)

    @property
    def real_requirements(self) -> list[T]:
        return [d for d in self.requires if not isinstance(d, Phony)]

    def __bool__(self):
        return self._result is not None and bool(self._result)

    @property
    def result(self) -> R:
        if self._result is None:
            raise ValueError("Task has not run yet.")
        if not self._result:
            raise ValueError("Task has failed.")
        assert isinstance(self._result, Ok)
        if isinstance(self._result.value, Lazy):
            return self._result.value.result
        return self._result.value

    async def run(self, ctx) -> R:
        raise NotImplementedError()

    async def run_after_deps(self, recurse, *args) -> Result[R]:
        dep_res = await asyncio.gather(
            *(recurse(dep, *args) for dep in self.requires)
        )
        if not all(dep_res):
            return DependencyFailure(
                {k: v for (k, v) in zip(self.requires, dep_res) if not v}
            )
        try:
            return Ok(await self.run(*args))
        except TaskFailure as f:
            return f

    async def run_cached(self, recurse, *args) -> Result[R]:
        async with self._lock:
            if self._result is not None:
                return self._result
            self._result = await self.run_after_deps(recurse, *args)
            return self._result

    def reset(self):
        self._result = None

    def fields(self):
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name[0] != "_"}


TaskT = TypeVar("TaskT", bound=Lazy)


class MissingDependency(Exception):
    pass


@dataclass
class LazyDB(Generic[T, TaskT]):
    """Collect tasks and coordinate running a task from a task identifier."""

    tasks: list[TaskT] = field(default_factory=list)
    index: dict[T, TaskT] = field(default_factory=dict)

    async def run(self, t: T, *args) -> Result[R]:
        if t not in self.index:
            try:
                task = self.on_missing(t)
            except MissingDependency:
                return MissingFailure(t)
        else:
            task = self.index[t]

        while True:
            match (result := await task.run_cached(self.run, *args)):
                case Ok(x) if isinstance(x, Lazy):
                    task = cast(TaskT, x)
                case _:
                    return result

    def on_missing(self, _: T) -> TaskT:
        raise MissingDependency()

    def add(self, task: TaskT):
        """Add a task to the DB."""
        log.debug(f"adding task ===\n{task}")
        self.tasks.append(task)
        for target in task.creates:
            self.index[target] = task

    def clean(self):
        self.tasks = []
        self.index = {}

    def reset(self):
        for t in self.tasks:
            t.reset()
# ~/~ end
