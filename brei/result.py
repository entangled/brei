# ~/~ begin <<docs/lazy.md#loom/result.py>>[init]
from typing import TypeVar, Generic
from dataclasses import dataclass


T = TypeVar("T")
R = TypeVar("R")


class Failure:
    def __bool__(self):
        return False


@dataclass
class MissingFailure(Failure, Generic[T]):
    target: T


@dataclass
class TaskFailure(Failure, Exception):
    message: str

    def __post_init__(self):
        Exception.__init__(self, self.message)


@dataclass
class DependencyFailure(Failure, Generic[T]):
    dependencies: dict[T, Failure]


@dataclass
class Ok(Generic[R]):
    value: R

    def __bool__(self):
        return True


Result = Failure | Ok[R]
# ~/~ end
