# Stage 6-R1 — Notion Knowledge System Result

## Status

`remediated_final_exact_head_ci_pending`

Stage 6-R1 repairs the P0 defects found during the whole-project audit. This record is not final private-corpus acceptance, release approval, or freeze authorization.

## Delivered remediation

- assertion support projection is independent of annotation input order;
- immutable Notion reports use `output_directory: "."` and do not disclose local absolute paths;
- the SQLite `relations` table has foreign keys to both source and target pages;
- verification compares every page, relation, review item, and sync action field across JSONL and SQLite;
- nine public Stage 6 JSON Schema contracts are included;
- installed `tkr-notion build|verify|plan` commands are packaged;
- bundled `python scripts/tkr.py notion ...` commands are available;
- Stage 6 schemas, project tests, R1 adversarial tests, full repository regression, and CLI smoke checks are included in the concise workflow;
- tracked Python bytecode was removed from the development line;
- remote deletion remains forbidden and archive actions remain review-only candidates.

## Focused R1 regression

The R1 suite covers:

1. reversed A/B/C annotation order with correct A→B→C support resolution;
2. byte-identical reports across different local output directories;
3. two real SQLite page foreign keys on the relation table;
4. field-level SQLite drift detection even when container hashes are recomputed.

## Validation before final candidate freeze

Head `928272a7cfa099bd94c58905b8978df48cf32aec` passed workflow run `29988760640`:

- package installation;
- Stage 6 module and bundled entry-point compilation;
- nine Stage 6 Schema load checks;
- Notion engine, Notion Project, and Stage 6-R1 focused tests;
- complete repository regression;
- installed and bundled CLI smoke checks.

The later compatibility head also passed the complete workflow after restoring the stable Skill contract section markers required by the product-layout audit.

## Final candidate freeze

The Stage 6-R1 candidate tree now uses the concise read-only workflow with no routine artifact upload. No runtime, Schema, package, Skill, test, or documentation files may change after this record until final exact-head CI completes.

## Remaining integration gate

This final candidate head must pass the same exact-head workflow before PR #33 is marked ready and squash merged.
