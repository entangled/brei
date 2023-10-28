from contextlib import chdir
from dataclasses import dataclass
from pathlib import Path
import sys
import time

import pytest
from loom.lazy import Phony
from loom.program import Program, resolve_tasks
from loom.task import Task


@dataclass
class LoomTest:
    script: str
    post_state: list[tuple[str, str]]


hello_world = LoomTest("""
[[task]]
name = "all"
requires = ["hello.txt"]

[[task]]
stdout = "hello.txt"
runner = "Bash"
script = "echo 'Hello, World'"
""", [ ("hello.txt", "Hello, World") ])


include = LoomTest("""
include = [
    "generated_wf.toml"
] 

[[task]]
stdout = "generated_wf.toml"
runner = "Python"
script = '''
print(\"\"\"
[[task]]
stdout = "hello.txt"
runner = "Bash"
script = "echo 'Hello, World'"
\"\"\")
'''

[[task]]
name = "all"
requires = ["hello.txt"]
""", [ ("hello.txt", "Hello, World") ])


template = LoomTest("""
[template.echo]
stdout = "${stdout}"
runner = "Python"
script = '''
print("${text}")
'''

[[task]]
name = "all"
requires = ["hello.txt"]

[[call]]
template = "echo"
args = { stdout = "hello.txt", text = "Hello, World" }
""", [ ("hello.txt", "Hello, World") ])


rot_13 = LoomTest("""
[[task]]
stdout = "secret.txt"
runner = "Python"
script = \"\"\"
print("Uryyb, Jbeyq!")
\"\"\"

[template.rot13]
stdout = "${stdout}"
stdin = "${stdin}"
script = "tr a-zA-Z n-za-mN-ZA-M"

[[call]]
template = "rot13"
  [call.args]
  stdin = "secret.txt"
  stdout = "hello.txt"

[[task]]
name = "all"
requires = ["hello.txt"]
""", [ ("hello.txt", "Hello, World!") ])


templated_task = LoomTest("""
[environment]
msg = "Hello, World!"

[[task]]
stdout = "hello.txt"
runner = "Bash"
script = "echo '${msg}'"

[[task]]
name = "all"
requires = ["hello.txt"]
""", [("hello.txt", "Hello, World!")])


variable_stdout = LoomTest("""
[template.echo]
runner = "Bash"
script = "echo '${text}'"
stdout = "${stdout}"

[[call]]
template = "echo"
  [call.args]
  text = "Hello, World!"
  stdout = "var(msg)"

[[task]]
runner = "Bash"
script = "cat"
stdin = "var(msg)"
stdout = "hello.txt"

[[call]]
template = "echo"
  [call.args]
  text = "goodbye.txt"
  stdout = "var(file_name)"

[[task]]
runner = "Bash"
script = "cat"
stdin = "var(msg)"
stdout = "${file_name}"

[[task]]
name = "all"
requires = ["hello.txt", "${file_name}"]
""", [("hello.txt", "Hello, World!"), ("goodbye.txt", "Hello, World!")])


array_call = LoomTest("""
[template.echo]
runner = "Bash"
script = "echo '${a}${b}'"
stdout = "${pre}-${a}-${b}"

[[call]]
template = "echo"
  [call.args]
  pre = "zip"
  a = ["1", "2", "3"]
  b = ["a", "b", "c"]

[[call]]
template = "echo"
join = "product"
  [call.args]
  pre = "prod"
  a = ["1", "2"]
  b = ["a", "b"]

[[task]]
name = "all"
requires = ["zip-1-a", "zip-2-b", "zip-3-c",
                "prod-1-a", "prod-1-b", "prod-2-a", "prod-2-b"]
""", [("zip-1-a", "1a"), ("zip-2-b", "2b"), ("zip-3-c", "3c"),
      ("prod-1-a", "1a"), ("prod-1-b", "1b"), ("prod-2-a", "2a"), ("prod-2-b", "2b")])

@pytest.mark.parametrize("test", [hello_world, include, template, rot_13, templated_task, variable_stdout, array_call])
@pytest.mark.asyncio
async def test_loom(tmp_path, test):
    with chdir(tmp_path):
        src = Path("loom.toml")
        src.write_text(test.script)
        prg = Program.read(src)
        db = await resolve_tasks(prg)

        await db.run(Phony("all"), db=db)

        for (tgt, content) in test.post_state:
            tgt = Path(tgt)
            assert tgt.exists()
            assert tgt.read_text().strip() == content.strip()

