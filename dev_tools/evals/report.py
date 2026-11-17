# SPDX-License-Identifier: Apache-2.0

"""A per-question report, and a paired comparison of two of them.

The comparison is *paired*: the same question, before and after, so a change is
judged on the questions it moved rather than on an aggregate that can hide a
regression behind an improvement. Each question is run several times because
generation is not deterministic; its score is the share of runs that passed.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Run:
    passed: bool
    reason: str
    matched: str | None = None
    sql: str | None = None
    rows: int | None = None
    seconds: float = 0.0
    error: str | None = None
    # The executed rows (capped), kept so a report can be re-scored under a
    # different convention without running the questions again. Reports written
    # before this field existed load with ``None``.
    actual: list[list[Any]] | None = None
    # Which business knowledge generation was offered and the SQL appears to
    # have used (``auto_ontology.retrieval.text_to_sql.knowledge_trace``). None
    # for reports written before the field existed.
    knowledge_trace: list[dict[str, Any]] | None = None
    # The language the question was detected in its text in the ontology language, and that language, recorded
    # when question translation ran. None for older reports.
    question_language: str | None = None
    question_translated: str | None = None
    ontology_language: str | None = None
    # Kept so a refusal run can be re-scored strict or tolerant (see
    # dev_tools.evals.refusal): the answer text and whether it carried the
    # explicit refusal marker. None for reports written before the field.
    text: str | None = None
    refusal_marker: bool | None = None


@dataclass
class CaseResult:
    question: str
    runs: list[Run] = field(default_factory=list)
    # "rows" (answerable) or "refusal" (the database cannot answer it).
    expect: str = "rows"

    @property
    def scored_runs(self) -> list[Run]:
        """Runs that count: a ``no_answer`` run (timeout, infrastructure) does not."""
        return [r for r in self.runs if r.reason != "no_answer"]

    @property
    def no_answer(self) -> int:
        return len(self.runs) - len(self.scored_runs)

    @property
    def pass_rate(self) -> float:
        scored = self.scored_runs
        return sum(r.passed for r in scored) / len(scored) if scored else 0.0


@dataclass
class Report:
    meta: dict[str, Any]
    cases: dict[str, CaseResult] = field(default_factory=dict)

    @property
    def score(self) -> float:
        """Mean pass rate over questions (each question counts once)."""
        counted = [c for c in self.cases.values() if c.scored_runs]
        if not counted:
            return 0.0
        return sum(c.pass_rate for c in counted) / len(counted)

    def to_json(self) -> dict[str, Any]:
        return {
            "meta": {**self.meta, "score": round(self.score, 4)},
            "cases": {
                cid: {
                    "question": c.question,
                    "pass_rate": round(c.pass_rate, 4),
                    **({"expect": c.expect} if c.expect != "rows" else {}),
                    "runs": [r.__dict__ for r in c.runs],
                }
                for cid, c in self.cases.items()
            },
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Report:
        cases = {
            cid: CaseResult(
                c["question"],
                [Run(**r) for r in c["runs"]],
                c.get("expect", "rows"),
            )
            for cid, c in data["cases"].items()
        }
        return cls(meta=data["meta"], cases=cases)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Report:
        return cls.from_json(json.loads(path.read_text(encoding="utf-8")))


def knowledge_agreement(report: Report) -> dict[str, int]:
    """How the trace's two signals relate over a report, as counts (information only).

    ``declared`` is the model's own account of what it applied and
    ``found_in_sql`` the text match on the final SQL. Entries without both
    (an older report, the flag off, or an undecided match) are counted as
    ``undecided``. No threshold belongs on this number.
    """
    counts = {"agree": 0, "declared_only": 0, "found_only": 0, "undecided": 0}
    for case in report.cases.values():
        for run in case.runs:
            for entry in run.knowledge_trace or []:
                declared, found = entry.get("declared"), entry.get("found_in_sql")
                if declared is None or found is None:
                    counts["undecided"] += 1
                elif declared == found:
                    counts["agree"] += 1
                else:
                    counts["declared_only" if declared else "found_only"] += 1
    return counts


def merge_reports(label: str, reports: list[Report]) -> Report:
    """Combine partial reports; a case present in a later report replaces earlier ones.

    Used to patch a baseline when only some questions had to be re-run (for
    example after an infrastructure outage or a scoring fix).
    """
    cases: dict[str, CaseResult] = {}
    for report in reports:
        cases.update(report.cases)
    meta = new_meta(
        label,
        merged_from=[r.meta.get("label") for r in reports],
        **_merged_provenance(reports),
    )
    return Report(meta=meta, cases=cases)


def _merged_provenance(reports: list[Report]) -> dict[str, Any]:
    """Keep what every part recorded about its conditions, and drop the rest.

    A merged report is only as well documented as its least documented part, so a
    field missing from any part is left out (reads as "unknown") rather than
    letting the parts that have it vouch for the whole.
    """
    out: dict[str, Any] = {}
    if all("cases_sha256" in r.meta for r in reports):
        hashes = sorted(
            {
                h
                for r in reports
                for h in (
                    [r.meta["cases_sha256"]]
                    if isinstance(r.meta["cases_sha256"], str)
                    else r.meta["cases_sha256"]
                )
            }
        )
        out["cases_sha256"] = hashes[0] if len(hashes) == 1 else hashes
    if all(isinstance(r.meta.get("ontology_index"), list) for r in reports):
        out["ontology_index"] = [e for r in reports for e in r.meta["ontology_index"]]
    return out


def git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).parent,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def new_meta(label: str, **extra: Any) -> dict[str, Any]:
    return {
        "label": label,
        "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        **extra,
    }


@dataclass
class Change:
    case_id: str
    question: str
    base: float
    candidate: float

    @property
    def delta(self) -> float:
        return self.candidate - self.base


@dataclass
class Comparison:
    base_score: float
    candidate_score: float
    regressions: list[Change]
    improvements: list[Change]
    unchanged: int
    only_in_base: list[str]
    only_in_candidate: list[str]
    margin: float
    tolerance: float
    # Mean pass rate per kind of case when a report mixes answerable ("rows") and
    # unanswerable ("refusal") questions: {expect: (base, candidate, questions)}.
    by_expect: dict[str, tuple[float, float, int]] = field(default_factory=dict)
    # Questions left out of the scores because a side has no scored run
    # (every run a ``no_answer``).
    unscored: list[str] = field(default_factory=list)

    @property
    def delta(self) -> float:
        return self.candidate_score - self.base_score

    @property
    def accepted(self) -> bool:
        """A candidate is accepted when it gains at least the margin overall and
        regresses no question beyond the tolerance."""
        return self.delta >= self.margin and not self.regressions

    def render(self) -> str:
        lines = [
            f"base       {self.base_score:6.1%}",
            f"candidate  {self.candidate_score:6.1%}  ({self.delta:+.1%}, "
            f"required >= {self.margin:+.1%})",
            f"paired questions: {len(self.regressions) + len(self.improvements) + self.unchanged}"
            f"  improved {len(self.improvements)}  regressed {len(self.regressions)}"
            f"  unchanged {self.unchanged}",
        ]
        if len(self.by_expect) > 1:
            for expect, (b, c, n) in sorted(self.by_expect.items()):
                lines.append(f"  {expect:8s} {b:6.1%} -> {c:6.1%}  ({n} questions)")
        if self.unscored:
            lines.append(
                f"not scored (no run with an answer on a side): {len(self.unscored)}"
            )
        for title, items in (
            ("REGRESSIONS", self.regressions),
            ("improvements", self.improvements),
        ):
            if items:
                lines.append(f"\n{title}")
                lines += [
                    f"  {c.base:4.0%} -> {c.candidate:4.0%}  {c.case_id}  {c.question}"
                    for c in sorted(items, key=lambda c: c.delta)
                ]
        for name, ids in (
            ("only in base", self.only_in_base),
            ("only in candidate", self.only_in_candidate),
        ):
            if ids:
                lines.append(f"\n{name} (not compared): {', '.join(sorted(ids))}")
        lines.append(f"\nverdict: {'ACCEPT' if self.accepted else 'REJECT'}")
        return "\n".join(lines)


def compare_reports(
    base: Report,
    candidate: Report,
    *,
    margin: float = 0.0,
    tolerance: float = 0.0,
) -> Comparison:
    """Pair two reports by case id.

    Scores are taken over the questions present in *both*, so adding a case does
    not move the comparison. A question *regresses* when its pass rate falls by
    more than *tolerance*; with three runs per question a tolerance of 0.34 lets
    one flaky run through but catches a real drop.
    """
    both = sorted(base.cases.keys() & candidate.cases.keys())
    shared = [
        c for c in both if base.cases[c].scored_runs and candidate.cases[c].scored_runs
    ]
    unscored = [c for c in both if c not in shared]
    regressions: list[Change] = []
    improvements: list[Change] = []
    unchanged = 0
    for cid in shared:
        change = Change(
            cid,
            candidate.cases[cid].question,
            base.cases[cid].pass_rate,
            candidate.cases[cid].pass_rate,
        )
        if change.delta < -tolerance - 1e-9:
            regressions.append(change)
        elif change.delta > tolerance + 1e-9:
            improvements.append(change)
        else:
            unchanged += 1

    def mean(report: Report) -> float:
        return (
            sum(report.cases[c].pass_rate for c in shared) / len(shared)
            if shared
            else 0.0
        )

    by_expect: dict[str, tuple[float, float, int]] = {}
    for expect in sorted({base.cases[c].expect for c in shared}):
        ids = [c for c in shared if base.cases[c].expect == expect]
        by_expect[expect] = (
            sum(base.cases[c].pass_rate for c in ids) / len(ids),
            sum(candidate.cases[c].pass_rate for c in ids) / len(ids),
            len(ids),
        )
    return Comparison(
        base_score=mean(base),
        candidate_score=mean(candidate),
        regressions=regressions,
        improvements=improvements,
        unchanged=unchanged,
        only_in_base=sorted(base.cases.keys() - candidate.cases.keys()),
        only_in_candidate=sorted(candidate.cases.keys() - base.cases.keys()),
        margin=margin,
        tolerance=tolerance,
        by_expect=by_expect,
        unscored=unscored,
    )
