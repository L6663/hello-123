---
name: text-knowledge-reader
description: Build auditable long-text knowledge projects with strict source identity, contamination isolation, exact Evidence Units, multi-file chapter catalogs, A/B/C epistemic separation, evidence-first literary queries, and Notion-ready exports. Use for novels, historical corpora, technical documents, notes, and other long text where source traceability and refusal are required.
---

# Text Knowledge Reader

**Development version:** 6.0.0-alpha1  
**Historical release:** 5.9.0 at `archive/v5.9.0-final`  
**Current development:** Stage 1 Evidence Engine integrated; Stage 2 Chapter Structure Engine under final integration  
**Authority:** no v6 final acceptance, release, or freeze

## Purpose

Use this Skill to convert uploaded long text into a source-bound, reviewable knowledge system without silently repairing, deleting, renumbering, reordering, or inventing source content.

The v6 system has four compatible layers:

1. **Base source project** — strict decoding, source identity, anomaly isolation, Unit structure, deterministic fact predicates, entity normalization, retrieval, citations, and refusal.
2. **Evidence Project** — complete trusted-body Evidence Units, exact Claim evidence anchors, Claim→Evidence edges, coverage accounting, SQLite integrity, and deterministic rebuild verification.
3. **Chapter Project** — one or more verified source projects mapped into an immutable physical chapter order plus a separate reviewable canonical-order candidate.
4. **Literary sidecar** — A/B/C assertions, selected entities, temporal relationships, event components, revisions, evidence-first queries, and Notion-ready projection.

Later layers never bypass verification of earlier inputs.

## Inputs

Supported inputs include:

- one uploaded `.txt` or `.md` file;
- several uploaded text files when their input order is explicitly supplied;
- an existing verified Text Knowledge Reader project;
- multiple verified source projects for one Chapter Project;
- a verified literary sidecar;
- optional reviewed literary annotation JSONL;
- factual, structural, relational, event, evidence, chapter-location, or literary-analysis questions.

Supported strict decoding:

- UTF-8;
- UTF-8 with BOM;
- UTF-16 LE with BOM;
- UTF-16 BE with BOM.

Never use replacement decoding. Never modify the user's original file in place.

## Epistemic contract

Every literary conclusion must retain its level.

### A — explicit source fact

A records require exact clean evidence bound to:

- source ID and SHA-256;
- Unit and chapter ID;
- original source span;
- exact evidence text and SHA-256;
- contamination and review state.

A records cannot be synthesis or interpretation.

### B — cross-evidence synthesis

B records summarize patterns or causal structure supported by multiple independent A records. Present them as synthesis, not as a sentence explicitly stated by the source.

### C — model literary interpretation

C records may discuss theme, symbolism, narrative strategy, ethics, politics, or one plausible reading. They must be labeled model interpretation, cite A/B support, disclose limitations, and never enter A-grade fact properties.

Do not silently promote C to B or B to A.

## Workflow

Treat the directory containing this `SKILL.md` as `SKILL_DIR`.

### 1. Check the bundled Skill

```bash
python "${SKILL_DIR}/scripts/tkr.py" doctor
python "${SKILL_DIR}/scripts/tkr.py" audit
```

### 2. Build and verify each base source project

```bash
python "${SKILL_DIR}/scripts/tkr.py" build INPUT.txt \
  --outdir BASE_PROJECT \
  --state-dir BUILD_STATE \
  --profile balanced

python "${SKILL_DIR}/scripts/tkr.py" verify BASE_PROJECT
```

Profiles:

- `balanced` — ordinary conservative build;
- `strict` — canonical indexing only when explicitly requested;
- `high-recall` — irregular corpora with additional review candidates.

### 3. Build the Chapter Project for one or more files

The source-project argument order is the immutable input and physical file order. A numbering-derived canonical order is stored separately as a candidate and never rewrites physical order.

```bash
python "${SKILL_DIR}/scripts/tkr.py" chapter build \
  PROJECT_A PROJECT_B PROJECT_C \
  --outdir CHAPTER_PROJECT
```

Verify using the same project order:

```bash
python "${SKILL_DIR}/scripts/tkr.py" chapter verify CHAPTER_PROJECT \
  --source-project PROJECT_A \
  --source-project PROJECT_B \
  --source-project PROJECT_C
```

Query an exact address:

```bash
python "${SKILL_DIR}/scripts/tkr.py" chapter query CHAPTER_PROJECT \
  --source-project PROJECT_A \
  --source-project PROJECT_B \
  --source-project PROJECT_C \
  --address 8 138
```

Query one chapter and its physical or canonical neighbors:

```bash
python "${SKILL_DIR}/scripts/tkr.py" chapter query CHAPTER_PROJECT \
  --source-project PROJECT_A \
  --source-project PROJECT_B \
  --chapter-id CHAPTER_ID \
  --neighbors physical

python "${SKILL_DIR}/scripts/tkr.py" chapter query CHAPTER_PROJECT \
  --source-project PROJECT_A \
  --source-project PROJECT_B \
  --chapter-id CHAPTER_ID \
  --neighbors canonical
```

`physical` means original input order. `canonical` means the numbering-derived candidate. Never describe the candidate as a source rewrite.

### 4. Build and verify the literary sidecar

```bash
python "${SKILL_DIR}/scripts/tkr.py" literary build BASE_PROJECT \
  --outdir LITERARY_PROJECT

python "${SKILL_DIR}/scripts/tkr.py" literary verify LITERARY_PROJECT
```

Optional reviewed annotations:

```bash
python "${SKILL_DIR}/scripts/tkr.py" literary build BASE_PROJECT \
  --outdir LITERARY_PROJECT \
  --annotations REVIEWED_ANNOTATIONS.jsonl
```

Annotations receive no automatic authority. They must pass exact evidence and A/B/C validation.

### 5. Build and verify the Evidence Project

```bash
python "${SKILL_DIR}/scripts/tkr.py" evidence build \
  BASE_PROJECT LITERARY_PROJECT \
  --outdir EVIDENCE_PROJECT

python "${SKILL_DIR}/scripts/tkr.py" evidence verify \
  BASE_PROJECT LITERARY_PROJECT EVIDENCE_PROJECT
```

### 6. Query the appropriate layer

Use the base layer for deterministic typed predicates:

```bash
python "${SKILL_DIR}/scripts/tkr.py" query BASE_PROJECT "陆川击败了谁？"
```

Use the Chapter Project for exact source location, numbering anomalies, file order, missing chapters, duplicate chapters, and neighbor queries.

Use the literary layer for relationships, events, evidence-linked profiles, and explicitly separated analysis:

```bash
python "${SKILL_DIR}/scripts/tkr.py" literary query LITERARY_PROJECT \
  "林舟与赵衡在第1卷第1章时是什么关系？"
```

Do not rewrite an A/B/C-separated response into one undifferentiated narrative.

### 7. Export a Notion-ready package

```bash
python "${SKILL_DIR}/scripts/tkr.py" literary export-notion LITERARY_PROJECT \
  --outdir NOTION_PACKAGE
```

Preserve page IDs and relation IDs so later revisions update existing records rather than create duplicates.

## Chapter Structure contract

A Chapter Project records both:

- **physical order** — immutable user-supplied project order and source-local position;
- **canonical-order candidate** — volume/chapter numbering order for review and retrieval.

Volume ordinals may be derived from:

1. a combined volume/chapter heading;
2. an explicit parent volume Unit;
3. conservative preceding-volume context;
4. unresolved state.

The derivation basis must always be retained.

Required structural findings include:

- duplicate canonical chapter keys;
- duplicate chapter content;
- chapter gaps and inversions;
- missing volume or chapter ordinal;
- missing, detached, or titleless headings;
- empty bodies;
- contaminated or review-only spans;
- overlapping source numbering ranges;
- input order that differs from numbering order.

Findings are review records. They do not authorize source mutation.

## Base deterministic predicates

The base fact engine supports:

- `alias`;
- `defeats`;
- `located_in`;
- `permission`;
- `count`;
- `date`.

These form an A-grade deterministic foundation, not a claim that every literary fact is already extracted.

## Refusal rules

Refuse rather than improvise when:

- a requested chapter address is absent;
- multiple chapters share one unresolved address;
- the file order or volume context is ambiguous;
- the relevant span is polluted or review-only;
- project, Chapter Project, Evidence Project, literary sidecar, SQLite, report, manifest, source, or answer verification fails;
- evidence exists but no validated conclusion supports the requested answer;
- a relationship has no interval covering the requested chapter;
- an interpretation lacks A/B support;
- the user requests missing post-gap content as established fact.

A refusal is a correct result.

## Safety boundaries

1. Preserve original source bytes and SHA-256 identity.
2. Never decode with replacement characters.
3. Never auto-delete pollution, paratext, anomalies, or duplicates.
4. Never rewrite chapter numbers, titles, file order, or source text.
5. Keep physical and canonical candidate order separate.
6. Never accept evidence whose offsets, text, and hashes do not match its source.
7. Never treat rumor, suspicion, accusation, questions, hypotheticals, or future intent as fact.
8. Never answer from model memory when verified evidence is absent.
9. Stop on any project, SQLite, report, manifest, source, or answer verification failure.
10. Do not combine files without explicit order.
11. Never present model interpretation as authorial fact.
12. Never claim all capabilities exceed 9.0 before final private blind evaluation.
13. Never claim v6 release or freeze from an engineering-stage check.

## Standard artifacts

Base project:

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

Evidence Project:

```text
evidence-units.jsonl
claim-evidence-anchors.jsonl
claim-evidence-edges.jsonl
evidence-coverage.json
claim-graph-report.json
evidence.sqlite
evidence-project-report.json
artifact-manifest.json
```

Chapter Project:

```text
source-bindings.jsonl
chapters.jsonl
canonical-order.jsonl
chapter-findings.jsonl
chapter.sqlite
chapter-project-report.json
artifact-manifest.json
```

Literary sidecar:

```text
chapters.jsonl
evidence-anchors.jsonl
entities.jsonl
assertions.jsonl
relationships.jsonl
events.jsonl
revisions.jsonl
literary.sqlite
literary-report.json
artifact-manifest.json
```

Notion-ready export:

```text
notion-database-schema.json
notion-chapter-pages.jsonl
notion-entity-pages.jsonl
notion-assertion-pages.jsonl
notion-event-pages.jsonl
chapter-ledger.csv
entity-ledger.csv
assertion-ledger.csv
notion-export-report.json
artifact-manifest.json
```

## Commands

Bundled command surface:

```text
doctor
audit
profiles
show-profile
build
verify
query
verify-answer
chapter build
chapter verify
chapter query
evidence build
evidence verify
literary build
literary verify
literary query
literary export-notion
```

Automation aliases:

```text
chapter-build
chapter-verify
chapter-query
evidence-build
evidence-verify
literary-build
literary-verify
literary-query
literary-export-notion
```

```bash
python "${SKILL_DIR}/scripts/tkr.py" --help
```

## Output requirements

For a Chapter Project, report:

- ordered source filenames, IDs, hashes, and project IDs;
- physical and canonical candidate order distinction;
- numbered chapter coverage;
- duplicate, gap, inversion, missing ordinal/title/body, contamination, and source-order findings;
- exact source offsets and content hashes;
- logical and database hashes;
- files requiring review.

For an answer, report:

- answer or refusal;
- physical or canonical order basis;
- source file, Unit, original heading, volume/chapter, and offsets;
- evidence tier for conclusions;
- limitations, conflicts, contamination, or alternative readings.

## Final checks

Before responding:

1. Verify every base project used.
2. Verify the Chapter Project when chapter/order information is used.
3. Verify the Evidence Project when claim support is used.
4. Verify the literary sidecar when literary records are used.
5. Confirm exact offsets, text, hashes, and source identity.
6. Confirm physical order was not rewritten.
7. Confirm canonical order is labeled candidate.
8. Confirm A/B/C separation remains intact.
9. Confirm unresolved conflict, ambiguity, or contamination is disclosed or causes refusal.
10. Confirm downloadable files exist at the exact linked path.
11. State that v6 remains under development until final integrated acceptance.

## Acceptance boundary

The historical v5.9 release remains archived and unchanged. Stage 1 and Stage 2 checks are engineering evidence for the v6 development line. They do not establish that every final literary capability has reached 9.0, do not create a release candidate, and do not authorize repository freeze.
