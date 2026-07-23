# Stage 3 — Event Causality Engine Result

## Decision

Stage 3 engineering validation: **PASSED — ready for final exact-head CI and integration into `develop/v6-literary-engine`**.

This decision covers the focused Event Causality Engine only. It is not final project acceptance, a release candidate, a production release, a final capability score, or repository freeze approval.

## Delivered scope

Stage 3 delivers:

- focused canonical events limited to mainline, core-character, major-faction, world-state, or later-major-event impact;
- exact Chapter Project start/end position binding;
- literary assertion and evidence-anchor binding;
- A/B/C-separated `cause`, `process`, `outcome`, `consequence`, `foreshadowing`, and `recovery` components;
- supported `triggers`, `enables`, `escalates`, `prevents`, `reveals`, `undermines`, `resolves`, `foreshadows`, and `recovers` edges;
- temporal-direction validation;
- active-cycle, unknown-support, endpoint, position, and interpretation-leakage findings;
- deterministic JSONL and SQLite Event Projects with foreign keys;
- logical hash, database hash, manifest, Chapter Project, literary-project, and annotation verification;
- active graph and `review_required` graph states;
- event profile, component, upstream, downstream, supported causal path, and foreshadowing queries;
- exact assertion and evidence expansion in query packets;
- `tkr-event build`, `verify`, and `query` commands;
- bundled `scripts/tkr.py event ...` entry points.

The engine does not create heavy nodes for low-impact scenes. Unsupported paths refuse, and review-required graphs cannot present causal conclusions.

## Focused regression

The Stage 3 focused suite contains **16 tests** covering:

- active-event significance and evidence requirements;
- B-grade multiple-support rules;
- C-grade attribution and limitation rules;
- forward temporal direction;
- backward-reference recovery edges;
- valid A-grade event graphs;
- unknown assertion/evidence rejection;
- event-position binding;
- active causal cycles;
- deterministic graph builds;
- immutable Event Project build and verification;
- SQLite integrity and foreign keys;
- deterministic JSONL and database bytes;
- review-required cycle projects;
- tampered artifact rejection;
- evidence-expanded event profile, path, and foreshadowing queries;
- refusal for unsupported paths and review-required graphs.

## Validation

Latest completed implementation validation before final documentation:

- workflow: `Stage 3 Event CI`;
- head: `5f9b1b9f5cbe1a6f568bd6f372adf2972c32d187`;
- run: `29974960981`;
- runtime: Python 3.12 on Ubuntu;
- conclusion: success.

Successful checks:

1. package installation;
2. Python compilation;
3. Stage 3 JSON Schema loading;
4. all 16 Stage 3 focused tests;
5. complete repository regression;
6. installed and bundled CLI smoke checks.

The final PR head must pass the same workflow before merge.

## Gate result

| Gate | Result |
|---|---|
| Every active event is chapter- and evidence-bound | Passed |
| Every active causal edge has supported endpoints | Passed |
| A/B/C event components and edges remain separate | Passed |
| Forward and recovery temporal directions are valid | Passed |
| Cycles and unsupported references are explicit | Passed |
| Review-required graphs refuse causal answers | Passed |
| Query paths return edge and evidence support | Passed |
| JSONL and SQLite identifiers agree | Passed |
| Report counts and hashes recompute | Passed |
| Repeated builds are deterministic | Passed |
| Unsupported causal paths refuse | Passed |
| Focused and repository regression | Passed |

## Workflow policy

GitHub Actions remain in reduced-noise mode:

- one Stage 3 workflow;
- one Python runtime;
- one job;
- pull request and manual triggers only;
- obsolete concurrent runs cancelled;
- no routine artifact upload;
- no release, final acceptance, or freeze workflow.

## Remaining boundary

Private-corpus blind evaluation and the requirement that all final core capability domains score at least 9.0 remain deferred to the final acceptance stage. Stage 3 does not assign a final capability score.
