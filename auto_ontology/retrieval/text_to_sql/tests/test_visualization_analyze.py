# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Visualization orchestration preserves detail results instead of charting one facet."""

import pandas as pd
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel
from pytest import MonkeyPatch

from auto_ontology.retrieval.text_to_sql.visualization import analyze
from auto_ontology.retrieval.text_to_sql.visualization.prompts import (
    PlotRecommendation,
    VisualizationDecisionModel,
    VisualizationRecommendation,
)


def _category_frame(rows: int) -> pd.DataFrame:
    """A grouped-by-category result: one text column, one numeric measure."""
    return pd.DataFrame(
        {
            "category": [f"cat-{i}" for i in range(rows)],
            "total": [float(i) for i in range(rows)],
        }
    )


def _time_series_frame(rows: int) -> pd.DataFrame:
    """A daily time series: a date column plus one numeric measure."""
    return pd.DataFrame(
        {
            "date": [f"2024-01-{(i % 28) + 1:02d}" for i in range(rows)],
            "value": [float(i) for i in range(rows)],
        }
    )


def _wide_frame(columns: int, rows: int = 5) -> pd.DataFrame:
    """A listing-shaped result with ``columns`` numeric fields per row."""
    return pd.DataFrame(
        {f"col{i}": [float(i + j) for j in range(rows)] for i in range(columns)}
    )


def _forbid_model_calls(monkeypatch: MonkeyPatch) -> list[type[BaseModel]]:
    """Stub the LLM entry point so any invocation fails loudly (and is counted)."""
    calls: list[type[BaseModel]] = []

    def invoke(
        _llm: object,
        _messages: list[BaseMessage],
        schema: type[BaseModel],
    ) -> BaseModel:
        calls.append(schema)
        raise AssertionError("model must not be called for a forced table")

    monkeypatch.setattr(analyze, "invoke_with_structured_output", invoke)
    return calls


def _stub_model_calls(
    monkeypatch: MonkeyPatch, render_as: str = "table"
) -> list[type[BaseModel]]:
    """Stub the LLM entry point with a canned decision (and chart fallback)."""
    calls: list[type[BaseModel]] = []

    def invoke(
        _llm: object,
        _messages: list[BaseMessage],
        schema: type[BaseModel],
    ) -> BaseModel:
        calls.append(schema)
        if schema is VisualizationDecisionModel:
            return VisualizationDecisionModel(render_as=render_as)
        return VisualizationRecommendation(
            plots=[
                PlotRecommendation(
                    plot_type="bar",
                    title="Chart",
                    x="category",
                    y="total",
                )
            ]
        )

    monkeypatch.setattr(analyze, "invoke_with_structured_output", invoke)
    return calls


def test_grouped_result_over_category_limit_forces_table(
    monkeypatch: MonkeyPatch,
) -> None:
    calls = _forbid_model_calls(monkeypatch)

    charts = analyze.analyze_and_visualize(
        object(),
        "Count by category",
        "SELECT category, total FROM t GROUP BY category",
        _category_frame(1000),
    )

    assert charts is None
    assert calls == []


def test_grouped_result_at_category_limit_still_charts(
    monkeypatch: MonkeyPatch,
) -> None:
    calls = _stub_model_calls(monkeypatch, render_as="chart")

    charts = analyze.analyze_and_visualize(
        object(),
        "Count by category",
        "SELECT category, total FROM t GROUP BY category",
        _category_frame(analyze.MAX_CHART_CATEGORIES),
    )

    assert charts is not None
    assert calls == [VisualizationDecisionModel, VisualizationRecommendation]


def test_grouped_result_one_past_category_limit_forces_table(
    monkeypatch: MonkeyPatch,
) -> None:
    calls = _forbid_model_calls(monkeypatch)

    charts = analyze.analyze_and_visualize(
        object(),
        "Count by category",
        "SELECT category, total FROM t GROUP BY category",
        _category_frame(analyze.MAX_CHART_CATEGORIES + 1),
    )

    assert charts is None
    assert calls == []


def test_time_series_within_limits_reaches_model(monkeypatch: MonkeyPatch) -> None:
    calls = _stub_model_calls(monkeypatch, render_as="table")

    charts = analyze.analyze_and_visualize(
        object(),
        "Trend over time",
        "SELECT date, value FROM t ORDER BY date",
        _time_series_frame(100),
    )

    assert charts is None
    assert calls == [VisualizationDecisionModel]


def test_long_time_series_forces_table(monkeypatch: MonkeyPatch) -> None:
    calls = _forbid_model_calls(monkeypatch)

    charts = analyze.analyze_and_visualize(
        object(),
        "Trend over time",
        "SELECT date, value FROM t ORDER BY date",
        _time_series_frame(250),
    )

    assert charts is None
    assert calls == []


def test_seven_columns_forces_table(monkeypatch: MonkeyPatch) -> None:
    calls = _forbid_model_calls(monkeypatch)

    charts = analyze.analyze_and_visualize(
        object(),
        "Show all fields",
        "SELECT * FROM t",
        _wide_frame(analyze.MAX_CHART_COLUMNS + 1),
    )

    assert charts is None
    assert calls == []


def test_six_columns_reaches_model(monkeypatch: MonkeyPatch) -> None:
    calls = _stub_model_calls(monkeypatch, render_as="table")

    charts = analyze.analyze_and_visualize(
        object(),
        "Show all fields",
        "SELECT * FROM t",
        _wide_frame(analyze.MAX_CHART_COLUMNS),
    )

    assert charts is None
    assert calls == [VisualizationDecisionModel]


def test_single_row_never_forced_to_table(monkeypatch: MonkeyPatch) -> None:
    calls = _stub_model_calls(monkeypatch, render_as="table")

    charts = analyze.analyze_and_visualize(
        object(),
        "One record",
        "SELECT category, total FROM t LIMIT 1",
        _category_frame(1),
    )

    assert charts is None
    assert calls == [VisualizationDecisionModel]


def test_forced_table_is_deterministic(monkeypatch: MonkeyPatch) -> None:
    calls = _forbid_model_calls(monkeypatch)
    frame = _category_frame(1000)

    for _ in range(5):
        charts = analyze.analyze_and_visualize(
            object(),
            "Count by category",
            "SELECT category, total FROM t GROUP BY category",
            frame,
        )
        assert charts is None

    assert calls == []


def test_must_be_table_reasons() -> None:
    assert analyze._must_be_table(_wide_frame(7)) == "wide result"
    assert analyze._must_be_table(_category_frame(31)) == "too many categories"
    assert analyze._must_be_table(_time_series_frame(250)) == "too many points"
    assert analyze._must_be_table(_category_frame(30)) is None
    assert analyze._must_be_table(_time_series_frame(100)) is None
    assert analyze._must_be_table(_wide_frame(6)) is None
    assert analyze._must_be_table(_category_frame(1)) is None


def test_detail_listing_uses_complete_table(monkeypatch: MonkeyPatch) -> None:
    question = "Give me specifications of all AWS clusters we collect telemetry from"
    sql = "SELECT name, location, gpu_technology, gpu_count FROM cluster_passport"
    response = (
        '[{"name":"cluster-a","location":"us-west","gpu_technology":"H100",'
        '"gpu_count":64}]'
    )
    calls: list[type[BaseModel]] = []

    def invoke(
        _llm: object,
        messages: list[BaseMessage],
        schema: type[BaseModel],
    ) -> BaseModel:
        calls.append(schema)
        prompt = next(
            message.content for message in messages if isinstance(message, HumanMessage)
        )
        assert question in prompt
        assert sql in prompt
        assert "gpu_technology" in prompt
        assert "gpu_count" in prompt
        return VisualizationDecisionModel(render_as="table")

    monkeypatch.setattr(analyze, "invoke_with_structured_output", invoke)

    charts = analyze.analyze_and_visualize(object(), question, sql, response)

    assert charts is None
    assert calls == [VisualizationDecisionModel]


def test_missing_render_decision_skips_chart_generation(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[type[BaseModel]] = []

    def invoke(
        _llm: object,
        _messages: list[BaseMessage],
        schema: type[BaseModel],
    ) -> None:
        calls.append(schema)
        return None

    monkeypatch.setattr(analyze, "invoke_with_structured_output", invoke)

    charts = analyze.analyze_and_visualize(
        object(),
        "Give me specifications of all AWS clusters",
        "SELECT name, location, gpu_count FROM cluster_passport",
        '[{"name":"a","location":"us-west","gpu_count":64}]',
    )

    assert charts is None
    assert calls == [VisualizationDecisionModel]


def test_comparison_continues_to_chart_generation(monkeypatch: MonkeyPatch) -> None:
    responses = iter(
        [
            VisualizationDecisionModel(render_as="chart"),
            VisualizationRecommendation(
                plots=[
                    PlotRecommendation(
                        plot_type="bar",
                        title="GPU Count by Cluster",
                        x="name",
                        y="gpu_count",
                    )
                ]
            ),
        ]
    )
    schemas: list[type[BaseModel]] = []

    def invoke(
        _llm: object,
        _messages: list[BaseMessage],
        schema: type[BaseModel],
    ) -> BaseModel:
        schemas.append(schema)
        return next(responses)

    monkeypatch.setattr(analyze, "invoke_with_structured_output", invoke)

    charts = analyze.analyze_and_visualize(
        object(),
        "Compare GPU counts across AWS clusters",
        "SELECT name, gpu_count FROM cluster_passport",
        '[{"name":"a","gpu_count":64},{"name":"b","gpu_count":128}]',
    )

    assert charts is not None
    assert charts[0]["x"]["key"] == "name"
    assert charts[0]["series"][0]["key"] == "gpu_count"
    assert schemas == [VisualizationDecisionModel, VisualizationRecommendation]
