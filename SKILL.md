---
name: text-knowledge-reader
description: Build auditable long-text knowledge systems with strict source identity, contamination isolation, exact Evidence Units, multi-file chapter catalogs, focused events and characters, A/B/C/H layered reasoning, reversible Notion synchronization plans, exact provenance, and deterministic refusal.
---

# Text Knowledge Reader

**Development version:** 6.0.0-alpha1  
**Historical stable release:** 5.9.0 at `archive/v5.9.0-final`  
**Integrated v6 stages:** Stage 1–5  
**Current stage:** Stage 6-R1 Notion Knowledge System, final integration  
**Authority:** no v6 final acceptance, release, or freeze

## Purpose

Convert uploaded long text into a source-bound, reviewable knowledge system without silently repairing, deleting, renumbering, reordering, merging, or inventing source content.

The v6 project chain is:

1. **Base source project** — strict decoding, source identity, contamination and anomaly isolation, deterministic Units, base fact predicates, retrieval, citations, and refusal.
2. **Chapter Project** — immutable physical order plus a separate reviewable canonical-order candidate.
3. **Literary sidecar** — source-bound A/B/C assertions, selected entities, temporal relations, events, revisions, and exact Evidence Anchors.
4. **Evidence Project** — complete clean-body Evidence Units, Claim→Evidence edges, coverage accounting, hashes, and SQLite integrity.
5. **Event Project** — materially significant events, cause/process/outcome/consequence/foreshadowing/recovery components, and supported causal paths.
6. **Character Project** — deep core characters, moderate important characters, minimal placeholders, time-bounded states and relationships, and evidence-bound arcs.
7. **Reasoning Project** — A facts, independently supported B synthesis, attributed C interpretation, explicitly non-canon H counterfactuals, and provenance.
8. **Notion Project** — stable page keys, physically separated A/B/C/H databases, referenced Evidence only, Review Queue, reversible sync plan, SQLite, Manifest, and verification.

No layer bypasses verification of its inputs.

## Epistemic contract

### A — explicit source fact

A records require exact clean evidence bound to source, Unit, chapter, original offsets, text, hashes, and contamination state.

### B — cross-evidence synthesis

B records require at least two independent A support branches. Repeated wording from one Evidence lineage does not count as independent support.

### C — model interpretation

C records must be labeled as model interpretation and include A/B support, limitations, attribution, and alternative readings. C never becomes source fact.

### H — hypothetical or counterfactual inference

H records are not canon. They must identify the changed premise, retained verified facts, inference rule, uncertainty, and alternatives.

Never silently promote H→C, C→B, or B→A.

## Entity policy

- `core` — deep evidence-bound model;
- `important` — role, major relations, states, and major-event model;
- `placeholder` — minimal identity, location, and necessary participation only;
- mention-only — remains in chapter/full-text retrieval and does not automatically become a canonical entity.

Mention frequency alone cannot promote a person. Low-impact people must not dilute mainline knowledge.

## Directly uploadable Skill commands

Treat the directory containing this file as `SKILL_DIR`.

### Check the Skill

```bash
python "${SKILL_DIR}/scripts/tkr.py" doctor
python "${SKILL_DIR}/scripts/tkr.py" audit
```

### 1. Build and verify source projects

```bash
python "${SKILL_DIR}/scripts/tkr.py" build INPUT.txt \
  --outdir BASE_PROJECT \
  --state-dir BUILD_STATE \
  --profile balanced

python "${SKILL_DIR}/scripts/tkr.py" verify BASE_PROJECT
```

Supported strict encodings: UTF-8, UTF-8 BOM, UTF-16 LE BOM, UTF-16 BE BOM. Never decode with replacement characters.

### 2. Build and verify the Chapter Project

Argument order is immutable physical input order.

```bash
python "${SKILL_DIR}/scripts/tkr.py" chapter build \
  PROJECT_A PROJECT_B --outdir CHAPTER_PROJECT

python "${SKILL_DIR}/scripts/tkr.py" chapter verify CHAPTER_PROJECT \
  --source-project PROJECT_A \
  --source-project PROJECT_B
```

Physical order is source authority. Canonical order is a numbering-derived candidate only.

### 3. Build literary sidecars and Evidence Projects

```bash
python "${SKILL_DIR}/scripts/tkr.py" literary build BASE_PROJECT \
  --outdir LITERARY_PROJECT \
  --annotations REVIEWED_LITERARY.jsonl

python "${SKILL_DIR}/scripts/tkr.py" literary verify LITERARY_PROJECT

python "${SKILL_DIR}/scripts/tkr.py" evidence build \
  BASE_PROJECT LITERARY_PROJECT \
  --outdir EVIDENCE_PROJECT

python "${SKILL_DIR}/scripts/tkr.py" evidence verify \
  BASE_PROJECT LITERARY_PROJECT EVIDENCE_PROJECT
```

Annotations receive no automatic authority. They must pass exact evidence and layer validation.

### 4. Build and verify the Event Project

```bash
python "${SKILL_DIR}/scripts/tkr.py" event build \
  CHAPTER_PROJECT EVENTS.jsonl \
  --source-project BASE_PROJECT \
  --literary-project LITERARY_PROJECT \
  --outdir EVENT_PROJECT

python "${SKILL_DIR}/scripts/tkr.py" event verify \
  EVENT_PROJECT CHAPTER_PROJECT EVENTS.jsonl \
  --source-project BASE_PROJECT \
  --literary-project LITERARY_PROJECT
```

Only events with material impact enter the formal graph. Unsupported causal paths refuse.

### 5. Build and verify the Focused Character Project

```bash
python "${SKILL_DIR}/scripts/tkr.py" character build \
  CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl CHARACTERS.jsonl \
  --source-project BASE_PROJECT \
  --literary-project LITERARY_PROJECT \
  --outdir CHARACTER_PROJECT

python "${SKILL_DIR}/scripts/tkr.py" character verify \
  CHARACTER_PROJECT CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl CHARACTERS.jsonl \
  --source-project BASE_PROJECT \
  --literary-project LITERARY_PROJECT
```

Placeholder depth requests must refuse.

### 6. Build and verify the Layered Reasoning Project

```bash
python "${SKILL_DIR}/scripts/tkr.py" reason build \
  CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl \
  CHARACTER_PROJECT CHARACTERS.jsonl REASONING.jsonl \
  --source-project BASE_PROJECT \
  --literary-project LITERARY_PROJECT \
  --evidence-binding BASE_PROJECT LITERARY_PROJECT EVIDENCE_PROJECT \
  --outdir REASONING_PROJECT

python "${SKILL_DIR}/scripts/tkr.py" reason verify \
  REASONING_PROJECT CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl \
  CHARACTER_PROJECT CHARACTERS.jsonl REASONING.jsonl \
  --source-project BASE_PROJECT \
  --literary-project LITERARY_PROJECT \
  --evidence-binding BASE_PROJECT LITERARY_PROJECT EVIDENCE_PROJECT
```

Query ceilings: `fact_only`, `fact_and_synthesis`, `analysis`, `counterfactual`, and `provenance`.

### 7. Build and verify the Notion Project

The Notion Project generates a deterministic package and reversible sync plan. It does not delete remote pages or claim unrestricted Notion API authority.

```bash
python "${SKILL_DIR}/scripts/tkr.py" notion build \
  CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl \
  CHARACTER_PROJECT CHARACTERS.jsonl \
  REASONING_PROJECT REASONING.jsonl \
  --source-project BASE_PROJECT \
  --literary-project LITERARY_PROJECT \
  --evidence-binding BASE_PROJECT LITERARY_PROJECT EVIDENCE_PROJECT \
  --outdir NOTION_PROJECT

python "${SKILL_DIR}/scripts/tkr.py" notion verify \
  NOTION_PROJECT \
  CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl \
  CHARACTER_PROJECT CHARACTERS.jsonl \
  REASONING_PROJECT REASONING.jsonl \
  --source-project BASE_PROJECT \
  --literary-project LITERARY_PROJECT \
  --evidence-binding BASE_PROJECT LITERARY_PROJECT EVIDENCE_PROJECT

python "${SKILL_DIR}/scripts/tkr.py" notion plan \
  NOTION_PROJECT \
  CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl \
  CHARACTER_PROJECT CHARACTERS.jsonl \
  REASONING_PROJECT REASONING.jsonl \
  --source-project BASE_PROJECT \
  --literary-project LITERARY_PROJECT \
  --evidence-binding BASE_PROJECT LITERARY_PROJECT EVIDENCE_PROJECT \
  --action create
```

An optional Ledger converts unchanged pages to `noop`, changed pages to `update`, missing remote IDs to review, and absent local pages to reversible `archive_candidate`. Automatic deletion is forbidden.

The earlier `literary export-notion` command remains a compatibility sidecar export. It is not the authoritative Stage 6 multi-project Notion workflow.

## Notion database contract

The workspace uses ten physically separated logical databases:

- Sources;
- Chapters;
- Evidence;
- Facts A;
- Synthesis B;
- Interpretations C;
- Counterfactuals H;
- Events;
- Characters;
- Review Queue.

A/B/C/H records may not share one database. Only Evidence Anchors referenced by published records are projected. Full Evidence Units remain local.

Synchronization is two-phase:

1. create/update pages and resolve stable `page_key` values to remote page IDs;
2. apply relations only after both endpoints resolve.

## Standard Notion Project artifacts

```text
notion-workspace-schema.json
notion-pages.jsonl
notion-relations.jsonl
notion-review-items.jsonl
notion-sync-plan.jsonl
notion.sqlite
notion-project-report.json
artifact-manifest.json
```

Every package verifies source lineage, Manifest membership, content hashes, relation hashes, SQLite integrity, SQLite foreign keys, and full JSONL↔SQLite field equality.

## Refusal rules

Refuse rather than improvise when:

- a source, project, report, Manifest, database, answer packet, or hash fails verification;
- the relevant span is polluted or review-only;
- a requested chapter address is missing or ambiguous;
- an A record lacks exact Evidence;
- a B record lacks independent A support;
- a C record lacks attribution, limitations, support, or alternatives;
- an H record lacks a changed premise, inference rule, uncertainty, or non-canon label;
- an Event, Character, or Reasoning graph is `review_required`;
- a placeholder is asked for unsupported depth;
- no supported causal path exists;
- a Notion relation endpoint is unresolved;
- a remote page ID is reused;
- a remote ID is absent for an existing Ledger page;
- a deletion or archive is requested without explicit authorization.

A refusal is a correct result.

## Safety boundaries

1. Preserve original bytes and SHA-256 identity.
2. Never mutate source text in place.
3. Never use replacement decoding.
4. Never silently repair chapter numbers, titles, order, or gaps.
5. Keep physical order and canonical candidate order separate.
6. Never accept mismatched offsets, text, or hashes.
7. Never invent events, causes, identities, relationships, abilities, arcs, or interpretations.
8. Never promote mention frequency into importance.
9. Never mix A/B/C/H layers.
10. Never count duplicate Evidence lineage as independent support.
11. Never present H as canon.
12. Never automatically delete remote Notion pages.
13. Stop on any verification failure.
14. Never claim all v6 capabilities exceed 9.0 before Stage 7–8 private blind acceptance.
15. Never claim v6 release or freeze from an engineering-stage check.
