"""CLI for evidence-bound entity and conflict normalization."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping, Sequence

from .cli import _load_units
from .entity_normalization import (
    EntityNormalizationError,
    IdentityLink,
    NormalizationBundle,
    normalize_entities,
)


def _load_jsonl_objects(path: Path, label: str) -> list[Mapping[str, object]]:
    rows: list[Mapping[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise EntityNormalizationError(f"blank {label} record at line {line_number}")
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EntityNormalizationError(
                    f"invalid {label} JSON at line {line_number}: {exc.msg}"
                ) from exc
            if not isinstance(payload, dict):
                raise EntityNormalizationError(
                    f"{label} record at line {line_number} must be an object"
                )
            rows.append(payload)
    if not rows:
        raise EntityNormalizationError(f"{label} JSONL is empty")
    return rows


def _load_identity_links(path: Path | None) -> list[IdentityLink]:
    if path is None:
        return []
    return [IdentityLink.from_dict(row) for row in _load_jsonl_objects(path, "identity link")]


def _jsonl_bytes(rows: Sequence[object]) -> bytes:
    lines: list[str] = []
    for row in rows:
        payload = row.to_dict() if hasattr(row, "to_dict") else row
        lines.append(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def _publish(
    bundle: NormalizationBundle,
    outdir: Path,
    *,
    accepted_path: Path,
    identity_links_path: Path | None,
) -> dict[str, object]:
    outdir.mkdir(parents=True, exist_ok=True)
    datasets: dict[str, Sequence[object]] = {
        "mentions.jsonl": bundle.mentions,
        "entities.jsonl": bundle.entities,
        "facts.jsonl": bundle.facts,
        "timeline.jsonl": bundle.timeline,
        "conflicts.jsonl": bundle.conflicts,
        "ambiguity-groups.jsonl": bundle.ambiguity_groups,
    }
    temporary: dict[str, Path] = {}
    artifact_hashes: dict[str, str] = {}
    try:
        for name, rows in datasets.items():
            data = _jsonl_bytes(rows)
            artifact_hashes[name] = sha256(data).hexdigest()
            temp = outdir / f".{name}.tmp"
            temp.write_bytes(data)
            temporary[name] = temp

        report = dict(bundle.report)
        report.update(
            {
                "accepted_claims_sha256": sha256(accepted_path.read_bytes()).hexdigest(),
                "identity_links_sha256": (
                    sha256(identity_links_path.read_bytes()).hexdigest()
                    if identity_links_path is not None
                    else None
                ),
                "artifact_sha256": dict(sorted(artifact_hashes.items())),
            }
        )
        report_bytes = (
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        report_temp = outdir / ".entity-normalization-report.json.tmp"
        report_temp.write_bytes(report_bytes)
        temporary["entity-normalization-report.json"] = report_temp

        # Data files are published first and the hash-bearing report is published
        # last. Downstream phases must verify the report hashes before consuming.
        for name in datasets:
            temporary[name].replace(outdir / name)
        report_temp.replace(outdir / "entity-normalization-report.json")
        return report
    except Exception:
        for path in temporary.values():
            path.unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tkr-entity-normalize",
        description=(
            "Revalidate accepted Claims and normalize entities, aliases, homonyms, "
            "timeline order, and conflicts."
        ),
    )
    parser.add_argument("source", type=Path, help="UTF-8 normalized source text")
    parser.add_argument("accepted_claims", type=Path, help="Phase 3 claims.accepted.jsonl")
    parser.add_argument("--units", type=Path, required=True, help="admission Unit index")
    parser.add_argument(
        "--identity-links",
        type=Path,
        help="optional evidence-bound same_as/different_from JSONL",
    )
    parser.add_argument("--source-id", default="source")
    parser.add_argument("--outdir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source_text = args.source.read_text(encoding="utf-8")
        if not source_text:
            raise EntityNormalizationError("source text is empty")
        units = _load_units(args.units, len(source_text), args.source_id)
        accepted_records = _load_jsonl_objects(args.accepted_claims, "accepted Claim")
        identity_links = _load_identity_links(args.identity_links)
        bundle = normalize_entities(
            accepted_records,
            source_text,
            units,
            identity_links=identity_links,
        )
        report = _publish(
            bundle,
            args.outdir,
            accepted_path=args.accepted_claims,
            identity_links_path=args.identity_links,
        )
    except (OSError, UnicodeError, TypeError, ValueError, KeyError) as exc:
        raise SystemExit(f"entity normalization failed: {exc}") from exc
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
