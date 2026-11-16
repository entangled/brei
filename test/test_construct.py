import pytest
from brei.errors import InputError
from brei.program import Join, Program
from brei.utility import construct


def test_construct_program():
    prg = construct(Program, {
        "task": [{"creates": ["hello.txt"], "script": "echo hello > hello.txt"}],
        "call": [{"template": "t", "args": {"x": ["a", "b"]}, "join": "outer"}],
    })
    assert prg.task[0].creates == ["hello.txt"]
    assert prg.call[0].join == Join.OUTER
    assert prg.environment == {}


def test_construct_error():
    with pytest.raises(InputError):
        construct(Program, {"task": [{"creates": "hello.txt"}]})
    with pytest.raises(InputError):
        construct(Program, {"call": [{"template": "t", "args": {}, "join": "sideways"}]})


@pytest.mark.parametrize("data", [
    {"tasks": []},
    {"task": [{"creates": ["x"], "requries": ["y"]}]},
    {"template": {"t": {"creates": ["${x}"], "bogus": 1}}},
    {"call": [{"template": "t", "args": {}, "jion": "outer"}]},
    {"runner": {"r": {"command": "r", "args": [], "env": {}}}},
])
def test_construct_unknown_field(data):
    with pytest.raises(InputError, match="unknown field"):
        construct(Program, data)
