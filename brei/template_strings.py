# ~/~ begin <<docs/template_strings.md#brei/template_strings.py>>[init]
from dataclasses import dataclass, is_dataclass, fields
from string import Template
from typing import Any, Generic, Mapping, TypeVar
from functools import singledispatch

from msgspec import Struct, structs


from .lazy import Lazy


T = TypeVar("T")


def substitute(template: T, env: Mapping[str, str]) -> T:
    return _substitute(template, env)


def _fields(obj: Any) -> list[str] | None:
    """Names of the fields to recurse into, or None if `obj` is a leaf."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return [f.name for f in fields(obj) if f.name[0] != "_"]
    if isinstance(obj, Struct):
        return list(obj.__struct_fields__)
    return None


def _rebuild(obj: Any, values: dict[str, Any]) -> Any:
    if isinstance(obj, Struct):
        return structs.replace(obj, **values)
    return type(obj)(**values)


@singledispatch
def _substitute(template: Any, env: Mapping[str, str]) -> Any:
    names = _fields(template)
    if names is None:
        return template
    return _rebuild(template, {n: substitute(getattr(template, n), env) for n in names})


@_substitute.register
def _(template: str, env: Mapping[str, str]) -> str:
    return Template(template).safe_substitute(env)


@_substitute.register
def _(template: list, env: Mapping[str, str]) -> list:
    return [substitute(x, env) for x in template]


@singledispatch
def gather_args(template: Any) -> set[str]:
    names = _fields(template)
    if names is None:
        return set()
    return set().union(*(gather_args(getattr(template, n)) for n in names))


@gather_args.register
def _(template: str) -> set[str]:
    return set(Template(template).get_identifiers())


@gather_args.register
def _(template: list) -> set[str]:
    return set().union(*map(gather_args, template))
# ~/~ end
