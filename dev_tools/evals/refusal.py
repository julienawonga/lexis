# SPDX-License-Identifier: Apache-2.0

"""Scoring for questions the database cannot answer (``expect: "refusal"``).

Nothing here depends on how a refusal is produced. A run of an unanswerable
question is judged only on what the user was handed:

* it FAILS when the run returned executed rows (even with a note beside them):
  the user got a result for something else;
* it PASSES when it returned no rows and
    - tolerant: nothing more is required;
    - strict: the answer text says the question cannot be answered, or the
      answer carries the explicit refusal marker;
* an explicit marker (``answer.refusal`` object, or ``answer.caveats`` holding
  the code ``unanswerable``) passes in both modes, unless rows were returned;
* a timeout or infrastructure error is ``no_answer``: neither pass nor fail,
  left out of the denominator and counted separately.

The marker is defined here, before any backend produces it. See "Unanswerable
questions" in docs/evaluation.md.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

EXPECT_ROWS = "rows"
EXPECT_REFUSAL = "refusal"
EXPECTS = (EXPECT_ROWS, EXPECT_REFUSAL)

KINDS = (
    "missing-entity",
    "missing-attribute",
    "missing-time-or-version",
    "undefined-term",
    "out-of-scope",
    "false-premise",
)

MARKER_CODE = "unanswerable"
NO_ANSWER = "no_answer"

# What counts as "the text says the question cannot be answered" for the strict
# score. Fixed with the frozen set: a test pins the hash of this tuple, so
# editing it is a deliberate act that must be explained in review.
CANNOT_ANSWER_PATTERNS: tuple[str, ...] = (
    r"\b(can ?not|can't|unable to|not able to|not possible to|impossible to)"
    r"\s+(be\s+)?(answer|answered|determine|determined|compute|computed|calculate"
    r"|calculated|construct|constructed|found)",
    r"\bno (such )?(table|column|field|attribute|data|information)\b",
    r"\b(does not|doesn't|do not|don't|did not|didn't)\s+"
    r"(contain|have|include|store|track|record|keep|hold|provide)",
    r"\bnot (available|stored|tracked|recorded|captured|part of)\b",
    r"\b(outside|beyond) (the )?(scope|data|database)\b",
    r"\b(ne peut pas|ne peuvent pas|impossible de|il n'y a pas de|n'existe pas"
    r"|n'existent pas|ne contient pas|ne contiennent pas|ne dispose pas"
    r"|ne disposons pas|pas disponible|hors du périmètre|hors périmètre)",
)
_CANNOT_ANSWER = re.compile("|".join(CANNOT_ANSWER_PATTERNS), re.IGNORECASE)


def patterns_sha256() -> str:
    """Hash of ``CANNOT_ANSWER_PATTERNS``, pinned by a test."""
    return hashlib.sha256("\n".join(CANNOT_ANSWER_PATTERNS).encode()).hexdigest()


def says_cannot_answer(text: str | None) -> bool:
    return bool(text and _CANNOT_ANSWER.search(text))


def has_refusal_marker(payload: dict[str, Any]) -> bool:
    """Whether a ``result`` answer carries the explicit refusal marker.

    Either ``refusal`` is an object, or ``caveats`` holds the code
    ``unanswerable`` (as a bare string or as ``{"code": "unanswerable"}``).
    """
    if isinstance(payload.get("refusal"), dict):
        return True
    caveats = payload.get("caveats")
    if isinstance(caveats, list):
        for item in caveats:
            if item == MARKER_CODE:
                return True
            if isinstance(item, dict) and item.get("code") == MARKER_CODE:
                return True
    return False


@dataclass(frozen=True)
class RefusalVerdict:
    passed: bool
    reason: str  # rows_returned | marker | text_refusal | no_rows | no_answer


def score_refusal(
    *,
    rows: list[list[Any]] | None,
    text: str | None,
    marker: bool,
    error: str | None,
    strict: bool = False,
) -> RefusalVerdict:
    """Score one run of an unanswerable question (tolerant unless *strict*)."""
    if rows:
        return RefusalVerdict(False, "rows_returned")
    if error and rows is None and not marker:
        return RefusalVerdict(False, NO_ANSWER)
    if marker:
        return RefusalVerdict(True, "marker")
    if says_cannot_answer(text):
        return RefusalVerdict(True, "text_refusal")
    return RefusalVerdict(not strict, "no_rows")


def validate_refusal_case(raw: dict[str, Any]) -> None:
    """Raise ``ValueError`` when a refusal case is malformed."""
    cid = raw.get("id")
    if raw.get("gold"):
        raise ValueError(f"{cid}: a refusal case has no gold answer")
    if raw.get("kind") not in KINDS:
        raise ValueError(f"{cid}: kind must be one of {KINDS}, got {raw.get('kind')!r}")
    if not str(raw.get("reason") or "").strip():
        raise ValueError(f"{cid}: a refusal case needs a reason")
