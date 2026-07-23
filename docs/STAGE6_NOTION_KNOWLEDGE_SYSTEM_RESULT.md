# Stage 6-R1 — Notion Knowledge System Result

## Status

`completed_and_integrated`

Stage 6-R1 repaired the P0 defects found during the whole-project audit and was squash merged through PR #33. This result is engineering integration only; it is not final private-corpus acceptance, release approval, or freeze authorization.

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
- remote deletion remains forbidden and archive actions remain review-only candidates;
- stable Skill product contract sections remain compatible with Doctor and Audit.

## Focused R1 regression

The R1 suite covers:

1. reversed A/B/C annotation order with correct A→B→C support resolution;
2. byte-identical reports across different local output directories;
3. two real SQLite page foreign keys on the relation table;
4. field-level SQLite drift detection even when container hashes are recomputed.

## Final exact-head validation

Final PR head:

`31ec0223fc0a64cb389a5ee737a2bcd60c4e5bb3`

Workflow run:

`29990180725`

The run passed:

- package installation;
- bundled entry-point and Stage 6 module compilation;
- all nine Stage 6 Schema checks;
- Notion engine, Notion Project, and Stage 6-R1 adversarial tests;
- complete repository regression;
- installed and bundled CLI smoke checks.

## Integration

- Pull request: `#33`
- Merge method: squash
- Squash merge commit: `07f10cf8552c730c29afd01197108441e126e3f3`
- Integration branch: `develop/v6-literary-engine`

## Remaining authority boundary

No real Notion API write, database creation, page upsert, relation application, remote readback verification, irreversible deletion, v6 final scoring, Release Candidate creation, release approval, or repository freeze was performed by Stage 6.

The next major stage is **Stage 7: Literary Regression Benchmark**.
