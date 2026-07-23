# Stage 1 — Evidence Engine

## Development policy

Stage 1 is one complete engineering stage. The internal items 1.1, 1.2, 1.3 and later subtasks are implementation slices only; they are not separate releases, acceptance events, or delivery points.

GitHub synchronization is continuous on:

- integration base: `develop/v6-literary-engine`
- stage branch: `feature/v6-stage1-evidence-engine`
- stage pull request: one PR covering the complete Evidence Engine

GitHub Actions remain disabled by user request. Validation is performed manually or locally and recorded in the stage result before merge.

## Goal

Build a source-bound evidence system in which every canonical fact, synthesis, interpretation, answer, and Notion record can be traced to immutable source locations. Unsupported or contaminated material must not be promoted into A-grade facts.

## Included scope

### 1.1 Evidence Schema

- immutable source identity;
- source, Unit, volume, chapter, paragraph and character offsets;
- exact evidence text and SHA-256;
- contamination and review state;
- deterministic IDs;
- JSON Schema and SQLite contracts.

### 1.2 Evidence Extractor

- strict decoding inherited from the base project;
- chapter/body-only evidence segmentation;
- paragraph and sentence-aware boundaries;
- complete clean-text coverage accounting;
- exact offset and text-hash verification;
- duplicate and missing-coverage reporting;
- deterministic JSONL and SQLite output.

### 1.3 Claim Engine

- A: explicit source fact;
- B: cross-evidence synthesis supported by at least two independent A records;
- C: explicitly attributed model literary interpretation;
- supporting, contradicting and contextual evidence edges;
- no silent B→A or C→B promotion;
- revision and supersession history.

### 1.4 Evidence Validator

- source SHA-256 validation;
- evidence span/text/hash validation;
- clean-source gate for A facts;
- Claim-to-Evidence referential integrity;
- JSONL/SQLite cross-store equality;
- coverage, ordering and determinism checks;
- fail-closed verification.

### 1.5 Query and Notion projection

- answer → Claim → Evidence → Unit → Source citation chain;
- A/B/C visibly separated in every answer;
- exact source excerpts and offsets;
- Evidence and Claim databases for Notion;
- interpretations excluded from fact properties;
- review-only records clearly marked.

### 1.6 Manual regression and stage integration

- synthetic clean-source fixtures;
- contaminated-span fixtures;
- modified-source/hash-failure fixtures;
- unsupported Claim and interpretation-leakage fixtures;
- deterministic rebuild comparison;
- bundled Skill CLI smoke tests;
- repository regression without GitHub Actions.

## Reuse of existing v6 work

The previously integrated literary foundation already contains useful components:

- `EvidenceAnchor` and chapter-address records;
- A/B/C assertion contracts;
- strict source-span binding;
- literary SQLite and JSONL artifacts;
- cross-store verification;
- evidence-first query/refusal;
- fact-separated Notion projection.

Stage 1 will audit, rename or extend these components into one coherent Evidence Engine rather than duplicate them.

## Explicit exclusions

Stage 1 does not attempt:

- complete event-causality extraction;
- full chapter-order restoration across multiple files;
- deep modeling of every minor character;
- final private-corpus acceptance;
- final score assignment;
- release-candidate creation or repository freeze.

## Acceptance gates for Stage 1

Stage 1 may merge into `develop/v6-literary-engine` only when all gates pass:

1. every A Claim has at least one exact, clean Evidence record;
2. every B Claim has at least two independent A supports or equivalent exact evidence;
3. every C Claim is explicitly attributed and cannot be rendered as a source fact;
4. source text, offsets and hashes recompute exactly;
5. contaminated or review-only evidence cannot support A facts;
6. all immutable Evidence/Claim JSONL IDs equal SQLite IDs;
7. clean-text evidence coverage is measured and no uncovered region is silently ignored;
8. repeated builds produce identical logical artifacts;
9. Notion export preserves A/B/C separation;
10. manual focused and full repository regression pass.

These gates are engineering completion criteria only. They do not establish final project acceptance or prove that every capability has reached 9.0.

## Planned outputs

```text
schemas/
  evidence-record.schema.json
  claim-record.schema.json
  claim-evidence-edge.schema.json
  evidence-report.schema.json

tkr/
  evidence_models.py
  evidence_extraction.py
  evidence_validation.py
  evidence_query.py
  evidence_export.py
  evidence_cli.py

tests/
  test_evidence_engine.py

docs/
  STAGE1_EVIDENCE_ENGINE.md
  STAGE1_EVIDENCE_ENGINE_RESULT.md
```

## Stage workflow

1. create and maintain one Stage 1 branch and PR;
2. implement all Stage 1 slices on that branch;
3. commit each meaningful code increment to GitHub;
4. keep GitHub Actions disabled;
5. run focused and repository tests manually;
6. write one final Stage 1 result report;
7. merge once the whole Evidence Engine passes its gates;
8. only then start Stage 2.
