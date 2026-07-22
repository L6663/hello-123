# Text Knowledge Reader — staged hardening workspace

Text Knowledge Reader is developed as a sequence of independently reviewable implementation stages. Intermediate stages optimize the Skill implementation; they do not certify the project, create a release candidate, or authorize a freeze. Project-level acceptance is performed once, after the final integrated Skill is complete.

## Current repository status

```yaml
main_baseline: c76d3b39e1a7d58f38b78c837e25aafff3ba2b07
main_version: 5.8.0-alpha1
development_version: 5.9.0-alpha1
canonical_phase9_base: feature/phase9-0-baseline-cleanup
active_stage_branch: feature/phase9-stage2-deterministic-structure
completed_large_stages:
  - Stage 1
current_large_stage: Stage 2 — deterministic corpus structure
stage_2_implementation: complete
stage_2_local_focused_checks: 21_passed
stage_2_github_focused_checks: pending
project_acceptance: deferred_until_final_integrated_product
minimum_score_per_capability: 9.0
release_candidate: false
freeze_approved: false
```

Stage 1 was merged through PR #11 into the canonical Phase 9 development base. Stage 2 is implemented on `feature/phase9-stage2-deterministic-structure` and is awaiting focused GitHub checks and integration review.

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
- **Stage 2:** deterministic heading candidates, source-covering Unit Index, and continuity findings.

Development-complete means the intended Skill code exists on the Phase 9 development line. It does not mean the final project has passed acceptance.

## Stage 1 result — corpus safety

Stage 1 provides source-bound anomaly and contamination review candidates, including Unicode anomalies, web residue, author paratext, repetitions, fixed-character window scanning, and conservative same-language cross-work transitions. Findings never delete source text or declare a corpus clean or contaminated.

Run:

```bash
tkr-anomaly-scan corpus.txt --outdir project/anomaly
```

Standard Stage 1 artifacts:

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

## Stage 2 implementation — deterministic corpus structure

Stage 2 converts a strictly decoded source into deterministic heading candidates, contiguous Unit records, and structure-review findings.

Implemented capabilities include:

- Arabic, full-width, spaced, and conventional Chinese ordinal parsing;
- `卷 / 部 / 篇 / 集 / 章 / 回 / 幕 / 节` hierarchy recognition;
- English `Volume / Book / Part / Chapter / Section` headings;
- Markdown headings while ignoring fenced code blocks;
- prologue, preface, epilogue, afterword, appendix, extra-story, and related special units;
- heading and body on the same physical line;
- numbered headings split across two lines;
- detached-title recovery candidates without silently rewriting the source;
- deterministic parent-child Unit relationships;
- exact decoded-character coverage with no gaps or overlaps;
- source-bound Unit IDs and per-Unit content SHA-256 values;
- duplicate ordinal, numbering gap, inversion, duplicate title, empty body, and placement findings;
- unit limits that stop promotion of new boundaries without truncating source scanning;
- post-scan source rehashing to detect concurrent modification;
- explicit validation that Stage 2 cannot authorize project acceptance or freezing.

Run:

```bash
tkr-structure-index corpus.txt --outdir project/structure
```

Standard Stage 2 artifacts:

```text
structure-report.json
heading-candidates.jsonl
unit-index.jsonl
structure-anomalies.jsonl
unit-ledger.csv
stage-result.json
artifact-manifest.json
```

The Unit Index covers every decoded source character exactly once. Ambiguous headings remain review candidates rather than being silently promoted to boundaries.

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
```

## Focused developer checks

Stage 1 passed focused checks on Python 3.10, 3.11, and 3.12.

Stage 2 currently has 21 passing local focused tests covering:

- ordinal parsing;
- numbered, special, English, and Markdown headings;
- hierarchy and parent IDs;
- inline body boundaries;
- split headings and detached-title recovery;
- fenced-code false-positive protection;
- full source coverage and fallback document Units;
- duplicate, missing, inverted, empty-body, and placement findings;
- UTF-8 BOM and UTF-16 LE/BE offsets;
- unsupported-source blocking;
- deterministic reports and artifacts;
- Unit-limit behavior;
- CLI output.

The Stage 2 GitHub workflow runs the same focused implementation checks on Python 3.10, 3.11, and 3.12. These checks are development evidence only. They are not real-corpus acceptance, long-corpus performance validation, final regression, package certification, release approval, or freeze authorization.

## Remaining large stages

1. **Stage 3 — evidence-grounded semantics:** Claim extraction, factual-status separation, entity and timeline integration. Estimated engineering time: 24–36 hours.
2. **Stage 4 — end-to-end knowledge system:** orchestration, indexing, retrieval, strict QA, citations, and refusal. Estimated engineering time: 18–28 hours.
3. **Stage 5 — engineering and Skill productization:** incremental builds, recovery, security, `SKILL.md`, profiles, examples, and final package layout. Estimated engineering time: 16–24 hours.
4. **Stage 6 — final capability analysis and project acceptance:** private blind sets, long-corpus execution, performance, drift, package audit, and one final project decision. Estimated engineering time: 20–30 hours plus corpus runtime.

Every final capability domain must score at least 9.0. Scores cannot compensate for another domain below 9.0.

## Evidence and interpretation boundary

The deterministic runtime is responsible for source integrity, stable structure, evidence localization, typed factual validation, strict retrieval, and refusal when evidence is insufficient. It must not present character motivation, foreshadowing, theme, or literary interpretation as mechanically proven fact.

Future semantic records distinguish:

- **A:** directly stated source fact;
- **B:** high-confidence multi-passage synthesis;
- **C:** literary interpretation;
- **X:** contamination, conflict, missing text, or insufficient evidence.

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
