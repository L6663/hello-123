# Text Knowledge Reader — staged hardening workspace

Text Knowledge Reader is developed as a sequence of independently reviewable implementation stages. Phase 9 substages optimize the Skill itself; they do not certify the project, declare acceptance, create a release candidate, or authorize a freeze. Project-level acceptance is deferred until the final integrated product is complete.

## Current repository status

```yaml
main_baseline: c76d3b39e1a7d58f38b78c837e25aafff3ba2b07
main_version: 5.8.0-alpha1
development_version: 5.9.0-alpha1
canonical_phase9_base: feature/phase9-0-baseline-cleanup
integrated_stage_1_commit: 444f21513002345c578f89d8afd32c1ff50eaa8b
completed_development_stages:
  - Phase 9.0
  - Phase 9.1
  - Phase 9.2
  - Phase 9.3
  - Phase 9.4
completed_large_stages:
  - Stage 1
next_large_stage: Stage 2 — deterministic corpus structure
next_stage_status: not_started
project_acceptance: deferred_until_final_integrated_product
release_candidate: false
freeze_approved: false
```

Stage 1 was merged through PR #11 into the canonical Phase 9 base. The earlier encoded-payload PR #9 and stale Phase 9.4 branches are superseded and must not be merged.

## Stable stack on `main`

- **Phase 2:** deterministic bounded chunking;
- **Phase 3:** typed Claim evidence validation;
- **Phase 4:** entity, alias, homonym, timeline, and conflict normalization;
- **Phase 5:** hash-verified SQLite indexing and predicate-aware hybrid retrieval;
- **Phase 6:** strict answers, evidence packets, citation entailment, and refusal decisions;
- **Phase 7:** immutable Gold Benchmark gates;
- **Phase 8:** reproducible packaging, source provenance, approval, and freeze boundaries.

## Phase 9 development lineage

- **Phase 9.0:** clean baseline and stage boundaries;
- **Phase 9.1:** bounded-memory streaming SHA-256;
- **Phase 9.2:** raw-byte source identity admission;
- **Phase 9.3:** strict encoding selection and Unicode-quality inspection;
- **Phase 9.4 / Stage 1:** conservative anomaly and corpus-contamination candidates.

Development-complete means the intended Skill code is present on the Phase 9 line. It does not mean the final project passed acceptance.

## Stage 1 result

Stage 1 converged the development line and strengthened the corpus safety layer. It includes:

- legacy Phase 2–8 PR workflows restricted to `main`-targeting PRs;
- exact source SHA-256 binding and post-scan mutation detection;
- Unicode anomaly, web residue, author paratext, long-line, repeated-line, and distant-duplicate candidates;
- line-level CJK/ASCII script-shift candidates;
- fixed-character window scanning that still works when an entire chapter is one physical line;
- same-language cross-work candidates using multiple independent signals:
  - character bigram distribution shift;
  - entity-system discontinuity;
  - narrative-register transition;
  - sentence-length transition;
- caller-supplied marker groups for known corpus-specific signals;
- deterministic Finding IDs, evidence SHA-256, exact character spans, line ranges, severity, confidence, and review actions;
- bounded finding and duplicate-fingerprint indexes;
- JSON Schema contracts for findings and reports;
- standard deterministic artifact publication;
- 15 focused tests executed on Python 3.10, 3.11, and 3.12.

Every finding is a review candidate. The detector does not declare a source clean or contaminated and never deletes source text automatically.

## Standard Phase 9.4 artifacts

Running `tkr-anomaly-scan SOURCE --outdir OUTPUT` writes:

```text
anomaly-report.json
anomaly-candidates.jsonl
contamination-candidates.jsonl
non-body-content.jsonl
structural-anomalies.jsonl
anomaly-ledger.csv
stage-result.json
artifact-manifest.json
```

The manifest binds file names, sizes, and SHA-256 values. Every stage result keeps:

```yaml
project_acceptance_performed: false
may_accept_project: false
may_freeze: false
```

## Console commands

```text
tkr-chunk
tkr-claim-validate
tkr-entity-normalize
tkr-retrieval
tkr-strict-qa
tkr-gold-benchmark
tkr-release-freeze
tkr-anomaly-scan
```

Example:

```bash
tkr-anomaly-scan corpus.txt --outdir project/anomaly
```

Known lexical families may be supplied only as review signals:

```bash
tkr-anomaly-scan corpus.txt \
  --marker-group 'modern=董事会|经理|邮件' \
  --marker-group 'digital=直播|手机|网络' \
  --outdir project/anomaly
```

## Focused developer checks

Stage 1 uses a Python 3.10/3.11/3.12 focused workflow that:

- installs the development package;
- compiles the Stage 1 modules;
- validates JSON Schema syntax;
- runs the Stage 1 anomaly tests;
- verifies the `tkr-anomaly-scan` entry point.

The focused workflow passed. This is development evidence only; it is not long-corpus acceptance, final regression, package certification, release approval, or freeze authorization.

## Remaining large stages

1. **Stage 2 — deterministic corpus structure:** heading candidates, Unit Index, and continuity validation. Estimated engineering time: 12–18 hours.
2. **Stage 3 — evidence-grounded semantics:** Claim extraction, factual-status separation, entity and timeline integration. Estimated engineering time: 24–36 hours.
3. **Stage 4 — end-to-end knowledge system:** orchestration, indexing, retrieval, strict QA, citations, and refusal. Estimated engineering time: 18–28 hours.
4. **Stage 5 — engineering and Skill productization:** incremental builds, recovery, security, `SKILL.md`, profiles, examples, and final package layout. Estimated engineering time: 16–24 hours.
5. **Stage 6 — final capability analysis and project acceptance:** private blind sets, long-corpus execution, performance, drift, package audit, and one final project decision. Estimated engineering time: 20–30 hours plus corpus runtime.

Every capability domain must score at least 9.0 in the final acceptance. Scores cannot compensate for another domain below 9.0.

## Evidence and interpretation boundary

The deterministic runtime is responsible for source integrity, stable structure, evidence localization, typed factual validation, strict retrieval, and refusal when evidence is insufficient. It must not present character motivation, foreshadowing, theme, or literary interpretation as mechanically proven fact.

Future semantic records distinguish:

- **A:** directly stated source fact;
- **B:** high-confidence multi-passage synthesis;
- **C:** literary interpretation;
- **X:** contamination, conflict, missing text, or insufficient evidence.

A character's suspicion, rumor, accusation, or belief may itself be a directly stated event, while the proposition being suspected remains unconfirmed.

## Development rule

Each Phase 9 implementation stage must provide:

1. a narrow Skill implementation scope;
2. explicit inputs, outputs, and safety boundaries;
3. focused developer checks where needed;
4. no hidden encoded source payloads;
5. no intermediate project acceptance, certification, release-candidate, or freeze claim;
6. no use of a real-corpus scan as a substitute for Skill implementation;
7. project-level acceptance only after the final integrated product is complete.
