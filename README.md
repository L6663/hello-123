# Text Knowledge Reader — staged hardening workspace

Text Knowledge Reader is developed as independently reviewable implementation stages. Intermediate stages optimize the Skill implementation; they do not certify the project, create a release candidate, or authorize a freeze. Project-level acceptance is performed once after the final integrated Skill is complete.

## Current repository status

```yaml
main_baseline: c76d3b39e1a7d58f38b78c837e25aafff3ba2b07
main_version: 5.8.0-alpha1
development_version: 5.9.0-alpha1
canonical_phase9_base: feature/phase9-0-baseline-cleanup
active_stage_branch: feature/phase9-stage3-evidence-semantics
completed_large_stages:
  - Stage 1
  - Stage 2
current_large_stage: Stage 3 — evidence-grounded semantics
stage_3_implementation: complete
stage_3_local_focused_checks: 31_passed
stage_3_github_focused_checks: pending
project_acceptance: deferred_until_final_integrated_product
minimum_score_per_capability: 9.0
release_candidate: false
freeze_approved: false
```

Stage 1 was merged through PR #11. Stage 2 was merged through PR #12. Stage 3 is implemented on `feature/phase9-stage3-evidence-semantics` and is awaiting focused GitHub checks and integration review.

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
- **Phase 9.4 / Stage 1:** conservative anomaly and corpus-contamination candidates;
- **Phase 9.5–9.7 / Stage 2:** deterministic headings, source-covering Unit Index, and continuity findings;
- **Phase 9.8–9.11 / Stage 3:** Claim candidates, six-predicate extraction, factual-status separation, and constrained model proposal tasks.

Development-complete means the intended Skill code exists on the Phase 9 development line. It does not mean the final project has passed acceptance.

## Stage 1 — corpus safety

Run:

```bash
tkr-anomaly-scan corpus.txt --outdir project/anomaly
```

Stage 1 emits source-bound anomaly, contamination, paratext, Unicode, repetition, and same-language transition candidates. Findings never delete source text or declare a corpus clean or contaminated.

## Stage 2 — deterministic corpus structure

Run:

```bash
tkr-structure-index corpus.txt --outdir project/structure
```

Stage 2 produces deterministic heading candidates, contiguous non-overlapping Units, source-covering character spans, parent-child relationships, content hashes, and numbering or placement findings. Ambiguous headings remain review candidates rather than being silently promoted.

## Stage 3 — evidence-grounded semantics

Stage 3 extracts typed Claim candidates only from exact Stage 2 Unit body spans. It supports the six predicates already enforced by the deterministic Claim validator:

```text
alias
defeats
located_in
permission
count
date
```

Implemented safeguards include:

- exact source, Unit, character, line, trigger, and Evidence SHA-256 binding;
- deterministic candidate, finding, model-task, validation, entity, fact, and timeline identities;
- assertion, belief, suspicion, rumor, accusation, hypothetical, question, and future-intent separation;
- asserted and negated facts represented separately through factual status and polarity;
- nonassertive propositions retained for review but never sent directly into canonical indexing;
- every assertive candidate revalidated through the existing Phase 3 deterministic validator;
- Units marked for structural review cannot contribute accepted Claims;
- Evidence overlapping Stage 1 contamination, paratext, or high-severity text anomalies cannot be indexed;
- accepted assertions bridged into the existing entity, fact, timeline, conflict, and ambiguity normalizer;
- model assistance restricted to source-bound proposal tasks with no authority to accept, index, certify, or freeze;
- source SHA-256 recalculated after extraction to detect concurrent modification.

Run:

```bash
tkr-semantic-extract corpus.txt --outdir project/semantics
```

Standard Stage 3 artifacts:

```text
semantic-report.json
claim-candidates.jsonl
accepted-claims.jsonl
nonassertive-claims.jsonl
semantic-findings.jsonl
model-extraction-tasks.jsonl
entities.jsonl
facts.jsonl
timeline.jsonl
conflicts.jsonl
ambiguity-groups.jsonl
normalization-report.json
semantic-ledger.csv
stage-result.json
artifact-manifest.json
```

Every Stage 3 result keeps:

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
tkr-structure-index
tkr-semantic-extract
```

## Focused developer checks

- Stage 1: 15 focused tests passed on Python 3.10, 3.11, and 3.12.
- Stage 2: 21 focused tests passed on Python 3.10, 3.11, and 3.12.
- Stage 3: 31 local focused tests passed; the GitHub Python 3.10/3.11/3.12 matrix is pending.

Stage 3 focused coverage includes:

- all six deterministic predicates;
- positive and negative permission;
- Chinese integer and decimal counts;
- exact dates;
- rumor, belief, suspicion, accusation, hypothetical, question, and future-intent indexing blocks;
- negated relation handling;
- exact Evidence span and hash binding;
- heading exclusion through Unit body boundaries;
- deterministic IDs and artifact manifests;
- constrained model-task envelopes;
- entity-normalization bridge;
- UTF-8 BOM and UTF-16 offsets;
- candidate limits;
- upstream contamination overlap blocking;
- CLI publication.

Focused checks are development evidence only. They are not private blind evaluation, real-corpus accuracy measurement, long-corpus performance validation, final regression, package certification, release approval, or freeze authorization.

## Remaining large stages

1. **Stage 4 — end-to-end knowledge system:** orchestration, indexing, retrieval, strict QA, citations, and refusal. Estimated engineering time: 18–28 hours.
2. **Stage 5 — engineering and Skill productization:** incremental builds, recovery, security, `SKILL.md`, profiles, examples, and final package layout. Estimated engineering time: 16–24 hours.
3. **Stage 6 — final capability analysis and project acceptance:** private blind sets, long-corpus execution, performance, drift, package audit, and one final project decision. Estimated engineering time: 20–30 hours plus corpus runtime.

Every final capability domain must score at least 9.0. Scores cannot compensate for another domain below 9.0.

## Evidence and interpretation boundary

The deterministic runtime is responsible for source integrity, stable structure, evidence localization, typed factual validation, strict retrieval, and refusal when evidence is insufficient. It must not present character motivation, foreshadowing, theme, or literary interpretation as mechanically proven fact.

A character's suspicion, rumor, accusation, or belief may itself be a directly stated event, while the proposition being suspected remains unconfirmed.

## Development rule

Each implementation stage must provide:

1. a narrow Skill implementation scope;
2. explicit inputs, outputs, and safety boundaries;
3. focused developer checks where needed;
4. no hidden encoded source payloads;
5. no intermediate project acceptance, certification, release-candidate, or freeze claim;
6. no use of a real-corpus scan as a substitute for Skill implementation;
7. project-level acceptance only after the final integrated product is complete.
