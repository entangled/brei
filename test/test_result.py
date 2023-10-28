# ~/~ begin <<docs/lazy.md#test/test_result.py>>[init]
from brei.result import Failure, TaskFailure, Ok
from hypothesis import given
from hypothesis.strategies import builds, booleans, text, integers


results = builds(lambda b, t, i: Ok(i) if b else TaskFailure(t),
                 booleans(), text(min_size=1), integers())


@given(results)
def test_result(r):
    assert (r and hasattr(r, "value")) or (not r and isinstance(r, Failure))
# ~/~ end