# Stage 1 Result — Development-Line Convergence and Corpus Safety

## Status

```yaml
stage: Stage 1
implementation: complete
integration: merged_into_feature/phase9-0-baseline-cleanup
pull_request: 11
merge_commit: 444f21513002345c578f89d8afd32c1ff50eaa8b
local_focused_tests: 15_passed
github_focused_checks: passed
python_versions:
  - "3.10"
  - "3.11"
  - "3.12"
project_acceptance_performed: false
release_candidate: false
freeze_approved: false
```

## Estimated engineering time

The planned Stage 1 effort was **4–6 engineering hours**. This estimate covers implementation, workflow governance, focused tests, schemas, artifact publication, repository-state synchronization, and integration review. It does not include real-corpus acceptance or final project validation.

## Completed work

### Development-line convergence

- Established `feature/phase9-stage1-safety-hardening` from the latest Phase 9.0–9.3 base.
- Superseded stale Phase 9.4 branches and PR #10.
- Restricted legacy Phase 2–8 pull-request workflows to `main` targets so intermediate Phase 9 work no longer triggers release or acceptance workflows.
- Merged PR #11 into the canonical Phase 9 development base.

### Corpus safety

- Added conservative source-bound anomaly findings.
- Added exact decoded-character spans, line ranges, evidence hashes, and deterministic Finding IDs.
- Added Unicode anomaly, web residue, author paratext, long-line, repeated-line, distant-duplicate, and line-level script-shift rules.
- Added fixed-character window scanning so single-line extracted corpora remain analyzable.
- Added same-language cross-work review candidates using multiple independent signals:
  - character bigram distribution;
  - entity-system discontinuity;
  - narrative-register transition;
  - sentence-length transition.
- Preserved manual-review semantics: no automatic deletion and no clean/contaminated verdict.
- Re-hashed the source after scanning to detect concurrent modification.

### Artifacts and contracts

- Registered `tkr-anomaly-scan`.
- Added complete JSON report output and the standard output directory.
- Added JSONL candidate partitions, CSV ledger, stage result, and SHA-256 artifact manifest.
- Added JSON Schema contracts for findings and reports.
- Added schema files to package data.

## Standard artifact set

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

## Focused check coverage

The 15 focused tests cover:

- clean-source false-positive guard;
- deterministic IDs and exact Unicode spans;
- external BOM offset behavior;
- web residue and paratext separation;
- long lines, repeated lines, and distant duplicates;
- CJK/ASCII script transitions;
- caller-supplied marker clusters;
- same-language cross-work transitions;
- single-physical-line window scanning;
- same-register false-positive guard;
- explicit finding limits;
- unsupported-source blocking;
- policy validation;
- deterministic artifact publication;
- CLI artifact output.

## Remaining limitations

Stage 1 does not claim measured production accuracy. The following remain for the final acceptance stage:

- private same-language pollution recall and precision;
- clean-corpus false-positive rate;
- long-corpus throughput and peak memory;
- adversarial boundary localization metrics;
- full package and end-to-end acceptance.

## Next large stage

**Stage 2 — Deterministic corpus structure**

Estimated engineering time: **12–18 hours**.

Scope:

- heading candidate detection;
- volume, chapter, section, preface, epilogue, and extra-story classification;
- deterministic Unit Index generation;
- exact Unit coverage and non-overlap checks;
- numbering continuity, duplication, inversion, and missing-unit candidates;
- structure artifacts and schemas.
