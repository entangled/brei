from __future__ import annotations
import asyncio
import pytest
from dataclasses import dataclass
from typing import Any
from brei.errors import CyclicWorkflowError
from brei.lazy import Lazy, LazyDB
import uuid


class PyFunc(Lazy[str, Any]):
    def __init__(self, db: LazyDB, foo: Any, tgt: str, deps: list[str]):
        super().__init__([tgt], deps)
        self.db = db
        self.foo = foo

    async def run(self):
        args = [self.db.index[t].result for t in self.requires]
        return self.foo(*args)

    async def eval(self):
        return await self.db.run(self.creates[0])


@dataclass
class PyLiteral(Lazy[str, Any]):
    def __init__(self, tgt: str, value: Any):
        super().__init__([tgt], [])
        self.value = value

    async def run(self):
        return self.value


class PyTaskDB(LazyDB[str, Any]):
    def lazy(self, f):
        def delayed(*args):
            target = uuid.uuid4().hex
            deps = []
            for arg in args:
                if isinstance(arg, Lazy):
                    deps.append(arg.creates[0])
                else:
                    dep = uuid.uuid4().hex
                    self.add(PyLiteral(dep, arg))
                    deps.append(dep)

            task = PyFunc(self, f, target, deps)
            self.add(task)
            return task

        return delayed


@pytest.mark.asyncio
async def test_noodles():
    db = PyTaskDB()

    @db.lazy
    def add1(x, y):
        return x + y

    @db.lazy
    def pure(v):
        return v

    z = add1(pure(3), pure(5))
    await z.eval()
    assert z and z.result == 8

    db.clean()

    exec_order = []

    @db.lazy
    def add2(label, x, y):
        exec_order.append(label)
        return x + y

    x = add2("x", 1, 2)
    y = add2("y", x, 3)
    z = add2("z", x, 4)
    w = add2("w", y, z)
    assert len(exec_order) == 0
    w_result = await w.eval()
    assert w_result.value == 13
    assert exec_order[-1] == "w"
    assert exec_order[0] == "x"


@pytest.mark.timeout(1)
def test_cycles():
    asyncio.run(atest_cycles())


# pytest-asyncio doesn't like this test and triggers the weirdest
# undefined behaviours. The exception manages to kill the event-loop
# and stuff just escalates from there.
async def atest_cycles():
    db = PyTaskDB()

    @db.lazy
    def add(x, y):
        return x + y

    @db.lazy
    def pure(x):
        return x

    w = pure(1)
    x = add(w, w)
    y = add(x, x)
    z = add(y, y)
    x.requires.append(z.creates[0])

    with pytest.raises(CyclicWorkflowError):
        await z.eval()

