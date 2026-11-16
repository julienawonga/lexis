# SPDX-License-Identifier: Apache-2.0

"""Paired evidence printed next to ``compare``'s verdict.

``compare`` decides with a margin and a per-question tolerance. That decision is
unchanged; this module adds what the decision does not show: the pass counts of
both sides per question, an exact sign (McNemar) test on the questions whose
majority outcome flipped, a paired bootstrap interval of the score difference,
and whether the difference is inside the baseline's own repeat-to-repeat spread.

Pure Python, deterministic (fixed bootstrap seed).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from math import comb

from dev_tools.evals.report import Report

BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260101


def exact_sign_p(only_base: int, only_candidate: int) -> float:
    """Exact two-sided sign test (McNemar's exact form) on the discordant pairs."""
    n = only_base + only_candidate
    if n == 0:
        return 1.0
    low = min(only_base, only_candidate)
    tail = sum(comb(n, k) for k in range(low + 1)) / 2**n
    return min(1.0, 2 * tail)


def bootstrap_interval(
    differences: list[float],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float]:
    """Percentile 95% interval of the mean of per-question differences."""
    if not differences:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(differences)
    means = sorted(
        sum(differences[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(resamples)
    )
    return means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]


def majority_pass(passes: int, runs: int) -> bool:
    """A question's majority outcome: passed in strictly more than half its runs."""
    return passes * 2 > runs


def repeat_spread(report: Report, ids: list[str]) -> float | None:
    """Max minus min score over the baseline's repeats (None without repeats).

    Repeat *k* of a question is its k-th run; only as many repeats as the
    shortest question has are used. Generation is concurrent, so the order of
    runs inside a question carries no meaning beyond being separate draws.
    """
    if not ids:
        return None
    k = min(len(report.cases[c].runs) for c in ids)
    if k < 2:
        return None
    scores = [
        sum(report.cases[c].runs[i].passed for c in ids) / len(ids) for i in range(k)
    ]
    return max(scores) - min(scores)


@dataclass
class PairedEvidence:
    rows: list[tuple[str, int, int, int, int]]  # id, base passes/runs, cand passes/runs
    only_base: int
    only_candidate: int
    both: int
    neither: int
    p_value: float
    delta: float
    interval: tuple[float, float]
    spread: float | None

    @property
    def noise_sentence(self) -> str:
        if self.spread is None:
            return (
                "The baseline has no repeats, so its own spread is unknown: nothing "
                "can be said about the noise band from this pair."
            )
        side = "inside" if abs(self.delta) <= self.spread + 1e-9 else "outside"
        return (
            f"The difference ({self.delta:+.1%}) is {side} the noise band "
            f"(baseline repeats differ by {self.spread:.1%})."
        )

    def render(self) -> str:
        lines = ["", "paired evidence (does not change the verdict)"]
        lines.append(f"  {'question':<24} {'base':>7} {'cand':>7}")
        for cid, bp, br, cp, cr in self.rows:
            mark = "" if (bp / br if br else 0) == (cp / cr if cr else 0) else "  *"
            lines.append(f"  {cid:<24} {bp:>3}/{br:<3} {cp:>3}/{cr:<3}{mark}")
        lines.append(
            f"  majority outcome: both pass {self.both}, only base {self.only_base}, "
            f"only candidate {self.only_candidate}, neither {self.neither}"
        )
        lines.append(
            f"  exact two-sided sign (McNemar) p = {self.p_value:.4f} on "
            f"{self.only_base + self.only_candidate} flipped question(s)"
        )
        lo, hi = self.interval
        lines.append(
            f"  paired bootstrap 95% interval of the score difference "
            f"({BOOTSTRAP_RESAMPLES} resamples of questions, seed {BOOTSTRAP_SEED}): "
            f"{self.delta:+.1%} [{lo:+.1%}, {hi:+.1%}]"
        )
        lines.append(f"  {self.noise_sentence}")
        return "\n".join(lines)


def paired_evidence(base: Report, candidate: Report) -> PairedEvidence:
    shared = sorted(base.cases.keys() & candidate.cases.keys())
    rows = []
    only_base = only_cand = both = neither = 0
    diffs: list[float] = []
    for cid in shared:
        b, c = base.cases[cid], candidate.cases[cid]
        bp, cp = sum(r.passed for r in b.runs), sum(r.passed for r in c.runs)
        rows.append((cid, bp, len(b.runs), cp, len(c.runs)))
        bm, cm = majority_pass(bp, len(b.runs)), majority_pass(cp, len(c.runs))
        if bm and cm:
            both += 1
        elif bm:
            only_base += 1
        elif cm:
            only_cand += 1
        else:
            neither += 1
        diffs.append(c.pass_rate - b.pass_rate)
    delta = sum(diffs) / len(diffs) if diffs else 0.0
    return PairedEvidence(
        rows=rows,
        only_base=only_base,
        only_candidate=only_cand,
        both=both,
        neither=neither,
        p_value=exact_sign_p(only_base, only_cand),
        delta=delta,
        interval=bootstrap_interval(diffs),
        spread=repeat_spread(base, shared),
    )
