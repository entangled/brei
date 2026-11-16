# Template strings

The goal is to have more flexible templates in Brei. I've looked into Jinja as a way to expand templates, but this is rejected due to large mostly unneeded complexity and ditto dependencies. A better alternative is to use Python's `string.Template` to do variable substition. Evaluation needs to be lazy, and I would like to be able to pipe standard output of a task to the contents of a variable. Considering this last point, we want to differentiate between writing output to the contents of a variable, and writing output to the file pointed to by the variable.

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

``` {.python file=brei/template_strings.py}
from dataclasses import dataclass, is_dataclass, fields
from string import Template
from typing import Any, Mapping
from functools import singledispatch

from msgspec import Struct, structs


from .lazy import Lazy


def substitute[T](template: T, env: Mapping[str, str]) -> T:
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
```

``` {.python file=test/test_template_strings.py}
from dataclasses import dataclass
from typing import Iterable, Optional
import pytest
from brei.task import TemplateVariable, Variable
from brei.template_strings import gather_args, substitute
from brei.lazy import LazyDB


class Environment(LazyDB[Variable, TemplateVariable]):
    def __setitem__(self, k: str, v: str):
        self.add(TemplateVariable([Variable(k)], [], v))

    def __getitem__(self, k: str) -> str:
        return self.index[Variable(k)].result

    def __contains__(self, k: str) -> bool:
        return Variable(k) in self.index

    def items(self) -> Iterable[str]:
        return (k.name for k in self.index if isinstance(k, Variable))

    @property
    def environment(self):
        return self


@pytest.mark.asyncio
async def test_template_string():
    env = Environment()
    env["x"] = "Hello, ${y}!"
    env["y"] = "World"
    env["z"] = "print('${x}')"
    await env.run(Variable("z"), db=env)
    assert env["x"] == "Hello, World!"
    assert env["z"] == "print('Hello, World!')"


@dataclass
class MyData:
    some_list: list[str]
    some_prop: str
    some_none: Optional[str] = None


def test_template_dtype():
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
