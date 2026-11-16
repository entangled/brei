# ~/~ begin <<docs/errors.md#brei/errors.py>>[init]
from dataclasses import dataclass
from typing import Any, Generic, TypeVar


class UserError(Exception):
    def __str__(self) -> str:
        return "Unknown user error."


T = TypeVar("T")

@dataclass
class CyclicWorkflowError(UserError, Generic[T]):
    cycle: list[T]

    def __str__(self):
        return f"Cycle detected: {self.cycle}"


@dataclass
class HelpfulUserError(UserError):
    msg: str

    def __str__(self):
        return self.msg


@dataclass
class InputError(UserError):
    expected: str
    msg: str

    def __str__(self):
        return f"Invalid input for `{self.expected}`: {self.msg}"


@dataclass
class FailedTaskError(UserError):
    error_code: int
    stderr: str

    def __str__(self):
        return (
            f"process returned code {self.error_code}\n"
            f"standard error output: {self.stderr}"
        )
# ~/~ end
