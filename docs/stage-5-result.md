# Stage 5 Result — Engineering Hardening and Complete Skill Productization

## Status

```yaml
stage: Stage 5
estimated_engineering_time: 16_to_24_hours
implementation: complete
integration: merged_into_feature/phase9-0-baseline-cleanup
pull_request: 16
merge_commit: 5db3dbc8a10954e4d5fd97f2aa45148c9bfd282e
focused_tests: 38_passed
github_focused_checks: passed
python_versions:
  - "3.10"
  - "3.11"
  - "3.12"
workflow_run_id: 29897596131
stage_2_regression_run_id: 29897596139
stage_3_regression_run_id: 29897596149
stage_4_regression_run_id: 29897596112
wheel_build: passed
clean_wheel_installation: passed
installed_doctor_and_audit: passed
installed_example_build_verify_query: passed
project_acceptance_performed: false
release_candidate: false
freeze_approved: false
```

## Completed scope

### Recoverable engineering runtime

Stage 5 adds a mutable engineering layer outside the immutable Stage 4 project. It provides:

- deterministic content-addressed build keys;
- strict engineering profiles;
- one exclusive build lock per state directory;
- atomic build-state journals;
- verified cache publication and restoration;
- explicit verified existing-project reuse;
- atomic replacement with backup rollback;
- orphaned backup recovery;
- stale temporary build and cache cleanup;
- explicit stale-lock recovery after process-liveness checks.

The build key binds:

```text
raw source SHA-256
+ engineering profile SHA-256
+ engineering runtime version
+ knowledge system version
```

A source, profile, runtime, system, build policy, Manifest, database, or project-integrity change invalidates cache reuse.

### Built-in profiles

```text
balanced
strict
high-recall
```

- `balanced` preserves bounded review-mode defaults and verified caching.
- `strict` uses canonical mode and disables model proposal tasks.
- `high-recall` expands deterministic candidate and finding limits for complex long-form corpora.

Profiles reject unknown fields and have deterministic SHA-256 identities.

### External mutable state

The default state path is a sibling of the immutable project:

```text
.<project-name>.tkr-state/
```

It can contain:

```text
build.lock
build-state.json
cache/<build_key>/cache-record.json
cache/<build_key>/project/
```

Lock, journal, and cache files are never added to the evidence-bearing project Manifest.

### Path and filesystem security

Stage 5 rejects:

- symbolic-link sources;
- symbolic-link project, state, cache, package, or recovery authority paths;
- output directories containing the source;
- overlapping project and state directories;
- absolute, parent-traversal, duplicate, or non-normalized Manifest paths;
- unregistered or missing project files;
- unexpected top-level project entries;
- non-regular files;
- unsafe or invalid replacement backups;
- control files beyond configured bounds.

Enhanced verification requires the actual project regular-file set to equal all Manifest-declared files plus `project-manifest.json` itself.

### Secure unified commands

All unified commands now enforce the Stage 5 security boundary:

```bash
tkr-project build
tkr-project verify
tkr-project query
tkr-project verify-answer
```

Build additions include:

```text
--profile
--state-dir
--no-cache
--no-resume
--recover-stale-lock
--reuse
--force
```

Strict question answering still requires complete project verification, typed Fact support, exact citations, and answer recomputation.

### Complete Skill contract

The repository and installed package now contain an authoritative `SKILL.md` that defines:

- purpose and supported inputs;
- complete workflow;
- supported predicates;
- factual-status boundaries;
- engineering profiles;
- commands;
- security and recovery behavior;
- cache identity;
- standard artifacts;
- failure behavior;
- package audit;
- final acceptance boundary.

### Skill product commands

```bash
tkr-skill doctor
tkr-skill audit
tkr-skill profiles
tkr-skill show-profile balanced
```

The audit checks required files and directories, UTF-8 readability, JSON Schema syntax, engineering profiles, example JSONL, console-script declarations, package-data declarations, file-count limits, and symbolic-link absence.

The doctor checks Python, SQLite, FTS5 availability, temporary storage, built-in profiles, and the complete Skill layout.

### Documentation and examples

Added:

```text
SKILL.md
profiles/balanced.json
profiles/strict.json
profiles/high-recall.json
examples/minimal-corpus.txt
examples/questions.jsonl
docs/INSTALL.md
docs/SECURITY.md
docs/MIGRATION_STAGE5.md
MANIFEST.in
```

### Package productization

The Wheel and source distribution include:

- Python runtime modules;
- all console scripts;
- `SKILL.md`;
- README and machine-readable project status;
- all JSON Schemas;
- engineering profiles;
- executable examples;
- installation, security, and migration documentation.

## Schema contracts

```text
schemas/engineering-profile.schema.json
schemas/engineering-build-result.schema.json
schemas/engineering-build-state.schema.json
schemas/skill-audit-report.schema.json
schemas/skill-doctor-report.schema.json
```

All Stage 5 contracts keep:

```yaml
project_acceptance_performed: false
may_accept_project: false
release_candidate: false
may_freeze: false
```

## Focused check coverage

The 38 Stage 5 tests passed on Python 3.10, 3.11, and 3.12. They cover:

- built-in profile validation and deterministic hashes;
- profile-sensitive build keys;
- source-checkout Skill audit and doctor;
- source, output, and state path separation;
- source and output symbolic-link rejection;
- first build and cache publication;
- verified cache restoration;
- tampered-cache invalidation and rebuild;
- verified existing-project reuse;
- source revision mismatch;
- atomic replacement and changed project identity;
- cache disabling;
- active lock rejection;
- explicit expired dead-lock recovery;
- orphaned backup restoration;
- stale build-directory cleanup;
- mutable-state separation;
- strict canonical profile build;
- no-Claim build blocking and failed journal state;
- unexpected project file rejection;
- project symbolic-link rejection;
- Manifest traversal rejection;
- typed answer citations;
- unsupported-question refusal;
- exact answer recomputation and tamper rejection;
- unified CLI build, verify, query, and verify-answer behavior.

## Clean installation checks

For each of Python 3.10, 3.11, and 3.12, the Stage 5 workflow:

1. installed the source checkout;
2. compiled Stage 5 modules;
3. validated all JSON Schemas and profiles;
4. ran the 38 focused tests;
5. ran source-checkout Doctor and Audit;
6. built a Wheel;
7. created a new virtual environment;
8. installed only the generated Wheel;
9. ran installed Doctor, Audit, and Profile discovery;
10. built, verified, and queried the installed executable example project.

All jobs passed.

## Regression checks

The final PR #16 Head also passed:

- Stage 2 focused developer checks;
- Stage 3 focused developer checks;
- Stage 4 focused developer checks.

## Remaining final-acceptance measurements

Stage 5 does not establish production capability scores. Stage 6 must still perform:

- complete regression execution on the frozen final candidate;
- private blind corpus and question evaluation;
- pollution, structure, Claim, factual-state, entity, retrieval, QA, and refusal metrics;
- real long-corpus throughput and peak-memory measurement;
- hostile-input and fault-injection campaigns;
- recovery, cache invalidation, and concurrent-build validation;
- deterministic output and cross-Python drift comparison;
- final source and Wheel package audit;
- measurement of all 18 capability domains;
- one final project acceptance decision.

No capability is declared to have reached the final 9.0 threshold merely because Stage 5 developer checks passed.

## Next large stage

**Stage 6 — Final Capability Analysis and Project Acceptance**

Estimated engineering time: **20–30 hours plus corpus runtime**.

Stage 6 is the first and only stage authorized to perform final project acceptance. Every capability domain must score at least 9.0; average compensation is not allowed, and any blocking integrity defect causes failure.
