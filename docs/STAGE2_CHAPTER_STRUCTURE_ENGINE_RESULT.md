# Stage 2 — Chapter Structure Engine Result

## Decision

Stage 2 engineering validation: **PASSED — completed and integrated into `develop/v6-literary-engine`**.

This decision covers the Chapter Structure Engine only. It is not final project acceptance, a release candidate, a production release, a final capability score, or repository freeze approval.

## Integration record

- pull request: `#29`;
- final PR head: `564e9282632390ccb39987be4964d903009c7394`;
- final workflow: `Stage 2 Chapter CI`;
- final workflow run: `29973788342`;
- final workflow conclusion: success;
- squash merge commit: `b09e6695a487fd12fa8285314914a93c7336d07f`;
- integration branch: `develop/v6-literary-engine`.

## Delivered scope

Stage 2 delivers:

- deterministic canonical chapter records over one or more verified source projects;
- immutable input/file order, source-local order, and global physical order;
- separate numbering-derived canonical-order candidates;
- parent-volume recovery from combined headings, explicit parent volume Units, or conservative preceding-volume context;
- exact source filename, source ID, source SHA-256, Unit, heading, title, body, character span, line span, and content SHA-256 binding;
- duplicate key, duplicate content, gap, inversion, missing ordinal, missing/detached/titleless heading, empty body, contamination, and terminal-placement findings;
- cross-source numbering-range overlap and input-order disagreement findings;
- deterministic JSONL and SQLite stores with foreign keys;
- logical hash, database hash, manifest, source rebuild, and source-order verification;
- exact address, finding-rule, chapter-ID, physical-neighbor, and canonical-neighbor queries;
- `tkr-chapter build`, `verify`, and `query` commands;
- bundled `scripts/tkr.py chapter ...` entry points.

The engine never rewrites, deletes, merges, renumbers, reorders, or repairs source text. Canonical order remains explicitly marked as a reviewable candidate.

## Focused regression

The Stage 2 focused suite contains **17 tests** across:

- parent-volume inheritance;
- combined volume/chapter headings;
- physical and canonical order separation;
- chapter gaps and inversions;
- duplicate chapter addresses;
- retained contaminated chapters with blocking findings;
- repeated deterministic catalog builds;
- cross-source numbering overlap and order disagreement;
- idempotent source-order augmentation;
- immutable Chapter Project build and verification;
- SQLite integrity and foreign keys;
- deterministic JSONL and database bytes;
- tampered artifact rejection;
- source-project order binding;
- unregistered-file rejection;
- exact address and neighbor queries;
- refusal for absent chapter addresses.

## Final validation

- runtime: Python 3.12 on Ubuntu;
- package installation: passed;
- Python compilation: passed;
- Stage 2 JSON Schema loading: passed;
- all 17 Stage 2 focused tests: passed;
- complete repository regression: passed;
- installed and bundled CLI smoke checks: passed.

## Gate result

| Gate | Result |
|---|---|
| Every chapter span and content hash recomputes from source | Passed |
| Parent-volume mappings remain source-bound and auditable | Passed |
| Physical order remains immutable | Passed |
| Canonical order remains a candidate | Passed |
| Duplicate, gap, inversion, unknown ordinal, and contamination states are explicit | Passed |
| Cross-source overlap and order disagreement are explicit | Passed |
| JSONL and SQLite identifiers agree | Passed |
| Report counts and logical hashes recompute | Passed |
| Repeated builds are deterministic | Passed |
| Missing addresses refuse instead of guessing | Passed |
| Focused and repository regression | Passed |

## Workflow policy

GitHub Actions remain in reduced-noise mode:

- one current-stage workflow;
- one Python runtime;
- one job;
- pull request and manual triggers only;
- obsolete concurrent runs cancelled;
- no routine artifact upload;
- no release, final acceptance, or freeze workflow.

## Remaining boundary

Private-corpus blind evaluation and the requirement that all final core capability domains score at least 9.0 remain deferred to the final acceptance stage. Stage 2 does not assign a final capability score.
