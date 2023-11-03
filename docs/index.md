# Welcome to Brei
Brei is a small workflow system in Python. The primary reason for creating Brei is to replace GNU Make, in order to be compatible on systems that are naturally deprived of this wonder of human ingenuity. In a nutshell:

```toml
[[task]]
description = "Greet the Globe"
stdout = "hello.txt"
script = "echo 'Hello, World!'"
```

- No new syntax: programmable workflows in TOML or JSON files.
- Efficient: Runs tasks lazily and in parallel.
- Feature complete: Supports templates, variables, includes and configurable runners.
- Few dependencies: Only needs Python &ge;3.11.
- Small codebase: Brei is around 1000 lines of Python.

```bash
pip install brei
```

## Why
Why yet another workflow tool? This tool was developed as part of the [Entangled project](https://entangled.github.io), but can be used on its own. Brei is meant to perform small scale automisations for literate programming in Entangled, like generating figures, and performing computations locally. It requires no setup to work with and workflows are easy to understand by novice users. If you have any more serious needs than that, we'd recommend to use a more tried and proven system, of which there are too many to count.

## When to use
You're running a project, there's lots of odds and ends that need automisation. You'd use a `Makefile` but your friend is on Windows and doesn't have GNU Make installed. You try to ship a product that needs this, but don't want to confront people trying it for the first time with a tonne of stuff they've never heard of.

# Running
Brei is available on PyPI:

```
pip install brei
```

Although for Python we recommend using virtual environments, for example [Poetry](https://python-poetry.org/). Once you've setup a project in Poetry

```
poetry add brei
```

Then `brei` should be available as a command-line executable.

``` {.bash .eval}
brei --help
```

# How it works
You give Brei a list of tasks that may depend on one another. Brei will run these when input files are newer than the target. Execution is lazy and in parallel.

## Tasks
Tasks are the elemental units of work in Brei. A task is the single execution of a given script, and can be indicated to depend on previous tasks by explicitly listing targets and dependencies.

``` {.toml file=examples/tasks.toml}
[[task]]
creates = ["hello.txt"]
runner = "bash"
script = "echo 'Hello, World!' > hello.txt"

[[task]]
name = "all"
requires = ["hello.txt"]

[[task]]
name = "clean"
script = "rm hello.txt"
```

This defines to named tasks `all` and `clean`, where `all` depends on the creation of a file `hello.txt`. Giving a `name` to a task is similar to creating a 'phony' target in Make.

## Templates
We can use patterns to create reusable items. Variables follow Python's `string.Template` syntax (similar to many scripting languages), `${var_name}` substitutes for the contents of the `var_name` variable. Use two dollar signs `$$` to make a `$` literal.

``` {.toml file=examples/rot13.toml}
[[task]]
description = "Creating temporary directory"
stdout = "var(dir)"
script = "mktemp -d"

[template.echo]
stdout = "${stdout}"
script = "echo ${text}"

[template.rot13]
stdout = "${stdout}"
stdin = "${stdin}"
script = "tr a-zA-Z n-za-mN-ZA-M"

[[call]]
template = "echo"
  [call.args]
  stdout = "${dir}/secret.txt"
  text = "Uryyb, Jbeyq!"

[[call]]
template = "rot13"
  [call.args]
  stdin = "${dir}/secret.txt"
  stdout = "${dir}/msg.txt"

[[task]]
name = "all"
requires = ["${dir}/msg.txt"]
script = "cat ${dir}/msg.txt"
```

``` {.bash .eval}
brei -i examples/rot13.toml all
```

### Multiplexing

You can call templates with lists of arguments to create many tasks. There are two ways to combine multiple arguments: `inner` and `outer`, configured with the `join` argument. The `inner` product uses `zip` to join the arguments, while `outer` uses `itertools.product` to join. The default is `inner`.

``` {.toml file=examples/template_multiplexing.toml}
[[task]]
description = "Creating temporary directory"
stdout = "var(dir)"
script = "mktemp -d"

[template.touch]
description = "${pre} ${a} ${b}"
creates = ["${dir}/${pre}-${a}-${b}"]
script = "touch '${dir}/${pre}-${a}-${b}'"

[[call]]
template = "touch"
collect = "inner"
  [call.args]
  pre = "inner"
  a = ["x", "y", "z"]
  b = ["1", "2", "3"]

[[call]]
template = "touch"
collect = "outer"
join = "outer"
  [call.args]
  pre = "outer"
  a = ["x", "y"]
  b = ["1", "2"]

[[task]]
name = "all"
requires = ["#inner", "#outer"]
```

The `collect` argument creates a collection phony task containing all items in the call.

``` {.bash .eval}
brei -i examples/template_multiplexing.toml all
```

## Variables
You may write the output of a command to the contents of a variable, by using `"var(name)"` as a target.
For instance, in many science applications its desirable to know which version of a software generated some output. 

``` {.toml file=examples/versioned_output.toml}
[environment]
data_dir = "./data"
output_dir = "./output/${commit}"

[[task]]
stdout = "var(commit)"
script = "git rev-parse HEAD"

[[task]]
creates = ["${output_dir}/data.h5"]
requires = ["${data_dir}/input.h5", "#prepare"]
runner = "python"
path = "scripts/run.py"

[[task]]
name = "prepare"
script = """
mkdir -p ${output_dir}
ln -sf ${output_dir} output/latest
"""

[[task]]
name = "all"
requires = ["${output_dir}/data.h5"]
```

Also note the following:

- Instead of listing a `script` you can give a `path` to an existing script.
- Named (phony) targets are referenced with a hash symbol `#`.
- Tasks with no targets are always run.
- The `[environment]` item lists global variables.
- All string substitution is done lazily.

## Includes
You can include parts of a workflow from other files, both TOML and JSON.

``` {.toml file=examples/echo.toml}
[template.echo]
stdout = "${stdout}"
script = "echo '${text}'"
```

``` {.toml file=examples/hello-includes.toml}
include = [
    "./echo.toml"
]

[[call]]
template = "echo"
  [call.args]
  stdout = "hello.txt"
  text = "Hello, World!"

[[task]]
name = "all"
requires = ["hello.txt"]
```

It is even possible to include files that still need to be generated. The following generates a file with ten tasks, includes that file and runs those tasks.

``` {.toml file=examples/include-gen.toml}
include = [
    "${dir}/gen.json"
]

[[task]]
description = "Creating temporary directory"
stdout = "var(dir)"
script = "mktemp -d"

[[task]]
description = "Generating workflow"
stdout = "${dir}/gen.json"
runner = "python"
script = """
import json
tasks = [
    {"stdout": f"${dir}/out{i}.dat",
     "script": f"echo '{i}'"} for i in range(10)
]
tasks.append({"name": "write-outs", "requires": [
    f"${dir}/out{i}.dat" for i in range(10)
]})
print(json.dumps({"task": tasks}))
"""

[[task]]
name = "all"
requires = ["#write-outs"]
```

``` {.bash .eval}
brei -i examples/include-gen.toml all
```

## Custom Runner
By default, the contents of `script` is split in lines, then each line is passed through Python's `shlex.split` function and then run using `asyncio.create_subprocess_exec`. What that means is that the script will perform the same operations on all platforms, and arguments are collected similar to a normal Unix shell or Windows command prompt. However, you can choose to have the script run by any other means by providing the `runner` argument.


``` {.toml file=examples/custom-runner.toml}
[[task]]
description = "Creating temporary directory"
stdout = "var(dir)"
script = "mktemp -d"

[runner.lua]
command = "lua"
args = ["${script}"]

[[task]]
runner = "lua"
stdout = "${dir}/hello.txt"
script = """
function fact (n)
  if n == 0 then
    return 1
  else
    return n * fact(n-1)
  end
end

print("10! = ", fact(10))
"""

[[task]]
name = "all"
requires = ["${dir}/hello.txt"]
script = "cat ${dir}/hello.txt"
```

``` {.bash .eval}
brei -i examples/custom-runner.toml all
```

There are a number of runners configured by default.

``` {.bash .eval}
brei --list-runners
```

## Forcing a rerun
Sometimes you want to always rerun a task no matter what.

``` {.toml file=examples/force_run.toml}
[[task]]
name = "test"
requires = ["#coverage-report"]

[[task]]
description = "Print coverage info"
name = "coverage-report"
requires = [".coverage"]
script = "coverage report"

[[task]]
creates = [".coverage"]
force = true
description = "Run tests"
script = "coverage run --source=brei -m pytest"
```

``` {.bash .eval}
brei -i examples/force_run.toml test
```

## Remarks

- If you need your workflows also execute on a Windows machine, it is advised to write scripts for the default runner (lists of commands) or in Python.
- Brei is not meant for building programs, so it doesn't have the same feature set as GNU Make. If you need more complex logic, you can write a Brei generator. The generator creates tasks, writes them to JSON and then Brei can `include` the result from your generator task.
- TOML is nice but not ideal: it can be tricky to see the difference beteween single `[...]` and double `[[...]]` square brackets. Sometimes TOML syntax will lead to very verbose notation, however, current alternatives are all worse.
- Many modern programming languages that we like (Python, Rust, Julia) have their project settings in a TOML file. This way your Brei workflow can piggy-back on project files that are already there.

# License
Copyright 2023 Netherlands eScience Center, Licensed under the Apache License, Version 2.0, see [LICENSE](https://www.apache.org/licenses/LICENSE-2.0).
