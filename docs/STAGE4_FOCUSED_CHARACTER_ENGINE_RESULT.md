# Stage 4 — Focused Character Engine Result

## Decision

Stage 4 engineering validation and integration: **PASSED**.

PR #31 was squash merged into `develop/v6-literary-engine` as commit `51887ce5fcd985a7ff42394ef902b144e04ede01`.

This decision covers the Focused Character Engine only. It is not final project acceptance, a release candidate, a production release, a final capability score, or repository freeze approval.

## Delivered scope

Stage 4 delivers:

- reviewed character selection based on main-plot, core-character, major-event, major-faction, or world-state impact;
- strict `core`, `important`, and `placeholder` scopes;
- mention-only names excluded from the canonical Character Project;
- exact Chapter Project position binding;
- literary assertion and evidence-anchor binding;
- verified Event Project participation, cause, choice, transformation, and consequence links;
- evidence-bound identity, role, goal, ability, choice, state, and relationship records;
- time-bounded state and relationship queries;
- A/B/C-separated character-arc records;
- explicit alias, support, temporal-state, placeholder-depth, and review-event findings;
- deterministic JSONL and SQLite Character Projects with foreign keys;
- logical hash, database hash, manifest, upstream-project, annotation, and deterministic rebuild verification;
- profile, state-at-position, relationship-at-position, major-event, arc, and selection-reason queries;
- `tkr-character build`, `verify`, and `query` commands;
- bundled `scripts/tkr.py character ...` entry points.

The engine does not create deep models for low-impact characters. Placeholder characters retain only minimal source-bound identity, role, location, and necessary event participation. Unsupported depth requests refuse.

## Focused regression

The Stage 4 focused suite contains **19 tests** covering:

- core-character material-impact requirements;
- placeholder impact-reason prohibition;
- placeholder ability and synthesis prohibition;
- character-arc restriction to core scope;
- C-grade attribution and limitation requirements;
- valid core/important/placeholder graph construction;
- alias collision findings;
- unknown assertion/evidence support findings;
- contradictory overlapping state findings;
- placeholder deep-relationship findings;
- review-required Event Project link blocking;
- deterministic graph builds;
- immutable Character Project build and verification;
- SQLite integrity and foreign keys;
- deterministic JSONL and database bytes;
- review-required Character Project propagation;
- tampered artifact rejection;
- evidence-linked profile, state, relationship, event, and arc queries;
- placeholder deep-query refusal;
- review-required graph query refusal.

## Final exact-head validation

- PR: #31;
- final PR head: `c737bb2d1625da2d356bcee39e3135070272bab0`;
- workflow: `Stage 4 Character CI`;
- workflow run: `29978838494`;
- runtime: Python 3.12 on Ubuntu;
- conclusion: success;
- squash merge commit: `51887ce5fcd985a7ff42394ef902b144e04ede01`.

Successful checks:

1. package installation;
2. Python compilation;
3. Stage 4 JSON Schema loading;
4. all 19 Stage 4 focused tests;
5. complete repository regression;
6. installed and bundled CLI smoke checks.

## Gate result

| Gate | Result |
|---|---|
| Core and important characters require material-impact reasons | Passed |
| Placeholder and mention-only scope cannot receive invented depth | Passed |
| Character records bind exact chapters, assertions, and evidence | Passed |
| Character-event links bind a verified Event Project | Passed |
| Review-required Event Projects cannot support active character conclusions | Passed |
| A/B/C character attributes and arcs remain separate | Passed |
| Time-bounded states and relationships remain queryable | Passed |
| Alias and temporal contradictions remain explicit findings | Passed |
| JSONL and SQLite identifiers agree | Passed |
| Report counts and hashes recompute | Passed |
| Repeated builds are deterministic | Passed |
| Unsupported deep queries refuse | Passed |
| Focused and repository regression | Passed |

## Workflow policy

GitHub Actions remain in reduced-noise mode:

- one Stage 4 workflow;
- one Python runtime;
- one job;
- pull request and manual triggers only;
- obsolete concurrent runs cancelled;
- no routine artifact upload;
- no release, final acceptance, or freeze workflow.

## Remaining boundary

Private-corpus blind evaluation and the requirement that all final core capability domains independently score at least 9.0 remain deferred to the final acceptance stage. Stage 4 does not assign a final capability score.
