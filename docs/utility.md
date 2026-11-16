# Utils

``` {.python file=brei/utility.py}
from __future__ import annotations

from dataclasses import dataclass

from pathlib import Path
from datetime import datetime

import os

from .construct import construct, read_from_file


def normal_relative(path: Path) -> Path:
    return path.resolve()  # .relative_to(Path.cwd())


@dataclass
class FileStat:
    path: Path
    modified: datetime

    @staticmethod
    def from_path(path: Path):
        stat = os.stat(path)
        return FileStat(path, datetime.fromtimestamp(stat.st_mtime))

    def __lt__(self, other: FileStat) -> bool:
        return self.modified < other.modified


def stat(path: Path) -> FileStat:
    path = normal_relative(path)
    return FileStat.from_path(path)
```

``` {.python file=brei/async_timer.py}
from dataclasses import dataclass
import time
from contextlib import asynccontextmanager

@dataclass
class Elapsed:
    elapsed: float | None = None

@asynccontextmanager
async def timer():
    e = Elapsed()
    t = time.perf_counter()
    yield e
    e.elapsed = time.perf_counter() - t
```

``` {.python file=brei/construct.py}
from typing import Any, Optional

import tomllib
import json

from pathlib import Path

import msgspec

from .errors import HelpfulUserError, InputError

def construct[T](annot: type[T], data: Any) -> T:
    """Construct an object of type `annot` from JSON compatible `data`, using
    `msgspec` for validation. Raises an `InputError` if the data doesn't match
    the type."""
    try:
        return msgspec.convert(data, type=annot)
    except msgspec.ValidationError as e:
        raise InputError(annot.__name__, str(e)) from e


def read_from_file[T](data_type: type[T], path: Path, section: Optional[str] = None) -> T:
    """Read a config from given `path` in given `section`. The path should refer to
    a TOML or JSON file that should decode to a `Config` object. If `section` is given, only
    that section is decoded to a `Config` object. The `section` string may contain
    periods to indicate deeper nesting.

    Example:

    ```python
    read_from_file(Config, Path("./pyproject.toml"), "tool.loom")
    ```
    """
    if not path.exists():
        raise HelpfulUserError(f"File not found: {path}")
    with open(path, "rb") as f:
        if path.suffix == ".toml":
            data: Any = tomllib.load(f)
        elif path.suffix == ".json":
            data = json.load(f)
        else:
            raise HelpfulUserError(f"Unrecognized file format: {path}")

    try:
        if section is not None:
            for s in section.split("."):
                data = data[s]
    except KeyError as e:
        raise HelpfulUserError(
            f"Data file `{path}` should contain section `{section}`."
        ) from e

    try:
        return construct(data_type, data)
    except InputError as e:
        raise HelpfulUserError(f"In `{path}`: {e}") from e
```
