# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Run a cassette set through the real pipeline: record it, or replay it.

A set is a directory ``dev_tools/cassettes/<set>/`` holding ``manifest.json``
and the ``<hash>.json`` cassettes (see ``auto_ontology/utils/cassette.py`` and
``docs/recorded-evaluation.md``). The manifest names the case ids to ask, never
their text: the questions are read from the frozen files in
``dev_tools/evals/cases/`` so there is one copy of each.

::

    # Replay (CI): no model, no secret.
    python -m dev_tools.cassettes.run_set --set pagila_smoke --mode replay
    # Record (maintainer, against a real model; see the doc for the environment).
    python -m dev_tools.cassettes.run_set --set pagila_smoke --mode record

Per case it ingests nothing itself: the database's catalog and embeddings are
built first (``dev_tools.local_ingest.run_ingest``, so the embedding calls are
cassettes too) and then each question goes through ``stream_agent_response``,
the function the chat worker calls. A replay passes when every question ends in
a ``result`` event with the same SQL and the same sequence of graph steps as the
recording. It proves the pipeline and prompt construction behave as they did
when the cassettes were recorded; it says nothing about model quality.

This module imports nothing from ``auto_ontology`` at the top: the model
configuration is read from the environment at import time, so the environment is
prepared first.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

CASSETTES_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASSETTES_DIR.parents[1]
CASES_DIR = REPO_ROOT / "dev_tools" / "evals" / "cases"
SQL_DIR = REPO_ROOT / "dev_tools" / "fixtures" / "sql"

REPLAY_ENDPOINT = "http://cassette.invalid/v1"
REPLAY_KEY = "replay-not-a-secret"
PREFIXES = ("REASONING", "NON_REASONING", "EMBED", "RERANK")
# Non-secret settings that change a request body, so they are part of the
# recording and restored for the replay.
RECORDED_ENV_KEYS = (
    "REASONING_MODEL",
    "NON_REASONING_MODEL",
    "EMBED_MODEL",
    "RERANK_MODEL",
    "DEFAULT_MODELS_MODEL",
    "MODEL_NAME",
    "EMBED_DIMENSIONS",
    "EMBED_EXTRA_FIELDS",
    "QUESTION_TRANSLATION_DISABLED",
)
RESULT_PREFIX = "CASSETTE_RESULT "


def manifest_path(set_name: str, root: Path = CASSETTES_DIR) -> Path:
    return root / set_name / "manifest.json"


def discover_sets(root: Path = CASSETTES_DIR) -> list[str]:
    """Names of the sets that exist (a directory with a manifest)."""
    return sorted(p.parent.name for p in root.glob("*/manifest.json"))


def validate_manifest(manifest: dict[str, Any], cases_dir: Path = CASES_DIR) -> None:
    """Raise ``ValueError`` naming what is wrong with *manifest*."""
    for key in ("database", "cases_file", "case_ids"):
        if not manifest.get(key):
            raise ValueError(f"manifest is missing {key!r}")
    if manifest["database"] not in ("pagila", "chinook"):
        raise ValueError("manifest database must be 'pagila' or 'chinook'")
    cases_path = cases_dir / manifest["cases_file"]
    if not cases_path.is_file():
        raise ValueError(f"cases file {manifest['cases_file']} does not exist")
    known = {c["id"] for c in json.loads(cases_path.read_text("utf-8"))["cases"]}
    unknown = [i for i in manifest["case_ids"] if i not in known]
    if unknown:
        raise ValueError(f"case ids not in {manifest['cases_file']}: {unknown}")
    recorded = manifest.get("recorded", {})
    unrecorded = [i for i in manifest["case_ids"] if i not in recorded]
    if unrecorded:
        raise ValueError(f"case ids with no recorded outcome: {unrecorded}")


def replay_environment(manifest: dict[str, Any], directory: Path) -> dict[str, str]:
    """The environment of a replay: fake endpoints and keys, the recorded models."""
    env = {
        "LLM_CASSETTE_MODE": "replay",
        "LLM_CASSETTE_DIR": str(directory),
        # Every request is answered from disk; nothing may wait on a retry.
        "LLM_RATE_LIMIT_BUDGET_S": "0",
    }
    for prefix in PREFIXES:
        env[f"{prefix}_ENDPOINT"] = REPLAY_ENDPOINT
        env[f"{prefix}_API_KEY"] = REPLAY_KEY
    env.update(manifest.get("env", {}))
    return env


def connection_string(database: str) -> str:
    if database == "chinook":
        return f"sqlite:///{(SQL_DIR / 'chinook.sqlite').as_posix()}"
    user = os.environ["POSTGRES_USER"]
    password = os.environ["POSTGRES_PASSWORD"]
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def compare(recorded: dict[str, Any], outcomes: dict[str, dict[str, Any]]) -> list[str]:
    """What differs between the recording and this run, one line per difference."""
    problems = []
    for case_id, want in recorded.items():
        got = outcomes.get(case_id)
        if got is None:
            problems.append(f"{case_id}: not run")
        elif got.get("error"):
            problems.append(f"{case_id}: {got['error']}")
        elif got["sql"] != want["sql"]:
            problems.append(
                f"{case_id}: SQL changed\n  recorded: {want['sql']}\n  now:      {got['sql']}"
            )
        elif got["steps"] != want["steps"]:
            problems.append(
                f"{case_id}: graph steps changed\n  recorded: {want['steps']}\n  now:      {got['steps']}"
            )
    return problems


def _ask_all(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    from dev_tools.evals.cases import load_cases
    from dev_tools.local_ingest import run_ingest

    os.environ["CONNECTION_STRINGS"] = connection_string(manifest["database"])
    from auto_ontology.connectors import get_connectors
    from auto_ontology.retrieval.text_to_sql.main import stream_agent_response
    from auto_ontology.utils.retriever import get_data_objects_retriever

    run_ingest(os.environ["CONNECTION_STRINGS"])
    connectors = get_connectors()
    retriever = get_data_objects_retriever()
    cases = {c.id: c for c in load_cases(CASES_DIR / manifest["cases_file"])}

    outcomes: dict[str, dict[str, Any]] = {}
    for case_id in manifest["case_ids"]:
        case = cases[case_id]
        payload: dict[str, Any] = {
            "question": case.question,
            "connectors": connectors,
            "data_retriever": retriever,
            "target_db": manifest["database"],
        }
        if case.evidence:
            payload["evidence"] = case.evidence
        steps: list[str] = []
        outcome: dict[str, Any] = {"sql": "", "steps": steps, "error": ""}
        try:
            for event in stream_agent_response(payload):  # type: ignore[arg-type]
                if event.get("type") == "step" and event.get("phase") == "start":
                    steps.append(str(event.get("node")))
                elif event.get("type") == "result":
                    outcome["sql"] = (event.get("answer") or {}).get("sql_code") or ""
                elif event.get("type") == "error":
                    outcome["error"] = str(event.get("message"))
        except Exception as exc:  # noqa: BLE001 - reported per case
            outcome["error"] = f"{type(exc).__name__}: {exc}"
        if not outcome["error"] and not outcome["sql"]:
            outcome["error"] = "no result with SQL"
        outcomes[case_id] = outcome
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--set", dest="set_name", required=True)
    parser.add_argument("--mode", choices=("replay", "record"), required=True)
    parser.add_argument("--root", type=Path, default=CASSETTES_DIR)
    args = parser.parse_args(argv)

    directory = args.root / args.set_name
    path = manifest_path(args.set_name, args.root)
    manifest: dict[str, Any] = json.loads(path.read_text("utf-8"))

    if args.mode == "replay":
        validate_manifest(manifest)
        os.environ.update(replay_environment(manifest, directory))
    else:
        # A recording replaces the set: stale cassettes of the old prompts
        # would otherwise stay behind and pass for coverage.
        for old in directory.glob("*.json"):
            if old.name != "manifest.json":
                old.unlink()
        os.environ["LLM_CASSETTE_MODE"] = "record"
        os.environ["LLM_CASSETTE_DIR"] = str(directory)

    outcomes = _ask_all(manifest)
    print(RESULT_PREFIX + json.dumps(outcomes, sort_keys=True))

    if args.mode == "record":
        manifest["env"] = {
            k: os.environ[k] for k in RECORDED_ENV_KEYS if os.environ.get(k)
        }
        manifest["recorded"] = {
            k: {"sql": v["sql"], "steps": v["steps"]}
            for k, v in outcomes.items()
            if not v["error"]
        }
        path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        failed = [k for k, v in outcomes.items() if v["error"]]
        if failed:
            print(f"Recording kept, but these cases failed: {failed}", file=sys.stderr)
            return 1
        return 0

    problems = compare(manifest["recorded"], outcomes)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
