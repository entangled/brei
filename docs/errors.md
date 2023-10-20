``` {.python file=loom/errors.py}
from dataclasses import dataclass
from typing import Any


class UserError(Exception):
    def __str__(self):
        return "Unknown user error."


@dataclass
class ConfigError(UserError):
    expected: str
    got: Any

    def __str__(self):
        return f"Expected {self.expected}, got: {self.got}"
```
