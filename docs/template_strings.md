---
title: Lazy Templates
---

The goal is to have more flexible templates in Loom. I've looked into Jinja as a way to expand templates, but this is rejected due to large mostly unneeded complexity and ditto dependencies. A better alternative is to use Python's `string.Template` to do variable substition. Evaluation needs to be lazy, and I would like to be able to pipe standard output of a task to the contents of a variable. Considering this last point, we want to differentiate between writing output to the contents of a variable, and writing output to the file pointed to by the variable.

To assign the output of a command to a variable, we can have the following:

```toml
[[task]]
stdout = "var(commit)"
language = "Bash"
script = "git rev-parse HEAD"
```

To use it, refer using Python's `string.Template` syntax, which is similar to Bash, Make, Perl etc, i.e. either `$commit` or `${commit}`.

```toml
[[task]]
targets = ["output/${commit}/run.h5"]
dependencies = ["build/bin/model", "data/input.csv"]
language = "Bash"
script = "model run"
```

The system should infer that the use of `$commit` creates an implicit dependency on running `git rev-parse HEAD`. However, there may be steps in between:

```toml
[environment]
output_path = "output/${commit}"

[[task]]
targets = ["${output_path}/run.h5"]
... etc ...
```

We can trace these variable substitutions using the same lazy evaluation strategy as the workflow itself.

``` {.python file=loom/template_strings.py}
from dataclasses import dataclass, is_dataclass, fields
from string import Template
from types import NoneType
from typing import Any, Generic, Mapping, TypeVar, cast
from functools import singledispatch


from .lazy import Lazy


@dataclass()
class Variable:
    name: str

    def __hash__(self):
        return hash(f"var({self.name})")


T = TypeVar("T")


@singledispatch
def substitute(template, env: Mapping[str, str]):
    dtype = type(template)
    if is_dataclass(dtype):
        args = { f.name: substitute(getattr(template, f.name), env)
                 for f in fields(dtype) if f.name[0] != '_' }
        return dtype(**args)

    raise TypeError(f"Can't perform string substitution on object of type: {dtype}")


@substitute.register
def _(template: str, env: Mapping[str, str]) -> str:
    return Template(template).substitute(env)


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
        args = (gather_args(getattr(template, f.name))
                for f in fields(dtype) if f.name[0] != '_')
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


@dataclass
class TemplateSubstitution(Lazy[Variable, T], Generic[T]):
    template: T

    def __post_init__(self):
        self.dependencies += [Variable(arg) for arg in gather_args(self.template)]

    async def run(self, env) -> T:
        return cast(T, substitute(self.template, env))
```

``` {.python file=test/test_template_strings.py}
from dataclasses import dataclass
from typing import Iterable, Optional
import pytest
from loom.template_strings import TemplateSubstitution, Variable, gather_args, substitute
from loom.lazy import LazyDB, Phony
import string


class Environment(LazyDB[Variable, TemplateSubstitution[str]]):
    def __setitem__(self, k: str, v: str):
        self.add(TemplateSubstitution([Variable(k)], [], v))

    def __getitem__(self, k: str) -> str:
        return self.index[Variable(k)].result

    def __contains__(self, k: str) -> bool:
        return Variable(k) in self.index

    def items(self) -> Iterable[str]:
        return (k.name for k in self.index if isinstance(k, Variable))

    @property
    def variables(self):
        return self


@pytest.mark.asyncio
async def test_template_string():
    env = Environment()
    env["x"] = "Hello, ${y}!"
    env["y"] = "World"
    env["z"] = "print('${x}')"
    await env.run(Variable("z"), env)
    assert env["x"] == "Hello, World!"
    assert env["z"] == "print('Hello, World!')"


@dataclass
class MyData:
    some_list: list[str]
    some_prop: str
    some_none: Optional[str] = None


@pytest.mark.asyncio
async def test_template_dtype():
    data = MyData(
        some_list = ["${x} bar", "bar ${x} bar"],
        some_prop = "bar ${x}"
    )

    assert gather_args(data) == set("x")
    subst =  substitute(data, {"x": "foo"})
    assert subst.some_list == ["foo bar", "bar foo bar"]
    assert subst.some_prop == "bar foo"
    assert subst.some_none is None
```
