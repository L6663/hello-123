from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: marker count {count} for {old[:90]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    benchmark = Path("tkr/gold_benchmark.py")
    replace_once(
        benchmark,
        "from .hybrid_retrieval import RetrievalError, parse_predicate_query\nfrom .strict_qa import StrictQAError, StrictQAPacket, answer_strict, verify_strict_packet",
        "from .gold_hard_negatives import validate_hard_negative_outcome\nfrom .hybrid_retrieval import RetrievalError, parse_predicate_query\nfrom .strict_qa import StrictQAError, StrictQAPacket, answer_strict, verify_strict_packet",
    )
    replace_once(
        benchmark,
        '''    "integrity_error_count": 0,
    "evaluator_error_count": 0,
}''',
        '''    "integrity_error_count": 0,
    "evaluator_error_count": 0,
    "hard_negative_validation_error_count": 0,
}''',
    )
    replace_once(
        benchmark,
        '''        verification = verify_strict_packet(database, packet.to_dict(), report_path=index_report)
    except (OSError, UnicodeError, RetrievalError, StrictQAError) as exc:''',
        '''        verification = verify_strict_packet(database, packet.to_dict(), report_path=index_report)
        hard_negative_failures = validate_hard_negative_outcome(
            database,
            parsed,
            packet,
            case.tags,
            source_id=case.source_id_filter,
        )
    except (OSError, UnicodeError, RetrievalError, StrictQAError) as exc:''',
    )
    replace_once(
        benchmark,
        '''    if not integrity:
        reasons.append("STRICT_PACKET_RECOMPUTATION_FAILED")

    if case.expected_decision == "answered":''',
        '''    if not integrity:
        reasons.append("STRICT_PACKET_RECOMPUTATION_FAILED")
    reasons.extend(hard_negative_failures)

    if case.expected_decision == "answered":''',
    )
    replace_once(
        benchmark,
        '''    exact = decision_correct and claim_correct and citations_correct and integrity and predicate_correct''',
        '''    exact = (
        decision_correct
        and claim_correct
        and citations_correct
        and integrity
        and predicate_correct
        and not hard_negative_failures
    )''',
    )
    replace_once(
        benchmark,
        '''        "evaluator_error_count": sum(result.actual_decision == "evaluator_error" for result in results),
    }''',
        '''        "evaluator_error_count": sum(result.actual_decision == "evaluator_error" for result in results),
        "hard_negative_validation_error_count": sum(
            any(code.startswith("HARD_NEGATIVE_EVIDENCE_NOT_ESTABLISHED:") for code in result.reason_codes)
            for result in results
        ),
    }''',
    )

    tests = Path("tests/test_gold_benchmark.py")
    replace_once(
        tests,
        '"来客共有10名。来客共有12名。"',
        '"来客共有100名。来客共有1000名。"',
    )
    replace_once(
        tests,
        '{"evidence": "来客共有10名。", "claim_type": "count", "subject": "来客", "value": 10, "unit": "名"},',
        '{"evidence": "来客共有100名。", "claim_type": "count", "subject": "来客", "value": 100, "unit": "名"},',
    )
    replace_once(
        tests,
        '{"evidence": "来客共有12名。", "claim_type": "count", "subject": "来客", "value": 12, "unit": "名"},',
        '{"evidence": "来客共有1000名。", "claim_type": "count", "subject": "来客", "value": 1000, "unit": "名"},',
    )

    adversarial = Path("tests/test_gold_benchmark_adversarial.py")
    marker = '''    def test_smoke_report_cannot_satisfy_required_release_profile(self):
'''
    insertion = '''    def test_relation_direction_tag_requires_reverse_fact_in_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, gold, rows = self.make_benchmark(root)
            spoofed = deepcopy(rows)
            direction = next(row for row in spoofed if row["case_id"] == "R-DIRECTION")
            direction["question"] = "王五击败了谁？"
            self.write_rows(gold, spoofed)
            report = evaluate_gold_benchmark(paths[4], gold, profile="smoke")
        self.assertFalse(report.passed)
        self.assertEqual(report.metrics["hard_negative_validation_error_count"], 1)
        self.assertIn(
            "METRIC_HARD_NEGATIVE_VALIDATION_ERROR_COUNT_ABOVE_POLICY_CEILING",
            report.blockers,
        )

    def test_smoke_report_cannot_satisfy_required_release_profile(self):
'''
    replace_once(adversarial, marker, insertion)


if __name__ == "__main__":
    main()
