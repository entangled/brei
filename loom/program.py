# ~/~ begin <<docs/program.md#loom/program.py>>[init]
from __future__ import annotations
from copy import copy
import logging
from typing import Any, Generic, Optional
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path

import tomllib

from loom.result import Failure, Ok

from .lazy import MissingDependency, Phony
from .template_strings import Variable
from .logging import logger
from .errors import UserError

from .utility import construct
from .task import Task, TaskDB, Pattern, Runner, TaskProxy, TemplateTask, TemplateVariable


log = logger()


@dataclass
class MissingInclude(UserError):
    path: Path

    def __str__(self):
        return f"Include `{self.path}` not found."


@dataclass
class MissingPattern(UserError):
    name: str

    def __str__(self):
        return f"Pattern `{self.name}` not found."


@dataclass
class PatternCall:
    pattern: str
    args: dict[str, Any]


@dataclass
class Program:
    task: list[TaskProxy] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    pattern: dict[str, Pattern] = field(default_factory=dict)
    call: list[PatternCall] = field(default_factory=list)
    include: list[Path] = field(default_factory=list)
    runner: dict[str, Runner] = field(default_factory=dict)

    # def write(self, path: Path):
    #     with open(path, "w") as f_out:
    #         tomlkit.dump(self.__dict__, f_out)

    @staticmethod
    def read(path: Path) -> Program:
        with open(path, "rb") as f_in:
            data = tomllib.load(f_in)
        return construct(Program, data)


async def resolve_tasks(program: Program) -> TaskDB:
    db = TaskDB()
    pattern_index = dict()

    async def go(program: Program):
        for var, template in program.environment.items():
            db.add(TemplateVariable([Variable(var)], [], template))

        task_templates = [TemplateTask([], [], t) for t in program.task]
        pattern_index.update(program.pattern)
        delayed_calls: list[PatternCall] = []
        delayed_templates: list[TemplateTask] = []

        db.runners.update(program.runner)

        for c in program.call:
            if c.pattern not in pattern_index:
                log.debug(
                    "pattern `%s` not available, waiting for includes to resolve",
                    c.pattern,
                )
                delayed_calls.append(c)
                continue
            p = pattern_index[c.pattern]
            task_templates.append(TemplateTask([], [], p.call(c.args)))

        for tt in task_templates:
            task = await tt.run_cached(db.run, db)
            match task:
                case Failure():
                    tt.reset()
                    delayed_templates.append(tt)
                case Ok(t):
                    db.add(t)

        for inc in program.include:
            if inc in db.index:
                await db.run(inc, db)
            if not inc.exists():
                raise MissingInclude(inc)

            prg = Program.read(inc)
            await go(prg)

        for c in delayed_calls:
            if c.pattern not in pattern_index:
                log.debug(
                    "pattern `%s` still not available, now this is an error", c.pattern
                )
                raise MissingPattern(c.pattern)
            p = pattern_index[c.pattern]
            delayed_templates.append(TemplateTask([], [], p.call(c.args)))

        for tt in delayed_templates:
            task = await tt.run_cached(db.run, db)
            match task:
                case Ok(t):
                    db.add(t)
                case Failure():
                    raise UserError(f"Missing dependency in {tt.dependencies}")

        return db

    return await go(program)
# ~/~ end
