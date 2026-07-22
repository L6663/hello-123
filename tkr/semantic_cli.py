"""CLI for Stage 3 evidence-grounded semantic candidate extraction."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .semantic_artifacts import publish_semantic_artifacts
from .semantic_extraction import inspect_source_semantics
from .semantic_models import SemanticPolicy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tkr-semantic-extract",
        description=(
            "Extract evidence-bound six-predicate candidates and discourse status; "
            "this command does not perform project acceptance."
        ),
    )
    parser.add_argument("source", type=Path)
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--output", type=Path, help="write one complete JSON report")
    output.add_argument("--outdir", type=Path, help="write the standard Stage 3 artifact set")
    parser.add_argument("--max-candidates", type=int, default=200_000)
    parser.add_argument("--max-findings", type=int, default=50_000)
    parser.add_argument("--max-model-tasks", type=int, default=50_000)
    parser.add_argument("--max-clause-characters", type=int, default=600)
    parser.add_argument("--no-model-tasks", action="store_true")
    parser.add_argument("--no-entity-normalization", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    policy = SemanticPolicy(
        max_candidates=args.max_candidates,
        max_findings=args.max_findings,
        max_model_tasks=args.max_model_tasks,
        max_clause_characters=args.max_clause_characters,
        emit_model_tasks=not args.no_model_tasks,
        run_entity_normalization=not args.no_entity_normalization,
    )
    report = inspect_source_semantics(args.source, policy=policy)
    if args.outdir is not None:
        manifest = publish_semantic_artifacts(report, args.outdir)
        print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
        return 0
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(payload, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(f".{args.output.name}.tmp")
        temporary.write_text(payload, encoding="utf-8", newline="\n")
        temporary.replace(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
