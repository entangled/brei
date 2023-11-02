# ~/~ begin <<docs/experimental.md#brei/experimental/lazy.py>>[init]
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
import asyncio
import functools
from typing import Any, TypeGuard
from ..result import DependencyFailure, Result, Ok, TaskFailure


@dataclass
class Lazy[T]:
    _thunk: Callable[[], Coroutine[None, None, Result[T]]]

    def __await__(self):
        return self._trampoline().__await__()

    def __hash__(self):
        return hash(id(self))

    async def _trampoline(self):
        while True:
            x = await self._thunk()
            match x:
                case Ok(Lazy() as l):
                    self._thunk = l._thunk
                case _:
                    return x


def pure[T](value: T) -> Lazy[T]:
    async def _pure() -> Result[T]:
        return Ok(value)
    return Lazy(_pure)


def ensure_lazy[T](v: Lazy[T] | T) -> Lazy[T]:
    if isinstance(v, Lazy):
        return v
    else:
        return pure(v)


def none_failed(rs: list[Result[Any]]) -> TypeGuard[list[Ok[Any]]]:
    return all(rs)


def lazy[T](coroutine: Callable[..., Coroutine[None, None, T]]) -> Callable[..., Lazy[T]]:
    """Transform a coroutine function `Any... -> T` into a `Lazy` function. The
    `Lazy[T]` is an awaitable for `Result[T]`.

    The wrapped function creates a closure with a lock and a result. The lock
    ensures that only one consuming thread performs the actual computation. Other
    threads have to wait until the computation has finished.

    All arguments to the function call are awaited in parallel. If any of them
    fail, we propagate these failures to the parent call.

    If the decorated function returns another `Lazy`, then the result is also
    awaited (trampoline fashion).
    """
    @functools.wraps(coroutine)
    def run(*args) -> Lazy[T]:
        lock = asyncio.Lock()
        result: Result[T] | None = None

        async def arun() -> Result[T]:
            nonlocal result
            async with lock:
                if result is None:
                    arg_values = await asyncio.gather(*map(ensure_lazy, args))
                    if none_failed(arg_values):
                        try:
                            result = Ok(await coroutine(*(r.value for r in arg_values)))

                        except TaskFailure as f:
                            result = f

                    else:
                        fails: dict[int, Any] = {k: f for k, f in enumerate(arg_values) if not f}
                        result = DependencyFailure(fails)

            return result

        return Lazy(arun)

    return run


@lazy
async def gather(*args):
    return list(args)
# ~/~ end