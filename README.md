# Text Knowledge Reader – staged hardening workspace

This repository implements and independently tests one subsystem at a time before integration into the complete Skill.

## Current stage

**v5.3.0-alpha1 — Phase 3 typed Claim validation**

Phase 3 is stacked on the completed Phase 2 chunking work. It validates structured Claim candidates against exact local evidence; it does not perform extraction, entity normalization, retrieval, benchmark scoring, or final freezing.

## Phase 2: deterministic chunking

- every Chunk is an exact contiguous slice of normalized source text;
- `0 < chunk.length <= max_chars`;
- `0 <= overlap <= overlap_chars < max_chars`;
- Unit boundaries are never crossed;
- Unit coverage is complete and gap-free;
- Chunk IDs are deterministic;
- JSONL output is independently validated before publication.

```bash
tkr-chunk project/admission/normalized-text.txt \
  --units project/admission/unit-index.csv \
  --max-chars 1400 \
  --overlap-chars 180 \
  --outdir project/chunks
```

## Phase 3: typed Claim validation

Supported deterministic Claim types:

```text
alias
defeats
located_in
permission
count
date
```

The validator enforces:

- exact source and evidence-span agreement;
- mandatory Unit binding in the CLI;
- subject/object direction for directional relations;
- explicit negation and permission polarity;
- exact Arabic and basic Chinese numeric comparison;
- normalized, calendar-valid dates;
- review routing for rumors, questions, hypotheticals, predictions, and conflicts;
- deterministic validation IDs;
- `may_index=true` only for fresh accepted results;
- `may_freeze=false` for every Phase 3 result, because final freeze requires later independent gates.

Candidate JSONL example:

```json
{"claim_type":"alias","subject":"北门","object":"玄门","source_id":"novel","unit_id":"chapter-12","evidence_start":1024,"evidence_end":1032,"evidence_text":"北门改称玄门。"}
```

Run:

```bash
tkr-claim-validate project/admission/normalized-text.txt \
  project/extraction/claim-candidates.jsonl \
  --units project/admission/unit-index.csv \
  --outdir project/claim-validation
```

Outputs:

```text
claims.accepted.jsonl
claims.rejected.jsonl
claims.review.jsonl
claim-validation-report.json
```

Incoming fields such as `verification_status`, `confidence`, `may_index`, or `may_freeze` are not trusted as validation evidence.

## Validation

```bash
python -m compileall -q tkr tests
python -m unittest discover -s tests -v
```

GitHub Actions runs the chunking and typed Claim suites on Python 3.10, 3.11, and 3.12 and preserves validation logs as workflow artifacts.

## Known boundaries

- Claim extraction is not implemented in this stage; Phase 3 validates candidates produced elsewhere.
- The rule set is intentionally closed. Unsupported Claim types enter review rather than using a generic similarity fallback.
- Reported speech, nested quotation semantics, coreference, temporal version resolution, and broad natural-language inference still require later extraction/normalization stages and Gold evaluation.
- The normalized source is still decoded into one Python string by the CLI; two-hundred-million-character production processing requires the later file-backed and resumable scale layer.
