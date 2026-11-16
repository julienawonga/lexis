# SPDX-License-Identifier: Apache-2.0

"""An append-only history of eval results, one JSON object per line.

``docs/eval-history/history.jsonl`` keeps a *summary* of each measurement worth
remembering: scores, the cases-file hash, per-question pass counts, the index
state. It never holds question text, gold answers, rows, SQL or credentials:
entries are built from a whitelist of fields, not copied from the report.

Entries seeded from ``docs/experiments.md`` carry ``"source": "experiments.md
(summary, no report kept)"`` and have no per-question detail, so ``check`` never
uses them as a baseline.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

from dev_tools.evals.provenance import report_case_hashes, report_index_state
from dev_tools.evals.report import Report, git_sha

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "docs/eval-history/history.jsonl"
SEED_SOURCE = "experiments.md (summary, no report kept)"
REPORT_SOURCE = "report"
_TOKEN_ENV = "INTERNAL_API_TOKEN"


class HistoryError(Exception):
    """A refused operation; the message says why."""


def _hash_field(report: Report) -> str | list[str] | None:
    hashes = report_case_hashes(report.meta)
    if hashes is None:
        return None
    ordered = sorted(hashes)
    return ordered[0] if len(ordered) == 1 else ordered


def build_entry(
    report: Report,
    *,
    note: str = "",
    strict_report: Report | None = None,
    backend_image: str | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Summarize *report*; only whitelisted fields, never text from the cases."""
    secret = os.environ.get(_TOKEN_ENV)
    if secret and secret in note:
        raise HistoryError("the note contains the internal API token; refused")
    meta = report.meta
    when = now or dt.datetime.now(dt.timezone.utc)
    return {
        "schema": 1,
        "source": REPORT_SOURCE,
        "label": str(meta.get("label", "")),
        "created": when.isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "report_git_sha": meta.get("git_sha"),
        "backend_image": backend_image or str(meta.get("backend_image") or "unknown"),
        "cases_file": meta.get("cases_file"),
        "cases_sha256": _hash_field(report),
        "strict_score": (
            round(strict_report.score, 4) if strict_report is not None else None
        ),
        "tolerant_score": round(report.score, 4),
        "per_question": {
            cid: [sum(r.passed for r in c.runs), len(c.runs)]
            for cid, c in sorted(report.cases.items())
        },
        "ontology_index": report_index_state(meta),
        "runs": max((len(c.runs) for c in report.cases.values()), default=0),
        "note": note,
    }


def append_entry(path: Path, entry: dict[str, Any]) -> None:
    """Append one line; the file is opened for append and never rewritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(line)


def read_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise HistoryError(f"{path.name} line {n} is not JSON: {exc}") from exc
    return out


def _hashes(value: Any) -> frozenset[str] | None:
    if isinstance(value, str):
        return frozenset({value})
    if isinstance(value, list) and value:
        return frozenset(str(v) for v in value)
    return None


def find_baseline(
    entries: list[dict[str, Any]], hashes: frozenset[str], against: str | None
) -> dict[str, Any]:
    """Latest entry with per-question detail and the same cases hash."""
    with_detail = [e for e in entries if e.get("per_question")]
    if against is not None:
        named = [e for e in with_detail if e.get("label") == against]
        if not named:
            raise HistoryError(
                f"no entry with per-question detail labelled {against!r}"
            )
        entry = named[-1]
        if _hashes(entry.get("cases_sha256")) != hashes:
            raise HistoryError(
                f"entry {against!r} was measured with a different cases file; "
                "not comparable"
            )
        return entry
    same = [e for e in with_detail if _hashes(e.get("cases_sha256")) == hashes]
    if not same:
        raise HistoryError(
            "no history entry with per-question detail and the same cases_sha256 "
            "as this report; not comparable (add a baseline with `history add`)"
        )
    return same[-1]


def check_report(
    report: Report,
    entries: list[dict[str, Any]],
    *,
    against: str | None = None,
    tolerance: float = 0.0,
) -> tuple[dict[str, Any], list[tuple[str, float, float]], list[str]]:
    """Return (baseline entry, regressions as (id, before, now), notes)."""
    hashes = report_case_hashes(report.meta)
    if hashes is None:
        raise HistoryError(
            "the report records no cases_sha256, so it cannot be matched to a "
            "history entry"
        )
    baseline = find_baseline(entries, hashes, against)
    regressions: list[tuple[str, float, float]] = []
    notes: list[str] = []
    prior: dict[str, list[int]] = baseline["per_question"]
    for cid in sorted(report.cases.keys() & prior.keys()):
        passes, runs = prior[cid]
        before = passes / runs if runs else 0.0
        now = report.cases[cid].pass_rate
        if now - before < -tolerance - 1e-9:
            regressions.append((cid, before, now))
    for name, ids in (
        ("only in history", sorted(prior.keys() - report.cases.keys())),
        ("only in report", sorted(report.cases.keys() - prior.keys())),
    ):
        if ids:
            notes.append(f"{name} (not compared): {', '.join(ids)}")
    return baseline, regressions, notes


def _cmd_add(args: Any) -> int:
    report = Report.load(Path(args.report))
    strict = Report.load(Path(args.strict_report)) if args.strict_report else None
    try:
        entry = build_entry(
            report,
            note=args.note,
            strict_report=strict,
            backend_image=args.backend_image,
        )
    except HistoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if entry["cases_sha256"] is None:
        print(
            "WARNING: report has no cases_sha256; `check` cannot match it",
            file=sys.stderr,
        )
    append_entry(Path(args.file), entry)
    print(f"appended {entry['label']!r} ({entry['tolerant_score']:.1%}) -> {args.file}")
    return 0


def _fmt(value: Any) -> str:
    return f"{value:.1%}" if isinstance(value, (int, float)) else "-"


def _cmd_show(args: Any) -> int:
    try:
        entries = read_entries(Path(args.file))
    except HistoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for e in entries:
        sha = e.get("cases_sha256")
        text = ",".join(sha) if isinstance(sha, list) else (sha or "")
        if args.cases_sha and not text.startswith(args.cases_sha):
            continue
        score = e.get("tolerant_score")
        if score is None and isinstance(e.get("score_percent"), (int, float)):
            score = e["score_percent"] / 100
        detail = "per-question" if e.get("per_question") else "summary only"
        print(
            f"{e.get('created') or e.get('date', '?'):<26} {e.get('label', ''):<34} "
            f"strict {_fmt(e.get('strict_score')):>6} tolerant {_fmt(score):>6} "
            f"[{e.get('kind', 'measured')}] {detail} cases {text[:12] or '-'}  "
            f"{e.get('source', '')}"
        )
    return 0


def _cmd_check(args: Any) -> int:
    try:
        entries = read_entries(Path(args.file))
        baseline, regressions, notes = check_report(
            Report.load(Path(args.report)),
            entries,
            against=args.against,
            tolerance=args.tolerance,
        )
    except HistoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"against {baseline.get('label')!r} ({baseline.get('created')})")
    for note in notes:
        print(note)
    if regressions:
        print("REGRESSIONS")
        for cid, before, now in regressions:
            print(f"  {before:4.0%} -> {now:4.0%}  {cid}")
        return 1
    print("no per-question regression beyond the tolerance")
    return 0


def add_parser(sub: Any) -> None:
    hist = sub.add_parser("history", help="append-only history of eval summaries")
    hist.add_argument(
        "--file",
        default=str(DEFAULT_FILE),
        help="history file (default docs/eval-history/history.jsonl)",
    )
    steps = hist.add_subparsers(dest="history_command", required=True)
    add = steps.add_parser("add", help="append a summary of a report")
    add.add_argument("report")
    add.add_argument("--note", default="")
    add.add_argument(
        "--strict-report", help="the same runs re-scored with `rescore --strict`"
    )
    add.add_argument("--backend-image", help="image tag or id the backend ran from")
    add.set_defaults(func=_cmd_add)
    show = steps.add_parser("show", help="list entries")
    show.add_argument(
        "--cases-sha", help="only entries whose cases hash starts with this"
    )
    show.set_defaults(func=_cmd_show)
    chk = steps.add_parser("check", help="exit 1 on a per-question regression")
    chk.add_argument("report")
    chk.add_argument("--against", help="label of the entry to compare with")
    chk.add_argument("--tolerance", type=float, default=0.0)
    chk.set_defaults(func=_cmd_check)
