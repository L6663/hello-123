# Stage 3 — Event Causality Engine Result

## Decision

Stage 3 engineering validation: **PASSED — completed and integrated into `develop/v6-literary-engine`**.

This decision covers the focused Event Causality Engine only. It is not final project acceptance, a release candidate, a production release, a final capability score, or repository freeze approval.

## Integration record

- pull request: `#30`;
- final PR head: `4b7a3f194e6d4843169a0ed6684bce950aff67f5`;
- final workflow: `Stage 3 Event CI`;
- final workflow run: `29975176620`;
- final workflow conclusion: success;
- squash merge commit: `9b2fd15972da1ba58f8d50f81b42ee7b7c708359`;
- integration branch: `develop/v6-literary-engine`.

## Delivered scope

Stage 3 delivers:

- focused canonical events limited to mainline, core-character, major-faction, world-state, or later-major-event impact;
- exact Chapter Project start/end position binding;
- literary assertion and evidence-anchor binding;
- A/B/C-separated `cause`, `process`, `outcome`, `consequence`, `foreshadowing`, and `recovery` components;
- supported `triggers`, `enables`, `escalates`, `prevents`, `reveals`, `undermines`, `resolves`, `foreshadows`, and `recovers` edges;
- temporal-direction validation;
- explicit cycle, unknown-support, endpoint, position, and interpretation findings;
- deterministic JSONL and SQLite Event Projects with foreign keys;
- logical hash, database hash, manifest, input-project and annotation verification;
- active graph and `review_required` graph states;
- evidence-expanded event profile, upstream, downstream, causal path, and foreshadowing queries;
- `tkr-event build`, `verify`, and `query` commands;
- bundled `scripts/tkr.py event ...` entry points.

The engine does not create heavy nodes for low-impact scenes. Unsupported paths refuse, and review-required graphs cannot present causal conclusions.

## Focused regression

The Stage 3 focused suite contains **16 tests** covering event significance, A/B/C support rules, temporal direction, recovery references, graph validation, unknown support, position binding, cycles, deterministic builds, SQLite integrity, review-required projects, tamper rejection, evidence-expanded queries, unsupported paths, and review refusal.

## Final validation

- runtime: Python 3.12 on Ubuntu;
- package installation: passed;
- Python compilation: passed;
- Stage 3 JSON Schema loading: passed;
- all 16 Stage 3 focused tests: passed;
- complete repository regression: passed;
- installed and bundled CLI smoke checks: passed.

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

## Remaining boundary

Private-corpus blind evaluation and the requirement that all final core capability domains score at least 9.0 remain deferred to the final acceptance stage. Stage 3 does not assign a final capability score.
