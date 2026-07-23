---
name: text-knowledge-reader
description: Build auditable long-text literary knowledge systems with strict source identity, contamination isolation, exact Evidence, chapter catalogs, causal events, focused characters, A/B/C/H layered reasoning, reversible Notion projection, literary regression benchmarking, and explicit final product acceptance.
---

# Text Knowledge Reader

**Product version:** 6.0.0rc1  
**Historical stable release:** 5.9.0 at `archive/v5.9.0-final`  
**Integrated v6 engineering stages:** Stage 1–7  
**Current engineering stage:** Stage 8 Final Productization and Acceptance  
**Authority:** no private-corpus acceptance, public release, or freeze without separate explicit approval

## Purpose

Convert one or more long-text works into a source-bound, reviewable literary knowledge system without silently repairing, deleting, renumbering, reordering, merging, or inventing source content.

The v6 product chain is:

1. strict Base Source Project;
2. exact Evidence Project;
3. canonical Chapter Project;
4. material Event Project;
5. focused Character Project;
6. A/B/C/H Reasoning Project;
7. reversible Notion Project;
8. twelve-domain Literary Regression Benchmark;
9. hash-bound Stage 8 technical candidate and explicit acceptance Seal.

No layer bypasses verification of its inputs.

## Inputs

Supported authoritative inputs include:

- one or more uploaded `.txt` or `.md` source files in explicit physical order;
- verified Base Source, Literary, Evidence, Chapter, Event, Character, Reasoning, and Notion Projects;
- reviewed Literary, Event, Character, and Reasoning annotation JSONL;
- Stage 7 Gold cases and already-produced answer observations;
- a private blind protocol attestation;
- package acceptance, reproducible-build, engineering-validation, and source-provenance artifacts;
- an explicit final product approval record created outside the CLI.

Supported strict encodings are UTF-8, UTF-8 with BOM, UTF-16 LE with BOM, and UTF-16 BE with BOM. Never decode with replacement characters and never modify original source files in place.

## Epistemic contract

### A — explicit source fact

A records require exact clean evidence bound to source, Unit, chapter, original offsets, text, hashes, and contamination state.

### B — cross-evidence synthesis

B records require at least two independent A-support branches. Repetition from one Evidence lineage is not independent support.

### C — model interpretation

C records must be labeled as interpretation and include support, attribution, limitations, and alternatives. C never becomes source fact.

### H — hypothetical or counterfactual

H records are non-canon. They identify the changed premise, retained facts, inference rule, uncertainty, and alternatives.

Never silently promote H→C, C→B, or B→A.

## Entity policy

- `core` — deep evidence-bound model;
- `important` — role, major relations, states, and major-event model;
- `placeholder` — minimal identity, location, and necessary participation only;
- mention-only — remains searchable but does not automatically become a canonical entity.

Mention frequency alone cannot promote a person. Low-impact people must not dilute mainline knowledge.

## Workflow

Treat the directory containing this file as `SKILL_DIR`. Run each build and verification step in order. Stop immediately when a verification fails.

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

### 2. Build Literary and Evidence Projects

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

Annotations receive no automatic authority.

### 3. Build and verify the Chapter Project

Argument order is immutable physical source order.

```bash
python "${SKILL_DIR}/scripts/tkr.py" chapter build \
  PROJECT_A PROJECT_B --outdir CHAPTER_PROJECT

python "${SKILL_DIR}/scripts/tkr.py" chapter verify CHAPTER_PROJECT \
  --source-project PROJECT_A \
  --source-project PROJECT_B
```

Physical order is source authority. Canonical order is a separate reviewable candidate.

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
  CHARACTER_PROJECT CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl \
  CHARACTERS.jsonl \
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

Query ceilings are `fact_only`, `fact_and_synthesis`, `analysis`, `counterfactual`, and `provenance`. A `review_required` graph refuses outside provenance mode.

### 7. Build and verify the Notion Project

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
```

The sync plan uses create, update, noop, review, and reversible archive-candidate states. Automatic deletion is forbidden.

### 8. Run the Literary Regression Benchmark

```bash
tkr-literary-benchmark evaluate \
  LITERARY_CASES.jsonl \
  LITERARY_OBSERVATIONS.jsonl \
  --profile release \
  --output LITERARY_REPORT.json

tkr-literary-benchmark verify \
  LITERARY_CASES.jsonl \
  LITERARY_OBSERVATIONS.jsonl \
  LITERARY_REPORT.json \
  --output LITERARY_VERIFICATION.json
```

The release profile requires at least 120 cases, at least eight cases in each of twelve domains, at least 24 refusal cases, approved/adjudicated Gold, two independent reviewers per case, and a minimum score of 9.0 in every domain, correctness score, and safety score.

Wrong answers, overanswers, citation mismatches, malformed packets, epistemic leakage, measurable hallucinations, and unauthorized authority flags are hard blockers.

### 9. Prepare the Stage 8 technical candidate

```bash
python "${SKILL_DIR}/scripts/tkr.py" acceptance prepare \
  --root ACCEPTANCE_ROOT \
  --version 6.0.0rc1 \
  --source-commit SOURCE_COMMIT \
  --source-date-epoch SOURCE_DATE_EPOCH \
  --artifact ROLE=PATH \
  --output final-acceptance-candidate.json
```

Required artifact roles are documented in `docs/STAGE8_FINAL_PRODUCTIZATION_ACCEPTANCE.md`.

The candidate must keep:

```yaml
project_acceptance_performed: false
may_accept_project: false
release_candidate: false
may_release: false
may_freeze: false
```

### 10. Verify the candidate

```bash
python "${SKILL_DIR}/scripts/tkr.py" acceptance verify \
  final-acceptance-candidate.json \
  --root ACCEPTANCE_ROOT
```

Verification recomputes Stage 7, private blind bindings, package matrix, reproducible Wheels, source provenance, CI evidence, documentation hashes, and every artifact identity.

### 11. Seal only after explicit approval

The CLI never generates an approval record. A separate approval must name the exact candidate ID and contain this statement:

```text
I explicitly approve final product acceptance for final_acceptance_candidate_<24 hex>.
```

Then:

```bash
python "${SKILL_DIR}/scripts/tkr.py" acceptance seal \
  final-acceptance-candidate.json \
  final-acceptance-approval.json \
  --root ACCEPTANCE_ROOT \
  --output final-acceptance-seal.json
```

A valid Seal grants project acceptance and Release Candidate eligibility only. It does not authorize publication or freeze.

## Notion database contract

The Notion workspace uses ten physically separated logical databases:

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

## Private blind contract

The private blind attestation must bind the exact corpus, Gold, observations, and report hashes. It must declare:

- Gold locked before the run;
- Gold hidden from the answer system;
- observations generated without Gold access;
- private corpus not used in v6 development;
- distinct evaluator and Gold custodian;
- at least two additional independent reviewers.

Stage 8 verifies the declared structure and identities. It cannot prove an external human statement was truthful, so the attestation remains visible review evidence.

## Standard artifacts

A complete v6 chain retains all earlier source, chapter, evidence, event, character, reasoning, Notion, report, database, Manifest, and verification artifacts.

Stage 8 additionally uses:

```text
private-blind-attestation.json
package-3.10.json
package-3.11.json
package-3.12.json
engineering-validation.json
reproducible-build.json
final-acceptance-candidate.json
final-acceptance-approval.json
final-acceptance-seal.json
```

The approval and Seal do not exist until the explicit acceptance step occurs.

## Commands

Installed v6 commands include:

```text
tkr-skill
tkr-project
tkr-literary
tkr-evidence
tkr-chapter
tkr-event
tkr-character
tkr-reason
tkr-notion
tkr-literary-benchmark
tkr-final-acceptance
```

The directly uploadable entry point is:

```bash
python "${SKILL_DIR}/scripts/tkr.py" --help
```

## Refusal rules

Refuse rather than improvise when:

- a source, project, report, Manifest, database, packet, candidate, Seal, or hash fails verification;
- the relevant span is polluted or review-only;
- a chapter address is missing or ambiguous;
- an A record lacks exact Evidence;
- a B record lacks independent A support;
- a C record lacks attribution, support, limitations, or alternatives;
- an H record lacks a changed premise, rule, uncertainty, or non-canon label;
- an Event, Character, or Reasoning graph is `review_required`;
- a placeholder is asked for unsupported depth;
- no supported causal path exists;
- a Notion relation endpoint is unresolved;
- a remote page ID is reused;
- a private blind protocol flag is absent or false;
- benchmark, package, reproducibility, source-provenance, or engineering evidence disagrees;
- approval does not name the exact candidate;
- release or freeze is requested without a separate explicit decision.

A refusal is a correct result.

## Safety boundaries

1. Preserve original bytes and SHA-256 identity.
2. Never mutate source text in place.
3. Never use replacement decoding.
4. Never silently repair chapter numbers, titles, order, or gaps.
5. Keep physical order and canonical candidate order separate.
6. Keep contaminated and clean Evidence separate.
7. Keep A/B/C/H epistemic layers separate.
8. Never use one Evidence lineage as multiple independent supports.
9. Never let a benchmark, model, CI run, or candidate self-grant acceptance.
10. Never let project acceptance self-grant public release or freeze.
11. Never fabricate a private blind or explicit approval record.
12. Preserve the historical v5.9.0 release unchanged.

## Acceptance boundary

Stage 8 engineering completion means the release-candidate package, public Schemas, commands, audits, CI matrix, reproducible-build checks, and acceptance mechanism have passed engineering validation.

It is not real private-corpus acceptance.

Before actual private blind artifacts and explicit approval exist, all authoritative status remains:

```yaml
private_blind_acceptance_performed: false
project_acceptance_performed: false
may_accept_project: false
release_candidate: false
may_release: false
may_freeze: false
```

After a valid explicit acceptance Seal:

```yaml
project_acceptance_performed: true
may_accept_project: true
release_candidate: true
may_release: false
may_freeze: false
```

Publication and repository freeze always require a later separate explicit decision.
