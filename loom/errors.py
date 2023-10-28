# ~/~ begin <<docs/errors.md#loom/errors.py>>[init]
from dataclasses import dataclass
from typing import Any, Generic, TypeVar


class UserError(Exception):
    def __str__(self):
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
    got: Any

    def __str__(self):
        return f"Expected {self.expected}, got: {self.got}"


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
