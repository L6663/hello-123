from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Insert the reviewed checkout before importing any policy code. This script is
# intentionally executed before the candidate wheel is installed.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_TEXT = str(REPOSITORY_ROOT)
if not sys.path or sys.path[0] != REPOSITORY_TEXT:
    sys.path.insert(0, REPOSITORY_TEXT)

import tkr.source_provenance as source_provenance  # noqa: E402

TRUSTED_POLICY_PATH = (REPOSITORY_ROOT / "tkr" / "source_provenance.py").resolve()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reject unbound or executable wheel payloads before installation."
    )
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()

    loaded = Path(source_provenance.__file__).resolve()
    if loaded != TRUSTED_POLICY_PATH:
        raise SystemExit(
            "pre-install wheel policy was not loaded from the reviewed checkout: "
            f"{loaded} != {TRUSTED_POLICY_PATH}"
        )
    violations = source_provenance.audit_wheel_installable_payload(args.wheel)
    if violations:
        raise SystemExit("\n".join(violations))
    print(f"pre-install wheel policy accepted: {args.wheel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
