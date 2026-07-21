from __future__ import annotations

from pathlib import Path


def main() -> None:
    path = Path("tkr/gold_benchmark.py")
    text = path.read_text(encoding="utf-8")

    def replace_once(old: str, new: str) -> None:
        nonlocal text
        if text.count(old) != 1:
            raise RuntimeError(f"hardening marker count is {text.count(old)}: {old[:80]!r}")
        text = text.replace(old, new, 1)

    replace_once(
        "import re\nfrom typing import Mapping, Sequence",
        "import re\nfrom types import MappingProxyType\nfrom typing import Mapping, Sequence",
    )
    replace_once(
        "    ),\n}\n\n\n@dataclass(frozen=True, slots=True)\nclass GoldCase:",
        '''    ),
}


def _freeze_policy(policy: BenchmarkPolicy) -> BenchmarkPolicy:
    """Return a recursively immutable copy of a built-in policy."""

    return BenchmarkPolicy(
        profile=policy.profile,
        policy_id=policy.policy_id,
        certifies_release=policy.certifies_release,
        min_cases=policy.min_cases,
        min_answered=policy.min_answered,
        min_refusal_by_decision=MappingProxyType(dict(policy.min_refusal_by_decision)),
        min_answered_per_predicate=policy.min_answered_per_predicate,
        required_hard_negative_tags=frozenset(policy.required_hard_negative_tags),
        min_each_required_hard_negative=policy.min_each_required_hard_negative,
        metric_floors=MappingProxyType(dict(policy.metric_floors)),
        metric_ceilings=MappingProxyType(dict(policy.metric_ceilings)),
        count_ceilings=MappingProxyType(dict(policy.count_ceilings)),
    )


POLICIES = MappingProxyType(
    {name: _freeze_policy(policy) for name, policy in POLICIES.items()}
)


@dataclass(frozen=True, slots=True)
class GoldCase:''',
    )
    replace_once(
        "    return tuple(result)\n\n\ndef _parse_case(row: Mapping[str, object], line_number: int) -> GoldCase:",
        '''    return tuple(result)


def _validate_hard_negative_tags(
    case_id: str,
    tags: Sequence[str],
    *,
    expected_decision: str,
    expected_predicate: str,
    parsed_temporal_scope: str,
) -> None:
    """Reject category labels that contradict the case's observable structure."""

    tag_set = set(tags)
    unsupported_tags = {"unsupported_open_predicate", "entity_only_no_predicate"}
    if tag_set & unsupported_tags:
        if expected_decision != "refused_unsupported" or expected_predicate != "unsupported":
            raise BenchmarkError(f"Gold case {case_id} has a spoofed unsupported hard-negative tag")
    if "relation_direction" in tag_set:
        if expected_predicate not in {"alias", "defeats", "located_in"} or expected_decision not in REFUSAL_DECISIONS:
            raise BenchmarkError(f"Gold case {case_id} has a spoofed relation-direction tag")
    if "numeric_prefix" in tag_set:
        if expected_predicate != "count" or expected_decision == "refused_unsupported":
            raise BenchmarkError(f"Gold case {case_id} has a spoofed numeric-prefix tag")
    if "temporal_scope" in tag_set:
        if expected_decision != "refused_ambiguous" or parsed_temporal_scope != "any":
            raise BenchmarkError(f"Gold case {case_id} has a spoofed temporal-scope tag")
    if "contested_fact" in tag_set and expected_decision != "refused_ambiguous":
        raise BenchmarkError(f"Gold case {case_id} has a spoofed contested-fact tag")
    if "lexical_distractor" in tag_set and expected_decision != "refused_insufficient_evidence":
        raise BenchmarkError(f"Gold case {case_id} has a spoofed lexical-distractor tag")
    if "absence_not_negative" in tag_set:
        if expected_predicate != "permission" or expected_decision != "refused_insufficient_evidence":
            raise BenchmarkError(f"Gold case {case_id} has a spoofed absence-not-negative tag")


def _parse_case(row: Mapping[str, object], line_number: int) -> GoldCase:''',
    )
    replace_once(
        '''        if expected_decision != "refused_unsupported" and not parsed.supported:
            raise BenchmarkError(f"typed refusal Gold case {case_id} parses as unsupported")

    return GoldCase(''',
        '''        if expected_decision != "refused_unsupported" and not parsed.supported:
            raise BenchmarkError(f"typed refusal Gold case {case_id} parses as unsupported")

    _validate_hard_negative_tags(
        case_id,
        tags,
        expected_decision=expected_decision,
        expected_predicate=expected_predicate,
        parsed_temporal_scope=parsed.temporal_scope,
    )

    return GoldCase(''',
    )
    replace_once(
        '''    *,
    index_report_path: str | Path | None = None,
) -> BenchmarkVerification:''',
        '''    *,
    index_report_path: str | Path | None = None,
    expected_profile: str | None = None,
) -> BenchmarkVerification:''',
    )
    replace_once(
        '''    if not isinstance(profile, str) or profile not in POLICIES:
        return BenchmarkVerification(
            "rejected", False, ("BENCHMARK_POLICY_PROFILE_INVALID",), supplied_id, ""
        )
    try:''',
        '''    if not isinstance(profile, str) or profile not in POLICIES:
        return BenchmarkVerification(
            "rejected", False, ("BENCHMARK_POLICY_PROFILE_INVALID",), supplied_id, ""
        )
    if expected_profile is not None:
        if expected_profile not in POLICIES:
            return BenchmarkVerification(
                "rejected", False, ("BENCHMARK_REQUIRED_PROFILE_INVALID",), supplied_id, ""
            )
        if profile != expected_profile:
            return BenchmarkVerification(
                "rejected", False, ("BENCHMARK_REQUIRED_PROFILE_MISMATCH",), supplied_id, ""
            )
    try:''',
    )
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
