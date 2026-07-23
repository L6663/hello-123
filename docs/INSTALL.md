# Installation and Clean-Environment Verification

## Supported Python

Text Knowledge Reader `6.0.0rc1` requires Python 3.10 or newer. Stage 8 package acceptance is executed independently on Python 3.10, 3.11, and 3.12.

A successful installation proves package integrity only. It does not perform private blind evaluation, approve project acceptance, authorize publication, or freeze the repository.

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

## Reproducible Wheel build

Set one fixed `SOURCE_DATE_EPOCH` for all candidate builds:

```bash
export SOURCE_DATE_EPOCH=1700000000
python -m pip install --upgrade build
python -m build --wheel --outdir dist-a
python -m build --wheel --outdir dist-b
sha256sum dist-a/*.whl dist-b/*.whl
```

The two Wheel files must be byte-identical. Stage 8 binds the Wheel filename, SHA-256, package version, source commit, and `SOURCE_DATE_EPOCH`.

Install the canonical Wheel into a new virtual environment:

```bash
python -m venv .venv-wheel
. .venv-wheel/bin/activate
python -m pip install dist-a/text_knowledge_reader_core-6.0.0rc1-py3-none-any.whl
```

## Required post-install checks

```bash
tkr-skill doctor
tkr-skill audit
tkr-skill profiles
tkr-project --help
tkr-literary --help
tkr-evidence --help
tkr-chapter --help
tkr-event --help
tkr-character --help
tkr-reason --help
tkr-notion --help
tkr-literary-benchmark --help
tkr-final-acceptance --help
```

A complete installation must include:

- the `tkr` Python package;
- all installed console commands;
- `SKILL.md`, `README.md`, `PROJECT_STATUS.yaml`, and `pyproject.toml`;
- all public JSON Schemas, including Stage 7 and Stage 8 contracts;
- three built-in engineering profiles;
- executable examples;
- Stage 1–8 operational documentation.

## Installed Skill audit

The installed package must produce a zero-finding audit and a passing doctor report:

```bash
tkr-skill audit --output skill-audit.json
tkr-skill doctor --output skill-doctor.json
```

Both reports retain:

```yaml
project_acceptance_performed: false
may_accept_project: false
release_candidate: false
may_freeze: false
```

They are technical evidence for Stage 8 and cannot approve the product.

## Minimal source build and query check

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

## Literary benchmark commands

```bash
tkr-literary-benchmark evaluate \
  literary-cases.jsonl \
  literary-observations.jsonl \
  --profile release \
  --output literary-report.json

tkr-literary-benchmark verify \
  literary-cases.jsonl \
  literary-observations.jsonl \
  literary-report.json \
  --output literary-verification.json
```

The release profile requires private, independently reviewed Gold evidence. Do not use synthetic smoke fixtures as final acceptance evidence.

## Final acceptance commands

```bash
tkr-final-acceptance prepare --help
tkr-final-acceptance verify --help
tkr-final-acceptance seal --help
tkr-final-acceptance verify-seal --help
```

`prepare` and `verify` create or recompute a technical candidate with all authority flags false. The CLI never generates the explicit approval record required by `seal`.

A valid acceptance Seal may establish project acceptance and Release Candidate eligibility, but it still keeps:

```yaml
may_release: false
may_freeze: false
```

Publication and freeze require later, separate explicit decisions.

## Uninstall

```bash
python -m pip uninstall text-knowledge-reader-core
```

After uninstalling, verify that commands no longer resolve from the removed virtual environment. User-created projects, private blind evidence, acceptance candidates, approval records, Seals, and external state directories are not deleted by package uninstall.

## Historical release boundary

The historical v5.9.0 release remains frozen on its existing release line. Installing or testing `6.0.0rc1` does not mutate or unfreeze v5.9.0.
