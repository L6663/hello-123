# Text Knowledge Reader

Text Knowledge Reader is an auditable long-text literary knowledge system. It preserves source identity, isolates contamination, indexes exact Evidence, models chapter structure, events and focused characters, separates A/B/C/H epistemic layers, projects verified knowledge into Notion, and refuses when support is insufficient.

## Current status

```yaml
v6_version: 6.0.0rc1
v6_branch: develop/v6-literary-engine
current_stage: Stage 8 Final Productization and Acceptance
integrated_engineering_stages: 1_to_7
stage_8_engineering: active
private_blind_acceptance_performed: false
project_acceptance_performed: false
release_candidate_created: false
may_release: false
may_freeze: false

historical_stable_release: 5.9.0
historical_stable_branch: main
historical_archive_branch: archive/v5.9.0-final
historical_release_mutated: false
```

Version `6.0.0rc1` is a productized release-candidate engineering line. It is not a final public release. The historical v5.9.0 release remains frozen and unchanged.

## v6 processing chain

```text
strict source bytes and SHA-256
→ anomaly, contamination, and paratext isolation
→ deterministic source-covering Units
→ canonical chapter catalog without rewriting physical order
→ exact Evidence Units and Claim→Evidence edges
→ material event and causal-path graph
→ focused character identities, states, relations, and arcs
→ A facts / B synthesis / C interpretation / H counterfactual reasoning
→ reversible Notion workspace package and sync plan
→ twelve-domain literary regression benchmark
→ Stage 8 product candidate and explicit acceptance boundary
```

No layer bypasses verification of its inputs.

## Epistemic layers

### A — source fact

A records require exact clean evidence, source identity, chapter identity, original offsets, text hashes, and contamination state.

### B — cross-evidence synthesis

B records require at least two independent A-support branches. Repeated wording from one lineage does not count as independent support.

### C — interpretation

C records are explicitly attributed interpretations. They retain evidence, limitations, and alternative readings and never become source facts.

### H — hypothetical or counterfactual

H records are explicitly non-canon. They bind the changed premise, retained facts, inference rule, uncertainty, and alternatives.

The system never silently promotes H→C, C→B, or B→A.

## Install

```bash
python -m pip install text_knowledge_reader_core-6.0.0rc1-py3-none-any.whl
```

Check the installed product:

```bash
tkr-skill doctor
tkr-skill audit
tkr-skill profiles
tkr-skill show-profile balanced
```

## Main project commands

```bash
tkr-project build corpus.txt \
  --outdir base-project \
  --state-dir .tkr-state/base-project \
  --profile balanced

tkr-project verify base-project
```

The mutable lock, journal, and cache remain outside immutable project artifacts.

## v6 subsystem commands

```text
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

The directly uploadable Skill entry point is:

```bash
python scripts/tkr.py --help
```

## Stage 1 — Evidence Engine

Builds clean Evidence Units and exact Claim→Evidence edges. Every published assertion must retain source, Unit, chapter, offset, text, hash, and contamination lineage.

## Stage 2 — Chapter Structure Engine

Separates immutable physical source order from a reviewable canonical-order candidate. Missing, duplicated, ambiguous, or conflicting chapter addresses remain visible findings.

## Stage 3 — Event Causality Engine

Models only materially significant events. Cause, process, outcome, consequence, foreshadowing, recovery, and causal paths require explicit support.

## Stage 4 — Focused Character Engine

Uses three depth levels:

- `core` — deep evidence-bound model;
- `important` — role, major relations, states, and major events;
- `placeholder` — minimal identity and necessary participation only.

Mention frequency alone cannot promote a person.

## Stage 5 — Layered Reasoning Engine

Builds deterministic A/B/C/H answer packets with query ceilings:

```text
fact_only
fact_and_synthesis
analysis
counterfactual
provenance
```

A graph marked `review_required` refuses outside provenance-only inspection.

## Stage 6 — Notion Knowledge System

Generates ten physically separated logical databases:

```text
Sources
Chapters
Evidence
Facts A
Synthesis B
Interpretations C
Counterfactuals H
Events
Characters
Review Queue
```

The sync plan is reversible. Missing remote IDs and unresolved relation endpoints enter review. Automatic deletion is forbidden.

## Stage 7 — Literary Regression Benchmark

The release profile evaluates twelve non-compensating domains:

```text
chapter_traceability
evidence_traceability
entity_identity
temporal_relationships
event_causality
cold_detail_recall
dialogue_recall
motive_reasoning
foreshadowing_resolution
theme_interpretation
epistemic_separation
refusal_safety
```

Release policy requires:

- at least 120 Gold cases;
- at least eight cases per domain;
- at least 24 refusal cases;
- approved/adjudicated Gold only;
- two independent reviewers per case;
- every domain, correctness score, and safety score at least 9.0;
- zero wrong answers, overanswers, citation mismatches, malformed packets, layer leakage, measurable hallucinations, or unauthorized authority flags.

Evidence is bound to the exact reasoning node. An anchor attached to the wrong conclusion cannot satisfy a case.

## Stage 8 — Final Productization and Acceptance

Stage 8 binds the complete product as one technical candidate:

- Stage 7 release-profile cases, observations, report, and recomputation;
- private blind protocol attestation;
- Python 3.10, 3.11, and 3.12 package acceptance;
- canonical and reproducibly built Wheels;
- source bundle and source-provenance verification;
- zero-finding Skill audit and passing doctor report;
- exact successful engineering CI commit;
- `README.md`, `SKILL.md`, and `PROJECT_STATUS.yaml` identities.

A technical candidate is not acceptance:

```yaml
technical_gate_passed: true
requires_explicit_approval: true
project_acceptance_performed: false
may_accept_project: false
release_candidate: false
may_release: false
may_freeze: false
```

### Private blind boundary

The private blind attestation must confirm that Gold was locked before the run, hidden from the answer system, and unavailable while observations were produced. The evaluator, Gold custodian, and at least two reviewers must be distinct.

Stage 8 verifies hashes, role separation, declared protocol flags, and report recomputation. It cannot prove that a human attestation is truthful; the attestation remains explicit review evidence.

### Explicit approval boundary

Only a separate approval record that names the exact candidate ID can create a final acceptance Seal. The CLI does not generate this approval.

A valid Seal means:

```yaml
project_acceptance_performed: true
may_accept_project: true
release_candidate: true
may_release: false
may_freeze: false
```

Product acceptance does not authorize publication or repository freeze. Those require a later explicit decision.

## Final acceptance commands

```bash
tkr-final-acceptance prepare --help
tkr-final-acceptance verify --help
tkr-final-acceptance seal --help
tkr-final-acceptance verify-seal --help
```

Bundled aliases:

```bash
python scripts/tkr.py acceptance prepare --help
python scripts/tkr.py acceptance verify --help
python scripts/tkr.py acceptance seal --help
python scripts/tkr.py acceptance verify-seal --help
```

See `docs/STAGE8_FINAL_PRODUCTIZATION_ACCEPTANCE.md` for artifact roles and the exact approval statement.

## Security and integrity

The product rejects:

- symbolic links in source, project, state, cache, package, or acceptance authority paths;
- absolute, parent-traversal, duplicate, or non-normalized artifact paths;
- undeclared, missing, changed, or non-regular files;
- changed source, project, database, evidence, report, citation, Wheel, or Seal identities;
- replacement decoding and unsupported silent recovery;
- contaminated evidence promoted as clean evidence;
- nonassertive propositions promoted as facts;
- unsupported A/B/C/H promotion;
- `review_required` graphs presented as ordinary answers;
- benchmark or candidate files that attempt to grant themselves authority.

No source text is automatically deleted or rewritten.

## Package contents

The v6 Wheel includes:

```text
SKILL.md
README.md
PROJECT_STATUS.yaml
Python runtime modules
75+ public JSON Schemas
3 engineering profiles
executable examples
Stage 1–8 documentation
all installed console entry points
```

## Historical v5 boundary

The v5.9.0 release on `main` remains a valid historical fact-oriented release and is preserved at `archive/v5.9.0-final`. Stage 8 does not mutate, reinterpret, or unfreeze it.

## Current acceptance boundary

The Stage 8 engineering implementation can be merged after CI validates the package, schemas, commands, adversarial regressions, and reproducible-build workflow.

Real final project acceptance still requires actual private blind artifacts and an explicit approval record. Until then:

```yaml
private_blind_acceptance_performed: false
project_acceptance_performed: false
release_candidate: false
may_release: false
may_freeze: false
```
