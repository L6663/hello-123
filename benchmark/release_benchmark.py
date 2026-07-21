from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Any

from tkr.chunking import UnitSpan
from tkr.claim_validation import ClaimCandidate, validate_claim
from tkr.entity_cli import _publish
from tkr.entity_normalization import normalize_entities
from tkr.gold_benchmark import GOLD_SCHEMA_VERSION, evaluate_gold_benchmark, verify_benchmark_report
from tkr.hybrid_retrieval import build_hybrid_index, parse_predicate_query
from tkr.strict_qa import answer_strict

SOURCE_ID = "release-novel-v1"
BENCHMARK_VERSION = "tkr-release-gold-v1"
CASE_SPEC_VERSION = "tkr-release-case-specs-v1"
CANONICAL_CASE_SPECS_SHA256 = "fbdfa21f1ef00ccb514a7db53560bb5937970930bf2abdb9b4916499edb624d2"
CANONICAL_GOLD_SHA256 = "859b2710c10bdbcb0f1a2f0a1f7e598e003d9bb507e57ed02496278e838ab22f"

ALIASES = (
    ("北门", "玄门"), ("西门", "白门"), ("东塔", "曙塔"), ("南桥", "赤桥"),
    ("古港", "新港"), ("星台", "天台"), ("云阁", "雾阁"), ("石关", "铁关"),
)
DEFEATS = (
    ("张三", "李四"), ("赵云", "王五"), ("陆川", "周明"), ("林岳", "陈河"),
    ("苏白", "沈青"), ("顾寒", "唐远"), ("叶舟", "韩石"), ("秦野", "宋风"),
)
LOCATIONS = (
    ("玄门", "皇城北侧"), ("白门", "皇城西侧"), ("曙塔", "东海岸"), ("赤桥", "南河口"),
    ("新港", "云州湾"), ("天台", "群星山"), ("雾阁", "青岚谷"), ("铁关", "黑石岭"),
)
COUNTS = (
    ("守卫", 100), ("学徒", 64), ("工匠", 32), ("船员", 88),
    ("医师", 24), ("骑兵", 120), ("信使", 16), ("侍从", 40),
)
DATES = (
    ("北城工程", "2001-02-03"), ("西港工程", "2002-03-04"),
    ("东塔工程", "2003-04-05"), ("南桥工程", "2004-05-06"),
    ("云阁工程", "2005-06-07"), ("星台工程", "2006-07-08"),
    ("石关工程", "2007-08-09"), ("古港工程", "2008-09-10"),
)
PERMISSIONS = (
    ("档案系统", "删除", True), ("访客系统", "登记", True),
    ("仓库系统", "入库", True), ("航运系统", "调度", True),
    ("文库系统", "导出", False), ("门禁系统", "复制", False),
    ("财务系统", "篡改", False), ("医疗系统", "外传", False),
)
CONTESTED = (
    ("来客甲", 100, 1000), ("来客乙", 20, 200), ("来客丙", 7, 70),
    ("来客丁", 45, 46), ("来客戊", 52, 53), ("来客己", 61, 63),
    ("来客庚", 71, 72), ("来客辛", 81, 82), ("来客壬", 91, 92),
    ("来客癸", 111, 112),
)
TEMPORAL = (
    ("护卫甲", 10, 11), ("护卫乙", 20, 21), ("护卫丙", 30, 31),
    ("护卫丁", 40, 41), ("护卫戊", 50, 51), ("护卫己", 60, 61),
    ("护卫庚", 70, 71), ("护卫辛", 80, 81), ("护卫壬", 90, 91),
    ("护卫癸", 100, 101),
)

UNSUPPORTED_MORE = (
    "西门为何关闭？", "东塔是谁建造的？", "南桥有什么传说？", "古港为何衰落？",
    "星台代表什么？", "云阁为什么被封锁？", "石关是谁命名的？", "李四为什么失败？",
    "王五后来去了哪里之外的地方？", "周明的性格如何？", "陈河真正害怕什么？",
    "沈青为何沉默？", "唐远是否值得信任？", "韩石的动机是什么？",
    "宋风改变了什么？", "北城工程有什么历史意义？", "档案系统为什么存在？",
)
INSUFFICIENT_MORE = (
    ("北门有多少名？", "count"), ("西门有多少名？", "count"),
    ("东塔什么时候开始？", "date"), ("南桥什么时候开始？", "date"),
    ("张三位于哪里？", "located_in"), ("赵云位于哪里？", "located_in"),
    ("守卫位于哪里？", "located_in"), ("学徒什么时候开始？", "date"),
    ("北城工程位于哪里？", "located_in"), ("文库系统有多少名？", "count"),
    ("铁关允许删除吗？", "permission"),
)


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def claim(evidence: str, claim_type: str, subject: str, **fields: Any) -> dict[str, Any]:
    return {
        "evidence": evidence,
        "claim_type": claim_type,
        "subject": subject,
        "object": str(fields.get("object", "")),
        "value": fields.get("value"),
        "unit": str(fields.get("unit", "")),
        "polarity": bool(fields.get("polarity", True)),
    }


def corpus_spec() -> list[tuple[str, list[dict[str, Any]]]]:
    rows: list[tuple[str, list[dict[str, Any]]]] = []
    for (subject, alias), (location_subject, place) in zip(ALIASES, LOCATIONS):
        if alias != location_subject:
            raise RuntimeError("alias/location fixture mismatch")
        alias_text = f"{subject}后来改称{alias}。"
        location_text = f"{location_subject}位于{place}。"
        rows.append((
            alias_text + location_text,
            [
                claim(alias_text, "alias", subject, object=alias),
                claim(location_text, "located_in", location_subject, object=place),
            ],
        ))
    for subject, object_value in DEFEATS:
        text = f"{subject}击败{object_value}。"
        rows.append((text, [claim(text, "defeats", subject, object=object_value)]))
    for subject, value in COUNTS:
        text = f"{subject}共有{value}名。"
        rows.append((text, [claim(text, "count", subject, value=value, unit="名")]))
    for subject, value in DATES:
        text = f"{subject}始于{value}。"
        rows.append((text, [claim(text, "date", subject, value=value)]))
    for subject, action, polarity in PERMISSIONS:
        text = f"{subject}{'允许' if polarity else '禁止'}{action}。"
        rows.append((text, [claim(text, "permission", subject, object=action, polarity=polarity)]))
    for subject, first, second in CONTESTED:
        first_text, second_text = f"{subject}共有{first}名。", f"{subject}共有{second}名。"
        rows.append((
            first_text + second_text,
            [
                claim(first_text, "count", subject, value=first, unit="名"),
                claim(second_text, "count", subject, value=second, unit="名"),
            ],
        ))
    for subject, first, second in TEMPORAL:
        first_text, second_text = f"{subject}共有{first}名。", f"后来{subject}共有{second}名。"
        rows.append((
            first_text + second_text,
            [
                claim(first_text, "count", subject, value=first, unit="名"),
                claim(second_text, "count", subject, value=second, unit="名"),
            ],
        ))
    return rows


def expected_claim(
    question: str,
    predicate: str,
    subject: str,
    *,
    object_value: str = "",
    value: object = None,
    unit: str = "",
    scope: str = "",
    fact_polarity: bool = True,
    boolean_answer: bool | None = None,
) -> dict[str, object]:
    parsed = parse_predicate_query(question)
    if not parsed.supported or parsed.predicate != predicate:
        raise RuntimeError(f"parser drift: {question}")
    return {
        "predicate": predicate,
        "requested_role": parsed.requested_role,
        "subject": subject,
        "object": object_value,
        "value": value,
        "unit": unit,
        "predicate_scope": scope,
        "fact_polarity": fact_polarity,
        "boolean_answer": boolean_answer,
        "temporal_scope": parsed.temporal_scope,
    }


def answer_case(case_id: str, question: str, predicate: str, answer: dict[str, object], *tags: str) -> dict[str, object]:
    return {
        "case_id": case_id,
        "question": question,
        "expected_decision": "answered",
        "expected_predicate": predicate,
        "expected_answer_claim": answer,
        "tags": list(tags),
    }


def refusal_case(case_id: str, question: str, decision: str, predicate: str, *tags: str) -> dict[str, object]:
    return {
        "case_id": case_id,
        "question": question,
        "expected_decision": decision,
        "expected_predicate": predicate,
        "expected_answer_claim": None,
        "tags": list(tags),
    }


def case_specs() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for i, (subject, alias) in enumerate(ALIASES, 1):
        q = f"{subject}后来叫什么？"
        cases.append(answer_case(f"A-ALIAS-{i:02d}", q, "alias", expected_claim(q, "alias", subject, object_value=alias, scope="identity"), "answerable", "alias"))
    for i, (subject, obj) in enumerate(DEFEATS, 1):
        q = f"{subject}击败了谁？"
        cases.append(answer_case(f"A-DEFEATS-{i:02d}", q, "defeats", expected_claim(q, "defeats", subject, object_value=obj, scope="defeats"), "answerable", "defeats"))
    for i, (subject, obj) in enumerate(LOCATIONS, 1):
        q = f"{subject}位于哪里？"
        cases.append(answer_case(f"A-LOCATION-{i:02d}", q, "located_in", expected_claim(q, "located_in", subject, object_value=obj, scope="location"), "answerable", "located_in"))
    for i, (subject, value) in enumerate(COUNTS, 1):
        q = f"{subject}有多少名？"
        cases.append(answer_case(f"A-COUNT-{i:02d}", q, "count", expected_claim(q, "count", subject, value=value, unit="名", scope="count:名"), "answerable", "count"))
    for i, (subject, value) in enumerate(DATES, 1):
        q = f"{subject}什么时候开始？"
        cases.append(answer_case(f"A-DATE-{i:02d}", q, "date", expected_claim(q, "date", subject, value=value, scope="start_date"), "answerable", "date"))
    for i, (subject, action, polarity) in enumerate(PERMISSIONS, 1):
        q = f"{subject}允许{action}吗？"
        cases.append(answer_case(
            f"A-PERMISSION-{i:02d}", q, "permission",
            expected_claim(q, "permission", subject, object_value=action, scope=f"permission:{action}", fact_polarity=polarity, boolean_answer=polarity),
            "answerable", "permission", "explicit_positive" if polarity else "explicit_negative",
        ))

    for i, question in enumerate(("北门是谁设计的？", "张三为什么远行？", "玄门象征什么？"), 1):
        cases.append(refusal_case(f"R-UNSUPPORTED-HARD-{i:02d}", question, "refused_unsupported", "unsupported", "entity_only_no_predicate", "unsupported_open_predicate"))
    for i, question in enumerate(UNSUPPORTED_MORE, 1):
        cases.append(refusal_case(f"R-UNSUPPORTED-{i:02d}", question, "refused_unsupported", "unsupported", "unsupported_open"))

    for i, question in enumerate(("李四击败了谁？", "王五击败了谁？", "周明击败了谁？"), 1):
        cases.append(refusal_case(f"R-INSUFFICIENT-DIRECTION-{i:02d}", question, "refused_insufficient_evidence", "defeats", "relation_direction"))
    for i, question in enumerate(("玄门有多少层？", "白门有多少层？", "曙塔有多少层？"), 1):
        cases.append(refusal_case(f"R-INSUFFICIENT-LEXICAL-{i:02d}", question, "refused_insufficient_evidence", "count", "lexical_distractor"))
    for i, question in enumerate(("档案系统允许进入吗？", "访客系统允许删除吗？", "仓库系统允许导出吗？"), 1):
        cases.append(refusal_case(f"R-INSUFFICIENT-ABSENCE-{i:02d}", question, "refused_insufficient_evidence", "permission", "absence_not_negative"))
    for i, (question, predicate) in enumerate(INSUFFICIENT_MORE, 1):
        cases.append(refusal_case(f"R-INSUFFICIENT-{i:02d}", question, "refused_insufficient_evidence", predicate, "missing_typed_fact"))

    for i, (subject, _, _) in enumerate(CONTESTED, 1):
        tags = ("contested_fact", "numeric_prefix") if i <= 3 else ("ambiguous_contested",)
        cases.append(refusal_case(f"R-AMBIGUOUS-CONTESTED-{i:02d}", f"{subject}有多少名？", "refused_ambiguous", "count", *tags))
    for i, (subject, _, _) in enumerate(TEMPORAL, 1):
        tags = ("temporal_scope",) if i <= 3 else ("ambiguous_temporal",)
        cases.append(refusal_case(f"R-AMBIGUOUS-TEMPORAL-{i:02d}", f"{subject}有多少名？", "refused_ambiguous", "count", *tags))

    if len(cases) != 108:
        raise RuntimeError(f"expected 108 curated cases, got {len(cases)}")
    return cases


def build_project(output: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    spec = corpus_spec()
    texts = [text for text, _ in spec]
    source = "".join(texts)
    source_path = output / "normalized-text.txt"
    source_path.write_text(source, encoding="utf-8")

    units: list[UnitSpan] = []
    offset = 0
    for i, text in enumerate(texts, 1):
        units.append(UnitSpan(f"chapter-{i:03d}", offset, offset + len(text), SOURCE_ID))
        offset += len(text)

    units_path = output / "unit-index.csv"
    with units_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source_id", "unit_id", "norm_start", "norm_end"])
        writer.writeheader()
        for unit in units:
            writer.writerow({"source_id": unit.source_id, "unit_id": unit.unit_id, "norm_start": unit.start, "norm_end": unit.end})

    records: list[dict[str, object]] = []
    line = 0
    for unit_index, (_, claims) in enumerate(spec):
        unit = units[unit_index]
        cursors: dict[str, int] = {}
        for item in claims:
            line += 1
            evidence = str(item["evidence"])
            start = source.find(evidence, cursors.get(evidence, unit.start), unit.end)
            if start < 0:
                raise RuntimeError(f"missing evidence: {evidence}")
            cursors[evidence] = start + 1
            candidate = ClaimCandidate(
                claim_type=str(item["claim_type"]), subject=str(item["subject"]),
                object=str(item.get("object", "")), value=item.get("value"),
                unit=str(item.get("unit", "")), polarity=bool(item.get("polarity", True)),
                source_id=SOURCE_ID, unit_id=unit.unit_id, evidence_start=start,
                evidence_end=start + len(evidence), evidence_text=evidence,
            )
            result = validate_claim(candidate, source, unit_span=unit, require_unit=True)
            if result.status != "accepted":
                raise RuntimeError(f"curated Claim rejected: {evidence}: {result.reason_codes}")
            records.append({"candidate_line": line, "candidate": candidate.to_dict(), "validation": result.to_dict()})

    accepted_path = output / "claims.accepted.jsonl"
    accepted_path.write_text("".join(canonical(row) + "\n" for row in records), encoding="utf-8")
    entity_dir = output / "entities"
    bundle = normalize_entities(records, source, units)
    _publish(bundle, entity_dir, accepted_path=accepted_path, identity_links_path=None, units_path=units_path)
    database = output / "knowledge.sqlite3"
    index_report = output / "knowledge.report.json"
    build_hybrid_index(source_path, units_path, accepted_path, entity_dir, database, index_mode="review", source_id=SOURCE_ID, report_path=index_report)
    return source_path, units_path, accepted_path, entity_dir, database, index_report


def compile_gold(database: Path, specs: list[dict[str, object]], output: Path) -> Path:
    rows: list[dict[str, object]] = []
    for spec in specs:
        question = str(spec["question"])
        parsed = parse_predicate_query(question)
        if parsed.predicate != spec["expected_predicate"]:
            raise RuntimeError(f"parser drift for {spec['case_id']}")
        packet = answer_strict(database, question, retrieval_limit=100, max_citations=20)
        if packet.decision != spec["expected_decision"]:
            raise RuntimeError(f"decision drift for {spec['case_id']}: {packet.decision}")
        actual_claim = packet.answer_claim.to_dict() if packet.answer_claim else None
        if canonical(actual_claim) != canonical(spec["expected_answer_claim"]):
            raise RuntimeError(f"answer Claim drift for {spec['case_id']}")
        rows.append({
            "gold_schema_version": GOLD_SCHEMA_VERSION,
            "case_id": spec["case_id"], "question": question,
            "expected_decision": spec["expected_decision"],
            "expected_predicate": spec["expected_predicate"],
            "expected_answer_claim": spec["expected_answer_claim"],
            "expected_fact_ids": [citation.fact_id for citation in packet.citations],
            "expected_evidence_sha256": [citation.evidence_sha256 for citation in packet.citations],
            "source_id_filter": None, "tags": spec["tags"],
        })
    path = output / "gold-release.jsonl"
    path.write_text("".join(canonical(row) + "\n" for row in rows), encoding="utf-8")
    return path


def run_release(output: Path) -> dict[str, object]:
    _, _, _, _, database, index_report = build_project(output)
    specs = case_specs()
    specs_sha256 = sha256(canonical(specs).encode("utf-8")).hexdigest()
    if specs_sha256 != CANONICAL_CASE_SPECS_SHA256:
        raise RuntimeError("curated case specifications differ from the canonical release commitment")
    gold = compile_gold(database, specs, output)
    gold_sha256 = digest(gold)
    if gold_sha256 != CANONICAL_GOLD_SHA256:
        raise RuntimeError("candidate-generated Gold differs from the fixed canonical release commitment")
    report = evaluate_gold_benchmark(database, gold, profile="release", report_path=index_report)
    report_path = output / "release-report.json"
    report_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verification = verify_benchmark_report(database, gold, report_path, index_report_path=index_report, expected_profile="release")
    verification_path = output / "release-verification.json"
    verification_path.write_text(json.dumps(verification.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not report.passed or not report.may_certify_release:
        raise RuntimeError(f"release policy failed: {report.blockers}")
    if not verification.accepted:
        raise RuntimeError(f"release verification failed: {verification.reason_codes}")

    file_names = (
        "normalized-text.txt", "unit-index.csv", "claims.accepted.jsonl",
        "knowledge.sqlite3", "knowledge.report.json", "gold-release.jsonl",
        "release-report.json", "release-verification.json",
    )
    manifest = {
        "benchmark_version": BENCHMARK_VERSION,
        "case_spec_version": CASE_SPEC_VERSION,
        "source_id": SOURCE_ID,
        "case_count": len(specs),
        "case_specs_sha256": specs_sha256,
        "canonical_gold_sha256": CANONICAL_GOLD_SHA256,
        "coverage": report.coverage,
        "metrics": report.metrics,
        "report_id": report.report_id,
        "governance": {
            "expected_decisions_and_claims": "first-party manually curated case families",
            "fact_ids_and_evidence_hashes": "candidate output must reproduce the fixed canonical Gold SHA-256 exactly",
            "independent_external_annotation": False,
            "open_domain_claim": False,
            "may_freeze": False,
        },
        "files": {name: digest(output / name) for name in file_names},
    }
    (output / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and verify the versioned v5.7 Release Gold benchmark.")
    parser.add_argument("--output", type=Path, default=Path("build/release-benchmark"))
    args = parser.parse_args()
    print(json.dumps(run_release(args.output), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
