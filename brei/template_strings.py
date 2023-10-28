# ~/~ begin <<docs/template_strings.md#brei/template_strings.py>>[init]
from dataclasses import dataclass, is_dataclass, fields
from string import Template
from typing import Any, Generic, Mapping, TypeVar, cast
from functools import singledispatch


from .lazy import Lazy


T = TypeVar("T")


@singledispatch
def substitute(template, env: Mapping[str, str]):
    dtype = type(template)
    if is_dataclass(dtype):
        args = {
            f.name: substitute(getattr(template, f.name), env)
            for f in fields(dtype)
            if f.name[0] != "_"
        }
        return dtype(**args)

    raise TypeError(f"Can't perform string substitution on object of type: {dtype}")


@substitute.register
def _(template: str, env: Mapping[str, str]) -> str:
    return Template(template).safe_substitute(env)


@substitute.register
def _(template: list, env: Mapping[str, str]) -> list:
    return [substitute(x, env) for x in template]


@substitute.register
def _(_template: None, _) -> None:
    return None


@singledispatch
def gather_args(template: Any) -> set[str]:
    dtype = type(template)
    if is_dataclass(dtype):
        args = (
            gather_args(getattr(template, f.name))
            for f in fields(dtype)
            if f.name[0] != "_"
        )
        return set().union(*args)

    raise TypeError(f"Can't perform string substitution on object of type: {dtype}")


@gather_args.register
def _(template: str) -> set[str]:
    return set(Template(template).get_identifiers())


@gather_args.register
def _(template: list) -> set[str]:
    return set().union(*map(gather_args, template))


@gather_args.register
def _(_template: None) -> set[str]:
    return set()
# ~/~ end