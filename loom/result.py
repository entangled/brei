# ~/~ begin <<docs/lazy.md#loom/result.py>>[init]
from typing import TypeVar, Generic
from dataclasses import dataclass


T = TypeVar("T")
R = TypeVar("R")


@dataclass
class Failure(Generic[T]):
    task: T

    def __bool__(self):
        return False


class MissingFailure(Failure[T]):
    pass


@dataclass
class TaskFailure(Failure[T], Exception):
    message: str

    def __post_init__(self):
        Exception.__init__(self, self.message)


@dataclass
class DependencyFailure(Failure[T], Generic[T]):
    dependent: list[Failure[T]]


@dataclass
class Ok(Generic[R]):
    value: R

    def __bool__(self):
        return True


Result = Failure[T] | Ok[R]
# ~/~ end
