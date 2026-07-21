"""CLI for Phase 8 release candidates and explicit freeze seals."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .release_freeze import (
    FreezeError,
    prepare_freeze_candidate,
    seal_freeze_candidate,
    verify_freeze_candidate,
    verify_freeze_seal,
)


def _artifact_spec(value: str) -> tuple[str, Path]:
    role, separator, path = value.partition("=")
    if not separator or not role.strip() or not path.strip():
        raise argparse.ArgumentTypeError("artifact must use ROLE=PATH")
    return role.strip(), Path(path.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tkr-release-freeze",
        description="Prepare, verify, explicitly approve, and verify release freeze artifacts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare",
        help="create a technical freeze candidate with may_freeze=false",
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

    verify = subparsers.add_parser("verify", help="recompute a freeze candidate")
    verify.add_argument("candidate", type=Path)
    verify.add_argument("--root", type=Path)

    seal = subparsers.add_parser(
        "seal",
        help="create a may_freeze=true seal from an explicit approval record",
    )
    seal.add_argument("candidate", type=Path)
    seal.add_argument("approval", type=Path)
    seal.add_argument("--root", type=Path)
    seal.add_argument("--output", type=Path, required=True)

    verify_seal = subparsers.add_parser("verify-seal", help="verify a sealed freeze")
    verify_seal.add_argument("seal", type=Path)
    verify_seal.add_argument("candidate", type=Path)
    verify_seal.add_argument("approval", type=Path)
    verify_seal.add_argument("--root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            payload = prepare_freeze_candidate(
                args.root,
                args.artifact,
                release_version=args.version,
                source_commit=args.source_commit,
                source_date_epoch=args.source_date_epoch,
                output_path=args.output,
            )
        elif args.command == "verify":
            payload = verify_freeze_candidate(args.candidate, root=args.root)
        elif args.command == "seal":
            payload = seal_freeze_candidate(
                args.candidate,
                args.approval,
                args.output,
                root=args.root,
            )
        else:
            payload = verify_freeze_seal(
                args.seal,
                args.candidate,
                args.approval,
                root=args.root,
            )
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload.get("accepted", True) else 2
    except (OSError, UnicodeError, FreezeError) as exc:
        raise SystemExit(f"release freeze failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
