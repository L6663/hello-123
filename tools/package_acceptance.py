from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
import sys
import zipfile

# The policy must come from the reviewed checkout, never from the wheel under test.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_TEXT = str(REPOSITORY_ROOT)
if not sys.path or sys.path[0] != REPOSITORY_TEXT:
    sys.path.insert(0, REPOSITORY_TEXT)

import tkr.source_provenance as source_provenance  # noqa: E402

DISTRIBUTION = "text-knowledge-reader-core"
EXPECTED_VERSION = "5.8.0a1"
EXPECTED_COMMANDS = {
    "tkr-chunk",
    "tkr-claim-validate",
    "tkr-entity-normalize",
    "tkr-retrieval",
    "tkr-strict-qa",
    "tkr-gold-benchmark",
    "tkr-release-freeze",
}
REQUIRED_MODULES = {
    "tkr/__init__.py",
    "tkr/chunking.py",
    "tkr/claim_validation.py",
    "tkr/entity_normalization.py",
    "tkr/hybrid_retrieval.py",
    "tkr/strict_qa.py",
    "tkr/gold_benchmark.py",
    "tkr/gold_hard_negatives.py",
    "tkr/release_freeze.py",
    "tkr/release_freeze_cli.py",
    "tkr/source_provenance.py",
}
FORBIDDEN_PREFIXES = ("tests/", "benchmark/", "tools/", ".github/")
TRUSTED_POLICY_PATH = (REPOSITORY_ROOT / "tkr" / "source_provenance.py").resolve()


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _assert_checkout_policy() -> Path:
    loaded = Path(source_provenance.__file__).resolve()
    if loaded != TRUSTED_POLICY_PATH:
        raise SystemExit(
            "wheel audit policy was not loaded from the reviewed checkout: "
            f"{loaded} != {TRUSTED_POLICY_PATH}"
        )
    return loaded


def installed_size(distribution: importlib.metadata.Distribution) -> int:
    total = 0
    for item in distribution.files or ():
        path = distribution.locate_file(item)
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def audit(wheel: Path) -> dict[str, object]:
    verifier_path = _assert_checkout_policy()
    if not wheel.is_file():
        raise SystemExit(f"wheel does not exist: {wheel}")
    try:
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
    except (OSError, zipfile.BadZipFile) as exc:
        raise SystemExit(f"invalid wheel: {exc}") from exc

    missing_modules = sorted(REQUIRED_MODULES - names)
    forbidden = sorted(
        name
        for name in names
        if name.startswith(FORBIDDEN_PREFIXES)
        or "/tests/" in name
        or name.endswith((".pyc", ".pyo"))
    )
    installable_payload_violations = list(
        source_provenance.audit_wheel_installable_payload(wheel)
    )

    distribution = importlib.metadata.distribution(DISTRIBUTION)
    commands = {
        entry.name
        for entry in distribution.entry_points
        if entry.group == "console_scripts"
    }
    missing_commands = sorted(EXPECTED_COMMANDS - commands)
    unexpected_commands = sorted(commands - EXPECTED_COMMANDS)

    failures: list[str] = []
    if distribution.version != EXPECTED_VERSION:
        failures.append("VERSION_MISMATCH")
    if missing_modules:
        failures.append("REQUIRED_RUNTIME_MODULES_MISSING")
    if forbidden:
        failures.append("NON_RUNTIME_CONTENT_PRESENT")
    if installable_payload_violations:
        failures.append("UNBOUND_INSTALLABLE_PAYLOAD")
    if missing_commands:
        failures.append("CONSOLE_SCRIPTS_MISSING")
    if unexpected_commands:
        failures.append("UNEXPECTED_CONSOLE_SCRIPTS")

    result = {
        "schema_version": "tkr-package-acceptance-v1",
        "python": sys.version,
        "distribution": DISTRIBUTION,
        "version": distribution.version,
        "wheel_name": wheel.name,
        "wheel_size_bytes": wheel.stat().st_size,
        "wheel_sha256": digest(wheel),
        "wheel_file_count": len(names),
        "installed_size_bytes": installed_size(distribution),
        "console_scripts": sorted(commands),
        "missing_modules": missing_modules,
        "forbidden_wheel_entries": forbidden,
        "installable_payload_violations": installable_payload_violations,
        "missing_commands": missing_commands,
        "unexpected_commands": unexpected_commands,
        "verifier_origin": "reviewed_checkout",
        "verifier_source_sha256": digest(verifier_path),
        "failures": failures,
        "accepted": not failures,
    }
    if failures:
        raise SystemExit(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit an installed Text Knowledge Reader wheel."
    )
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.wheel)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
