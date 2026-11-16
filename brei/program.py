# ~/~ begin <<docs/program.md#brei/program.py>>[init]
from __future__ import annotations
import asyncio
from copy import copy
from itertools import chain, product, repeat
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path

import tomllib
from msgspec import Struct, field
from msgspec.structs import replace


from .template_strings import gather_args, substitute
from .logging import logger
from .errors import HelpfulUserError, UserError

from .utility import construct, read_from_file
from .task import (
    splice_name,
    Variable,
    TaskDB,
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
    INNER = "inner"
    OUTER = "outer"


class TemplateCall(Struct, forbid_unknown_fields=True):
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
            # Lists may be computed with `splice`, so a difference in length
            # is an error, instead of silently dropping items.
            lengths = {k: len(v) for k, v in self.args.items() if not isinstance(v, str)}
            if len(set(lengths.values())) > 1:
                raise HelpfulUserError(
                    f"Template `{self.template}`: the arguments of an inner join should "
                    "have the same length, got " + ", ".join(f"{k}: {n}" for k, n in lengths.items()))
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


class Program(Struct, forbid_unknown_fields=True):
    """A Brei program.

    Members:

      - task: list of tasks.
      - environment: variables.
      - template: set of templates; these are tasks with template variables
        that are substituted by a `TemplateCall`.
      - call: list of calls to templates.
      - include: list of includes.
      - runner: extra configured task runners.
    """
    task: list[TaskProxy] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    template: dict[str, TaskProxy] = field(default_factory=dict)
    call: list[TemplateCall] = field(default_factory=list)
    include: list[str] = field(default_factory=list)
    runner: dict[str, Runner] = field(default_factory=dict)

    @staticmethod
    def read(path: Path, section: str | None = None) -> Program:
        return read_from_file(Program, path, section)


def call_splices(call: TemplateCall) -> list[str]:
    """Names of the list variables spliced into the arguments of `call`."""
    return [n for v in call.args.values() for item in ([v] if isinstance(v, str) else v)
            if (n := splice_name(item))]


async def expand_splices(db: TaskDB, call: TemplateCall) -> TemplateCall:
    """Compute the list variables spliced into the arguments of `call`, and
    insert their elements."""
    names = call_splices(call)
    results = await asyncio.gather(*(db.run(Variable(n), db=db) for n in names))
    for n, r in zip(names, results):
        if not r:
            raise HelpfulUserError(f"Could not compute list variable `{n}`: {r}")

    def expand(v: str | list[str]) -> str | list[str]:
        if isinstance(v, str):
            return db.splice([v]) if splice_name(v) else v
        return db.splice(v)

    return replace(call, args={k: expand(v) for k, v in call.args.items()})


def tasks_from_call(template: TaskProxy, call: TemplateCall) -> list[TaskProxy]:
    tasks = [substitute(template, args) for args in call.all_args]
    if call.collect:
        targets = list(chain.from_iterable(t.all_targets for t in tasks))
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


async def resolve_tasks(program: Program, history_path: Path | None = None) -> TaskDB:
    """Resolve a program. A resolved program has all of its includes and
    template calls done, so that only tasks remains. In order to resolve
    a program, some tasks may need to be run. Variables that appear in
    the `creates` field of a task (aka targets), will be resolved eagerly.

    Returns: TaskDB instance.
    """
    db = TaskDB(history_path = history_path)
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
            if call_splices(c):
                log.debug("call to `%s` splices list variables, waiting for tasks", c.template)
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

            c = await expand_splices(db, c)
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

    with db.persistent_history():
        await go(program)

    return db
# ~/~ end
