from asyncio import sleep
from contextlib import chdir
from pathlib import Path

import pytest
from brei.construct import construct
from brei.lazy import Phony
from brei.program import Program, resolve_tasks
from brei.utility import stat


wf1 = { "task": [
    { "stdout": "x",
      "script": "echo 'hello'" },
    { "name": "all",
      "requires": ["x"] }
]}

wf2 = { "task": [
    { "stdout": "x",
      "script": "echo 'goodbye'" },
    { "name": "all",
      "requires": ["x"] }
]}

@pytest.mark.asyncio
async def test_without_history(tmp_path):
    with chdir(tmp_path):
        prg1 = construct(Program, wf1)
        db = await resolve_tasks(prg1)
        with db.persistent_history():
            await db.run(Phony("all"), db=db)
        s1 = stat(Path("x"))
        await sleep(0.01)
        db = await resolve_tasks(prg1)
        with db.persistent_history():
            await db.run(Phony("all"), db=db)
        s2 = stat(Path("x"))

        await sleep(0.01)
        prg2 = construct(Program, wf2)
        db = await resolve_tasks(prg2)
        with db.persistent_history():
            await db.run(Phony("all"), db=db)
        s3 = stat(Path("x"))

        assert Path("x").read_text().strip() == "goodbye"
        assert s1 < s2
        assert s2 < s3


@pytest.mark.asyncio
async def test_history(tmp_path):
    with chdir(tmp_path):
        prg1 = construct(Program, wf1)
        db = await resolve_tasks(prg1, Path("brei_history"))
        with db.persistent_history():
            await db.run(Phony("all"), db=db)
        s1 = stat(Path("x"))
        await sleep(0.01)
        db = await resolve_tasks(prg1, Path("brei_history"))
        with db.persistent_history():
            await db.run(Phony("all"), db=db)
        s2 = stat(Path("x"))

        await sleep(0.01)
        prg2 = construct(Program, wf2)
        db = await resolve_tasks(prg2, Path("brei_history"))
        with db.persistent_history():
            await db.run(Phony("all"), db=db)
        s3 = stat(Path("x"))

        assert Path("x").read_text().strip() == "goodbye"
        assert s1 == s2
        assert s3 > s2

