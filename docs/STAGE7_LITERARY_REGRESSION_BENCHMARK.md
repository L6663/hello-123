# Stage 7 — Literary Regression Benchmark

## Objective

Stage 7 converts the v6 literary engine from a set of independently tested subsystems into a measurable literary-knowledge product. It evaluates completed A/B/C/H answer packets against immutable, independently reviewed Gold cases. The evaluator does not generate answers, infer missing Gold labels, or grade model prose with another model.

This is one major engineering stage. Internal implementation slices are checkpoints only; they are not releases, final acceptance events, or freeze authority.

## Why the legacy Gold benchmark is insufficient

The v5 strict-QA benchmark measures six typed predicates and hard refusals. Those gates remain valuable for exact facts, but they cannot establish literary reliability for:

- motives that require multiple pieces of evidence;
- foreshadowing and later resolution;
- chapter-bounded relationship change;
- multi-step event causality and consequences;
- cold details, minor characters, and exact dialogue;
- theme or symbolism that must be labeled interpretation;
- counterfactual answers that must remain explicitly non-canon.

Stage 7 therefore introduces a separate benchmark contract rather than weakening or rebranding the old typed-fact Gold.

## Twelve non-compensating domains

Every release-profile domain must independently satisfy its minimum score, correctness score, and safety score:

1. `chapter_traceability` — correct chapter/volume address and source location;
2. `evidence_traceability` — exact evidence-anchor lineage;
3. `entity_identity` — entity resolution, aliasing, and same-name separation;
4. `temporal_relationships` — relationship state at a specified chapter/time;
5. `event_causality` — cause, process, outcome, and consequence chains;
6. `cold_detail_recall` — low-frequency details and minor-character facts;
7. `dialogue_recall` — exact or source-bounded dialogue retrieval;
8. `motive_reasoning` — evidence-backed motive synthesis without fact promotion;
9. `foreshadowing_resolution` — supported setup/payoff linkage;
10. `theme_interpretation` — attributed C-layer interpretation with alternatives;
11. `epistemic_separation` — A/B/C/H section and mode discipline;
12. `refusal_safety` — unsupported, ambiguous, polluted, or forbidden requests refuse.

A high score in one domain cannot compensate for another domain below threshold.

## Inputs

### Gold cases

`literary-benchmark-cases.jsonl` contains one `tkr-literary-benchmark-case-v1` object per line. Each case binds:

- stable case ID, domain, question, and permitted query mode;
- expected decision and expected epistemic layers;
- exact expected reasoning node IDs;
- required evidence-anchor IDs;
- forbidden node IDs and required refusal reasons;
- source SHA-256 identities;
- annotation status, annotator, independent reviewers, and rationale.

Release Gold must contain at least 120 cases, at least eight per domain, at least 24 refusal cases, approved/adjudicated annotations, and two independent reviewers per case.

### Observations

`literary-benchmark-observations.jsonl` contains one already-produced answer packet per Gold case. The benchmark never invokes an answer model and never accepts a scalar self-score. Observations must retain the A/B/C/H sections, provenance, query mode, decision, refusal reasons, and false authority flags.

## Metrics and blockers

Each domain reports:

- exact case pass rate;
- decision accuracy;
- node precision and recall;
- citation/evidence-anchor entailment rate;
- epistemic layer separation rate;
- correctness score;
- safety score;
- final domain score, defined as the lower of correctness and safety.

The following are hard blockers:

- insufficient total, per-domain, refusal, annotation, or reviewer coverage;
- any domain, correctness, or safety score below 9.0;
- wrong answers or overanswers;
- citation mismatches;
- A/B/C/H layer leakage;
- measurable hallucinations;
- benchmark packets claiming project-acceptance, release, or freeze authority.

## Profiles

### `smoke`

Engineering-only profile for deterministic tests:

- 12 cases;
- at least one case per domain;
- at least two refusal cases;
- no reviewer or approval requirement;
- every domain still must score at least 9.0.

### `release`

Final Stage 7 benchmark policy:

- at least 120 cases;
- at least eight cases per domain;
- at least 24 refusal cases;
- approved/adjudicated annotations only;
- at least two independent reviewers per case;
- every domain, correctness score, and safety score at least 9.0;
- zero wrong answers, overanswers, citation mismatches, layer leakage, measurable hallucinations, and authority escalation.

Passing this engineering benchmark alone does not perform final private-corpus acceptance. Stage 8 remains responsible for integrated private blind evaluation and explicit user-controlled release decisions.

## CLI

```bash
tkr-literary-benchmark evaluate \
  literary-benchmark-cases.jsonl \
  literary-benchmark-observations.jsonl \
  --profile smoke \
  --output literary-benchmark-report.json

tkr-literary-benchmark verify \
  literary-benchmark-cases.jsonl \
  literary-benchmark-observations.jsonl \
  literary-benchmark-report.json
```

Bundled Skill entry point:

```bash
python scripts/tkr.py benchmark evaluate CASES OBSERVATIONS --profile smoke --output REPORT
python scripts/tkr.py benchmark verify CASES OBSERVATIONS REPORT
```

## Determinism and verification

The report binds both byte SHA-256 and canonical logical SHA-256 for Gold cases and observations. Verification recomputes every field and rejects any mismatch, including a changed score, blocker, case result, authority flag, or report ID.

## Authority boundary

Stage 7 reports always set:

```yaml
project_acceptance_performed: false
may_accept_project: false
may_release: false
may_freeze: false
```

No benchmark command creates a Release Candidate, authorizes publication, mutates the frozen v5.9.0 release, writes to Notion, or freezes the repository.
