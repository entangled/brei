# Programs

``` {.python file=brei/program.py}
from __future__ import annotations
import asyncio
from copy import copy
from itertools import chain, product, repeat
from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path

import tomllib


from .template_strings import gather_args
from .logging import logger
from .errors import HelpfulUserError, UserError

from .utility import construct, read_from_file
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
    INNER = 1
    OUTER = 2


@dataclass
class TemplateCall:
    """Calls a template with a set of arguments.

    Members:

      - template: name of the template.
      - args: arguments to the call.
      - collect: name of the phony target by which to collect all generated targets.
      - join: `inner` or `outer` join.
    """
    template: str
    args: dict[str, str | list[str]]
    collect: str | None = None
    join: Join = Join.INNER

    @property
    def all_args(self):
        if all(isinstance(v, str) for v in self.args.values()):
            yield self.args
            return

        if self.join == Join.INNER:
            for v in zip(
                *map(
                    lambda x: repeat(x) if isinstance(x, str) else x,
                    self.args.values(),
                )
            ):
                yield dict(zip(self.args.keys(), v))

        else:  # cartesian product
            for v in product(
                *map(lambda x: [x] if isinstance(x, str) else x, self.args.values())
            ):
                yield dict(zip(self.args.keys(), v))


@dataclass
class Program:
    """A Brei program.

    Members:

      - task: list of tasks.
      - environment: variables.
      - template: set of templates.
      - call: list of calls to templates.
      - include: list of includes.
      - runner: extra configured task runners.
    """
    task: list[TaskProxy] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    template: dict[str, Template] = field(default_factory=dict)
    call: list[TemplateCall] = field(default_factory=list)
    include: list[str] = field(default_factory=list)
    runner: dict[str, Runner] = field(default_factory=dict)

    @staticmethod
    def read(path: Path, section: str | None = None) -> Program:
        return read_from_file(Program, path, section)


def tasks_from_call(template: Template, call: TemplateCall) -> list[TaskProxy]:
    tasks = [template.call(args) for args in call.all_args]
    if call.collect:
        targets = list(chain.from_iterable(t.creates for t in tasks))
        collection = TaskProxy([], targets, name=call.collect)
        return tasks + [collection]
    else:
        return tasks


async def resolve_delayed(db: TaskDB, tasks: list[TaskProxy]) -> list[TaskProxy]:
    """Resolve `tasks` (substituting variables in targets).

    Returns: list of unresolvable tasks.
    """
    async def resolve(task: TaskProxy) -> TaskProxy | None:
        if not db.is_resolvable(task.all_targets):
            return task
        tt = await db.resolve_object(task)
        db.add(TemplateTask([], [], tt))
        return None

    return [t for t in await asyncio.gather(*map(resolve, tasks)) if t]


async def resolve_tasks(program: Program) -> TaskDB:
    """Resolve a program. A resolved program has all of its includes and
    template calls done, so that only tasks remains. In order to resolve
    a program, some tasks may need to be run. Variables that appear in
    the `creates` field of a task (aka targets), will be resolved eagerly.

    Returns: TaskDB instance.
    """
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

            task_templates.extend(tasks_from_call(template_index[c.template], c))

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

        delayed_templates = await resolve_delayed(db, delayed_templates)

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

            for tt in tasks_from_call(template_index[c.template], c):
                if gather_args(tt.creates):
                    delayed_templates.append(tt)
                else:
                    db.add(TemplateTask([], [], tt))

        delayed_templates = await resolve_delayed(db, delayed_templates)
        if delayed_templates:
            unresolvable = [p for t in delayed_templates for p in t.creates if not db.is_resolvable(p)]
            raise UserError(f"Task has unresolvable targets: {unresolvable}")

        return db

    return await go(program)
```
