# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from math import comb
from pathlib import Path

import pytest

from dev_tools.evals.__main__ import main
from dev_tools.evals.history import (
    HistoryError,
    append_entry,
    build_entry,
    check_report,
    read_entries,
)
from dev_tools.evals.paired import (
    bootstrap_interval,
    exact_sign_p,
    paired_evidence,
)
from dev_tools.evals.report import CaseResult, Report, Run

SHA = "a" * 64


def _report(
    label: str, rates: dict[str, tuple[int, int]], sha: str | None = SHA
) -> Report:
    meta: dict = {"label": label}
    if sha:
        meta["cases_sha256"] = sha
    report = Report(meta=meta)
    for cid, (passes, total) in rates.items():
        runs = [Run(True, "match") for _ in range(passes)] + [
            Run(False, "values") for _ in range(total - passes)
        ]
        report.cases[cid] = CaseResult(f"SECRET QUESTION {cid}", runs)
    return report


def test_exact_sign_p_matches_hand_computation() -> None:
    # 1 vs 6 flipped: n = 7, P(X <= 1) = (1 + 7) / 128, two-sided = 16 / 128.
    hand = 2 * (comb(7, 0) + comb(7, 1)) / 2**7
    assert hand == 0.125
    assert exact_sign_p(1, 6) == hand
    assert exact_sign_p(6, 1) == hand
    assert exact_sign_p(0, 0) == 1.0
    assert exact_sign_p(3, 3) == 1.0  # capped at 1
    assert exact_sign_p(0, 5) == pytest.approx(2 / 32)


def test_bootstrap_is_deterministic_and_brackets_the_mean() -> None:
    diffs = [1.0, 0.0, 0.0, 1 / 3, -1 / 3, 0.0, 1.0, 0.0]
    first = bootstrap_interval(diffs)
    assert first == bootstrap_interval(diffs)
    mean = sum(diffs) / len(diffs)
    assert first[0] <= mean <= first[1]
    assert bootstrap_interval([0.5, 0.5, 0.5]) == (0.5, 0.5)
    assert bootstrap_interval([]) == (0.0, 0.0)


def test_paired_evidence_counts_and_noise_sentence() -> None:
    base = _report("b", {"a": (0, 3), "b": (3, 3), "c": (3, 3), "d": (0, 3)})
    cand = _report("c", {"a": (3, 3), "b": (3, 3), "c": (0, 3), "d": (0, 3)})
    ev = paired_evidence(base, cand)
    assert (ev.only_base, ev.only_candidate, ev.both, ev.neither) == (1, 1, 1, 1)
    assert ev.p_value == 1.0
    assert ev.rows[0] == ("a", 0, 3, 3, 3)
    text = ev.render()
    assert "0/3" in text and "3/3" in text and "McNemar" in text
    big = paired_evidence(
        _report("b", {"a": (0, 3), "b": (0, 3)}),
        _report("c", {"a": (3, 3), "b": (3, 3)}),
    )
    assert "outside the noise band" in big.render()
    single = paired_evidence(_report("b", {"a": (0, 1)}), _report("c", {"a": (1, 1)}))
    assert "no repeats" in single.render()


def test_inside_noise_band_when_baseline_repeats_vary() -> None:
    base = Report(meta={"label": "b"})
    base.cases["a"] = CaseResult("q", [Run(True, "m"), Run(False, "v")])
    base.cases["b"] = CaseResult("q", [Run(False, "v"), Run(False, "v")])
    cand = _report("c", {"a": (1, 2), "b": (1, 2)})
    ev = paired_evidence(base, cand)
    assert ev.spread == pytest.approx(0.5)
    assert "inside the noise band" in ev.noise_sentence


def _write(path: Path, report: Report) -> str:
    report.save(path)
    return str(path)


def test_compare_verdict_and_exit_code_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _write(tmp_path / "b.json", _report("b", {"a": (1, 3), "b": (3, 3)}))
    good = _write(tmp_path / "g.json", _report("c", {"a": (3, 3), "b": (3, 3)}))
    bad = _write(tmp_path / "r.json", _report("c", {"a": (3, 3), "b": (0, 3)}))
    assert main(["compare", base, good, "--margin", "0.05"]) == 0
    out = capsys.readouterr().out
    assert "verdict: ACCEPT" in out and "paired evidence" in out
    assert main(["compare", base, bad]) == 1
    assert "verdict: REJECT" in capsys.readouterr().out


def test_history_add_is_append_only_and_stores_no_text_or_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INTERNAL_API_TOKEN", "s3cret-token-value")
    report = _report("r1", {"a": (2, 3), "b": (3, 3)})
    report.meta["token"] = "s3cret-token-value"
    report.cases["a"].runs[0].sql = "SELECT secret_sql"
    report.cases["a"].runs[0].actual = [["gold row"]]
    file = tmp_path / "h.jsonl"
    append_entry(file, build_entry(report, note="first"))
    first = file.read_text(encoding="utf-8")
    append_entry(file, build_entry(_report("r2", {"a": (3, 3)}), note="second"))
    second = file.read_text(encoding="utf-8")
    assert second.startswith(first) and len(second.splitlines()) == 2
    for forbidden in ("s3cret", "SECRET QUESTION", "secret_sql", "gold row"):
        assert forbidden not in second
    entry = read_entries(file)[0]
    assert entry["per_question"] == {"a": [2, 3], "b": [3, 3]}
    assert entry["cases_sha256"] == SHA
    with pytest.raises(HistoryError):
        build_entry(report, note="oops s3cret-token-value")


def test_history_check_refuses_other_cases_hash_and_flags_regressions(
    tmp_path: Path,
) -> None:
    file = tmp_path / "h.jsonl"
    append_entry(file, build_entry(_report("base", {"a": (3, 3), "b": (3, 3)})))
    entries = read_entries(file)
    same = _report("new", {"a": (3, 3), "b": (1, 3)})
    baseline, regressions, _ = check_report(same, entries, tolerance=0.34)
    assert baseline["label"] == "base"
    assert [r[0] for r in regressions] == ["b"]
    _, none, _ = check_report(same, entries, tolerance=0.7)
    assert none == []
    other = _report("new", {"a": (3, 3)}, sha="b" * 64)
    with pytest.raises(HistoryError, match="not comparable"):
        check_report(other, entries)
    with pytest.raises(HistoryError):
        check_report(other, entries, against="base")


def test_history_cli_exit_codes_and_seed_lines_are_not_baselines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = str(tmp_path / "h.jsonl")
    seed = {
        "source": "experiments.md (summary, no report kept)",
        "label": "E08",
        "per_question": None,
        "cases_sha256": SHA,
    }
    Path(file).write_text(json.dumps(seed) + "\n", encoding="utf-8")
    rep = _write(tmp_path / "r.json", _report("r", {"a": (3, 3)}))
    assert main(["history", "--file", file, "check", rep]) == 2  # no baseline
    assert main(["history", "--file", file, "add", rep, "--note", "n"]) == 0
    assert main(["history", "--file", file, "check", rep]) == 0
    worse = _write(tmp_path / "w.json", _report("w", {"a": (0, 3)}))
    assert main(["history", "--file", file, "check", worse]) == 1
    assert "REGRESSIONS" in capsys.readouterr().out
    assert main(["history", "--file", file, "show", "--cases-sha", "aaaa"]) == 0
    assert main(["history", "--file", file, "show", "--cases-sha", "zzz"]) == 0
