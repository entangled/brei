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
dependencies = ["hello.txt"]

[[task]]
stdout = "hello.txt"
language = "Bash"
script = "echo 'Hello, World'"
""", [ ("hello.txt", "Hello, World") ])


include = LoomTest("""
include = [
    "generated_wf.toml"
] 

[[task]]
stdout = "generated_wf.toml"
language = "Python"
script = '''
print(\"\"\"
[[task]]
stdout = "hello.txt"
language = "Bash"
script = "echo 'Hello, World'"
\"\"\")
'''

[[task]]
name = "all"
dependencies = ["hello.txt"]
""", [ ("hello.txt", "Hello, World") ])


pattern = LoomTest("""
[pattern.echo]
targets = ["${stdout}"]
stdout = "${stdout}"
language = "Python"
script = '''
print("${text}")
'''

[[task]]
name = "all"
dependencies = ["hello.txt"]

[[call]]
pattern = "echo"
args = { stdout = "hello.txt", text = "Hello, World" }
""", [ ("hello.txt", "Hello, World") ])


rot_13 = LoomTest("""
[[task]]
stdout = "secret.txt"
language = "Python"
script = \"\"\"
print("Uryyb, Jbeyq!")
\"\"\"

[pattern.rot13]
stdout = "${stdout}"
stdin = "${stdin}"
language = "Bash"
script = \"\"\"
tr a-zA-Z n-za-mN-ZA-M
\"\"\"

[[call]]
pattern = "rot13"
  [call.args]
  stdin = "secret.txt"
  stdout = "hello.txt"

[[task]]
name = "all"
dependencies = ["hello.txt"]
""", [ ("hello.txt", "Hello, World!") ])


templated_task = LoomTest("""
[environment]
msg = "Hello, World!"

[[task]]
stdout = "hello.txt"
language = "Bash"
script = "echo '${msg}'"

[[task]]
name = "all"
dependencies = ["hello.txt"]
""", [("hello.txt", "Hello, World!")])


variable_stdout = LoomTest("""
[pattern.echo]
language = "Bash"
script = "echo '${text}'"
stdout = "${stdout}"

[[call]]
pattern = "echo"
  [call.args]
  text = "Hello, World!"
  stdout = "var(msg)"

[[task]]
language = "Bash"
script = "cat"
stdin = "var(msg)"
stdout = "hello.txt"

[[call]]
pattern = "echo"
  [call.args]
  text = "goodbye.txt"
  stdout = "var(file_name)"

[[task]]
language = "Bash"
script = "cat"
stdin = "var(msg)"
stdout = "${file_name}"

[[task]]
name = "all"
dependencies = ["hello.txt", "${file_name}"]
""", [("hello.txt", "Hello, World!"), ("goodbye.txt", "Hello, World!")])

@pytest.mark.parametrize("test", [hello_world, include, pattern, rot_13, templated_task, variable_stdout])
@pytest.mark.asyncio
async def test_loom(tmp_path, test):
    with chdir(tmp_path):
        src = Path("loom.toml")
        src.write_text(test.script)
        prg = Program.read(src)
        db = await resolve_tasks(prg)
        await db.run(Phony("all"), db)

        for (tgt, content) in test.post_state:
            tgt = Path(tgt)
            assert tgt.exists()
            assert tgt.read_text().strip() == content.strip()

