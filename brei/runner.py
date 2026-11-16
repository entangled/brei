# ~/~ begin <<docs/tasks.md#brei/runner.py>>[init]
from msgspec import Struct


class Runner(Struct, forbid_unknown_fields=True):
    command: str
    args: list[str]


DEFAULT_RUNNERS: dict[str, Runner] = {
    "python": Runner("python", ["${script}"]),
    "bash": Runner("bash", ["${script}"]),
}
# ~/~ end
