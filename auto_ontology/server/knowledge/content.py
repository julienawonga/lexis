# SPDX-License-Identifier: Apache-2.0
"""The shape of a knowledge item's ``content``, one model per kind.

``knowledge_item.content`` is JSONB because its shape differs by kind, so the
database cannot check it. The routes do, here, before anything reaches the DAL.
Only ``term`` and ``synonym`` can be written by a person in this slice; the
other kinds exist in the schema for later slices.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

#: The kinds a person may create or edit from the API for now.
WRITABLE_KINDS = ("term", "synonym")

MAX_NAME = 200
MAX_DEFINITION = 2000
MAX_SYNONYMS = 20


class _Content(BaseModel):
    # An unknown key is a mistake (a typo, or a client from the future): refuse
    # it rather than store something nothing will ever read.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TermContent(_Content):
    """A business term and what it means."""

    name: str = Field(min_length=1, max_length=MAX_NAME)
    definition: str = Field(min_length=1, max_length=MAX_DEFINITION)
    database: str | None = None


class SynonymContent(_Content):
    """Other words people use for an existing term."""

    term: str = Field(min_length=1, max_length=MAX_NAME)
    synonyms: list[str] = Field(min_length=1, max_length=MAX_SYNONYMS)
    database: str | None = None

    @field_validator("synonyms")
    @classmethod
    def _each_synonym(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            value = value.strip()
            if not value or len(value) > MAX_NAME:
                raise ValueError(f"each synonym must be 1 to {MAX_NAME} characters")
            if value.lower() not in {c.lower() for c in cleaned}:
                cleaned.append(value)
        return cleaned


_MODELS: dict[str, type[_Content]] = {"term": TermContent, "synonym": SynonymContent}


class InvalidContent(ValueError):
    """The content does not have the shape its kind requires."""


def validate_content(kind: str, content: Any) -> dict[str, Any]:
    """The normalised content for *kind*, or :class:`InvalidContent` with why."""
    model = _MODELS.get(kind)
    if model is None:
        raise InvalidContent(
            f"kind {kind!r} cannot be created here; use one of {', '.join(WRITABLE_KINDS)}"
        )
    if not isinstance(content, dict):
        raise InvalidContent("content must be an object")
    try:
        return model.model_validate(content).model_dump()
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'content'}: {err['msg']}"
            for err in exc.errors()
        )
        raise InvalidContent(problems) from exc
