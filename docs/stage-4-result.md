# Stage 4 Result — End-to-End Verified Typed Knowledge System

## Status

```yaml
stage: Stage 4
estimated_engineering_time: 18_to_28_hours
implementation: complete
integration: merged_into_feature/phase9-0-baseline-cleanup
pull_request: 15
merge_commit: 3b5cc2852bfefbbc70f2af04dd43a25b35eee2ff
focused_tests: 27_passed
github_focused_checks: passed
python_versions:
  - "3.10"
  - "3.11"
  - "3.12"
workflow_run_id: 29895687071
stage_2_regression_run_id: 29895687036
stage_3_regression_run_id: 29895687057
project_acceptance_performed: false
release_candidate: false
freeze_approved: false
```

## Completed scope

Stage 4 joins raw-corpus ingestion to the existing typed index and strict-QA stack:

```text
raw source
→ strict source identity and decoding
→ anomaly and contamination candidates
→ deterministic Unit Index
→ evidence-bound Claim candidates
→ entity, fact, timeline, conflict, and ambiguity artifacts
→ freshly verified compatibility bridge
→ SQLite typed knowledge index
→ strict QA, citations, and deterministic refusal
```

### Self-contained project

The project preserves the exact original bytes and canonical UTF-8 decoded text. Stage 1, Stage 2, Stage 3, compatibility, index, report, and manifest artifacts are published into one directory only after the complete build passes post-build verification.

### Compatibility revalidation

Stage 3 accepted records are not copied directly into the index as authority. Stage 4 creates a bound compatibility layer and invokes the existing Phase 4 and Phase 5 verification paths. Accepted Claims are freshly revalidated; entity, fact, timeline, conflict, and ambiguity artifacts must reproduce before SQLite construction proceeds.

### Project integrity

`project-manifest.json` binds every immutable project file by relative path, byte size, and SHA-256. Verification checks:

- original and normalized source hashes;
- source metadata bindings;
- all manifest file records;
- index report and database SHA-256;
- SQLite logical index identity;
- query-path database verification;
- absence of project-acceptance, release-candidate, and freeze authority.

### Strict query and refusal

`tkr-project query` verifies the entire project before invoking existing strict QA. Only supported typed predicates may be answered. Unsupported literary interpretation questions and supported questions without typed evidence are refused.

### Answer packets

A Stage 4 answer packet binds:

- project ID;
- project-manifest SHA-256;
- raw-source SHA-256;
- normalized-source SHA-256;
- source ID;
- question;
- complete strict-QA packet;
- citations and refusal decision.

`tkr-project verify-answer` verifies the project, recomputes the strict packet, and recomputes the complete Stage 4 answer packet. Changed answers, citations, hashes, questions, authority flags, or database state are rejected.

## Unified command

```bash
tkr-project build SOURCE --outdir PROJECT
tkr-project verify PROJECT
tkr-project query PROJECT "QUESTION"
tkr-project verify-answer PROJECT ANSWER.json
```

Existing projects require an explicit policy:

```bash
tkr-project build SOURCE --outdir PROJECT --reuse
tkr-project build SOURCE --outdir PROJECT --force
```

`--reuse` succeeds only after complete project verification and exact raw-source identity comparison. `--force` builds and verifies a replacement in a temporary directory before swapping it into place.

## Standard project layout

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

## Schema contracts

```text
schemas/knowledge-project-report.schema.json
schemas/knowledge-project-manifest.schema.json
schemas/knowledge-project-verification.schema.json
schemas/knowledge-answer-packet.schema.json
schemas/knowledge-answer-verification.schema.json
```

## Focused check coverage

The 27 focused tests passed on Python 3.10, 3.11, and 3.12. They cover:

- raw-source-to-SQLite construction;
- all six predicates reaching the index;
- alias, defeat, and location answers with citations;
- unsupported and insufficient-evidence refusal;
- exact project verification;
- deterministic answer packets and answer recomputation;
- source, database, manifest, and answer tampering rejection;
- explicit reuse and atomic replacement policies;
- source-revision mismatch rejection;
- UTF-16 source ingestion with separate raw and normalized hashes;
- no-Claim build blocking;
- clean canonical build and paratext canonical blocking;
- deterministic project and index logical identities;
- CLI query, verify, and verify-answer operations;
- policy validation.

Stage 2 and Stage 3 regression workflows also passed on PR #15 after shared package configuration changed.

## Branch resolution

The first tested Stage 4 PR (#14) was closed without merge because its branch was created before the canonical Stage 3 documentation commits and therefore had divergent history. The identical functional implementation was replayed onto `feature/phase9-stage4-end-to-end-knowledge-v3`, which was created from the latest canonical base. PR #15 passed all focused and regression checks and was merged.

## Remaining final-acceptance measurements

Stage 4 does not claim measured production accuracy or performance. The following remain deferred until Stage 6:

- private retrieval Recall@10 and MRR;
- private strict-answer accuracy;
- refusal precision and recall;
- citation correctness and entailment;
- measured hallucination count;
- long-corpus throughput and peak memory;
- incremental-build behavior;
- recovery and hostile-input testing;
- final package and Skill audit;
- confirmation that every capability domain scores at least 9.0.

## Next large stage

**Stage 5 — Engineering Hardening and Complete Skill Productization**

Estimated engineering time: **16–24 hours**.

Scope:

- incremental and resumable project builds;
- crash recovery and cache invalidation;
- hostile-input and path-safety hardening;
- complete `SKILL.md` and package layout;
- profiles, examples, migration documentation, and clean-install verification;
- release-facing package preparation without performing final acceptance.
