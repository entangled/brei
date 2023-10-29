# ~/~ begin <<docs/tasks.md#brei/runner.py>>[init]
from dataclasses import dataclass


@dataclass
class Runner:
    command: str
    args: list[str]


DEFAULT_RUNNERS: dict[str, Runner] = {
    "python": Runner("python", ["${script}"]),
    "bash": Runner("bash", ["${script}"]),
}
# ~/~ end
