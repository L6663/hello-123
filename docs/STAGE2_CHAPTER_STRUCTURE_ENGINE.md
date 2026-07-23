# Stage 2 — Chapter Structure Engine

## Status

Development version: `6.0.0-alpha1`

Integration base: `develop/v6-literary-engine`

Development branch: `feature/v6-stage2-chapter-structure-engine`

Stage 2 is one complete major engineering stage. Internal tasks are implementation checkpoints only; they are not separate releases, scores, or acceptance events.

## Objective

Convert one or more already verified Text Knowledge Reader source projects into one deterministic, source-bound chapter catalog that can answer:

- which file, volume, chapter, and exact source span a chapter belongs to;
- whether the chapter number comes from an explicit parent volume, a combined heading, or remains unresolved;
- which chapters are duplicated, inverted, missing, unnumbered, titleless, empty, contaminated, or structurally ambiguous;
- what the physical file order is and what canonical order is suggested by explicit numbering;
- where one file ends and the next file plausibly continues;
- which corrections are source facts and which are review-only mappings.

The engine never rewrites, renumbers, deletes, splices, or repairs the original corpus.

## Major-stage scope

### 2.1 Canonical chapter model

Each chapter record binds:

- source project ID, source ID, source filename, and source SHA-256;
- source input order, local physical order, and global physical order;
- Unit ID, parent Unit ID, and heading ID;
- original heading and normalized display heading;
- volume ordinal and its derivation basis;
- chapter ordinal and its derivation basis;
- heading, title, body, and full Unit character spans;
- Unit content SHA-256;
- structure confidence and review status;
- contamination state;
- deterministic canonical key and chapter ID.

### 2.2 Parent-volume recovery

Volume ordinals are recovered in this priority order:

1. explicit combined volume/chapter heading signal;
2. explicit parent volume Unit;
3. nearest preceding accepted volume Unit within the same source;
4. unresolved.

A carried or inferred value is never presented as an original heading field.

### 2.3 Cross-file order map

For multiple input projects the engine records both:

- immutable user/input order;
- numbering-derived canonical-order candidate.

If numbering overlaps, is absent, or conflicts, the engine preserves input order and emits an ambiguity finding rather than silently rearranging files.

### 2.4 Structural findings

Required finding classes:

- duplicate canonical chapter key;
- duplicate chapter content;
- ordinal gap;
- ordinal inversion;
- conflicting titles for one canonical key;
- missing volume ordinal;
- missing chapter ordinal;
- missing or detached title;
- empty chapter body;
- chapter after terminal unit;
- source-order ambiguity;
- contaminated or review-only chapter span.

### 2.5 Deterministic chapter project

The Stage 2 package contains:

```text
source-bindings.jsonl
chapters.jsonl
canonical-order.jsonl
chapter-findings.jsonl
chapter.sqlite
chapter-project-report.json
artifact-manifest.json
```

JSONL, SQLite, report counts, hashes, and identifier sets must agree exactly.

### 2.6 Query and downstream integration

Stage 2 will expose deterministic queries for:

- chapter by volume/chapter number;
- first/last chapter of a file or volume;
- physical neighbors;
- canonical neighbors;
- all duplicate/gap/inversion findings;
- exact original heading and source location.

The literary and Evidence layers may consume the verified Stage 2 catalog in later integration, but Stage 2 does not grant facts or literary interpretations authority.

## Entity policy

Stage 2 is chapter-centered. It does not expand minor-character modeling. Character, event, ability, and place mentions remain downstream concerns.

## Concise workflow policy

Only one Stage 2 workflow will run:

- one Python 3.12 job;
- pull requests into `develop/v6-literary-engine` and manual dispatch only;
- obsolete concurrent runs cancelled;
- no routine artifact upload;
- no release, acceptance, or freeze workflow.

## Merge gates

Stage 2 may merge only when all of the following pass:

1. every chapter span and content hash recomputes from its source;
2. every explicit parent-volume mapping is referentially valid;
3. no canonical-order candidate mutates physical order records;
4. duplicate, gap, inversion, unknown-ordinal, and contamination cases are represented explicitly;
5. JSONL and SQLite identifier sets match;
6. report counts and logical hashes recompute;
7. repeated builds are logically identical;
8. focused, tamper, adversarial, CLI, and full repository regression pass;
9. no workflow or report claims final acceptance, release, or freeze authority.

## Boundary

Stage 2 provides chapter structure and ordering evidence. It does not perform final literary evaluation, assign final capability scores, create a release candidate, or freeze the repository.
