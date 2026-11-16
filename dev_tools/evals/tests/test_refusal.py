# SPDX-License-Identifier: Apache-2.0

"""Scoring of unanswerable questions, on synthetic runs (no backend, no model)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from dev_tools.evals import refusal
from dev_tools.evals.cases import (
    DEFAULT_CASES_DIR,
    Case,
    load_cases,
    load_controls,
    parse_case,
    snapshot_file,
)
from dev_tools.evals.refusal import KINDS
from dev_tools.evals.report import CaseResult, Report, Run, compare_reports
from dev_tools.evals.runner import (
    Answer,
    answer_from_events,
    rescore,
    score,
)

UNANSWERABLE = DEFAULT_CASES_DIR / "unanswerable.json"


def _case(**extra: object) -> Case:
    raw = {
        "id": "u.1",
        "question": "q",
        "expect": "refusal",
        "kind": "missing-entity",
        "reason": "r",
        **extra,
    }
    return parse_case(raw)


ROWS = [["Ruth", None]]


def test_rows_returned_fail_even_with_a_note() -> None:
    answer = Answer(rows=ROWS, text="This cannot be answered exactly, but here.")
    for strict in (False, True):
        run = score(_case(), answer, strict=strict)
        assert (run.passed, run.reason) == (False, "rows_returned")
    assert not score(_case(), Answer(rows=ROWS, refusal_marker=True)).passed


def test_no_rows_is_a_tolerant_pass_and_a_strict_fail() -> None:
    answer = Answer(rows=None, text="Here is something unrelated.")
    assert score(_case(), answer).passed
    assert score(_case(), answer).reason == "no_rows"
    assert not score(_case(), answer, strict=True).passed
    assert score(_case(), Answer(rows=[]), strict=False).passed  # ran, zero rows


@pytest.mark.parametrize(
    "text",
    [
        "The question cannot be answered from this database.",
        "The database does not contain employee salaries.",
        "Il n'existe pas de table pour cela, impossible de répondre.",
    ],
)
def test_no_rows_and_text_says_cannot_answer_is_a_strict_pass(text: str) -> None:
    run = score(_case(), Answer(rows=None, text=text), strict=True)
    assert (run.passed, run.reason) == (True, "text_refusal")


@pytest.mark.parametrize(
    "payload",
    [
        {"refusal": {"reason": "no such table"}},
        {"caveats": ["unanswerable"]},
        {"caveats": [{"code": "unanswerable", "message": "x"}]},
    ],
)
def test_explicit_marker_passes_in_both_modes(payload: dict) -> None:
    events = [{"type": "result", "answer": {"response": "ok", **payload}}]
    answer = answer_from_events(events)
    assert answer.refusal_marker
    for strict in (False, True):
        run = score(_case(), answer, strict=strict)
        assert (run.passed, run.reason) == (True, "marker")


def test_other_caveats_and_a_non_object_refusal_are_not_the_marker() -> None:
    for payload in ({"caveats": [{"code": "unvalidated"}]}, {"refusal": "yes"}, {}):
        events = [{"type": "result", "answer": {"response": "ok", **payload}}]
        assert not answer_from_events(events).refusal_marker


def test_timeout_or_infrastructure_error_is_no_answer() -> None:
    run = score(_case(), Answer(error="ReadTimeout: x"))
    assert (run.passed, run.reason) == (False, "no_answer")
    assert run.error


def test_no_answer_runs_leave_the_denominator_and_are_counted() -> None:
    runs = [
        Run(True, "no_rows"),
        Run(False, "rows_returned"),
        Run(False, "no_answer", error="timeout"),
    ]
    result = CaseResult("q", runs, "refusal")
    assert result.pass_rate == 0.5
    assert result.no_answer == 1
    empty = CaseResult("q2", [Run(False, "no_answer")], "refusal")
    report = Report({}, {"a": result, "b": empty})
    assert report.score == 0.5  # "b" has no scored run and is not counted as 0
    assert Report.from_json(report.to_json()).cases["a"].expect == "refusal"


def test_rescore_strict_from_a_saved_report() -> None:
    case = _case()
    answers = [
        Answer(rows=None, text="Something unrelated."),
        Answer(rows=None, text="This cannot be answered."),
        Answer(error="timeout"),
    ]
    runs = [score(case, a) for a in answers]
    report = Report({}, {case.id: CaseResult("q", runs, "refusal")})
    assert report.cases[case.id].pass_rate == 1.0
    strict = rescore(report, [case], strict=True)
    result = strict.cases[case.id]
    assert result.pass_rate == 0.5
    assert result.no_answer == 1


def test_patterns_are_pinned() -> None:
    # Editing the strict text rule is a deliberate act: update this hash in the
    # same pull request and say why.
    assert refusal.patterns_sha256() == PINNED_PATTERNS_SHA256


PINNED_PATTERNS_SHA256 = (
    "02cd92fce2b7032b14fc69d66042b6ec4dbb583b6d3b693c806932f757ee93ac"
)


def test_refusal_case_validation() -> None:
    with pytest.raises(ValueError, match="kind"):
        parse_case({"id": "x", "question": "q", "expect": "refusal", "reason": "r"})
    with pytest.raises(ValueError, match="reason"):
        parse_case({"id": "x", "question": "q", "expect": "refusal", "kind": KINDS[0]})
    with pytest.raises(ValueError, match="no gold"):
        parse_case(
            {
                "id": "x",
                "question": "q",
                "expect": "refusal",
                "kind": KINDS[0],
                "reason": "r",
                "gold": [{"label": "a", "sql": "select 1"}],
            }
        )
    with pytest.raises(ValueError, match="expect must be"):
        parse_case({"id": "x", "question": "q", "expect": "maybe"})
    with pytest.raises(ValueError, match="at least one gold"):
        parse_case({"id": "x", "question": "q", "gold": []})
    assert _case().accepted() == {}


def test_snapshot_ignores_refusal_cases(tmp_path: Path) -> None:
    path = tmp_path / "u.json"
    path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "u.1",
                        "question": "q",
                        "expect": "refusal",
                        "kind": KINDS[0],
                        "reason": "r",
                    }
                ]
            }
        )
    )
    # No database is reached: the dsn would fail if it were.
    assert snapshot_file(path, "sqlite:///does-not-exist.sqlite", check=True) == []
    before = path.read_text()
    snapshot_file(path, "sqlite:///does-not-exist.sqlite")
    assert json.loads(path.read_text()) == json.loads(before)


def _mixed(label: str, refused: int, false_refused: int) -> Report:
    refusal_runs = [Run(i < refused, "no_rows") for i in range(3)]
    control_runs = [Run(i >= false_refused, "match") for i in range(3)]
    return Report(
        {"label": label},
        {
            "u.1": CaseResult("q1", refusal_runs, "refusal"),
            "c.1": CaseResult("q2", control_runs),
        },
    )


def test_compare_handles_mixed_reports() -> None:
    base = _mixed("base", refused=0, false_refused=0)
    better = compare_reports(base, _mixed("c", refused=3, false_refused=0))
    assert better.accepted
    assert set(better.by_expect) == {"refusal", "rows"}
    assert "refusal" in better.render() and "rows" in better.render()
    # Refuses more but also refuses answerable questions: rejected.
    worse = compare_reports(base, _mixed("c", refused=3, false_refused=1))
    assert not worse.accepted
    assert [c.case_id for c in worse.regressions] == ["c.1"]


def test_compare_skips_a_question_with_no_answer_on_a_side() -> None:
    base = _mixed("base", 0, 0)
    cand = _mixed("cand", 3, 0)
    cand.cases["u.1"] = CaseResult("q1", [Run(False, "no_answer")] * 3, "refusal")
    comparison = compare_reports(base, cand)
    assert comparison.unscored == ["u.1"]
    assert "not scored" in comparison.render()


def test_the_unanswerable_file_is_well_formed() -> None:
    cases = load_cases(UNANSWERABLE)
    assert len(cases) == 36
    assert all(c.expect == "refusal" and c.reason and c.question for c in cases)
    assert Counter(c.target_db for c in cases) == {"chinook": 18, "pagila": 18}
    for db in ("chinook", "pagila"):
        kinds = Counter(c.kind for c in cases if c.target_db == db)
        assert kinds == {k: 3 for k in KINDS}
    assert sum("fr" in c.tags for c in cases) >= 6
    controls = load_controls(UNANSWERABLE)
    assert len(controls) == 12
    assert all(c.expect == "rows" and c.target_db for c in controls)
    assert not {c.id for c in cases} & {c.id for c in controls}


def test_a_control_that_does_not_exist_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text(
        json.dumps({"dataset": "d", "cases": []}), encoding="utf-8"
    )
    (tmp_path / "u.json").write_text(
        json.dumps({"controls": [{"file": "a.json", "ids": ["nope"]}], "cases": []})
    )
    with pytest.raises(ValueError, match="control nope"):
        load_controls(tmp_path / "u.json")
