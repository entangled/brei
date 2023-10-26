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
from .template_strings import Variable, gather_args
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
    include: list[str] = field(default_factory=list)
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

        task_templates = copy(program.task)
        pattern_index.update(program.pattern)
        delayed_calls: list[PatternCall] = []
        delayed_templates: list[TaskProxy] = []

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
            task_templates.append(p.call(c.args))

        for tt in task_templates:
            # we could check for resolvability here, but I don't like the
            # idea that order then matters. this way the rule is:
            # > if a task has a templated target, those variables should be
            # > resolvable after all other tasks were added, seeing that the
            # > task to resolve these variables can't have templated targets
            # > themselves.
            if gather_args(tt.all_targets):
                delayed_templates.append(tt)
            else:
                db.add(TemplateTask([], [], tt))

        for inc in program.include:
            incp = Path(await db.resolve_object(inc))
            if incp in db.index:
                await db.run(incp, db)
            if not incp.exists():
                raise MissingInclude(incp)

            prg = Program.read(incp)
            await go(prg)

        for c in delayed_calls:
            if c.pattern not in pattern_index:
                log.debug(
                    "pattern `%s` still not available, now this is an error", c.pattern
                )
                raise MissingPattern(c.pattern)
            p = pattern_index[c.pattern]
            tt = p.call(c.args)
            if gather_args(tt.targets):
                delayed_templates.append(tt)
            else:
                db.add(TemplateTask([], [], tt))

        for tt in delayed_templates:
            if not db.is_resolvable(tt.all_targets):
                raise UserError(f"Task has unresolvable targets: {tt.targets}")
            tt = await db.resolve_object(tt)
            db.add(TemplateTask([], [], tt))

        return db

    return await go(program)
# ~/~ end
