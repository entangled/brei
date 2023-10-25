# ~/~ begin <<docs/template_strings.md#test/test_template_strings.py>>[init]
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
# ~/~ end
