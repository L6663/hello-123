# Stage 3 — Event Causality Engine

## Status

Development version: `6.0.0-alpha1`

Integration base: `develop/v6-literary-engine`

Development branch: `feature/v6-stage3-event-causality-engine`

Stage 3 is one complete major engineering stage. Internal tasks are implementation checkpoints only; they are not separate releases, scores, or acceptance events.

## Objective

Transform reviewed major literary events into an auditable, temporal, evidence-bound causality graph that can answer:

- why a major event occurred;
- what happened during it;
- what its immediate result was;
- what long-term consequences it produced;
- which earlier event enabled, triggered, escalated, revealed, prevented, or resolved it;
- where a foreshadowing clue appeared and where it was recovered;
- which parts are explicit source facts, cross-evidence synthesis, or model interpretation;
- when evidence is insufficient and the system must refuse.

The engine does not generate a node for every scene or minor action.

## Event significance policy

An event may enter the canonical Event Project only when it materially affects at least one of:

1. the main plot direction;
2. a core character's identity, goal, relationship, survival, or irreversible choice;
3. control, legitimacy, alliance, collapse, or strategy of a major faction;
4. world-state, major location, key artifact, or central power balance;
5. a later major event through a supported causal dependency.

Low-impact scenes remain chapter passages or review candidates. They do not receive heavy canonical modeling.

## Major-stage scope

### 3.1 Canonical event model

Each event binds:

- event ID, canonical name, type, significance level, and review status;
- start/end canonical chapter IDs and physical/canonical positions;
- participating core or important entities;
- place entities when material;
- exact Evidence anchors;
- A/B/C assertions for cause, process, outcome, consequence, foreshadowing, and recovery;
- limitations and unresolved conflicts.

### 3.2 Causal edge model

Supported event-to-event relations:

- `triggers` — directly initiates the target;
- `enables` — creates a necessary or materially enabling condition;
- `escalates` — raises conflict, stakes, or scale;
- `prevents` — blocks or aborts the target outcome;
- `reveals` — makes hidden information or identity causally available;
- `undermines` — weakens authority, legitimacy, alliance, plan, or capability;
- `resolves` — closes the target conflict or dependency;
- `foreshadows` — introduces a supported clue later recovered;
- `recovers` — explicitly pays off a prior foreshadowing event or clue.

Every edge carries an epistemic tier, supporting assertions/evidence, temporal direction, confidence, limitations, and status.

### 3.3 Temporal and causal validation

- direct causal edges cannot silently point from a later event to an earlier event;
- `foreshadows` must point forward;
- `recovers` must point backward to a prior clue/event while storing the semantic direction explicitly;
- causal cycles are retained as review findings, not silently broken;
- unsupported links cannot enter the active graph;
- C-grade interpretations cannot render as A-grade causes.

### 3.4 Event chain queries

Required queries:

- event profile;
- why event X happened;
- how event X unfolded;
- immediate and long-term consequences;
- all upstream causes within a bounded depth;
- all downstream consequences within a bounded depth;
- shortest supported causal path between two events;
- foreshadowing and recovery pairs;
- refusal when no supported path exists.

### 3.5 Deterministic Event Project

The Stage 3 package contains:

```text
events.jsonl
event-components.jsonl
event-causal-edges.jsonl
event-findings.jsonl
event.sqlite
event-project-report.json
artifact-manifest.json
```

JSONL, SQLite, report counts, hashes, and identifier sets must agree exactly.

### 3.6 Downstream use

The Event Project will feed:

- focused character arcs;
- layered reasoning answers;
- Notion event timelines;
- literary benchmark questions.

It does not expand minor-character modeling or replace Chapter/Evidence verification.

## Concise workflow policy

Only one Stage 3 workflow will run:

- one Python 3.12 job;
- pull requests into `develop/v6-literary-engine` and manual dispatch only;
- obsolete concurrent runs cancelled;
- no routine artifact upload;
- no release, final acceptance, or freeze workflow.

## Merge gates

Stage 3 may merge only when:

1. every active event is chapter- and evidence-bound;
2. every active causal edge has support and valid endpoint events;
3. A/B/C tiers remain non-leaking;
4. temporal direction is valid or explicitly review-only;
5. cycles, contradictions, unsupported links, and ambiguous event identity are explicit findings;
6. JSONL and SQLite identifier sets match;
7. report counts and hashes recompute;
8. repeated builds are deterministic;
9. query paths cite their supporting event edges and evidence;
10. unsupported causal questions refuse;
11. focused, adversarial, tamper, CLI, and full repository regression pass;
12. no workflow or report claims final acceptance, release, or freeze authority.

## Boundary

Stage 3 provides event causality engineering evidence only. Private-corpus final evaluation, final scores, release candidate creation, and repository freeze remain deferred.
