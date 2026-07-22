# Stage 7 — Complete Literary Knowledge Engine

## Status

Development line: `6.0.0-alpha1`

Historical archive: `archive/v5.9.0-final`

Stage 7 was opened after real-use evaluation showed that the v5.9 typed-fact engine was strong on contamination isolation and major facts but remained below the requested threshold for chapter-level traceability, cold-detail recall, complete entity coverage, temporal relationships, and fact/interpretation separation.

This document describes a development capability. It is not a project-acceptance, score, release, or freeze record.

## Non-compensating target gates

Every domain must independently reach at least 9.0 during final integrated evaluation:

1. chapter and volume reconstruction;
2. exact evidence traceability;
3. entity coverage and identity resolution;
4. temporal relationship retrieval;
5. event causality and consequence chains;
6. cold-detail and minor-character retrieval;
7. exact dialogue and source-text retrieval;
8. A/B/C epistemic separation;
9. unsupported and polluted-source refusal;
10. Notion projection correctness;
11. incremental revision and supersession;
12. deterministic rebuild and security verification.

A high score in one domain cannot compensate for a failure in another.

## Epistemic tiers

### A — source-explicit fact

A records require exact evidence anchors. Each anchor binds:

- source identifier and source SHA-256;
- Unit and literary chapter identifier;
- volume and chapter ordinal when available;
- original and normalized heading;
- character start and end offsets;
- exact source quote and quote SHA-256;
- Unit content SHA-256;
- contamination/review status.

A records must not use synthesis or interpretation as their assertion kind.

### B — cross-evidence synthesis

B records summarize patterns or causal structure supported by at least two independent A records or exact anchors. B records are useful, but they are not presented as a single sentence stated by the source.

### C — model literary interpretation

C records may discuss themes, symbolism, narrative strategy, ethics, or political meaning. They must:

- be explicitly attributed to model interpretation;
- cite A or B support;
- disclose limitations;
- never assert definitive author intent without direct evidence;
- never enter A-grade Notion fact properties.

## Stage 7.1 artifacts

A verified literary sidecar contains:

- `chapters.jsonl`
- `evidence-anchors.jsonl`
- `entities.jsonl`
- `assertions.jsonl`
- `relationships.jsonl`
- `events.jsonl`
- `revisions.jsonl`
- `literary.sqlite`
- `literary-report.json`
- `artifact-manifest.json`

The source project must first pass the existing secure knowledge-project verification.

## CLI

```bash
tkr-literary build PROJECT --outdir LITERARY_DIR
tkr-literary verify LITERARY_DIR
tkr-literary query LITERARY_DIR "林舟首次出场在哪一章？"
tkr-literary export-notion LITERARY_DIR --outdir NOTION_PACKAGE
```

The commands have no project-acceptance or freeze authority.

## Notion projection

The export keeps separate databases/sections for:

- chapter index;
- entity knowledge graph;
- tiered assertions;
- event timeline.

Entity pages contain separate sections for A facts, B syntheses, and C interpretations. C content cannot be placed into A fact properties by the deterministic exporter.

## Remaining Stage 7 work

Stage 7.1 provides the evidence and epistemic foundation. The following slices remain before integrated scoring:

- full-text mention and dialogue indexing beyond the six typed predicates;
- conservative minor-character, ability, place, item, and event discovery;
- cross-file canonical chapter map and missing/duplicate chapter registry;
- relationship change extraction and state-at-chapter querying;
- event cause/process/outcome/consequence/foreshadowing extraction;
- cold-detail and exact-occurrence benchmark;
- incremental revision ledger and Notion update application;
- final private-corpus blind evaluation with all domains measured independently.
