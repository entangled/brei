# Utils

``` {.python file=loom/utility.py}
from __future__ import annotations
from typing import Iterable, Optional, Self, TypeGuard, TypeVar, Any, Union
from enum import Enum
from contextlib import contextmanager
from datetime import datetime
import os
from pathlib import Path
import typing
import types
from dataclasses import dataclass, is_dataclass
from .errors import ConfigError
import traceback

T = TypeVar("T")


@contextmanager
def pushd(wd: Path):
    olddir = os.getcwd()
    os.chdir(wd)
    yield wd
    os.chdir(olddir)


def cat_maybes(it: Iterable[Optional[T]]) -> Iterable[T]:
    def pred(x: Optional[T]) -> TypeGuard[T]:
        return x is not None

    return filter(pred, it)


def normal_relative(path: Path) -> Path:
    return path.resolve().relative_to(Path.cwd())


@dataclass
class FileStat:
    path: Path
    modified: datetime

    @staticmethod
    def from_path(path: Path, deps: Optional[list[Path]]):
        stat = os.stat(path)
        return FileStat(path, datetime.fromtimestamp(stat.st_mtime))

    def __lt__(self, other: FileStat) -> bool:
        return self.modified < other.modified


def stat(path: Path, deps: Optional[list[Path]] = None) -> FileStat:
    path = normal_relative(path)
    deps = None if deps is None else [normal_relative(d) for d in deps]
    return FileStat.from_path(path, deps)

def isgeneric(annot):
    return hasattr(annot, "__origin__") and hasattr(annot, "__args__")


class FromStr:
    @classmethod
    def from_str(cls, _: str) -> Self:
        raise NotImplementedError()


def construct(annot: Any, json: Any) -> Any:
    try:
        return _construct(annot, json)
    except (AssertionError, ValueError):
        traceback.print_exc()
        raise ConfigError(annot, json)


def _construct(annot: Any, json: Any) -> Any:
    """Construct an object from a given type from a JSON stream.

    The `annot` type should be one of: str, int, list[T], Optional[T],
    or a dataclass, and the JSON data should match exactly the given
    definitions in the dataclass hierarchy.
    """
    if annot is str:
        assert isinstance(json, str)
        return json
    if annot is int:
        assert isinstance(json, int)
        return json
    if (
        isgeneric(annot)
        and typing.get_origin(annot) is dict
        and typing.get_args(annot)[0] is str
    ):
        assert isinstance(json, dict)
        return {k: construct(typing.get_args(annot)[1], v) for k, v in json.items()}
    if annot is Any:
        return json
    if annot is dict or isgeneric(annot) and typing.get_origin(annot) is dict:
        assert isinstance(json, dict)
        return json
    if annot is Path and isinstance(json, str):
        return Path(json)
    if isgeneric(annot) and typing.get_origin(annot) is list:
        assert isinstance(json, list)
        return [construct(typing.get_args(annot)[0], item) for item in json]
    if (
        isgeneric(annot)
        and typing.get_origin(annot) is Union
        and typing.get_args(annot)[1] is types.NoneType
    ):
        if json is None:
            return None
        else:
            return construct(typing.get_args(annot)[0], json)
    if issubclass(annot, FromStr) and isinstance(json, str):
        return annot.from_str(json)
    if is_dataclass(annot):
        assert isinstance(json, dict)
        arg_annot = typing.get_type_hints(annot)
        # assert all(k in json for k in arg_annot)
        args = {k: construct(arg_annot[k], json[k]) for k in json}
        return annot(**args)
    if isinstance(json, str) and isinstance(annot, type) and issubclass(annot, Enum):
        options = {opt.name.lower(): opt for opt in annot}
        assert json.lower() in options
        return options[json.lower()]
    raise ValueError(f"Couldn't construct {annot} from {repr(json)}")
```
