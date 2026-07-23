# Stage 4 — Focused Character Engine

## Status

Development version: `6.0.0-alpha1`

Integration base: `develop/v6-literary-engine`

Development branch: `feature/v6-stage4-focused-character-engine`

Stage 4 is one complete major engineering stage. Internal tasks are implementation checkpoints only; they are not separate releases, scores, or acceptance events.

## Objective

Build a high-reliability character model centered on the people who materially drive the work, while preventing low-impact names from diluting retrieval and reasoning.

The engine must answer:

- who a core or important character is;
- which identities, aliases, roles, goals, abilities, and states are source facts;
- how a character's relationships and objectives change over time;
- which major events the character causes, participates in, or is transformed by;
- which decisions form a supported character arc;
- which conclusions are A facts, B synthesis, or C interpretation;
- why a minor name was intentionally not deeply modeled;
- when evidence is insufficient and the system must refuse.

## Character scope policy

### Core character

Deep model. A character qualifies only when they materially drive the main plot or repeatedly determine major events.

Allowed records:

- canonical identity and aliases;
- major identity/state transitions;
- stable and changing goals;
- time-bounded important relationships;
- signature abilities and material limitations;
- key choices and their consequences;
- major event participation;
- A/B/C-separated character arc.

### Important character

Moderate model. A character qualifies when they substantially affect a core character, major faction, major event, or world-state change.

Allowed records:

- identity and role;
- material relationships;
- major events and decisions;
- current/last trusted state;
- evidence-bound significance explanation.

### Placeholder

Minimal record only:

- canonical name or unresolved surface;
- first/last trusted chapter;
- one material event or role when applicable;
- review status.

Placeholder records do not receive personality, theme, complete relationships, or speculative arcs.

### Mention only

No canonical character record. The name remains searchable in chapter/evidence indexes.

## Major-stage scope

### 4.1 Reviewed character selection

Canonical deep/moderate characters must be explicitly selected with evidence of material impact. Mention frequency alone cannot promote a character.

Selection reasons:

- main plot driver;
- core-character transformation;
- major-event cause or resolution;
- major-faction authority or collapse;
- world-state or central artifact impact.

### 4.2 Identity and state model

Records include:

- canonical name and aliases;
- identity assertions and conflicts;
- role/faction changes;
- alive, dead, revived, missing, imprisoned, transformed, or unknown states;
- start/end Chapter Project positions;
- exact assertion/evidence support.

### 4.3 Temporal relationship model

Important relationships are intervals, not static labels. Each interval stores:

- character A and B;
- relation type;
- start/end chapter and position;
- change cause components or major events;
- A/B/C tier;
- evidence, confidence, limitations, and status.

### 4.4 Goal, choice, and arc model

Character arcs are separated into:

- A — explicit goals, choices, and state changes;
- B — supported cross-event development pattern;
- C — literary interpretation with limitations.

C-grade growth, symbolism, morality, or authorial meaning cannot enter A/B character properties.

### 4.5 Event integration

Character records bind only to verified Event Project nodes and edges. The engine supports:

- major events participated in;
- events caused or enabled;
- choices and resulting consequences;
- event sequence forming an arc;
- refusal when event graph is review-required.

### 4.6 Deterministic Character Project

The Stage 4 package contains:

```text
characters.jsonl
character-attributes.jsonl
character-states.jsonl
character-relationships.jsonl
character-event-links.jsonl
character-findings.jsonl
character.sqlite
character-project-report.json
artifact-manifest.json
```

JSONL, SQLite, report counts, hashes, and identifier sets must agree exactly.

## Required queries

- character profile;
- identity and alias history;
- state at a chapter;
- relationship with another character at a chapter;
- major events and choices;
- supported arc summary with A/B/C separation;
- why the character is core/important/placeholder;
- refusal for mention-only or unsupported deep analysis.

## Findings

Required findings include:

- unsupported core/important promotion;
- alias collision or unresolved identity merge;
- overlapping contradictory states;
- relationship interval overlap/conflict;
- event link to unknown or review-required event;
- B conclusion without independent A support;
- C interpretation presented as fact;
- placeholder receiving deep-model fields;
- missing evidence or chapter binding.

## Concise workflow policy

Only one Stage 4 workflow will run:

- one Python 3.12 job;
- pull requests into `develop/v6-literary-engine` and manual dispatch only;
- obsolete concurrent runs cancelled;
- no routine artifact upload;
- no release, final acceptance, or freeze workflow.

## Merge gates

Stage 4 may merge only when:

1. every core/important selection has material-impact support;
2. placeholders cannot receive deep-model records;
3. identity, state, relationship, and event links are chapter/evidence-bound;
4. temporal state and relationship conflicts are explicit;
5. A/B/C character-arc layers do not leak;
6. review-required Event Projects cannot support active arc conclusions;
7. JSONL and SQLite identifier sets match;
8. report counts and hashes recompute;
9. repeated builds are deterministic;
10. unsupported character-depth questions refuse;
11. focused, adversarial, tamper, CLI, and full repository regression pass;
12. no workflow or report claims final acceptance, release, or freeze authority.

## Boundary

Stage 4 provides focused character engineering evidence only. Private-corpus final evaluation, final scores, release candidate creation, and repository freeze remain deferred.
