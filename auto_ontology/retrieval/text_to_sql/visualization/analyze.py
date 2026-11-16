# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Orchestrate LLM chart recommendations → ResultChart specs (no image rendering)."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from auto_ontology.retrieval.text_to_sql.visualization.chart_specs import (
    generate_chart_specs,
)
from auto_ontology.retrieval.text_to_sql.visualization.helpers import (
    parse_sql_response_to_dataframe,
)
from auto_ontology.retrieval.text_to_sql.visualization.prompts import (
    VISUALIZATION_DECISION_PROMPT,
    VISUALIZATION_PROMPT,
    VisualizationDecisionModel,
    VisualizationRecommendation,
)
from auto_ontology.utils.llm_invoke import invoke_with_structured_output

logger = logging.getLogger(__name__)

MAX_CHART_CATEGORIES = 30  # a categorical axis longer than this is unreadable
MAX_CHART_COLUMNS = 6  # a wide result is a listing, not a chart
MAX_CHART_POINTS = 200  # even a time series beyond this is a table

_DATE_NAME_TOKENS = ("date", "time", "day", "month", "year", "week")
_DATE_PROBE_ROWS = 50


def _looks_like_datetime_column(column: pd.Series) -> bool:
    """Return True when *column* plausibly holds datetimes (dtype or name probe)."""
    if pd.api.types.is_datetime64_any_dtype(column):
        return True
    if pd.api.types.is_numeric_dtype(column):
        return False
    name = "".join(ch for ch in str(column.name).lower() if ch.isalpha())
    if not any(token in name for token in _DATE_NAME_TOKENS):
        return False
    sample = column.dropna().head(_DATE_PROBE_ROWS)
    if sample.empty:
        return False
    try:
        pd.to_datetime(sample, errors="raise")
    except (ValueError, TypeError, OverflowError, pd.errors.OutOfBoundsDatetime):
        return False
    return True


def _must_be_table(df: pd.DataFrame) -> str | None:
    """Deterministic render guard: reason string if df must be a table, else None."""
    if len(df.columns) > MAX_CHART_COLUMNS:
        return "wide result"

    has_datetime = any(_looks_like_datetime_column(df[col]) for col in df.columns)
    has_non_numeric = any(
        not pd.api.types.is_numeric_dtype(df[col])
        and not _looks_like_datetime_column(df[col])
        for col in df.columns
    )
    if not has_datetime and has_non_numeric and len(df) > MAX_CHART_CATEGORIES:
        return "too many categories"

    if len(df) > MAX_CHART_POINTS:
        return "too many points"
    return None


def analyze_and_visualize(
    llm: BaseChatModel,
    question: str,
    sql: str,
    sql_response_from_db: Any,
) -> list[dict[str, Any]] | None:
    """Recommend charts for an SQL result and return ResultChart JSON specs.

    Returns ``None`` when visualization should be skipped (empty data, the
    complete result is more appropriate, LLM failure, etc.). Never raises.
    """
    try:
        df = parse_sql_response_to_dataframe(sql_response_from_db)
        if df is None or df.empty:
            logger.info("analyze_and_visualize: no tabular data — skip")
            return None

        # Deterministic guardrails first: some shapes are unreadable as charts
        # no matter what the model thinks (a 1,000-bar categorical chart, a
        # 20-column listing, an endless time series). Skip the model entirely.
        forced_reason = _must_be_table(df)
        if forced_reason is not None:
            logger.info("analyze_and_visualize: table forced (%s)", forced_reason)
            return None

        # Decide before building a chart: a detail/listing question often has a
        # numeric column, but charting that one measure would silently discard
        # the other fields the user asked to see.
        decision_messages = [
            SystemMessage(content="You are a data visualization expert."),
            HumanMessage(
                content=VISUALIZATION_DECISION_PROMPT.format(
                    sql=sql,
                    question=question,
                    df_size=len(df),
                    df_columns=list(df.columns),
                ),
            ),
        ]
        decision = invoke_with_structured_output(
            llm, decision_messages, VisualizationDecisionModel
        )
        if decision is None:
            logger.info("analyze_and_visualize: render decision failed — skip")
            return None
        if decision.render_as != "chart":
            logger.info("analyze_and_visualize: complete result table is preferable")
            return None

        viz_messages = [
            SystemMessage(content="You are a data visualization expert."),
            HumanMessage(
                content=VISUALIZATION_PROMPT.format(
                    sql=sql,
                    question=question,
                    df_size=len(df),
                    df_columns=list(df.columns),
                ),
            ),
        ]
        recommendation = invoke_with_structured_output(
            llm, viz_messages, VisualizationRecommendation
        )
        if recommendation is None or not recommendation.plots:
            logger.info("analyze_and_visualize: no plot recommendations — skip")
            return None

        # The prompt already tells the model to use "kpi" for a single-row
        # result, but it doesn't always comply — so the exact same one-row
        # result could come back as a KPI card one time and a one-bar chart
        # the next. Enforce it here instead of trusting the model every time,
        # so a single-row result renders identically on every run.
        if len(df) == 1:
            for plot in recommendation.plots:
                plot.plot_type = "kpi"

        specs = generate_chart_specs(df, recommendation.plots)
        if not specs:
            logger.info("analyze_and_visualize: no valid chart specs built — skip")
            return None
        # One primary chart only (avoid bar+line duplicates for the same data).
        return specs[:1]
    except Exception as exc:  # noqa: BLE001 — soft-fail the whole viz step
        logger.error("analyze_and_visualize failed: %s", exc)
        return None
