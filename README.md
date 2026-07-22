# Text Knowledge Reader — staged hardening workspace

Text Knowledge Reader is developed as independently reviewable implementation stages. Intermediate stages optimize the Skill implementation; they do not certify the project, create a release candidate, or authorize a freeze. Project-level acceptance is performed once after the final integrated Skill is complete.

## Current repository status

```yaml
main_baseline: c76d3b39e1a7d58f38b78c837e25aafff3ba2b07
main_version: 5.8.0-alpha1
development_version: 5.9.0-alpha1
canonical_phase9_base: feature/phase9-0-baseline-cleanup
active_stage_branch: feature/phase9-stage4-end-to-end-knowledge-v2
integrated_stage_1_commit: 444f21513002345c578f89d8afd32c1ff50eaa8b
integrated_stage_2_commit: 5b985a7bdde81900159125f597196bb7aa8c5b56
integrated_stage_3_commit: 17aae8a1ca65c47df0c86481c2d0e07c3e77a1e8
completed_large_stages:
  - Stage 1
  - Stage 2
  - Stage 3
current_large_stage: Stage 4 — end-to-end knowledge system
stage_4_implementation: complete
stage_4_focused_checks: passed_on_python_3_10_3_11_3_12
stage_4_integration: pending_pull_request_14
project_acceptance: deferred_until_final_integrated_product
minimum_score_per_capability: 9.0
release_candidate: false
freeze_approved: false
```

Stage 1 was merged through PR #11, Stage 2 through PR #12, and Stage 3 through PR #13. Stage 4 is implemented in PR #14 and has passed focused checks; it is not a final project acceptance result.

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
- **Phase 9.8–9.11 / Stage 3:** Claim candidates, six-predicate extraction, factual-status separation, and constrained model proposal tasks;
- **Phase 9.12 / Stage 4:** raw-source-to-index orchestration, project verification, strict QA, citations, refusal, and answer recomputation.

Development-complete means the intended Skill code exists on the Phase 9 development line. It does not mean the final project has passed acceptance.

## Stage 1 — corpus safety

```bash
tkr-anomaly-scan corpus.txt --outdir project/anomaly
```

Stage 1 emits source-bound anomaly, contamination, paratext, Unicode, repetition, and same-language transition candidates. Findings never delete source text or declare a corpus clean or contaminated.

## Stage 2 — deterministic corpus structure

```bash
tkr-structure-index corpus.txt --outdir project/structure
```

Stage 2 produces deterministic heading candidates, contiguous non-overlapping Units, source-covering character spans, parent-child relationships, content hashes, and numbering or placement findings. Ambiguous headings remain review candidates rather than being silently promoted.

## Stage 3 — evidence-grounded semantics

```bash
tkr-semantic-extract corpus.txt --outdir project/semantics
```

Stage 3 extracts exact Evidence-bound candidates for:

```text
alias
defeats
located_in
permission
count
date
```

It separates assertions from belief, suspicion, rumor, accusation, hypothetical, question, and future-intent propositions. Only accepted direct assertions outside unsafe Stage 1 spans and accepted Stage 2 Units may enter indexing.

## Stage 4 — end-to-end knowledge system

Stage 4 creates one self-contained immutable project from a raw source:

```text
raw source
→ strict source identity and decoding
→ Stage 1 anomaly candidates
→ Stage 2 Unit Index
→ Stage 3 Claim and entity artifacts
→ fresh compatibility revalidation
→ SQLite typed knowledge index
→ strict QA, citations, and refusal
```

Build a review project:

```bash
tkr-project build corpus.txt --outdir project
```

Build a canonical project only when all canonical gates permit it:

```bash
tkr-project build corpus.txt --outdir project --index-mode canonical
```

Verify the full immutable project hash chain:

```bash
tkr-project verify project
```

Ask a supported typed question:

```bash
tkr-project query project "陆川击败了谁？"
```

Save and later recompute an answer packet:

```bash
tkr-project query project "陆川击败了谁？" --output answer.json
tkr-project verify-answer project answer.json
```

The project contains:

```text
source/
stage1-anomaly/
stage2-structure/
stage3-semantics/
bridge/
index/
project-report.json
project-manifest.json
```

The original source bytes and canonical UTF-8 decoded text are both preserved. Every immutable file is bound by relative path, size, and SHA-256. Querying requires successful project verification. Answer packets bind the project manifest, raw source, normalized source, SQLite index, strict QA packet, exact citations, and refusal decision.

Unsupported questions and questions without sufficient typed evidence are refused. Stage 4 does not answer open literary interpretation questions and cannot authorize acceptance or freezing.

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
tkr-project
```

## Focused developer checks

- Stage 1: 15 focused tests passed on Python 3.10, 3.11, and 3.12.
- Stage 2: 21 focused tests passed on Python 3.10, 3.11, and 3.12.
- Stage 3: 31 focused tests passed on Python 3.10, 3.11, and 3.12.
- Stage 4: 27 focused tests passed on Python 3.10, 3.11, and 3.12.

Stage 4 checks cover end-to-end construction, six-predicate indexing, strict typed answers, unsupported and insufficient-evidence refusal, source and database tampering, answer tampering, project reuse, atomic replacement, canonical gating, UTF-16 input, deterministic project identities, CLI output, and policy validation. Stage 2 and Stage 3 regression workflows also passed on PR #14 after shared package configuration changed.

Focused checks are development evidence only. They are not private blind evaluation, real-corpus accuracy measurement, long-corpus performance validation, final regression, package certification, release approval, or freeze authorization.

## Remaining large stages

1. **Stage 5 — engineering and Skill productization:** incremental builds, recovery, security, `SKILL.md`, profiles, examples, and final package layout. Estimated engineering time: 16–24 hours.
2. **Stage 6 — final capability analysis and project acceptance:** private blind sets, long-corpus execution, performance, drift, package audit, and one final project decision. Estimated engineering time: 20–30 hours plus corpus runtime.

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
