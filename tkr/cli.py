"""Command line interface for the isolated chunking hardening stage."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Mapping, Sequence

from .chunking import ChunkConfig, UnitSpan, stream_chunk_artifacts


def _required_int(item: Mapping[str, object], key: str, index: int) -> int:
    if key not in item or item[key] in (None, ""):
        raise KeyError(f"unit item {index} is missing {key!r}")
    value = item[key]
    if isinstance(value, bool):
        raise TypeError(f"unit item {index} field {key!r} must be an integer")
    try:
        return int(value)  # CSV values are strings by design.
    except (TypeError, ValueError) as exc:
        raise TypeError(f"unit item {index} field {key!r} must be an integer") from exc


def _unit_from_mapping(item: Mapping[str, object], index: int, source_id: str) -> UnitSpan:
    unit_id = str(item.get("unit_id", "")).strip()
    if not unit_id:
        raise ValueError(f"unit item {index} has an empty unit_id")

    # Admission output normally contains both complete unit spans and body spans.
    # Semantic chunking defaults to body spans so headings are not duplicated into
    # every downstream extraction task. Generic indexes may provide norm_* only.
    has_body = item.get("body_start") not in (None, "") and item.get("body_end") not in (None, "")
    start_key, end_key = ("body_start", "body_end") if has_body else ("norm_start", "norm_end")
    return UnitSpan(
        unit_id=unit_id,
        start=_required_int(item, start_key, index),
        end=_required_int(item, end_key, index),
        source_id=str(item.get("source_id", source_id)).strip() or source_id,
    )


def _load_json_units(path: Path) -> list[Mapping[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("units JSON must be a non-empty array")
    if not all(isinstance(item, dict) for item in payload):
        raise TypeError("every units JSON item must be an object")
    return payload


def _load_jsonl_units(path: Path) -> list[Mapping[str, object]]:
    rows: list[Mapping[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise TypeError(f"unit JSONL line {line_number} must be an object")
        rows.append(payload)
    if not rows:
        raise ValueError("units JSONL must contain at least one object")
    return rows


def _load_csv_units(path: Path) -> list[Mapping[str, object]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("units CSV must contain at least one data row")
    return rows


def _load_units(path: Path | None, text_length: int, source_id: str) -> list[UnitSpan]:
    if path is None:
        if text_length == 0:
            raise ValueError("input text is empty")
        return [UnitSpan(unit_id="unit-1", start=0, end=text_length, source_id=source_id)]

    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows = _load_csv_units(path)
    elif suffix == ".jsonl":
        rows = _load_jsonl_units(path)
    elif suffix == ".json":
        rows = _load_json_units(path)
    else:
        raise ValueError("units file must use .csv, .json, or .jsonl")
    return [_unit_from_mapping(item, index, source_id) for index, item in enumerate(rows, start=1)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tkr-chunk",
        description="Create deterministic bounded chunks from normalized text.",
    )
    parser.add_argument("input", type=Path, help="UTF-8 normalized text file")
    parser.add_argument(
        "--units",
        type=Path,
        help="optional admission unit index in CSV, JSON, or JSONL format",
    )
    parser.add_argument("--source-id", default="source", help="default source identifier")
    parser.add_argument("--max-chars", type=int, default=1400)
    parser.add_argument("--overlap-chars", type=int, default=180)
    parser.add_argument("--outdir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        text = args.input.read_text(encoding="utf-8")
        units = _load_units(args.units, len(text), args.source_id)
        chunks_path, report_path, report = stream_chunk_artifacts(
            text,
            units,
            ChunkConfig(max_chars=args.max_chars, overlap_chars=args.overlap_chars),
            args.outdir,
        )
    except (OSError, UnicodeError, TypeError, ValueError, KeyError) as exc:
        raise SystemExit(f"chunking failed: {exc}") from exc

    print(
        json.dumps(
            {
                "status": report["status"],
                "mode": "streaming-validated",
                "chunks": str(chunks_path),
                "report": str(report_path),
                "chunk_count": report["chunk_count"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
