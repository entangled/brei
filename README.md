# Brei
[![GitHub Org's stars](https://img.shields.io/github/stars/entangled)](https://github.com/entangled/brei)
[![Python package](https://github.com/entangled/brei/actions/workflows/python-package.yml/badge.svg)](https://github.com/entangled/brei/actions/workflows/python-package.yml)
[![PyPI - Version](https://img.shields.io/pypi/v/brei)](https://pypi.org/project/brei)
[![Entangled badge](https://img.shields.io/badge/entangled-Use%20the%20source!-%2300aeff)](https://entangled.github.io/)

Minimal workflow system and alternative to Make.

- Read from TOML or JSON (also `pyproject.toml` in `[tool.brei]` section)
- Only Python &ge; 3.11 required
- Runs task lazily and in parallel
- Supports variables, templates, includes and custom runners

Read more: [documentation](https://entangled.github.io/brei)

## Why (yet another workflow tool)
This tool was developed as part of the Entangled project, but can be used on its own. Brei is meant to perform small scale automisations for literate programming in Entangled, like generating figures, and performing computations locally. It requires no setup to work with and workflows are easy to understand by novice users. If you have any more serious needs than that, we'd recommend to use a more tried and proven system, of which there are too many to count.

## When to use
You're running a project, there's lots of odds and ends that need automisation. You'd use a `Makefile` but your friend is on Windows and doesn't have GNU Make installed. You try to ship a product that needs this, but don't want to confront people trying it for the first time with a tonne of stuff they've never heard of.

## Install
To install, you may:

```
pip install brei
```

Or you use a tool for virtual environments, we recommend [Poetry](https://python-poetry.org/), after creating a new project with `poetry init`:

```
poetry add brei
```

## Development
To run unit tests and type checker:

```
poetry install
poetry shell
brei test
```

To build the documentation, run the `brei weave` workflow:

```
# poetry shell
brei weave
```

Some parts of Brei are literate. Run the entangled watch daemon while editing code,

```
entangled watch
```

or else, as a batch job, stitch changes before committing:

```
entangled stitch
```

## License
Copyright Netherlands eScience Center, Apache License, see LICENSE.
