# ~/~ begin <<docs/experimental.md#test/experimental/test_func_lazy.py>>[init]
import pytest
import asyncio

from brei.experimental import lazy
from brei.experimental.lazy import lazy, pure
from brei.result import Ok
from brei.async_timer import timer

# ~/~ begin <<docs/experimental.md#lazy-example-functions>>[init]
@lazy
async def gather(*args):
    return list(args)

@lazy
async def sleep(t):
    await asyncio.sleep(t)

@lazy
async def add(a, b):
    return a + b
# ~/~ end

@pytest.mark.asyncio
async def test_lazy():
    # ~/~ begin <<docs/experimental.md#lazy-spec>>[init]
    async with timer() as t:
        p = gather(sleep(0.1), sleep(0.1), sleep(0.1), sleep(0.1))
    assert t.elapsed and t.elapsed < 0.01
    async with timer() as t:
        await p
    assert t.elapsed and t.elapsed > 0.1 and t.elapsed < 0.2
    # ~/~ end
    # ~/~ begin <<docs/experimental.md#lazy-spec>>[1]
    fib_cache = { }
    @lazy
    async def fib(i):
        if i < 2:
            return 1
        if i not in fib_cache:
            fib_cache[i] = add(fib(i-2), fib(i-1))
        return fib_cache[i]

    assert await fib(20) == Ok(10946);
    # ~/~ end
    # ~/~ begin <<docs/experimental.md#lazy-spec>>[2]
    for x in "abc":
        v = pure(x)
        for _ in range(10):
            assert (await v) == Ok(x)
    # ~/~ end
    # ~/~ begin <<docs/experimental.md#lazy-spec>>[3]
    @lazy
    async def factorial(n, total=1):
        if n == 0:
            return total
        else:
            return factorial(n - 1, n * total)

    assert (await factorial(1000)).value > 1
    # ~/~ end
# ~/~ end