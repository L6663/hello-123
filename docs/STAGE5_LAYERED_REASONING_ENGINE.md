# Stage 5 — Layered Reasoning Engine

## Objective

Convert verified Stage 1–4 knowledge into answerable reasoning graphs without allowing synthesis, interpretation, or counterfactual inference to masquerade as source fact.

Stage 5 is one major engineering stage. Its internal tasks are implementation slices, not separate releases or acceptance events.

## Upstream authority

The engine may consume only verified inputs:

- Chapter Project for immutable physical position and reviewable canonical addresses;
- Literary sidecars for assertions and exact evidence anchors;
- Evidence Project for Claim→Evidence support and coverage;
- Event Project for reviewed event components and causal edges;
- Character Project for scoped character attributes, states, relationships, events, and arcs;
- reviewed reasoning annotation JSONL for explicit B/C/counterfactual conclusions.

It cannot create source facts from model memory or raw semantic similarity.

## Epistemic layers

### A — source fact

A reasoning item must resolve to one or more active upstream A-grade records with exact source evidence. It may restate those records conservatively but cannot add unstated causality, intention, symbolism, morality, or authorial purpose.

### B — cross-evidence synthesis

A B item must have at least two independent A support branches. Independence is measured by support lineage, evidence anchors, and source/chapter location; duplicate restatements of one fact do not count as two supports.

B items must be labeled synthesis and preserve limitations, conflicts, and temporal scope.

### C — literary interpretation

A C item must:

- identify itself as model interpretation or one plausible reading;
- cite active A or B support;
- include at least one limitation or competing reading;
- never be rendered in the fact section;
- never claim definite authorial intent without explicit A-grade evidence.

### H — hypothetical / counterfactual

Counterfactual reasoning is a separate layer, not a factual tier. Every H item must record:

- the changed premise;
- verified facts retained from the source world;
- the inference rule or causal path used;
- uncertainty and alternative outcomes;
- a statement that the result is not original plot.

## Query modes

- `fact_only` — may return A items only;
- `fact_and_synthesis` — may return A and B;
- `analysis` — may return A, B, and C in separate sections;
- `counterfactual` — may return A premises plus H inferences, never as canon;
- `provenance` — returns support graph and evidence locations without prose promotion.

The requested mode is a ceiling, not permission to invent missing higher-layer content.

## Reasoning graph

Every reasoning node records:

- stable ID and epistemic layer;
- statement and normalized question intents;
- temporal and entity/event scope;
- upstream support references;
- exact evidence-anchor lineage;
- support independence group;
- confidence, attribution, limitations, and alternatives;
- active, contested, superseded, or review status.

Edges include:

- `direct_support`;
- `independent_support`;
- `derived_from`;
- `contradicts`;
- `context`;
- `alternative_reading`;
- `counterfactual_premise`;
- `counterfactual_inference`.

## Answer packet

A deterministic answer packet separates:

1. source facts;
2. supported synthesis;
3. model interpretation;
4. counterfactual inference;
5. conflicts and limitations;
6. exact provenance;
7. refusal reasons.

No renderer may collapse these sections into one undifferentiated narrative.

## Refusal rules

Refuse or partially refuse when:

- an upstream project fails verification;
- a requested address or entity is ambiguous;
- the relevant source span is polluted or review-only;
- A support lacks exact evidence;
- B support is not independently sufficient;
- C support or limitations are missing;
- a counterfactual premise or inference path is unstated;
- active high-severity conflicts invalidate a unique conclusion;
- the requested mode forbids the available layer;
- no supported answer path exists.

Partial refusal must state which subquestion is unsupported while preserving supported sections.

## Scope policy

Stage 5 reasons over the focused knowledge graph. It does not expand minor characters merely to answer broad list questions. Placeholder and mention-only entities retain Stage 4 depth restrictions.

## Engineering outputs

Planned runtime modules:

- `tkr/reasoning_engine.py`;
- `tkr/reasoning_project.py`;
- `tkr/reasoning_cli.py`.

Planned artifacts:

- `reasoning-nodes.jsonl`;
- `reasoning-edges.jsonl`;
- `reasoning-findings.jsonl`;
- `reasoning.sqlite`;
- `reasoning-project-report.json`;
- `artifact-manifest.json`.

Planned query outputs:

- `reasoning-answer-packet.json`;
- optional fact/synthesis/interpretation/counterfactual renderings;
- exact support and evidence lineage.

## Mandatory integration gates

Stage 5 cannot merge until:

1. every presented A item resolves to exact clean evidence;
2. every B item has at least two independent active A branches;
3. every C item has active support, attribution, limitations, and separate rendering;
4. every H item identifies changed premise, inference path, uncertainty, and non-canon status;
5. conflicts and alternatives remain visible;
6. unsupported or mode-forbidden layers refuse;
7. answer packets preserve section separation;
8. support and evidence lineage recompute exactly;
9. JSONL and SQLite identifiers agree;
10. repeated builds are deterministic;
11. focused, adversarial, tamper, query, CLI, and full repository regression pass;
12. final exact-head concise CI passes.

## Workflow policy

- one Stage 5 workflow;
- one Python 3.12 job;
- pull request and manual triggers only;
- obsolete runs cancelled;
- no routine artifact upload;
- no release, final acceptance, or freeze automation.

## Authority boundary

Stage 5 engineering validation does not prove that all final capability domains exceed 9.0. Private-corpus blind evaluation remains Stage 7–8 work.
