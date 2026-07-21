# Text Knowledge Reader – staged hardening workspace

This repository hardens one subsystem at a time and keeps every stage independently testable.

## Current stack

- **v5.2 Phase 2:** deterministic bounded chunking;
- **v5.3 Phase 3:** typed Claim evidence validation;
- **v5.4 Phase 4:** entity, alias, homonym, timeline, and conflict normalization;
- **v5.5 Phase 5:** hash-verified SQLite indexing and predicate-aware hybrid retrieval;
- **v5.6 Phase 6:** strict answers, evidence packets, citation entailment, and refusal decisions.

## Phase 6 contract

Phase 6 consumes only a verified Phase 5 database and index report. It does not use lexical similarity as proof and does not generate open-ended prose. For the closed typed predicate family it produces either:

- one deterministic answer with exact Fact citations; or
- one deterministic refusal for unsupported, missing, ambiguous, contested, or temporally underspecified evidence.

Supported predicates remain:

```text
alias
defeats
located_in
permission
count
date
```

Every answered packet contains:

- the parsed predicate and requested role;
- the structured answer claim;
- exact source, Unit, start/end offsets, Fact ID, evidence text, and evidence SHA-256;
- the Phase 5 logical index hash, database SHA-256, and report SHA-256;
- deterministic citation markers such as `[E1]`;
- `citation_entailment=entailed_structured`;
- `may_freeze=false`.

A packet verifier recomputes the query, answer, citations, hashes, refusal policy, and packet ID from the current database. Any modified sentence, number, direction, citation span, citation text, authority flag, or packet field is rejected.

## Usage

```bash
python -m pip install .

# Build/query the Phase 5 index.
tkr-retrieval build \
  project/admission/normalized-text.txt \
  project/claims/claims.accepted.jsonl \
  project/entities \
  --units project/admission/unit-index.csv \
  --identity-links project/entities/identity-links.jsonl \
  --database project/index/knowledge.sqlite3 \
  --mode review

# Generate an answer or refusal packet.
tkr-strict-qa answer \
  project/index/knowledge.sqlite3 \
  "守卫现在有多少名？" \
  --output project/qa/answer.json

# Recompute and verify the complete packet.
tkr-strict-qa verify \
  project/index/knowledge.sqlite3 \
  project/qa/answer.json
```

## Refusal policy

Phase 6 refuses rather than guesses when:

- the predicate is outside the closed typed family;
- no matching typed Fact exists;
- entity identity is ambiguous;
- Facts are contested;
- multiple time versions exist without a requested scope;
- multiple structured answers remain;
- the database or index report fails integrity verification.

Absence is not treated as false. A negative permission answer requires an explicit opposite-polarity permission Fact.

## Validation

```bash
python -m compileall -q tkr tests
python -m unittest discover -s tests -v
```

GitHub Actions runs the complete stack on Python 3.10, 3.11, and 3.12.

## Deliberate limits

Phase 6 does not perform open-ended natural-language inference, stylistic answer generation, causal explanation, personality analysis, pronoun resolution, embeddings, neural reranking, Gold Benchmark certification, or final freezing. It validates deterministic answers for the six closed predicates only. Review packets remain non-freezable artifacts.
