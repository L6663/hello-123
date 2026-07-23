# Stage 1 — Evidence Engine Result

## Decision

Stage 1 engineering validation: **PASSED AND INTEGRATED** into `develop/v6-literary-engine`.

This decision covers the Stage 1 Evidence Engine implementation only. It is not final project acceptance, a release candidate, a production release, or repository freeze approval.

## Integration record

- pull request: `#28`;
- final PR head: `322ec12aacacaf0d123a28641c933d0e60e4e37b`;
- final exact-head workflow: `29971391164`;
- workflow conclusion: success;
- squash merge commit: `9e7bac7837ceccf54b9b2e5bd8eac2c6748f5562`;
- integration branch: `develop/v6-literary-engine`.

## Integrated scope

Stage 1 delivers:

- deterministic Evidence Units over trusted chapter bodies;
- exact source, Unit, chapter, paragraph and character-offset binding;
- source text and SHA-256 verification;
- pollution and review-state blocking;
- clean-body coverage, omission and overlap accounting;
- explicit Claim→Evidence `support`, `contradict` and `context` edges;
- A/B/C epistemic enforcement;
- self-contained Claim evidence anchors;
- JSONL and SQLite evidence stores with foreign keys;
- logical and database hash manifests;
- deterministic rebuild verification;
- `tkr-evidence build` and `tkr-evidence verify` commands;
- bundled `scripts/tkr.py evidence ...` entry points.

The existing v6 literary query and Notion projection remain the presentation layer. Stage 1 supplies the stronger source-bound evidence project beneath them and preserves the existing A/B/C separation contract.

## Validation

Concise GitHub workflow:

- workflow: `Stage 1 Evidence CI`;
- runtime: Python 3.12 on Ubuntu;
- final run: `29971391164`;
- conclusion: success.

Successful checks:

1. package installation;
2. Python compilation of the bundled entry point and Evidence modules;
3. Stage 1 focused tests;
4. complete repository regression;
5. installed and bundled CLI smoke checks.

Stage 1 focused coverage includes clean-body extraction, pollution blocking, exact span/hash recomputation, source mutation, uncovered content, duplicate/overlap handling, deterministic IDs, A/B/C graph constraints, contradiction/context isolation, unknown evidence rejection, self-contained project output, SQLite foreign keys, deterministic repeated builds, tamper rejection and unregistered-file rejection.

## Gate result

| Gate | Result |
|---|---|
| Every A Claim has exact clean Evidence | Passed |
| B Claim requires multiple independent A supports | Passed |
| C Claim remains explicit model interpretation | Passed |
| Source offsets, text and hashes recompute | Passed |
| Polluted/review material cannot support A | Passed |
| JSONL and SQLite identifiers agree | Passed |
| Clean-body evidence coverage is measured | Passed |
| Repeated builds are logically deterministic | Passed |
| A/B/C presentation separation is retained | Passed through integrated literary projection |
| Focused and repository regression | Passed |

## Workflow policy

GitHub Actions are enabled in a reduced-noise form:

- one Stage 1 workflow;
- one Python runtime;
- one job;
- pull requests into `develop/v6-literary-engine` plus manual dispatch only;
- concurrent obsolete runs are cancelled;
- no routine artifact upload;
- no release, acceptance or freeze workflow.

## Remaining boundary

Private-corpus blind evaluation and the requirement that all final core capability domains score at least 9.0 remain deferred to the final acceptance stage. Stage 1 does not assign a final capability score.
