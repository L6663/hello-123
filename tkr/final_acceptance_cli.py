"""CLI for Stage 8 technical candidates and explicit acceptance seals."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .final_acceptance import (
    FinalAcceptanceError,
    prepare_final_acceptance_candidate,
    seal_final_acceptance,
    verify_final_acceptance_candidate,
    verify_final_acceptance_seal,
)


def _artifact_spec(value: str) -> tuple[str, Path]:
    role, separator, path = value.partition("=")
    if not separator or not role.strip() or not path.strip():
        raise argparse.ArgumentTypeError("artifact must use ROLE=PATH")
    return role.strip(), Path(path.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tkr-final-acceptance",
        description=(
            "Prepare and verify a hash-bound v6 final-product candidate. "
            "Only a separate explicit approval record can create an acceptance "
            "seal; no command grants release or freeze authority."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser(
        "prepare",
        help="create a technical candidate with all authority flags false",
    )
    prepare.add_argument("--root", type=Path, required=True)
    prepare.add_argument("--version", required=True)
    prepare.add_argument("--source-commit", required=True)
    prepare.add_argument("--source-date-epoch", type=int, required=True)
    prepare.add_argument(
        "--artifact",
        type=_artifact_spec,
        action="append",
        required=True,
        metavar="ROLE=PATH",
    )
    prepare.add_argument("--output", type=Path)

    verify = commands.add_parser(
        "verify",
        help="recompute every technical candidate gate",
    )
    verify.add_argument("candidate", type=Path)
    verify.add_argument("--root", type=Path)

    seal = commands.add_parser(
        "seal",
        help="seal product acceptance from a separate explicit approval record",
    )
    seal.add_argument("candidate", type=Path)
    seal.add_argument("approval", type=Path)
    seal.add_argument("--root", type=Path)
    seal.add_argument("--output", type=Path, required=True)

    verify_seal = commands.add_parser(
        "verify-seal",
        help="recompute a product acceptance seal",
    )
    verify_seal.add_argument("seal", type=Path)
    verify_seal.add_argument("candidate", type=Path)
    verify_seal.add_argument("approval", type=Path)
    verify_seal.add_argument("--root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            payload = prepare_final_acceptance_candidate(
                args.root,
                args.artifact,
                release_version=args.version,
                source_commit=args.source_commit,
                source_date_epoch=args.source_date_epoch,
                output_path=args.output,
            )
        elif args.command == "verify":
            payload = verify_final_acceptance_candidate(
                args.candidate, root=args.root
            )
        elif args.command == "seal":
            payload = seal_final_acceptance(
                args.candidate,
                args.approval,
                args.output,
                root=args.root,
            )
        else:
            payload = verify_final_acceptance_seal(
                args.seal,
                args.candidate,
                args.approval,
                root=args.root,
            )
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload.get("valid", payload.get("technical_gate_passed", True)) else 2
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        FinalAcceptanceError,
    ) as exc:
        raise SystemExit(f"final acceptance command failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
