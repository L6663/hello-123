# Stage 6 — Notion Knowledge System

## Objective

Project the verified Stage 1–5 knowledge graph into a deterministic, incrementally synchronizable Notion workspace without allowing page duplication, relation loss, epistemic-layer leakage, silent deletion, or loss of source provenance.

Stage 6 is one major engineering stage. Its internal tasks are implementation slices, not separate releases or acceptance events.

## Upstream authority

The system may consume only verified:

- Chapter Projects;
- Literary sidecars and Evidence Anchors;
- Evidence Projects;
- Event Projects;
- Character Projects;
- Reasoning Projects.

A review-required Event, Character, or Reasoning graph cannot be published as accepted knowledge. It may be represented only in the Review Queue.

## Workspace databases

The target workspace uses physically separated logical databases:

1. `Sources` — source identity, hashes, encoding, and project lineage;
2. `Chapters` — immutable physical order, canonical-order candidate, headings, offsets, hashes, and contamination state;
3. `Evidence` — only exact Evidence Anchors referenced by published knowledge records;
4. `Facts A` — explicit source facts only;
5. `Synthesis B` — independently supported cross-evidence synthesis only;
6. `Interpretations C` — explicitly attributed model interpretations only;
7. `Counterfactuals H` — explicitly non-canon hypothetical reasoning only;
8. `Events` — materially significant events and causal structure;
9. `Characters` — scoped core, important, and minimal placeholder characters;
10. `Review Queue` — conflicts, contamination, blocking findings, missing relations, and sync discrepancies.

A single database may not mix A/B/C/H records. The database key is an enforced contract, not a presentation preference.

## Stable identity

Every projected page records:

- stable `page_key` derived from database key and upstream record ID;
- upstream record ID and type;
- content SHA-256;
- source-project lineage hashes;
- review and publication status;
- optional Notion page ID from a sync ledger.

Titles may change without changing `page_key`. Renames update pages; they do not create replacements.

## Relation model

Relations are emitted as independent deterministic intents whose endpoints are stable page keys. Required relation classes include:

- chapter → source;
- evidence → chapter;
- fact → evidence;
- B/C/H → support or premise nodes;
- event → start/end chapter;
- event → participating characters;
- character → first/last chapter;
- character → major events;
- reasoning → chapters, events, characters, and Evidence lineage;
- Review Queue item → affected page keys.

Relation application uses two phases:

1. create or update all pages and resolve stable page keys to Notion page IDs;
2. apply relations only after every endpoint is resolved.

Unresolved endpoints never produce partial relations silently.

## Incremental synchronization

An optional sync ledger maps:

- `page_key` → Notion page ID;
- last synchronized content hash;
- last synchronized relation hash;
- archive state;
- last successful package logical hash.

The deterministic sync plan classifies each page and relation as:

- `create`;
- `update`;
- `noop`;
- `review_missing_remote_id`;
- `archive_candidate`.

Missing local pages are not deleted automatically. Archiving requires explicit authorization and remains reversible.

## Rendering contract

Every page body and property set preserves epistemic boundaries:

- A pages say they are source facts and include exact Evidence;
- B pages say they are synthesis and list independent A supports;
- C pages say they are model interpretation and include limitations and alternative readings;
- H pages say they are non-canon and include changed premise, inference rule, uncertainty, and alternatives;
- Event and Character pages link to A/B/C/H pages rather than copying all conclusions into one untyped prose block;
- placeholder characters receive only minimal properties and necessary relations.

## Review Queue

The Review Queue includes:

- polluted or review-only source spans;
- chapter gaps, duplicates, inversions, and ambiguous order;
- Event, Character, or Reasoning blocking findings;
- unresolved relation endpoints;
- duplicate stable keys;
- sync-ledger conflicts;
- remote page ID reuse;
- archive candidates;
- content or relation hash drift.

Review items never become accepted Facts pages.

## Engineering outputs

Planned runtime modules:

- `tkr/notion_engine.py`;
- `tkr/notion_project.py`;
- `tkr/notion_cli.py`.

Planned artifacts:

- `notion-workspace-schema.json`;
- `notion-pages.jsonl`;
- `notion-relations.jsonl`;
- `notion-review-items.jsonl`;
- `notion-sync-plan.jsonl`;
- `notion.sqlite`;
- `notion-project-report.json`;
- `artifact-manifest.json`.

The package does not itself assume unrestricted Notion API authority. An external connector may execute the verified sync plan and return a new ledger.

## Mandatory integration gates

Stage 6 cannot merge until:

1. every page key is deterministic and unique;
2. A/B/C/H pages are physically isolated by database key;
3. every A page links exact Evidence Anchors;
4. every B page links independently supported A pages;
5. every C/H page retains all required disclosures;
6. all relation endpoints resolve or become Review Queue items;
7. two builds over identical inputs are byte deterministic;
8. a prior ledger yields idempotent `noop` plans for unchanged pages;
9. title changes produce `update`, not duplicate `create`;
10. missing pages produce archive candidates, never automatic deletion;
11. remote page ID reuse is blocked;
12. JSONL and SQLite identifiers agree;
13. report, content, relation, and logical hashes recompute exactly;
14. focused, adversarial, tamper, incremental, CLI, and full repository regression pass;
15. final exact-head concise CI passes.

## Workflow policy

- one Stage 6 workflow;
- one Python 3.12 job;
- pull request and manual triggers only;
- obsolete runs cancelled;
- no routine artifact upload;
- no release, final acceptance, or freeze automation.

## Authority boundary

Stage 6 validates deterministic Notion projection and synchronization planning. It does not itself prove final private-corpus knowledge quality, execute irreversible remote deletion, assign final capability scores, or authorize release/freeze.
