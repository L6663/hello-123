# Text Knowledge Reader – staged hardening workspace

This repository hardens one subsystem at a time and keeps every stage independently testable.

## Current stack

- **v5.2 Phase 2:** deterministic bounded chunking;
- **v5.3 Phase 3:** typed Claim evidence validation;
- **v5.4 Phase 4:** entity, alias, homonym, timeline, and conflict normalization;
- **v5.5 Phase 5:** hash-verified SQLite indexing and predicate-aware hybrid retrieval.

## Phase 5 contract

Phase 5 consumes the normalized source, Unit index, Phase 3 accepted Claims, and the complete Phase 4 artifact directory. Before building an index it verifies:

- source, Unit index, accepted Claims, and optional identity-link SHA-256 values;
- every Phase 4 artifact hash recorded by `entity-normalization-report.json`;
- unique identifiers and cross-artifact references;
- exact mention spans and Fact evidence hashes;
- Phase 4 review/canonical publication permissions.

The resulting SQLite database contains Units, entities, aliases, mentions, typed Facts, timeline events, conflicts, and ambiguity groups. FTS5 with the trigram tokenizer is used when available; standard-library fallbacks remain available.

## Predicate-aware answerability

The deterministic query parser supports the same closed predicate family as Phase 3:

```text
alias
defeats
located_in
permission
count
date
```

A lexical match may rank supplemental evidence but **cannot** make a question answerable. `answerable=true` requires a matching typed Fact, unambiguous entity resolution, correct subject/object direction, and non-contested evidence. Unsupported open predicates are returned as `unsupported`; conflicting or unresolved temporal answers are returned as `ambiguous`.

## Usage

```bash
python -m pip install .

tkr-retrieval build \
  project/admission/normalized-text.txt \
  project/claims/claims.accepted.jsonl \
  project/entities \
  --units project/admission/unit-index.csv \
  --identity-links project/entities/identity-links.jsonl \
  --database project/index/knowledge.sqlite3 \
  --mode review

tkr-retrieval query \
  project/index/knowledge.sqlite3 \
  "北门位于哪里？"
```

The index report is written beside the database and binds the database SHA-256 plus a deterministic logical index hash. Query integrity verification is enabled by default. `--skip-integrity-check` is reserved for trusted interactive workloads and does not grant canonical or freeze authority.

## Validation

```bash
python -m compileall -q tkr tests
python -m unittest discover -s tests -v
```

GitHub Actions runs the complete stack on Python 3.10, 3.11, and 3.12.

## Deliberate limits

Phase 5 does not perform open-ended natural-language inference, embeddings, neural reranking, pronoun resolution, implicit identity merging, answer generation, Gold Benchmark certification, or final freezing. The database and report remain Phase 5 review artifacts with `may_freeze=false`.
