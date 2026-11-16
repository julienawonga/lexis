# SPDX-License-Identifier: Apache-2.0

"""Conversation-aware measurements: what the stateless harness cannot reach.

``run`` sends every question without a conversation, so a path that needs one
(clarification) can never move its scores. This module drives authenticated
conversations instead, turn by turn, and computes the metrics of the protocol
in ``docs/conversation-protocol.md`` (M1 to M4 and their gates). It is a port of
the two scripts that protocol was first run with (``probe.py`` and
``report.py``); the definitions were copied, not redesigned.

Authentication: the API trusts the ``x-auto-ontology-user-id`` header a trusted
proxy forwards. When the backend sets ``INTERNAL_API_TOKEN`` the token must
accompany it (``x-internal-token``). The token is used for requests only and is
never written to a record or a report.

Every measured run is appended to a JSON Lines file as one record keyed by
question and repetition, so an interrupted run resumes: keys already present are
skipped.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from auto_ontology.server.internal_auth import INTERNAL_TOKEN_HEADER
from dev_tools.evals.cases import DEFAULT_CASES_DIR
from dev_tools.evals.runner import parse_sse

USER_HEADER = "x-auto-ontology-user-id"
DEFAULT_USER = "eval-clarification"
CASES_FILE = DEFAULT_CASES_DIR / "conversation_clarification.json"
ANSWERABLE_FILE = DEFAULT_CASES_DIR / "chinook.json"
TIMEOUT = 330.0
FENCE = "`" * 3 + "clarification"
# Printed in the backend log right after the database is pinned or voted.
DB_READ = r"Retrieved \d+ ColumnAttributes"

# Preregistered sizes (docs/conversation-protocol.md). The gates are only
# evaluated on a complete set of runs, as in the original report.
M3_REPEATS = 3
M4_REPEATS = 20
M12_REPEATS = 5
M3A_RUNS = 60
M3B_RUNS = 24
M3A_MARGIN = 5
M3B_MARGIN = 4
M3_WORKERS = 3

GROUP_UNDEFINED = "undefined"
GROUP_STABILITY = "label_stability"

# Backend log since an ISO timestamp.
LogReader = Callable[[str], str]
OptionStore = Callable[[str], "list[dict[str, Any]] | None"]


# --- cases ------------------------------------------------------------------


def _group(path: Path, group: str) -> list[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [c["question"] for c in raw["cases"] if c.get("group") == group]


def undefined_questions(path: Path = CASES_FILE) -> list[str]:
    return _group(path, GROUP_UNDEFINED)


def stability_question(path: Path = CASES_FILE) -> str:
    found = _group(path, GROUP_STABILITY)
    if len(found) != 1:
        raise ValueError(f"{path.name}: expected one {GROUP_STABILITY} question")
    return found[0]


def answerable_questions(path: Path = ANSWERABLE_FILE) -> list[str]:
    """The questions of the frozen answerable set (questions only, no gold)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [c["question"] for c in raw["cases"]]


# --- one turn ---------------------------------------------------------------


def auth_headers(user: str, token: str | None) -> dict[str, str]:
    headers = {USER_HEADER: user, "content-type": "application/json"}
    if token:
        headers[INTERNAL_TOKEN_HEADER] = token
    return headers


def post_turn(
    client: httpx.Client,
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    *,
    stop: Callable[[], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
    poll_seconds: float = 2.0,
    attempts: int = 20,
) -> tuple[list[dict[str, Any]], float]:
    """One chat turn: ``(events, seconds)``. Waits out 503 back-pressure.

    *stop*, polled every *poll_seconds* while streaming, closes the stream early
    when it returns true (M1 and M2 only need the database the run selected,
    which the backend logs well before the answer is written).
    """
    t0 = clock()
    last_poll = 0.0
    for _ in range(attempts):
        events: list[dict[str, Any]] = []
        with client.stream(
            "POST",
            url.rstrip("/") + "/api/chat/completions",
            json=body,
            headers=headers,
            timeout=TIMEOUT,
        ) as r:
            if r.status_code == 503:
                try:
                    wait = float(r.headers.get("retry-after", 5))
                except ValueError:
                    wait = 5.0
                sleep(wait)
                continue
            if r.status_code != 200:
                return (
                    [
                        {
                            "type": "http_error",
                            "status": r.status_code,
                            "body": r.read().decode("utf-8", "replace")[:300],
                        }
                    ],
                    clock() - t0,
                )
            for line in r.iter_lines():
                events.extend(parse_sse([line]))
                if line.strip() == "data: [DONE]":
                    break
                if stop and clock() - last_poll >= poll_seconds:
                    last_poll = clock()
                    if stop():
                        break
            return events, clock() - t0
    return [{"type": "http_error", "status": 503}], clock() - t0


def outcome(events: list[dict[str, Any]]) -> str:
    """``asked`` (a clarification), ``answered`` (a result) or ``error``."""
    kinds = {e.get("type") for e in events}
    if "clarification" in kinds:
        return "asked"
    if "result" in kinds:
        return "answered"
    return "error"


def clarification_of(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((e for e in events if e.get("type") == "clarification"), None)


def pick_option(clarification: dict[str, Any], rep: int) -> dict[str, Any]:
    """The option answered in repetition *rep*: round-robin by repetition."""
    options = clarification["options"]
    return options[rep % len(options)]


# --- backend log and stored options (M1, M2) -------------------------------


def docker_log_reader(container: str) -> LogReader:
    def read(since: str) -> str:
        out = subprocess.run(
            ["docker", "logs", container, "--since", since],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
        return out.stdout + out.stderr

    return read


def make_option_store(container: str, db_user: str, db_name: str) -> OptionStore:
    """Options with their databases, as stored with the question.

    The client-facing clarification event does not carry the databases; the
    stored message does, so M1 and M2 read it from the database.
    """

    def stored_options(conv_id: str) -> list[dict[str, Any]] | None:
        # conv_id is a uuid this module generated; it is never user input.
        sql = (
            "select content from frontend.messages where conversation_id='%s' "
            "and content like '%%%s%%' limit 1" % (conv_id, FENCE)
        )
        out = subprocess.run(
            ["docker", "exec", container, "psql", "-U", db_user, "-d", db_name]
            + ["-At", "-c", sql],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        ).stdout
        return options_from_stored(out)

    return stored_options


def options_from_stored(text: str) -> list[dict[str, Any]] | None:
    """Options (with their databases) from a stored clarification message."""
    m = re.search(re.escape(FENCE) + r"\n(.*?)\n" + "`" * 3, text, re.S)
    return json.loads(m.group(1))["options"] if m else None


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_db(text: str) -> dict[str, str | None]:
    """The database a run voted for and the ``target_db`` of its intent."""
    sel = re.findall(r"Selected candidate database '([^']+)'", text)
    intent = re.findall(r"Question intent:.*?target_db=(\S+)", text)
    return {
        "voted": sel[-1] if sel else None,
        "intent_target_db": intent[-1] if intent else None,
    }


# --- resumable records ------------------------------------------------------


def load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_done(path: Path) -> set[str]:
    return {r["key"] for r in load_records(path)}


def append_record(path: Path, rec: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# --- M3 / M4: turn 1 only ---------------------------------------------------


def m3_tasks(
    answerable: list[str], undefined: list[str], stability: str
) -> list[tuple[str, str, int]]:
    tasks = [("m3a", q, r) for q in answerable for r in range(M3_REPEATS)]
    tasks += [("m3b", q, r) for q in undefined for r in range(M3_REPEATS)]
    tasks += [("m4", stability, r) for r in range(M4_REPEATS)]
    return tasks


def run_m3(
    client: httpx.Client,
    *,
    arm: str,
    url: str,
    out: Path,
    headers: dict[str, str],
    answerable: list[str],
    undefined: list[str],
    stability: str,
    workers: int = M3_WORKERS,
) -> int:
    """M3a, M3b and M4 for one arm. Returns the number of runs measured now."""
    done = load_done(out)
    measured: list[str] = []

    def one(task: tuple[str, str, int]) -> None:
        kind, q, r = task
        key = f"{arm}|{kind}|{q}|{r}"
        if key in done:
            return
        events, secs = post_turn(
            client,
            url,
            {
                "question": q,
                "conversation_id": str(uuid.uuid4()),
                "supports_clarification": True,
            },
            headers,
        )
        c = clarification_of(events)
        append_record(
            out,
            {
                "key": key,
                "arm": arm,
                "kind": kind,
                "question": q,
                "rep": r,
                "outcome": outcome(events),
                "labels": [o["label"] for o in c["options"]] if c else None,
                "seconds": round(secs, 1),
            },
        )
        measured.append(key)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, m3_tasks(answerable, undefined, stability)))
    return len(measured)


# --- M1 / M2: one answered option per run -----------------------------------


def run_m12(
    client: httpx.Client,
    *,
    cand_url: str,
    main_url: str,
    out: Path,
    headers: dict[str, str],
    undefined: list[str],
    read_cand_log: LogReader,
    read_main_log: LogReader,
    stored_options: OptionStore,
    clock_iso: Callable[[], str] = iso_now,
    sleep: Callable[[float], None] = time.sleep,
    poll_seconds: float = 2.0,
) -> int:
    """M1 and M2, strictly sequential (each run is matched to its log lines).

    Each run answers ONE option chosen round-robin by repetition, from a fresh
    conversation (a clarification can be answered once). Returns the number of
    runs recorded now.
    """
    done = load_done(out)
    measured = 0

    def stopper(read: LogReader, since: str) -> Callable[[], bool]:
        return lambda: bool(re.search(DB_READ, read(since)))

    for q in undefined:
        for r in range(M12_REPEATS):
            key = f"{q}|{r}"
            if key in done:
                continue
            cid = str(uuid.uuid4())
            e1, _ = post_turn(
                client,
                cand_url,
                {
                    "question": q,
                    "conversation_id": cid,
                    "supports_clarification": True,
                },
                headers,
                sleep=sleep,
            )
            rec: dict[str, Any] = {
                "key": key,
                "question": q,
                "rep": r,
                "turn1": outcome(e1),
            }
            c = clarification_of(e1)
            if c is None:
                append_record(out, rec)
                measured += 1
                continue
            opts = stored_options(cid) or []
            by_id = {o["id"]: o for o in opts}
            rec["options"] = [
                {"id": o["id"], "label": o["label"], "database": o.get("database")}
                for o in opts
            ]
            chosen = pick_option(c, r)
            full = by_id.get(chosen["id"], chosen)
            rec["chosen"] = {
                "id": chosen["id"],
                "label": chosen["label"],
                "database": full.get("database"),
            }
            # M2: answer by option_id on the candidate; read the database it used.
            t = clock_iso()
            e2, _ = post_turn(
                client,
                cand_url,
                {
                    "question": chosen["label"],
                    "conversation_id": cid,
                    "supports_clarification": True,
                    "clarification": {
                        "clarification_id": c["clarification_id"],
                        "option_id": chosen["id"],
                    },
                },
                headers,
                stop=stopper(read_cand_log, t),
                sleep=sleep,
                poll_seconds=poll_seconds,
            )
            rec["m2"] = {"outcome": outcome(e2), **parse_db(read_cand_log(t))}
            # M1: what main's vote picks for the same choice, built as main builds
            # it from a click (no conversation, the choice as evidence).
            desc = chosen.get("description")
            answer = f"{chosen['label']} ({desc})" if desc else chosen["label"]
            t = clock_iso()
            e3, _ = post_turn(
                client,
                main_url,
                {
                    "question": q,
                    "evidence": f'The user defined "{c["term"]}" as: {answer}',
                },
                headers,
                stop=stopper(read_main_log, t),
                sleep=sleep,
                poll_seconds=poll_seconds,
            )
            rec["m1"] = {"outcome": outcome(e3), **parse_db(read_main_log(t))}
            append_record(out, rec)
            measured += 1
    return measured


# --- metrics and gates (report) --------------------------------------------


def _asked(
    by: dict[tuple[str, str], list[dict[str, Any]]], arm: str, kind: str
) -> tuple[int, int]:
    rs = by[(arm, kind)]
    return sum(1 for r in rs if r["outcome"] == "asked"), len(rs)


def summarize_m3(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """M3a and M3b counts and gates, and M4 label stability, from turn-1 rows."""
    by: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by[(r["arm"], r["kind"])].append(r)
    out: dict[str, Any] = {"counts": {}, "m4": {}}
    for kind in ("m3a", "m3b"):
        for arm in ("main", "cand"):
            a, n = _asked(by, arm, kind)
            errs = sum(1 for r in by[(arm, kind)] if r["outcome"] == "error")
            out["counts"][f"{kind}_{arm}"] = {"asked": a, "runs": n, "errors": errs}
    a_c, n_c = _asked(by, "cand", "m3a")
    a_m, n_m = _asked(by, "main", "m3a")
    complete_a = n_c == M3A_RUNS and n_m == M3A_RUNS
    out["m3a"] = {
        "cand_asks": a_c,
        "main_asks": a_m,
        "cand_runs": n_c,
        "main_runs": n_m,
        "complete": complete_a,
        "gate": ("PASS" if a_c <= a_m + M3A_MARGIN else "FAIL") if complete_a else None,
    }
    b_c, nb_c = _asked(by, "cand", "m3b")
    b_m, nb_m = _asked(by, "main", "m3b")
    complete_b = nb_c == M3B_RUNS and nb_m == M3B_RUNS
    out["m3b"] = {
        "cand_asks": b_c,
        "main_asks": b_m,
        "cand_runs": nb_c,
        "main_runs": nb_m,
        "complete": complete_b,
        "gate": ("PASS" if b_c >= b_m - M3B_MARGIN else "FAIL") if complete_b else None,
    }
    for arm in ("main", "cand"):
        labelled = [r for r in by[(arm, "m4")] if r["labels"]]
        sets = {tuple(sorted(r["labels"])) for r in labelled}
        out["m4"][arm] = {"distinct_label_sets": len(sets), "asked_runs": len(labelled)}
    return out


def _pinned(r: dict[str, Any]) -> bool:
    """The run's target_db is the option's database and no vote ran."""
    m2 = r["m2"]
    return m2["intent_target_db"] == r["chosen"]["database"] and m2["voted"] is None


def summarize_m12(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """M1 (how often main's vote contradicts the option) and the M2 gate."""
    asked = [r for r in rows if "chosen" in r]
    # Only runs that offered options from >= 2 databases count.
    multi = [
        r
        for r in asked
        if len({o["database"] for o in r["options"] if o["database"]}) >= 2
    ]
    pinnable = [r for r in multi if r["chosen"]["database"]]
    misses = [
        {
            "question": r["question"],
            "label": r["chosen"]["label"],
            "database": r["chosen"]["database"],
            "intent_target_db": r["m2"]["intent_target_db"],
            "voted": r["m2"]["voted"],
            "outcome": r["m2"]["outcome"],
        }
        for r in pinnable
        if not _pinned(r)
    ]
    # Informational, wider than the gate: every asked run that carries a database.
    any_db = [r for r in asked if r["chosen"]["database"]]
    dis = tot = 0
    by_q: Counter[str] = Counter()
    for r in pinnable:
        voted = r["m1"]["voted"]
        if voted is None:
            continue
        tot += 1
        if voted != r["chosen"]["database"]:
            dis += 1
            by_q[r["question"]] += 1
    return {
        "runs": len(rows),
        "turn1_asked": len(asked),
        "multi_database_runs": len(multi),
        "pinnable": len(pinnable),
        "m2": {
            "pinned": len(pinnable) - len(misses),
            "of": len(pinnable),
            "gate": None if not pinnable else ("PASS" if not misses else "FAIL"),
            "misses": misses,
            "all_asked_with_database": {
                "pinned": sum(1 for r in any_db if _pinned(r)),
                "of": len(any_db),
            },
        },
        "m1": {
            "differs": dis,
            "of": tot,
            "share": (dis / tot) if tot else None,
            "by_question": by_q.most_common(),
        },
    }


def render(m3: dict[str, Any] | None, m12: dict[str, Any] | None) -> str:
    lines: list[str] = []
    if m3 is not None:
        lines.append("== M3 / M4 (turn 1 only)")
        names = {"m3a": "M3a answerable", "m3b": "M3b undefined"}
        for kind in ("m3a", "m3b"):
            for arm in ("main", "cand"):
                c = m3["counts"][f"{kind}_{arm}"]
                lines.append(
                    "  %-15s %-5s asked %3d / %3d   (errors %d)"
                    % (names[kind], arm, c["asked"], c["runs"], c["errors"])
                )
        for kind, gate_text, total in (
            ("m3a", "cand asks <= main + %d" % M3A_MARGIN, M3A_RUNS),
            ("m3b", "cand asks >= main - %d" % M3B_MARGIN, M3B_RUNS),
        ):
            g = m3[kind]
            if g["gate"]:
                lines.append(f"  GATE M{kind[1:]} ({gate_text}): {g['gate']}")
            else:
                lines.append(
                    "  GATE %s: incomplete (%d/%d cand, %d/%d main)"
                    % ("M" + kind[1:], g["cand_runs"], total, g["main_runs"], total)
                )
        for arm in ("main", "cand"):
            s = m3["m4"][arm]
            lines.append(
                "  M4 %-5s distinct label sets: %d over %d asked runs"
                % (arm, s["distinct_label_sets"], s["asked_runs"])
            )
    if m12 is not None:
        lines.append("== M1 / M2 (one answered option per run)")
        lines.append("  runs %d, turn 1 asked %d" % (m12["runs"], m12["turn1_asked"]))
        lines.append(
            "  runs offering options from >= 2 databases: %d"
            % m12["multi_database_runs"]
        )
        lines.append("  answered options that carry a database: %d" % m12["pinnable"])
        m2 = m12["m2"]
        for miss in m2["misses"]:
            lines.append(
                "   M2 MISS: %s | chose %r (%s) -> intent=%s voted=%s outcome=%s"
                % (
                    miss["question"],
                    miss["label"],
                    miss["database"],
                    miss["intent_target_db"],
                    miss["voted"],
                    miss["outcome"],
                )
            )
        if m2["gate"]:
            lines.append(
                "  GATE M2 (pinned in 100%%): %d / %d -> %s"
                % (m2["pinned"], m2["of"], m2["gate"])
            )
        else:
            lines.append("  GATE M2: no answered option with a database yet")
        wide = m2["all_asked_with_database"]
        lines.append(
            "  (info, wider than the gate: %d / %d answered options with a "
            "database, any run)" % (wide["pinned"], wide["of"])
        )
        m1 = m12["m1"]
        if m1["of"]:
            lines.append(
                "  M1 (main's vote differs from the option's database): "
                "%d / %d = %.0f%%" % (m1["differs"], m1["of"], 100 * m1["share"])
            )
        for q, n in m1["by_question"]:
            lines.append("     %d  %s" % (n, q))
    return "\n".join(lines)


def build_report(
    m3_rows: list[dict[str, Any]], m12_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """The structured report: counts, gates and hashes, never a token."""
    from dev_tools.integrity.freeze import file_cases_sha256

    return {
        "protocol": "docs/conversation-protocol.md",
        "cases_file": CASES_FILE.name,
        "cases_sha256": file_cases_sha256(CASES_FILE),
        "answerable_file": ANSWERABLE_FILE.name,
        "answerable_sha256": file_cases_sha256(ANSWERABLE_FILE),
        "m3": summarize_m3(m3_rows) if m3_rows else None,
        "m12": summarize_m12(m12_rows) if m12_rows else None,
    }


# --- command line -----------------------------------------------------------


def cmd_run(args: Any, *, client: httpx.Client | None = None) -> int:
    """``conversation run``: measure (resumable) into a JSON Lines file."""
    import os
    import sys

    from auto_ontology.server.internal_auth import INTERNAL_TOKEN_ENV

    token = args.token or os.environ.get(INTERNAL_TOKEN_ENV) or None
    headers = auth_headers(args.user, token)
    out = Path(args.out)
    own = client is None
    http = client or httpx.Client()
    try:
        undefined = undefined_questions()
        if args.measure == "m3":
            if not args.arm or not args.url:
                print("error: m3 needs --arm and --url", file=sys.stderr)
                return 2
            n = run_m3(
                http,
                arm=args.arm,
                url=args.url,
                out=out,
                headers=headers,
                answerable=answerable_questions(),
                undefined=undefined,
                stability=stability_question(),
                workers=min(args.workers, M3_WORKERS * 2),
            )
        else:
            needed = (args.cand_url, args.cand_container, args.main_url)
            if not all(needed) or not args.main_container:
                print(
                    "error: m12 needs --cand-url, --cand-container, --main-url "
                    "and --main-container",
                    file=sys.stderr,
                )
                return 2
            n = run_m12(
                http,
                cand_url=args.cand_url,
                main_url=args.main_url,
                out=out,
                headers=headers,
                undefined=undefined,
                read_cand_log=docker_log_reader(args.cand_container),
                read_main_log=docker_log_reader(args.main_container),
                stored_options=make_option_store(
                    args.postgres_container, args.db_user, args.db_name
                ),
            )
    finally:
        if own:
            http.close()
    print(f"{n} run(s) recorded in {out}")
    return 0


def cmd_report(args: Any) -> int:
    """``conversation report``: print the metrics and gates; optionally save JSON."""
    m3_rows = load_records(Path(args.m3)) if args.m3 else []
    m12_rows = load_records(Path(args.m12)) if args.m12 else []
    report = build_report(m3_rows, m12_rows)
    print(render(report["m3"], report["m12"]))
    if args.out:
        Path(args.out).write_bytes(
            (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        )
    return 0
