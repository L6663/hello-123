"""Command line interface for the isolated chunking hardening stage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .chunking import ChunkConfig, UnitSpan, chunk_units, write_chunk_artifacts


def _load_units(path: Path | None, text_length: int, source_id: str) -> list[UnitSpan]:
    if path is None:
        if text_length == 0:
            raise ValueError("input text is empty")
        return [UnitSpan(unit_id="unit-1", start=0, end=text_length, source_id=source_id)]

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("units JSON must be a non-empty array")

    units: list[UnitSpan] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise TypeError(f"unit item {index} must be an object")
        units.append(
            UnitSpan(
                unit_id=str(item.get("unit_id", "")),
                start=int(item["norm_start"]),
                end=int(item["norm_end"]),
                source_id=str(item.get("source_id", source_id)),
            )
        )
    return units


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tkr-chunk",
        description="Create deterministic bounded chunks from normalized text.",
    )
    parser.add_argument("input", type=Path, help="UTF-8 normalized text file")
    parser.add_argument("--units", type=Path, help="optional JSON array of unit spans")
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
        chunks, report = chunk_units(
            text,
            units,
            ChunkConfig(max_chars=args.max_chars, overlap_chars=args.overlap_chars),
        )
        chunks_path, report_path = write_chunk_artifacts(chunks, report, args.outdir)
    except (OSError, UnicodeError, TypeError, ValueError, KeyError) as exc:
        raise SystemExit(f"chunking failed: {exc}") from exc

    print(
        json.dumps(
            {
                "status": report["status"],
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
