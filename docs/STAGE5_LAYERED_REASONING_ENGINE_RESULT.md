# Stage 5 — Layered Reasoning Engine Result

## Decision

Stage 5 engineering validation and integration: **PASSED**.

PR #32 was squash merged into `develop/v6-literary-engine` as commit `00d835b7680bdbcbc1c2384647d7f47603585657`.

This decision covers the Layered Reasoning Engine only. It is not final project acceptance, a release candidate, a production release, a final capability score, or repository freeze approval.

## Delivered scope

Stage 5 delivers:

- strict A source-fact, B cross-evidence synthesis, C model-interpretation, and H counterfactual layers;
- exact upstream bindings across Chapter, Literary, Evidence, Event, and Character projects;
- source/chapter-derived evidence-independence groups;
- rejection when an A node cites Evidence not owned by its upstream records;
- rejection when B independence declarations differ from actual A support lineages;
- explicit support edges whose active targets must equal each derived node's declared support nodes;
- mandatory C attribution, limitations, and alternative readings;
- mandatory H changed premise, inference rule, uncertainty, alternatives, and non-canon attribution;
- derivation-cycle, unknown-support, unsupported-layer, and edge-endpoint findings;
- deterministic JSONL and SQLite Reasoning Projects with foreign keys;
- logical hash, database hash, manifest, upstream-project, annotation, and deterministic rebuild verification;
- `fact_only`, `fact_and_synthesis`, `analysis`, `counterfactual`, and `provenance` query modes;
- section-separated answer packets with facts, synthesis, interpretation, counterfactuals, conflicts, limitations, alternatives, provenance, and partial-refusal reasons;
- expanded upstream records and Evidence Anchors in query provenance;
- `tkr-reason build`, `verify`, and `query` commands;
- bundled `scripts/tkr.py reason ...` entry points.

The query mode is a ceiling. Selecting `analysis` or `counterfactual` never creates missing C or H records. Unsupported or mode-forbidden layers are refused or partially refused.

## Focused regression

The Stage 5 focused suite contains **28 tests** covering:

- A-grade exact Evidence requirements;
- A-grade chapter and evidence-independence lineage;
- B-grade minimum support count;
- C-grade attribution, limitation, and alternative-reading requirements;
- H-grade premise and inference disclosure;
- valid A/B/C/H reasoning graphs;
- duplicate evidence lineage not counting as independent support;
- B nodes prohibited from using C as direct support;
- unknown upstream and Evidence references;
- explicit derivation cycles;
- deterministic graph builds;
- fact-only leakage prevention;
- separated analysis sections;
- non-canon counterfactual packets;
- review-required graph refusal and provenance-only inspection;
- missing-node refusal;
- immutable Reasoning Project build and verification;
- SQLite integrity and foreign keys;
- deterministic JSONL and database bytes;
- tampered artifact and unregistered-file rejection;
- A Evidence ownership verification;
- B lineage-group verification;
- support-edge equality verification;
- review-required cycle projects;
- build/verify/query CLI integration;
- resolved upstream and Evidence provenance;
- fact-only CLI leakage prevention;
- missing-intent refusal.

## Final exact-head validation

- PR: #32;
- final PR head: `55e958a8c30f45ed9a3f5b35f2b15cfe109972d6`;
- workflow: `Stage 5 Reasoning CI`;
- workflow run: `29980429897`;
- runtime: Python 3.12 on Ubuntu;
- conclusion: success;
- squash merge commit: `00d835b7680bdbcbc1c2384647d7f47603585657`.

Successful checks:

1. package installation;
2. Python compilation;
3. Stage 5 JSON Schema loading;
4. all 28 Stage 5 focused tests;
5. complete repository regression;
6. installed and bundled CLI smoke checks.

## Gate result

| Gate | Result |
|---|---|
| Every presented A item resolves to exact upstream-bound Evidence | Passed |
| Every B item has at least two independent A branches | Passed |
| Every C item has support, attribution, limitations, and alternatives | Passed |
| Every H item identifies premise, inference, uncertainty, and non-canon status | Passed |
| Support-node declarations equal active support edges | Passed |
| Conflicts and review findings remain visible | Passed |
| Mode-forbidden or unsupported layers refuse | Passed |
| Answer packets preserve A/B/C/H section separation | Passed |
| Upstream and Evidence provenance recomputes | Passed |
| JSONL and SQLite identifiers agree | Passed |
| Report counts and hashes recompute | Passed |
| Repeated builds are deterministic | Passed |
| Focused and repository regression | Passed |

## Workflow policy

GitHub Actions remain in reduced-noise mode:

- one Stage 5 workflow;
- one Python runtime;
- one job;
- pull request and manual triggers only;
- obsolete concurrent runs cancelled;
- no routine artifact upload;
- no release, final acceptance, or freeze workflow.

## Remaining boundary

Stage 5 validates reasoning structure and provenance, not natural-language quality on the private corpus. Private-corpus blind evaluation and the requirement that all final core capability domains independently score at least 9.0 remain deferred to Stages 7–8. Stage 5 does not assign a final capability score.
