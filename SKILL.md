---
name: text-knowledge-reader
description: Build an evidence-bound long-text knowledge project and an optional chapter-addressable literary knowledge engine. Preserve source identity, detect contamination and structural defects, separate explicit facts from cross-evidence synthesis and model interpretation, retrieve exact evidence, export a Notion-ready package, and refuse unsupported conclusions. Use for novels, historical corpora, technical documents, notes, and other long text where traceability matters.
---

# Text Knowledge Reader

**Development version:** 6.0.0-alpha1  
**Historical release:** 5.9.0 at `archive/v5.9.0-final`  
**Current status:** Stage 7 literary-engine development; no v6 final acceptance or freeze

## Purpose

Use this Skill to transform uploaded long text into an auditable knowledge system without silently repairing, deleting, or inventing source content.

The Skill has two compatible layers:

1. **Base evidence project** — source identity, decoding, anomaly isolation, Unit/chapter structure, six deterministic fact predicates, entity normalization, retrieval, citations, and strict refusal.
2. **Literary knowledge sidecar** — chapter addresses, exact evidence anchors, broader literary entities, time-bounded relationships, causal event components, revision history, A/B/C epistemic separation, and a Notion-ready export.

The literary sidecar extends the base project. It does not bypass base-project verification.

## Inputs

Primary inputs:

- one uploaded `.txt` or `.md` file;
- several uploaded text files when the user explicitly authorizes a combination order;
- an existing verified Text Knowledge Reader project;
- optional reviewed literary annotation JSONL;
- a factual, structural, relational, event, evidence, or literary-analysis question.

Supported strict decoding:

- UTF-8;
- UTF-8 with BOM;
- UTF-16 LE with BOM;
- UTF-16 BE with BOM.

Never use replacement decoding. Never modify, overwrite, delete, or normalize the user's original file in place.

## Epistemic contract

Every literary conclusion must be classified.

### A — explicit source fact

A records are facts directly supported by exact source evidence. Every A record must bind:

- source ID and source SHA-256;
- Unit and literary chapter ID;
- volume/chapter ordinal when recoverable;
- original and normalized heading;
- exact start/end character offsets;
- exact evidence text and evidence SHA-256;
- Unit content SHA-256;
- source contamination/review status.

A records cannot be synthesis or literary interpretation.

### B — cross-evidence synthesis

B records summarize a pattern, long-term causal connection, character arc, faction strategy, or other conclusion supported by at least two independent A supports.

A B record is not an original sentence from the source. Present it as **high-confidence synthesis**, not as an explicit authorial statement.

### C — model literary interpretation

C records may discuss theme, symbolism, narrative strategy, ethics, political meaning, or one plausible reading. Every C record must:

- be explicitly labeled model interpretation;
- cite A or B support;
- disclose limitations or competing readings;
- never claim definitive author intent without direct evidence;
- never be placed into an A-grade fact property in Notion.

Do not silently promote C to B or B to A.

## Workflow

### 1. Locate the Skill and inputs

Treat the directory containing this `SKILL.md` as `SKILL_DIR`.

Use only files actually available in the current conversation or sandbox. Do not infer a sandbox path from a filename alone. Do not use model memory to fill missing chapters, polluted suffixes, or absent source passages.

### 2. Check the bundled Skill

```bash
python "${SKILL_DIR}/scripts/tkr.py" doctor
python "${SKILL_DIR}/scripts/tkr.py" audit
```

### 3. Build the base evidence project

```bash
python "${SKILL_DIR}/scripts/tkr.py" build INPUT.txt \
  --outdir BASE_PROJECT \
  --state-dir BUILD_STATE \
  --profile balanced
```

Profiles:

- `balanced` — ordinary build with conservative review findings;
- `strict` — canonical indexing only when the user explicitly requests it;
- `high-recall` — irregular corpora where additional review candidates are acceptable.

Verify before any query or literary build:

```bash
python "${SKILL_DIR}/scripts/tkr.py" verify BASE_PROJECT
```

### 4. Build the literary sidecar

```bash
python "${SKILL_DIR}/scripts/tkr.py" literary build BASE_PROJECT \
  --outdir LITERARY_PROJECT
```

Optional reviewed annotations:

```bash
python "${SKILL_DIR}/scripts/tkr.py" literary build BASE_PROJECT \
  --outdir LITERARY_PROJECT \
  --annotations REVIEWED_ANNOTATIONS.jsonl
```

Annotations do not receive automatic authority. They must satisfy the A/B/C contracts and exact evidence checks.

Verify the sidecar:

```bash
python "${SKILL_DIR}/scripts/tkr.py" literary verify LITERARY_PROJECT
```

### 5. Query the correct layer

Use the base layer for the deterministic six predicates:

```bash
python "${SKILL_DIR}/scripts/tkr.py" query BASE_PROJECT "陆川击败了谁？"
```

Use the literary layer for chapter, relationship, event, evidence, entity-profile, and explicitly separated analysis questions:

```bash
python "${SKILL_DIR}/scripts/tkr.py" literary query LITERARY_PROJECT \
  "林舟首次出场在哪一章？"

python "${SKILL_DIR}/scripts/tkr.py" literary query LITERARY_PROJECT \
  "林舟与赵衡在第1卷第1章时是什么关系？"

python "${SKILL_DIR}/scripts/tkr.py" literary query LITERARY_PROJECT \
  "这一结论是原文事实、跨证据归纳还是模型解释？"
```

A literary answer packet must return the tier of every item. Do not rewrite an A/B/C-separated response into one undifferentiated narrative.

### 6. Export a Notion-ready package

```bash
python "${SKILL_DIR}/scripts/tkr.py" literary export-notion LITERARY_PROJECT \
  --outdir NOTION_PACKAGE
```

The deterministic package separates:

- chapter index;
- entity knowledge graph;
- A/B/C assertions;
- event timeline;
- source evidence and hashes;
- CSV review ledgers.

An external Notion connector may upload these records. Before writing, preserve page IDs and relation IDs so later revisions update existing records rather than create uncontrolled duplicates.

## Base deterministic predicates

The existing fact engine supports:

- `alias` — names and aliases;
- `defeats` — who defeated whom;
- `located_in` — where an entity is located;
- `permission` — who may or may not perform an action;
- `count` — explicit quantities;
- `date` — explicit dates.

These predicates form an A-grade deterministic foundation. They are not a claim that every literary fact is already extracted.

## Literary records

The Stage 7 sidecar can store:

- chapters and volume/chapter addresses;
- evidence anchors;
- people, factions, abilities, places, items, events, concepts, and species;
- aliases and identity basis;
- first and last trusted appearance;
- A/B/C assertions;
- time-bounded relationships;
- event causes, process, outcome, consequences, and foreshadowing;
- revisions and supersession links.

Current Stage 7.1 provides these contracts and storage/query/export foundations. Full-text dialogue indexing, conservative minor-entity discovery, canonical cross-file chapter mapping, automatic relationship/event extraction, and final cold-detail evaluation remain later Stage 7 work.

## Factual-status handling

Keep direct assertions separate from:

- negation;
- belief;
- suspicion;
- rumor;
- accusation;
- hypothetical statements;
- questions;
- future intent.

Only direct assertions that pass source, structure, anomaly, evidence, validation, entity, conflict, and integrity gates may enter A facts.

## Refusal rules

Refuse rather than improvise when:

- the requested chapter is missing;
- the relevant source span is polluted or review-only;
- the entity name maps to multiple unresolved entities;
- a relationship has no interval covering the requested chapter;
- lexical text exists but no validated conclusion supports the answer;
- the user asks for a post-gap ending not present in trusted source material;
- evidence, database, report, manifest, or source verification fails;
- a requested interpretation lacks A/B support;
- a B or C conclusion is being requested as an explicit source fact.

A refusal is a correct result. Do not turn it into speculation to appear helpful.

## Safety boundaries

Always enforce these rules:

1. Preserve original source bytes and SHA-256 identity.
2. Never decode with replacement characters.
3. Never auto-delete pollution, paratext, anomalies, or duplicate-looking text.
4. Never accept evidence whose offsets, text, and hashes do not exactly match its source binding.
5. Never treat rumor, suspicion, accusation, question, hypothetical, or future intent as established fact.
6. Never answer from model memory when project evidence is absent.
7. Stop when project, literary sidecar, SQLite, report, manifest, source, or answer verification fails.
8. Do not combine files without explicit authorization and a documented order.
9. Keep mutable state, journals, locks, and caches outside immutable project directories.
10. Never present model interpretation as authorial fact.
11. Never claim all capabilities exceed 9.0 until final private blind evaluation measures every target domain independently.
12. Never claim v6 acceptance, release, or freeze from Stage 7 development checks.

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

The bundled entry point exposes the base and literary command surfaces:

```text
doctor
audit
profiles
show-profile
build
verify
query
verify-answer
literary build
literary verify
literary query
literary export-notion
```

Equivalent literary aliases are available for automation:

```text
literary-build
literary-verify
literary-query
literary-export-notion
```

Use the bundled script so source checkouts and directly uploaded Skill packages
follow the same command contract:

```bash
python "${SKILL_DIR}/scripts/tkr.py" --help
```

## Output requirements

For a build, report:

- source name and SHA-256;
- selected encoding;
- project and sidecar status;
- chapter/Unit count;
- clean, polluted, review, and missing-address findings;
- entity and assertion counts by A/B/C tier;
- evidence traceability and chapter-address coverage;
- blockers and files requiring review.

For an answer, report:

- answer or refusal;
- A/B/C classification for every conclusion;
- exact evidence excerpts and character offsets when available;
- volume/chapter and original heading;
- source ID, Unit ID, and evidence hash;
- limitations, conflicts, or alternative readings.

For a Notion export, report:

- page counts by database;
- A/B/C counts;
- manifest and hash verification;
- whether any record remains review-only;
- whether an incremental update or a fresh import is intended.

## Final checks

Before responding:

1. Verify the base project.
2. Verify the literary sidecar when used.
3. Confirm every A claim has exact source evidence.
4. Confirm every B claim has at least two independent A supports.
5. Confirm every C claim is explicitly attributed and limited.
6. Confirm cited offsets and text match the bound evidence anchor.
7. Confirm no unresolved conflict, ambiguity, or contamination invalidates the answer.
8. Confirm Notion properties preserve A/B/C separation.
9. Confirm downloadable files exist at the exact linked path.
10. State clearly that v6 remains under development until final integrated acceptance.

## Acceptance boundary

The historical v5.9 release remains archived and unchanged. The v6 literary engine is an active development line created in response to real-use gaps. Stage 7 unit and regression checks are engineering evidence only; they do not establish that every literary capability has reached 9.0, and they do not authorize a final release or repository freeze.
