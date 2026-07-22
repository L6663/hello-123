# Text Knowledge Reader Skill

## Purpose

Text Knowledge Reader converts one text corpus into a source-bound, auditable, typed knowledge project. The Skill is designed for long-form books, historical corpora, technical documents, notes, and other text collections where every accepted fact and answer must remain traceable to exact source evidence.

The Skill prioritizes evidence integrity over answer coverage. It may refuse to index or answer when decoding, corpus safety, structure, semantic status, entity identity, conflicts, citations, or project integrity remain unresolved.

This Stage 5 package is a development candidate. It does not certify that the final product has passed the all-capability 9.0 acceptance threshold.

## Inputs

The primary input is one regular text file.

Supported decoding paths:

- strict UTF-8;
- UTF-8 with an external BOM;
- UTF-16 little-endian with BOM;
- UTF-16 big-endian with BOM.

The source must:

- be a regular file rather than a directory, device, pipe, or symbolic link;
- decode strictly without replacement-character recovery;
- remain unchanged during inspection and extraction;
- satisfy source-admission and Unicode-quality constraints;
- be stored outside the immutable output project directory.

Optional inputs:

- a built-in engineering profile name;
- a custom engineering profile JSON that conforms to `engineering-profile.schema.json`;
- a separate mutable state directory for locks, journals, and verified cache entries;
- supported typed questions for the completed project;
- previously saved answer packets for exact recomputation.

## Workflow

The complete deterministic workflow is:

```text
raw source bytes
→ source identity and strict decoding
→ Unicode and text-quality inspection
→ anomaly, paratext, repetition, and contamination candidates
→ deterministic headings and source-covering Unit Index
→ six-predicate Claim candidates
→ discourse and factual-status separation
→ deterministic Claim validation
→ entity, alias, timeline, conflict, and ambiguity normalization
→ freshly revalidated compatibility bridge
→ hash-bound SQLite typed knowledge index
→ strict typed retrieval
→ evidence citations or deterministic refusal
→ project and answer recomputation verification
```

The engineering wrapper adds:

```text
path validation
→ exclusive build lock
→ build journal
→ orphan backup and stale workspace recovery
→ content-addressed cache lookup
→ atomic project build or verified cache restore
→ enhanced non-symlink filesystem verification
→ immutable project publication
```

Mutable engineering state is always kept outside the immutable project directory.

## Supported semantic predicates

The deterministic extraction, validation, retrieval, and answer stack supports:

```text
alias
beats / defeats
located_in
permission
count
date
```

Examples:

- `玄霄又称青帝。`
- `陆川击败韩岳。`
- `听雪楼位于北境。`
- `守门人允许陆川进入内殿。`
- `剑阵共有十二柄飞剑。`
- `大战发生于2026年7月22日。`

Open-ended literary interpretation, motive analysis, symbolism, theme, foreshadowing, and unsupported predicates are not mechanically accepted as typed facts.

## Factual-status model

The Skill separates:

- direct assertions;
- negated assertions;
- beliefs;
- suspicions;
- rumors;
- accusations;
- hypotheticals;
- questions;
- future intentions.

Only direct assertions that pass deterministic validation and every upstream safety gate may enter accepted typed Claims. A statement that a character believes, suspects, reports, or accuses something may be retained as an attributed proposition, while the embedded proposition remains unconfirmed.

## Engineering profiles

### `balanced`

Default review-mode profile. It preserves Stage 4 behavior, emits bounded model proposal tasks, and enables verified content-addressed caching.

### `strict`

Canonical-mode profile. It blocks unresolved Stage 1, Stage 2, Stage 3, conflict, and ambiguity findings and disables model proposal tasks.

### `high-recall`

Review-mode profile with expanded deterministic candidate, finding, model-task, and clause limits for complex long-form corpora.

Profile identity is included in the Stage 5 build key. Any profile change invalidates the prior cache entry.

## Commands

### Environment and package checks

```bash
tkr-skill doctor
tkr-skill audit
tkr-skill profiles
tkr-skill show-profile balanced
```

### Build

```bash
tkr-project build corpus.txt --outdir project --profile balanced
```

Use a separate state directory when desired:

```bash
tkr-project build corpus.txt \
  --outdir project \
  --state-dir .tkr-state/project \
  --profile balanced
```

Disable cache or automatic workspace recovery:

```bash
tkr-project build corpus.txt --outdir project --no-cache
tkr-project build corpus.txt --outdir project --no-resume
```

Reuse an exact existing project or atomically replace it:

```bash
tkr-project build corpus.txt --outdir project --reuse
tkr-project build corpus.txt --outdir project --force
```

Recover a sufficiently old lock only after the recorded process is no longer alive:

```bash
tkr-project build corpus.txt \
  --outdir project \
  --recover-stale-lock
```

### Verify

```bash
tkr-project verify project
```

Verification includes the Stage 4 hash chain plus Stage 5 exact filesystem membership and symbolic-link rejection.

### Query

```bash
tkr-project query project "陆川击败了谁？"
```

Save the complete answer packet:

```bash
tkr-project query project "陆川击败了谁？" --output answer.json
```

### Verify a saved answer

```bash
tkr-project verify-answer project answer.json
```

## Safety boundaries

The Skill must never:

- modify the source corpus;
- silently replace undecodable characters;
- follow source, project, cache, state, or package symbolic links as authority;
- auto-delete suspected contamination from the source;
- promote a rumor, belief, suspicion, accusation, hypothetical, question, or intention into a fact;
- index Evidence that overlaps blocked contamination or non-body content;
- trust copied Stage 3 semantic files without fresh deterministic normalization;
- answer from lexical similarity alone;
- treat absence of evidence as a negative fact;
- accept a changed answer or citation without exact recomputation;
- store mutable lock, cache, or journal files inside the immutable project;
- reuse a cache entry whose source, profile, system version, Manifest, or SQLite identity differs;
- declare project acceptance, a Release Candidate, or Freeze approval during an intermediate stage.

Manifest paths must be normalized relative POSIX paths. Absolute paths, parent traversal, duplicates, undeclared files, missing files, symbolic links, devices, and non-regular files are rejected.

## Recovery model

Stage 5 records build state in `build-state.json` under the external state directory.

Recorded phases include:

- prepared;
- restoring cache;
- building project;
- publishing cache;
- completed;
- failed.

Recovery may:

- restore an orphaned verified replacement backup;
- remove a redundant backup after the current project verifies;
- roll back an invalid replacement when the backup verifies;
- remove sufficiently old temporary build and cache directories;
- discard an invalid cache entry;
- reject a live or insufficiently old build lock.

Recovery never treats an unverified backup or cache entry as authoritative.

## Cache model

The content-addressed build key is derived from:

```text
raw source SHA-256
+ engineering profile SHA-256
+ engineering runtime version
+ knowledge system version
```

A cache entry contains a complete immutable project and a cache record stored beside, not inside, the project. Cache restoration copies into a temporary directory, verifies the copied project, and only then publishes it atomically.

## Standard artifacts

A completed immutable project contains:

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

The external mutable state directory may contain:

```text
build.lock
build-state.json
cache/<build_key>/cache-record.json
cache/<build_key>/project/
```

The state directory is not part of the immutable knowledge project and must not be cited as evidence.

## Project identity and citations

A typed answer is bound through:

```text
answer packet
→ strict QA packet
→ Fact
→ accepted Claim
→ exact Evidence span
→ Unit
→ normalized source SHA-256
→ original source SHA-256
→ project Manifest SHA-256
```

Any mismatch causes rejection or refusal.

## Failure behavior

Expected failures include:

- unsafe source or output path;
- unsupported or ambiguous encoding;
- source mutation during processing;
- unresolved canonical blockers;
- no accepted typed Claims;
- active build lock;
- invalid cache or project;
- existing output without `--reuse` or `--force`;
- unsupported question;
- insufficient typed evidence;
- unresolved conflict or entity ambiguity;
- citation, answer, Manifest, database, or package tampering.

Failures must leave no project that is presented as verified. The build journal records the failure type and a bounded message without changing acceptance authority.

## Installation and package audit

A complete installation includes:

```text
SKILL.md
README.md
PROJECT_STATUS.yaml
profiles/
examples/
docs/
schemas/
tkr Python package
console scripts
```

Run both checks after installation:

```bash
tkr-skill doctor
tkr-skill audit
```

The audit validates required files, UTF-8 readability, JSON Schema syntax, profile contracts, example JSONL, console-script declarations, package-data declarations, and symbolic-link absence.

## Acceptance boundary

Stage 5 developer checks establish implementation and packaging evidence only.

They do not perform:

- private blind evaluation;
- final retrieval Recall@10 or MRR measurement;
- final answer or refusal accuracy measurement;
- final citation-correctness measurement;
- real long-corpus performance acceptance;
- final hostile-input campaign;
- final drift comparison;
- Release Candidate approval;
- Freeze authorization.

Final project acceptance occurs once, after the complete Skill is frozen for Stage 6 evaluation. Every capability domain must score at least 9.0. Average scores cannot compensate for any domain below 9.0, and blocking integrity defects remain automatic failures.
