"""CLI for typed Claim validation against a normalized local source."""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from typing import Iterator, Sequence

from .claim_validation import (
    ClaimCandidate,
    ClaimValidationError,
    VALIDATOR_VERSION,
    validate_claim,
)
from .cli import _load_units


def _iter_candidates(path: Path) -> Iterator[tuple[int, ClaimCandidate]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ClaimValidationError(f"blank candidate record at line {line_number}")
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ClaimValidationError(
                    f"invalid candidate JSON at line {line_number}: {exc.msg}"
                ) from exc
            if not isinstance(payload, dict):
                raise ClaimValidationError(
                    f"candidate record at line {line_number} must be an object"
                )
            yield line_number, ClaimCandidate.from_dict(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tkr-claim-validate",
        description="Validate typed Claim candidates against exact local evidence spans.",
    )
    parser.add_argument("source", type=Path, help="UTF-8 normalized source text")
    parser.add_argument("candidates", type=Path, help="Claim candidate JSONL")
    parser.add_argument(
        "--units",
        type=Path,
        required=True,
        help="required unit index in CSV, JSON, or JSONL format",
    )
    parser.add_argument("--source-id", default="source")
    parser.add_argument("--outdir", type=Path, required=True)
    return parser


def _publish(
    source_text: str,
    candidates_path: Path,
    units_path: Path,
    source_id: str,
    outdir: Path,
) -> dict[str, object]:
    outdir.mkdir(parents=True, exist_ok=True)
    names = {
        "accepted": "claims.accepted.jsonl",
        "rejected": "claims.rejected.jsonl",
        "review": "claims.review.jsonl",
    }
    temporary = {status: outdir / f".{name}.tmp" for status, name in names.items()}
    final = {status: outdir / name for status, name in names.items()}
    report_tmp = outdir / ".claim-validation-report.json.tmp"
    report_path = outdir / "claim-validation-report.json"

    units = _load_units(units_path, len(source_text), source_id)
    unit_lookup = {(unit.source_id, unit.unit_id): unit for unit in units}
    counts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    candidate_count = 0

    handles = {
        status: path.open("w", encoding="utf-8", newline="\n")
        for status, path in temporary.items()
    }
    try:
        for line_number, candidate in _iter_candidates(candidates_path):
            candidate_count += 1
            unit = unit_lookup.get((candidate.source_id, candidate.unit_id))
            result = validate_claim(
                candidate,
                source_text,
                unit_span=unit,
                require_unit=True,
            )
            counts[result.status] += 1
            reasons.update(result.reason_codes)
            record = {
                "candidate_line": line_number,
                "candidate": candidate.to_dict(),
                "validation": result.to_dict(),
            }
            handles[result.status].write(
                json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            )
    finally:
        for handle in handles.values():
            handle.close()

    if candidate_count == 0:
        for path in temporary.values():
            path.unlink(missing_ok=True)
        raise ClaimValidationError("candidate JSONL is empty")

    report: dict[str, object] = {
        "validator_version": VALIDATOR_VERSION,
        "status": "completed",
        "source_sha256": sha256(source_text.encode("utf-8")).hexdigest(),
        "candidates_sha256": sha256(candidates_path.read_bytes()).hexdigest(),
        "unit_index_sha256": sha256(units_path.read_bytes()).hexdigest(),
        "unit_binding_required": True,
        "unit_count": len(units),
        "candidate_count": candidate_count,
        "accepted_count": counts["accepted"],
        "rejected_count": counts["rejected"],
        "review_count": counts["review"],
        "may_index_count": counts["accepted"],
        "may_freeze_count": 0,
        "reason_counts": dict(sorted(reasons.items())),
    }
    report_tmp.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    try:
        for status in ("accepted", "rejected", "review"):
            temporary[status].replace(final[status])
        report_tmp.replace(report_path)
    except Exception:
        for path in temporary.values():
            path.unlink(missing_ok=True)
        report_tmp.unlink(missing_ok=True)
        raise
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source_text = args.source.read_text(encoding="utf-8")
        if not source_text:
            raise ClaimValidationError("source text is empty")
        report = _publish(
            source_text,
            args.candidates,
            args.units,
            args.source_id,
            args.outdir,
        )
    except (OSError, UnicodeError, TypeError, ValueError, KeyError) as exc:
        raise SystemExit(f"claim validation failed: {exc}") from exc

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
