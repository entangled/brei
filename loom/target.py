# ~/~ begin <<docs/target.md#loom/target.py>>[init]
from __future__ import annotations
from dataclasses import dataclass
from typing import Self
from pathlib import Path
import re
from .utility import FromStr


class Parsable:
    @classmethod
    def from_str(cls, _: str) -> Self:
        raise NotImplementedError()


@dataclass
class Phony(FromStr):
    name: str

    @classmethod
    def from_str(cls, s: str) -> Phony:
        if m := re.match(r"phony\(([^()\s]+)\)", s):
            return Phony(m.group(1))
        raise ValueError(f"Not a phony target: '{s}'")

    def __str__(self):
        return f"phony({self.name})"

    def __hash__(self):
        return hash(f"#{self.name}#")


@dataclass
class Target(FromStr):
    phony_or_path: Phony | Path

    @classmethod
    def from_str(cls, s: str) -> Target:
        try:
            phony = Phony.from_str(s)
            return Target(phony)
        except ValueError:
            return Target(Path(s))

    def __str__(self):
        return f"Target({self.phony_or_path})"

    def __hash__(self):
        return hash(self.phony_or_path)

    def is_phony(self) -> bool:
        return isinstance(self.phony_or_path, Phony)

    def is_path(self) -> bool:
        return isinstance(self.phony_or_path, Path)

    @property
    def path(self) -> Path:
        if not isinstance(self.phony_or_path, Path):
            raise ValueError("Not a path")
        return self.phony_or_path
# ~/~ end