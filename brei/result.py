# ~/~ begin <<docs/lazy.md#brei/result.py>>[init]
from dataclasses import dataclass


class Failure(Exception):
    def __bool__(self):
        return False


@dataclass
class MissingFailure[T](Failure):
    target: T

    def __str__(self):
        return f"Missing dependency: {self.target}"


@dataclass
class TaskFailure(Failure):
    message: str

    def __post_init__(self):
        Exception.__init__(self, self.message)


@dataclass
class DependencyFailure[T](Failure):
    dependencies: dict[T, Failure]

    def __str__(self):
        return "\n".join(f"{key} -> {fail}" for key, fail in self.dependencies.items())

@dataclass
class Ok[R]:
    value: R

    def __bool__(self):
        return True


type Result[R] = Failure | Ok[R]
# ~/~ end
