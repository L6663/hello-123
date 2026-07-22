# Text Knowledge Reader — staged hardening workspace

Text Knowledge Reader is developed as a sequence of independently reviewable and testable stages. The repository does not treat a partially integrated package as a release candidate or as an approved freeze artifact.

## Current repository status

```yaml
main_baseline: c76d3b39e1a7d58f38b78c837e25aafff3ba2b07
main_version: 5.8.0-alpha1
development_version: 5.9.0-alpha1
current_development_stage: Phase 9.0
development_status: alpha
release_candidate: false
freeze_approved: false
```

The active clean development branch is `feature/phase9-0-baseline-cleanup`, created directly from `main`. The earlier encoded-payload draft PR #9 is closed and is not an accepted implementation source.

## Implemented stack on `main`

- **v5.2 Phase 2:** deterministic bounded chunking;
- **v5.3 Phase 3:** typed Claim evidence validation;
- **v5.4 Phase 4:** entity, alias, homonym, timeline, and conflict normalization;
- **v5.5 Phase 5:** hash-verified SQLite indexing and predicate-aware hybrid retrieval;
- **v5.6 Phase 6:** strict answers, evidence packets, citation entailment, and refusal decisions;
- **v5.7 Phase 7:** immutable Gold Benchmark coverage, accuracy, refusal, citation, and hallucination gates;
- **v5.8 Phase 8:** artifact-chain manifests, reproducible wheel checks, Git-backed source provenance, explicit approval, and freeze seals.

## Missing integration layers

The following capabilities are not yet integrated into `main` and must not be described as completed:

- **Phase 0:** raw-source identity, encoding, Unicode, and admission checks;
- **Phase 1:** heading recovery, Unit Index generation, and structural continuity validation;
- **Phase 2E:** conservative Claim candidate extraction before Phase 3 validation;
- shared streaming hashing for large source, database, wheel, benchmark, and freeze artifacts;
- raw-corpus end-to-end orchestration;
- independent long-corpus blind evaluation and result-drift measurement.

## Phase 9 — full ingestion integration

Phase 9 connects the existing Phase 2–8 components to a raw-corpus entry point. It is intentionally split into short stages so each change can be reviewed, tested, and reverted independently.

| Stage | Scope | Full regression required now |
|---|---|---:|
| 9.0 | clean baseline, version identity, phase boundaries | No |
| 9.1 | shared streaming SHA-256 module | No |
| 9.2 | source identity admission | No |
| 9.3 | encoding and Unicode inspection | No |
| 9.4 | anomaly and contamination candidates | No |
| 9.5 | heading candidate detection | No |
| 9.6 | deterministic Unit Index generation | No |
| 9.7 | Unit continuity and structure validation | No |
| 9.8 | Claim candidate schema | No |
| 9.9 | six-predicate deterministic extraction | No |
| 9.10 | fact, belief, suspicion, rumor, and accusation separation | No |
| 9.11 | constrained model-extraction task interface | No |
| 9.12 | raw text to Claim-candidate orchestration | No |
| 9.13 | private long-corpus blind-test contracts | No |
| 9.14 | Skill documentation and Alpha package layout | No |
| 9.15 | focused integration acceptance | Focused tests only |

The complete Python 3.10/3.11/3.12 regression matrix, long-corpus execution, performance measurement, drift comparison, release packaging, and candidate PR are deferred until the implementation stages are complete.

## Current console commands

Only commands backed by code already present in the repository are registered:

```text
tkr-chunk
tkr-claim-validate
tkr-entity-normalize
tkr-retrieval
tkr-strict-qa
tkr-gold-benchmark
tkr-release-freeze
```

Phase 0, Phase 1, extraction, blind-test, and full-pipeline commands will be registered only when their implementations and focused tests exist.

## Evidence and interpretation boundary

The deterministic runtime is responsible for source integrity, stable structure, evidence localization, typed factual validation, strict retrieval, and refusal when evidence is insufficient. It must not present character motivation, foreshadowing resolution, theme, or narrative interpretation as mechanically proven fact.

Future novel-semantic records will distinguish:

- **A:** directly stated source fact;
- **B:** high-confidence synthesis supported by multiple source passages;
- **C:** literary interpretation;
- **X:** contamination, conflict, missing text, or insufficient evidence.

A character's suspicion, rumor, accusation, or stated belief may itself be an A-level fact when directly quoted, while the proposition being suspected remains unconfirmed.

## Phase 7 contract

Phase 7 evaluates strict QA against a bound JSONL Gold set. A passing release-profile report may set `may_certify_release=true`, but Phase 7 must always keep `may_freeze=false`.

## Phase 8 contract

Phase 8 separates technical verification from release authority. A technical candidate binds exact artifacts, source provenance, package version, and reproducible wheel evidence. It cannot authorize itself. A freeze seal requires a separate explicit approval record matching the verified candidate.

The current approval model is an operator assertion and is not described as a cryptographically authenticated identity signature.

## Development rule

Each Phase 9 substage must provide:

1. a narrow implementation scope;
2. focused tests or a deterministic validation example;
3. explicit inputs and outputs;
4. no hidden encoded source payloads;
5. no claim of release, approval, or freeze readiness.
