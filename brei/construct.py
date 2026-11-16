# ~/~ begin <<docs/utility.md#brei/construct.py>>[init]
from typing import Any, TypeVar, Optional

import tomllib
import json

from pathlib import Path

import msgspec

from .errors import HelpfulUserError, InputError

T = TypeVar("T")


def construct(annot: type[T], data: Any) -> T:
    """Construct an object of type `annot` from JSON compatible `data`, using
    `msgspec` for validation. Raises an `InputError` if the data doesn't match
    the type."""
    try:
        return msgspec.convert(data, type=annot)
    except msgspec.ValidationError as e:
        raise InputError(annot.__name__, str(e)) from e


def read_from_file(data_type: type[T], path: Path, section: Optional[str] = None) -> T:
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
# ~/~ end
