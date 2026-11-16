# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from dev_tools.evals import conversation as cv
from dev_tools.integrity.freeze import check_frozen

TOKEN = "t0ken-" + "x" * 40


def _sse(*events: object) -> bytes:
    lines = [f"data: {json.dumps(e)}" for e in events] + ["data: [DONE]"]
    return ("\n\n".join(lines) + "\n\n").encode()


def _clar(n: int = 3, with_db: bool = False) -> dict[str, Any]:
    return {
        "type": "clarification",
        "clarification_id": "c1",
        "term": "satisfaction",
        "options": [
            {"id": f"o{i}", "label": f"label{i}", "description": f"d{i}"}
            for i in range(n)
        ],
    }


# --- cases file -------------------------------------------------------------


def test_case_file_is_frozen_and_intact() -> None:
    assert check_frozen(cv.CASES_FILE) is None
    assert len(cv.undefined_questions()) == 8
    assert cv.stability_question()
    assert len(cv.answerable_questions()) == 20


# --- SSE turn reader --------------------------------------------------------


def test_post_turn_reads_events_until_done_and_sends_auth() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        seen["path"] = request.url.path
        body = b": keepalive\n\ndata: not json\n\n" + _sse(
            {"type": "step"}, {"type": "result", "response": "x"}
        )
        return httpx.Response(200, content=body)

    headers = cv.auth_headers("u1", TOKEN)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        events, secs = cv.post_turn(client, "http://b/", {"question": "q"}, headers)
    assert [e["type"] for e in events] == ["step", "result"]
    assert secs >= 0
    assert seen["path"] == "/api/chat/completions"
    assert seen["headers"]["x-auto-ontology-user-id"] == "u1"
    assert seen["headers"]["x-internal-token"] == TOKEN
    assert cv.outcome(events) == "answered"


def test_no_token_header_when_none() -> None:
    assert "x-internal-token" not in cv.auth_headers("u", None)


def test_503_is_waited_out_then_retried() -> None:
    calls = {"n": 0}
    waits: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, headers={"retry-after": "7"})
        return httpx.Response(200, content=_sse({"type": "result"}))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        events, _ = cv.post_turn(client, "http://b", {}, {}, sleep=waits.append)
    assert waits == [7.0, 7.0]
    assert events == [{"type": "result"}]


def test_http_error_is_an_event_and_counts_as_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        events, _ = cv.post_turn(client, "http://b", {}, {})
    assert events[0]["type"] == "http_error" and events[0]["status"] == 500
    assert cv.outcome(events) == "error"


def test_stop_closes_the_stream_early() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=_sse({"type": "a"}, {"type": "b"}, {"type": "c"})
        )

    ticks = iter(range(0, 1000, 10))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        events, _ = cv.post_turn(
            client,
            "http://b",
            {},
            {},
            stop=lambda: True,
            clock=lambda: float(next(ticks)),
            poll_seconds=1.0,
        )
    assert len(events) < 3


# --- clarification detection and option answering ---------------------------


def test_outcome_precedence() -> None:
    assert cv.outcome([{"type": "result"}, _clar()]) == "asked"
    assert cv.outcome([{"type": "step"}]) == "error"
    assert cv.outcome([]) == "error"
    assert cv.clarification_of([{"type": "result"}]) is None
    assert cv.clarification_of([{"type": "x"}, _clar()])["clarification_id"] == "c1"


def test_options_are_answered_round_robin_by_repetition() -> None:
    c = _clar(3)
    assert [cv.pick_option(c, r)["id"] for r in range(5)] == [
        "o0",
        "o1",
        "o2",
        "o0",
        "o1",
    ]


def test_options_from_stored_message() -> None:
    payload = {"options": [{"id": "o0", "label": "a", "database": "db1"}]}
    text = "x\n" + cv.FENCE + "\n" + json.dumps(payload) + "\n```\ny"
    assert cv.options_from_stored(text)[0]["database"] == "db1"
    assert cv.options_from_stored("nothing") is None


def test_parse_db_takes_the_last_match() -> None:
    log = (
        "Selected candidate database 'a'\n"
        "Question intent: foo target_db=b\n"
        "Selected candidate database 'c'\n"
        "Question intent: bar target_db=d\n"
    )
    assert cv.parse_db(log) == {"voted": "c", "intent_target_db": "d"}
    assert cv.parse_db("") == {"voted": None, "intent_target_db": None}


# --- metrics ----------------------------------------------------------------


def _row(arm: str, kind: str, out: str, labels: list[str] | None = None, i: int = 0):
    return {
        "key": f"{arm}|{kind}|{i}",
        "arm": arm,
        "kind": kind,
        "outcome": out,
        "labels": labels,
    }


def _m3_rows(a_main: int, a_cand: int, b_main: int, b_cand: int) -> list[dict]:
    rows = []
    for arm, a, b in (("main", a_main, b_main), ("cand", a_cand, b_cand)):
        rows += [
            _row(arm, "m3a", "asked" if i < a else "answered", i=i) for i in range(60)
        ]
        rows += [
            _row(arm, "m3b", "asked" if i < b else "answered", i=i) for i in range(24)
        ]
    return rows


@pytest.mark.parametrize(
    ("a_main", "a_cand", "gate"), [(0, 5, "PASS"), (0, 6, "FAIL"), (10, 3, "PASS")]
)
def test_m3a_gate_candidate_asks_at_most_main_plus_five(a_main, a_cand, gate) -> None:
    s = cv.summarize_m3(_m3_rows(a_main, a_cand, 10, 10))
    assert s["m3a"]["gate"] == gate


@pytest.mark.parametrize(
    ("b_main", "b_cand", "gate"), [(20, 16, "PASS"), (20, 15, "FAIL"), (3, 9, "PASS")]
)
def test_m3b_gate_candidate_asks_at_least_main_minus_four(b_main, b_cand, gate) -> None:
    s = cv.summarize_m3(_m3_rows(0, 0, b_main, b_cand))
    assert s["m3b"]["gate"] == gate


def test_m3_gates_are_incomplete_without_every_run() -> None:
    s = cv.summarize_m3(_m3_rows(0, 0, 10, 10)[:-1])
    assert s["m3b"]["gate"] is None and s["m3b"]["complete"] is False
    assert "incomplete" in cv.render(s, None)


def test_m3_counts_errors_and_m4_distinct_label_sets_ignore_order() -> None:
    rows = _m3_rows(0, 0, 0, 0)
    rows.append(_row("cand", "m3a", "error", i=99))
    rows += [
        _row("cand", "m4", "asked", ["b", "a"], 0),
        _row("cand", "m4", "asked", ["a", "b"], 1),
        _row("cand", "m4", "asked", ["a", "c"], 2),
        _row("cand", "m4", "answered", None, 3),
        _row("main", "m4", "answered", None, 0),
    ]
    s = cv.summarize_m3(rows)
    assert s["counts"]["m3a_cand"]["errors"] == 1
    assert s["m4"]["cand"] == {"distinct_label_sets": 2, "asked_runs": 3}
    assert s["m4"]["main"] == {"distinct_label_sets": 0, "asked_runs": 0}


def _m12(
    q: str,
    dbs: list[str | None],
    chosen: int,
    intent: str | None,
    voted: str | None,
    main_voted: str | None,
) -> dict[str, Any]:
    return {
        "key": f"{q}|{chosen}",
        "question": q,
        "turn1": "asked",
        "options": [
            {"id": f"o{i}", "label": "l", "database": d} for i, d in enumerate(dbs)
        ],
        "chosen": {"id": f"o{chosen}", "label": "l", "database": dbs[chosen]},
        "m2": {"outcome": "answered", "intent_target_db": intent, "voted": voted},
        "m1": {"outcome": "answered", "intent_target_db": None, "voted": main_voted},
    }


def test_m2_gate_passes_only_when_every_option_is_pinned() -> None:
    rows = [
        _m12("q1", ["a", "b"], 0, "a", None, "b"),
        _m12("q1", ["a", "b"], 1, "b", None, "b"),
    ]
    s = cv.summarize_m12(rows)
    assert s["m2"]["gate"] == "PASS" and (s["m2"]["pinned"], s["m2"]["of"]) == (2, 2)


def test_m2_one_miss_fails_the_gate_wrong_target_or_vote_ran() -> None:
    wrong_target = _m12("q1", ["a", "b"], 0, "b", None, "a")
    vote_ran = _m12("q2", ["a", "b"], 0, "a", "a", "a")
    for bad in (wrong_target, vote_ran):
        s = cv.summarize_m12([_m12("q0", ["a", "b"], 1, "b", None, "b"), bad])
        assert s["m2"]["gate"] == "FAIL"
        assert len(s["m2"]["misses"]) == 1
        assert "M2 MISS" in cv.render(None, s)


def test_m2_ignores_single_database_runs_and_options_without_database() -> None:
    rows = [
        _m12("single", ["a", "a"], 0, "zzz", None, "a"),
        _m12("nodb", ["a", None], 1, None, None, "a"),
    ]
    s = cv.summarize_m12(rows)
    assert s["multi_database_runs"] == 0  # neither offers >= 2 different databases
    assert s["pinnable"] == 0 and s["m2"]["gate"] is None
    # the informational, wider check still sees the single-database miss
    assert s["m2"]["all_asked_with_database"] == {"pinned": 0, "of": 1}


def test_m1_share_counts_only_runs_where_main_logged_a_vote() -> None:
    rows = [
        _m12("q1", ["a", "b"], 0, "a", None, "b"),  # differs
        _m12("q1", ["a", "b"], 1, "b", None, "b"),  # same
        _m12("q2", ["a", "b"], 0, "a", None, None),  # no vote logged
    ]
    m1 = cv.summarize_m12(rows)["m1"]
    assert (m1["differs"], m1["of"]) == (1, 2)
    assert m1["share"] == 0.5 and m1["by_question"] == [("q1", 1)]


def test_runs_that_did_not_ask_are_counted_but_have_no_options() -> None:
    s = cv.summarize_m12([{"key": "q|0", "question": "q", "turn1": "answered"}])
    assert s["runs"] == 1 and s["turn1_asked"] == 0


# --- a fake backend, run end to end ----------------------------------------


class FakeBackend:
    """Chat endpoint: asks on the questions in *asking*, answers otherwise."""

    def __init__(self, asking: set[str]) -> None:
        self.asking = asking
        self.requests: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        self.headers.append(dict(request.headers))
        if "clarification" not in body and body["question"] in self.asking:
            return httpx.Response(200, content=_sse(_clar(3)))
        return httpx.Response(200, content=_sse({"type": "result", "response": "ok"}))


def _run_m3(
    out: Path, backend: FakeBackend, answerable: list[str] | None = None
) -> int:
    with httpx.Client(transport=httpx.MockTransport(backend)) as client:
        return cv.run_m3(
            client,
            arm="cand",
            url="http://b",
            out=out,
            headers=cv.auth_headers("u", TOKEN),
            answerable=answerable or ["ans1", "ans2"],
            undefined=["und1"],
            stability="stab",
            workers=1,
        )


def test_run_m3_records_every_turn_one_conversation_each(tmp_path: Path) -> None:
    out = tmp_path / "m3.jsonl"
    backend = FakeBackend({"und1", "stab"})
    n = _run_m3(out, backend)
    # 2 answerable x 3 + 1 undefined x 3 + stability x 20
    assert n == 6 + 3 + 20
    rows = cv.load_records(out)
    assert len(rows) == n
    assert all(r["arm"] == "cand" for r in rows)
    assert {r["outcome"] for r in rows if r["kind"] == "m3b"} == {"asked"}
    assert {r["outcome"] for r in rows if r["kind"] == "m3a"} == {"answered"}
    asked = next(r for r in rows if r["kind"] == "m4")
    assert asked["labels"] == ["label0", "label1", "label2"]
    ids = [b["conversation_id"] for b in backend.requests]
    assert len(set(ids)) == len(ids)
    assert all(b["supports_clarification"] is True for b in backend.requests)
    assert all(
        b["supports_clarification"] and "clarification" not in b
        for b in backend.requests
    )


def test_run_m3_is_resumable_and_skips_done_keys(tmp_path: Path) -> None:
    out = tmp_path / "m3.jsonl"
    first = FakeBackend(set())
    _run_m3(out, first)
    again = FakeBackend(set())
    assert _run_m3(out, again) == 0
    assert again.requests == []
    # drop the last two records: only those are measured again
    lines = out.read_text(encoding="utf-8").splitlines()
    out.write_text("\n".join(lines[:-2]) + "\n", encoding="utf-8")
    third = FakeBackend(set())
    assert _run_m3(out, third) == 2
    assert len(cv.load_records(out)) == len(lines)


def test_token_reaches_the_request_but_never_the_files(tmp_path: Path) -> None:
    out = tmp_path / "m3.jsonl"
    backend = FakeBackend({"und1"})
    _run_m3(out, backend)
    assert all(h["x-internal-token"] == TOKEN for h in backend.headers)
    assert TOKEN not in out.read_text(encoding="utf-8")
    report = tmp_path / "report.json"
    args = argparse.Namespace(m3=str(out), m12=None, out=str(report))
    assert cv.cmd_report(args) == 0
    assert TOKEN not in report.read_text(encoding="utf-8")
    saved = json.loads(report.read_text(encoding="utf-8"))
    assert saved["cases_sha256"] and saved["answerable_sha256"]


def test_cmd_run_uses_the_environment_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INTERNAL_API_TOKEN", TOKEN)
    backend = FakeBackend(set())
    args = argparse.Namespace(
        measure="m3",
        out=str(tmp_path / "m3.jsonl"),
        user="u",
        token=None,
        arm="main",
        url="http://b",
        workers=3,
    )
    with httpx.Client(transport=httpx.MockTransport(backend)) as client:
        assert cv.cmd_run(args, client=client) == 0
    # 20 + 8 questions x 3 runs, plus 20 stability runs
    assert len(backend.requests) == 60 + 24 + 20
    assert backend.headers[0]["x-internal-token"] == TOKEN
    assert TOKEN not in (tmp_path / "m3.jsonl").read_text(encoding="utf-8")


def test_run_m12_answers_by_option_id_and_reads_the_logs(tmp_path: Path) -> None:
    out = tmp_path / "m12.jsonl"
    cand_calls: list[dict[str, Any]] = []
    main_calls: list[dict[str, Any]] = []

    def cand(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        cand_calls.append(body)
        if "clarification" not in body:
            return httpx.Response(200, content=_sse(_clar(2)))
        return httpx.Response(200, content=_sse({"type": "result"}))

    def main(request: httpx.Request) -> httpx.Response:
        main_calls.append(json.loads(request.content))
        return httpx.Response(200, content=_sse({"type": "result"}))

    def route(request: httpx.Request) -> httpx.Response:
        return (cand if request.url.host == "cand" else main)(request)

    dbs = {"o0": "db_a", "o1": "db_b"}

    def stored(conv_id: str) -> list[dict[str, Any]]:
        return [
            {"id": k, "label": f"label{k[1:]}", "database": v} for k, v in dbs.items()
        ]

    def cand_log(since: str) -> str:
        return "Question intent: x target_db=db_a\nRetrieved 4 ColumnAttributes\n"

    def main_log(since: str) -> str:
        return "Selected candidate database 'db_b'\n"

    with httpx.Client(transport=httpx.MockTransport(route)) as client:
        n = cv.run_m12(
            client,
            cand_url="http://cand",
            main_url="http://main",
            out=out,
            headers=cv.auth_headers("u", None),
            undefined=["u1"],
            read_cand_log=cand_log,
            read_main_log=main_log,
            stored_options=stored,
            clock_iso=lambda: "2026-01-01T00:00:00Z",
            poll_seconds=0.0,
        )
    assert n == cv.M12_REPEATS
    rows = cv.load_records(out)
    # round-robin: repetition 0 answers o0, 1 answers o1, 2 answers o0 ...
    assert [r["chosen"]["id"] for r in rows] == ["o0", "o1", "o0", "o1", "o0"]
    answers = [b for b in cand_calls if "clarification" in b]
    assert answers[0]["clarification"] == {"clarification_id": "c1", "option_id": "o0"}
    assert all(b["conversation_id"] for b in answers)
    # main is replayed without a conversation, the choice as evidence
    assert all("conversation_id" not in b for b in main_calls)
    assert (
        main_calls[0]["evidence"] == 'The user defined "satisfaction" as: label0 (d0)'
    )
    # the fake logs make rep 0 a pin and rep 1 a miss (target db_a, option db_b)
    s = cv.summarize_m12(rows)
    assert s["m2"]["of"] == 5 and s["m2"]["gate"] == "FAIL"
    assert s["m1"]["of"] == 5
    # resumable
    with httpx.Client(transport=httpx.MockTransport(route)) as client:
        assert (
            cv.run_m12(
                client,
                cand_url="http://cand",
                main_url="http://main",
                out=out,
                headers={},
                undefined=["u1"],
                read_cand_log=cand_log,
                read_main_log=main_log,
                stored_options=stored,
            )
            == 0
        )


def test_run_m12_records_a_turn_that_did_not_ask(tmp_path: Path) -> None:
    out = tmp_path / "m12.jsonl"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse({"type": "result"}))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        cv.run_m12(
            client,
            cand_url="http://c",
            main_url="http://m",
            out=out,
            headers={},
            undefined=["u1"],
            read_cand_log=lambda s: "",
            read_main_log=lambda s: "",
            stored_options=lambda c: None,
        )
    rows = cv.load_records(out)
    assert len(rows) == cv.M12_REPEATS
    assert all(r["turn1"] == "answered" and "chosen" not in r for r in rows)


def test_report_renders_without_runs_or_with_old_records(tmp_path: Path) -> None:
    assert cv.render(None, None) == ""
    args = argparse.Namespace(m3=None, m12=str(tmp_path / "missing.jsonl"), out=None)
    assert cv.cmd_report(args) == 0
