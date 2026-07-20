# Text Knowledge Reader – staged hardening workspace

This repository implements and independently tests one subsystem at a time before integration into the complete Skill.

## Current stage

**v5.2.0-alpha1 — Phase 2 chunking hardening**

The stage is intentionally narrow. It contains no claim entailment, entity normalization, retrieval, benchmark, freeze, character-state inference, timeline inference, or world-building inference.

## Guarantees under test

- every chunk is an exact contiguous slice of normalized source text;
- `0 < chunk.length <= max_chars`;
- `0 <= overlap <= overlap_chars < max_chars`;
- unit boundaries are never crossed;
- each supplied unit receives complete, gap-free coverage;
- chunk IDs are deterministic from schema, source, unit, offsets, and text hash;
- paragraph and sentence boundaries are preferred without weakening size limits;
- immediately closing quotes/brackets remain with a sentence when they fit;
- decimal points are not treated as sentence endings;
- the CLI writes JSONL incrementally and validates it in a separate pass before publication.

## Integration with admission output

The CLI accepts `unit-index.csv`, JSON, or JSONL. When a row contains both `body_start/body_end` and `norm_start/norm_end`, body spans are used for semantic chunking.

```bash
python -m pip install .

tkr-chunk project/admission/normalized-text.txt \
  --units project/admission/unit-index.csv \
  --max-chars 1400 \
  --overlap-chars 180 \
  --outdir project/chunks
```

Outputs:

```text
project/chunks/chunks.jsonl
project/chunks/chunking-report.json
```

## Validation

```bash
python -m compileall -q tkr tests
python -m unittest discover -s tests -v
```

GitHub Actions executes the full suite on Python 3.10, 3.11, and 3.12 and preserves compile/test logs as workflow artifacts.

## Known boundary of this stage

Chunk records are streamed, but the normalized UTF-8 source is still decoded into one Python string by the CLI. File-backed text access and resumable multi-hundred-million-character processing belong to the later scale/performance stage; they are not falsely claimed here.
