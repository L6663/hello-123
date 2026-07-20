# Text Knowledge Reader – staged hardening workspace

This repository hardens one subsystem at a time and keeps every stage independently testable.

## Current stack

- **v5.2 Phase 2:** deterministic bounded chunking;
- **v5.3 Phase 3:** typed Claim evidence validation;
- **v5.4 Phase 4:** entity, alias, homonym, timeline, and conflict normalization.

## Phase 4 contract

Phase 4 accepts only `claims.accepted.jsonl` from Phase 3. It re-runs Phase 3 validation against the normalized source and Unit index before building any entity or fact. Modified, stale, duplicate, or non-accepted records are rejected.

Normalization rules are conservative:

- accepted alias Claims may merge names;
- exact repeated surfaces merge automatically only inside the same source and Unit;
- the same name in different Units remains an ambiguity group;
- cross-Unit `same_as` and `different_from` links require their own exact evidence span;
- identity links may not cross source boundaries;
- actor/place type conflicts block unsafe merges;
- unresolved factual conflicts remain contested instead of being overwritten;
- explicit earlier/later language creates temporal variants only when source order supports the transition;
- Phase 4 never grants final freeze authority.

## Usage

```bash
python -m pip install .

tkr-entity-normalize \
  project/admission/normalized-text.txt \
  project/claims/claims.accepted.jsonl \
  --units project/admission/unit-index.csv \
  --identity-links project/entities/identity-links.jsonl \
  --outdir project/entities
```

`--identity-links` is optional. Each link must cite a local span and reference two Phase 3 Claim roles.

## Outputs

```text
mentions.jsonl
entities.jsonl
facts.jsonl
timeline.jsonl
conflicts.jsonl
ambiguity-groups.jsonl
entity-normalization-report.json
```

The report includes SHA-256 values for the source, Unit index, accepted Claims, optional identity links, and every generated artifact.

## Validation

```bash
python -m compileall -q tkr tests
python -m unittest discover -s tests -v
```

GitHub Actions runs Python 3.10, 3.11, and 3.12 matrices for Phase 2, Phase 3, and Phase 4.

## Deliberate limits

Phase 4 does not perform pronoun resolution, implicit identity inference, open-ended character understanding, embeddings, or graph-database storage. Repeated names inside one Unit use a documented local-continuity heuristic; difficult same-Unit homonyms require explicit `different_from` evidence. Those limits prevent an apparent recall gain from silently creating false entity merges.
