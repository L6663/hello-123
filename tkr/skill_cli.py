"""CLI for Stage 5 Skill product audit, doctor, and profile discovery."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .engineering import load_engineering_profile, profile_sha256
from .skill_audit import audit_skill_layout, doctor_environment, profile_catalog


def _write(path: Path | None, payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(text, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tkr-skill",
        description=(
            "Inspect the complete Text Knowledge Reader Skill product. "
            "These checks do not perform final project acceptance."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="check Python, SQLite, storage, profiles, and Skill layout")
    doctor.add_argument("--root", type=Path)
    doctor.add_argument("--output", type=Path)

    audit = commands.add_parser("audit", help="audit required Skill files, schemas, profiles, docs, and examples")
    audit.add_argument("--root", type=Path)
    audit.add_argument("--output", type=Path)

    profiles = commands.add_parser("profiles", help="list built-in engineering profiles and hashes")
    profiles.add_argument("--output", type=Path)

    show = commands.add_parser("show-profile", help="show and validate one built-in or file-based profile")
    show.add_argument("profile")
    show.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            report = doctor_environment(args.root)
            _write(args.output, report.to_dict())
            return 0 if report.passed else 2
        if args.command == "audit":
            report = audit_skill_layout(args.root)
            _write(args.output, report.to_dict())
            return 0 if report.passed else 2
        if args.command == "profiles":
            _write(args.output, {"profiles": profile_catalog(), "project_acceptance_performed": False})
            return 0
        profile = load_engineering_profile(args.profile)
        payload = profile.to_dict()
        payload["profile_sha256"] = profile_sha256(profile)
        payload["project_acceptance_performed"] = False
        payload["may_accept_project"] = False
        payload["may_freeze"] = False
        _write(args.output, payload)
        return 0
    except (OSError, UnicodeError, TypeError, ValueError, KeyError) as exc:
        raise SystemExit(f"Skill inspection failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
