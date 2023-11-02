# ~/~ begin <<docs/utility.md#brei/async_timer.py>>[init]
from dataclasses import dataclass
import time
from contextlib import asynccontextmanager

@dataclass
class Elapsed:
    elapsed: float | None = None

@asynccontextmanager
async def timer():
    e = Elapsed()
    t = time.perf_counter()
    yield e
    e.elapsed = time.perf_counter() - t
# ~/~ end
