# ~/~ begin <<docs/program.md#loom/program.py>>[init]
from __future__ import annotations
from copy import copy
import itertools
from typing import Any
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import tomllib


from .template_strings import gather_args
from .logging import logger
from .errors import UserError

from .utility import construct
from .task import (
    Variable,
    TaskDB,
    Template,
    Runner,
    TaskProxy,
    TemplateTask,
    TemplateVariable,
)


log = logger()


@dataclass
class MissingInclude(UserError):
    path: Path

    def __str__(self):
        return f"Include `{self.path}` not found."


@dataclass
class MissingTemplate(UserError):
    name: str

    def __str__(self):
        return f"Template `{self.name}` not found."


class Join(Enum):
    ZIP = 1
    PRODUCT = 2


@dataclass
class TemplateCall:
    template: str
    args: dict[str, str | list[str]]
    join: Join = Join.ZIP

    @property
    def all_args(self):
        if all(isinstance(v, str) for v in self.args.values()):
            yield self.args
            return

        if self.join == Join.ZIP:
            for v in zip(
                *map(
                    lambda x: itertools.repeat(x) if isinstance(x, str) else x,
                    self.args.values(),
                )
            ):
                yield dict(zip(self.args.keys(), v))

        else:  # cartesian join
            for v in itertools.product(
                *map(lambda x: [x] if isinstance(x, str) else x, self.args.values())
            ):
                yield dict(zip(self.args.keys(), v))


@dataclass
class Program:
    task: list[TaskProxy] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    template: dict[str, Template] = field(default_factory=dict)
    call: list[TemplateCall] = field(default_factory=list)
    include: list[str] = field(default_factory=list)
    runner: dict[str, Runner] = field(default_factory=dict)

    @staticmethod
    def read(path: Path) -> Program:
        with open(path, "rb") as f_in:
            data = tomllib.load(f_in)
        return construct(Program, data)


async def resolve_tasks(program: Program) -> TaskDB:
    db = TaskDB()
    template_index = dict()

    async def go(program: Program):
        for var, template in program.environment.items():
            db.add(TemplateVariable([Variable(var)], [], template))

        task_templates = copy(program.task)
        template_index.update(program.template)
        delayed_calls: list[TemplateCall] = []
        delayed_templates: list[TaskProxy] = []

        db.runners.update(program.runner)

        for c in program.call:
            if c.template not in template_index:
                log.debug(
                    "template `%s` not available, waiting for includes to resolve",
                    c.template,
                )
                delayed_calls.append(c)
                continue
            p = template_index[c.template]
            for args in c.all_args:
                task_templates.append(p.call(args))

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
                await db.run(incp, db=db)
            if not incp.exists():
                raise MissingInclude(incp)

            prg = Program.read(incp)
            await go(prg)

        for c in delayed_calls:
            if c.template not in template_index:
                log.debug(
                    "template `%s` still not available, now this is an error", c.template
                )
                raise MissingTemplate(c.template)
            p = template_index[c.template]
            for args in c.all_args:
                tt = p.call(c.args)
                if gather_args(tt.creates):
                    delayed_templates.append(tt)
                else:
                    db.add(TemplateTask([], [], tt))

        for tt in delayed_templates:
            if not db.is_resolvable(tt.all_targets):
                raise UserError(f"Task has unresolvable targets: {tt.creates}")
            tt = await db.resolve_object(tt)
            db.add(TemplateTask([], [], tt))

        return db

    return await go(program)
# ~/~ end
