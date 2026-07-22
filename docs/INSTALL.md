# Installation and Clean-Environment Verification

## Supported Python

Text Knowledge Reader requires Python 3.10 or newer. Stage 5 developer checks run on Python 3.10, 3.11, and 3.12.

## Source checkout installation

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
```

On Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .
```

## Wheel installation

Build a wheel without installing project dependencies:

```bash
python -m pip wheel . --no-deps --wheel-dir dist
```

Install the generated wheel into a new virtual environment:

```bash
python -m venv .venv-wheel
. .venv-wheel/bin/activate
python -m pip install dist/text_knowledge_reader_core-*.whl
```

## Required post-install checks

```bash
tkr-skill doctor
tkr-skill audit
tkr-skill profiles
tkr-project --help
```

A complete installation must include:

- the `tkr` Python package;
- all console commands;
- `SKILL.md`;
- `README.md`;
- `PROJECT_STATUS.yaml`;
- JSON Schemas;
- built-in engineering profiles;
- examples;
- operational documentation.

## Minimal build and query check

From a source checkout:

```bash
tkr-project build examples/minimal-corpus.txt \
  --outdir .tmp/example-project \
  --state-dir .tmp/example-state \
  --profile balanced

tkr-project verify .tmp/example-project
tkr-project query .tmp/example-project "陆川击败了谁？"
```

The project directory and state directory must not overlap.

## Uninstall

```bash
python -m pip uninstall text-knowledge-reader-core
```

After uninstalling, verify that console commands are no longer resolved by the removed virtual environment. User-created projects and external state directories are not deleted by package uninstall.

## Development-only status

Successful installation and doctor/audit output are engineering checks. They do not perform final project acceptance, create a Release Candidate, or approve Freeze.
