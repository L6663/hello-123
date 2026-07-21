from pathlib import Path
import re

p = Path('tkr/release_freeze.py')
s = p.read_text(encoding='utf-8')

def one(old, new):
    global s
    if s.count(old) != 1:
        raise SystemExit(f'anchor mismatch: {old[:60]!r}: {s.count(old)}')
    s = s.replace(old, new, 1)

def func(name, block):
    global s
    m = re.search(rf'^def {name}\(.*?(?=^def |\Z)', s, re.M | re.S)
    if not m:
        raise SystemExit(f'function not found: {name}')
    s = s[:m.start()] + block.rstrip() + '\n\n\n' + s[m.end():]

one(
'''"""Phase 8 release evidence binding and explicit freeze sealing.

A technical candidate recomputes every bound artifact and the Phase 7 Release Gold
report, but always remains ``may_freeze=false``. Freeze authority exists only in a
separate seal that binds an explicit operator approval record.
"""''',
'''"""Phase 8 lightweight candidate preparation and explicit freeze sealing.

Preparation only validates metadata and records required artifact sizes and
SHA-256 values. Expensive benchmark, package, reproducibility, and Git checks are
deferred to verification. A prepared candidate never grants technical or freeze
authority; a separate seal still requires explicit operator approval.
"""''')
one('FREEZE_CANDIDATE_SCHEMA_VERSION = "tkr-freeze-candidate-v1"',
    'FREEZE_CANDIDATE_SCHEMA_VERSION = "tkr-freeze-candidate-v2"')
one(
'''    if unknown:
        raise FreezeError(f"unsupported artifact roles: {unknown}")
    return grouped


def _single_path(''',
'''    if unknown:
        raise FreezeError(f"unsupported artifact roles: {unknown}")
    return grouped


def _preparation_summary(records: Sequence[ArtifactRecord]) -> dict[str, object]:
    grouped = _group_records(records)
    return {
        "mode": "lightweight",
        "hash_algorithm": "sha256",
        "artifact_count": len(records),
        "artifact_role_count": len(grouped),
        "artifact_roles": {role: len(grouped[role]) for role in sorted(grouped)},
        "total_size_bytes": sum(record.size_bytes for record in records),
        "deep_verification_deferred": True,
    }


def _single_path(''')
func('_candidate_core', '''def _candidate_core(
    *,
    release_version: str,
    source_commit: str,
    source_date_epoch: int,
    records: Sequence[ArtifactRecord],
) -> dict[str, object]:
    return {
        "schema_version": FREEZE_CANDIDATE_SCHEMA_VERSION,
        "release_version": release_version,
        "source_commit": source_commit,
        "source_date_epoch": source_date_epoch,
        "artifacts": [record.to_dict() for record in records],
        "preparation": _preparation_summary(records),
        "technical_gate_passed": False,
        "requires_verification": True,
        "requires_explicit_approval": True,
        "may_freeze": False,
        "status": "prepared",
    }''')
one(
'''    records = _records_from_specs(root_path, artifact_specs)
    evidence = _validate_release_evidence(
        root_path,
        records,
        release_version=version,
        source_commit=commit,
        source_date_epoch=source_date_epoch,
    )
    core = _candidate_core(
        release_version=version,
        source_commit=commit,
        source_date_epoch=source_date_epoch,
        records=records,
        evidence=evidence,
    )''',
'''    records = _records_from_specs(root_path, artifact_specs)
    core = _candidate_core(
        release_version=version,
        source_commit=commit,
        source_date_epoch=source_date_epoch,
        records=records,
    )''')
one('    """Build a hash-bound technical candidate that cannot freeze by itself."""',
'''    """Prepare a lightweight hash-bound candidate without deep verification."""''')
one(
'''        "artifacts",
        "evidence",
        "technical_gate_passed",
        "requires_explicit_approval",''',
'''        "artifacts",
        "preparation",
        "technical_gate_passed",
        "requires_verification",
        "requires_explicit_approval",''')
one(
'''    _bool_is(payload, "technical_gate_passed", True, "freeze candidate")
    _bool_is(payload, "requires_explicit_approval", True, "freeze candidate")
    _bool_is(payload, "may_freeze", False, "freeze candidate")
    if payload["status"] != "candidate":
        raise FreezeError("freeze candidate status must be candidate")''',
'''    _bool_is(payload, "technical_gate_passed", False, "freeze candidate")
    _bool_is(payload, "requires_verification", True, "freeze candidate")
    _bool_is(payload, "requires_explicit_approval", True, "freeze candidate")
    _bool_is(payload, "may_freeze", False, "freeze candidate")
    if payload["status"] != "prepared":
        raise FreezeError("freeze candidate status must be prepared")''')
one(
'''    evidence = _validate_release_evidence(
        root_path,
        records,
        release_version=release_version,
        source_commit=source_commit,
        source_date_epoch=source_date_epoch,
    )
    if payload["evidence"] != evidence:
        raise FreezeError("freeze candidate evidence summary mismatch")''',
'''    if payload["preparation"] != _preparation_summary(records):
        raise FreezeError("freeze candidate preparation summary mismatch")

    evidence = _validate_release_evidence(
        root_path,
        records,
        release_version=release_version,
        source_commit=source_commit,
        source_date_epoch=source_date_epoch,
    )''')
one(
'''    return {
        "status": "accepted",
        "accepted": True,
        "candidate_id": supplied_id,
        "reason_codes": [
            "ARTIFACT_HASHES_RECOMPUTED",
            "RELEASE_BENCHMARK_RECOMPUTED",
            "REPRODUCIBLE_WHEELS_REHASHED",
            "EXPLICIT_APPROVAL_STILL_REQUIRED",
        ],
        "may_freeze": False,
    }''',
'''    verification_core = {
        "candidate_id": supplied_id,
        "candidate_sha256": _sha256_path(path),
        "evidence": evidence,
        "technical_gate_passed": True,
    }
    verification_id = "freeze_verification_" + _sha256_bytes(
        _canonical_json(verification_core).encode("utf-8")
    )[:24]
    return {
        "status": "accepted",
        "accepted": True,
        "verification_id": verification_id,
        "candidate_id": supplied_id,
        "candidate_sha256": verification_core["candidate_sha256"],
        "verification_mode": "full",
        "technical_gate_passed": True,
        "evidence": evidence,
        "reason_codes": [
            "LIGHTWEIGHT_PREPARATION_BOUND",
            "ARTIFACT_HASHES_RECOMPUTED",
            "RELEASE_BENCHMARK_RECOMPUTED",
            "REPRODUCIBLE_WHEELS_REHASHED",
            "SOURCE_PROVENANCE_RECOMPUTED",
            "EXPLICIT_APPROVAL_STILL_REQUIRED",
        ],
        "may_freeze": False,
    }''')
p.write_text(s, encoding='utf-8')
