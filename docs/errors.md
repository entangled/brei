``` {.python file=loom/errors.py}
from dataclasses import dataclass
from typing import Any


class UserError(Exception):
    def __str__(self):
        return "Unknown user error."


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


```
