# SPDX-License-Identifier: Apache-2.0

"""The recorded-model regression check (roadmap step 12, part A).

Until a set of cassettes is committed under ``dev_tools/cassettes/<set>/`` these
tests pass with a printed note rather than skip: the CI guard that fails a run
with more than three skipped tests exists so that a fixture silently going
missing is noticed, and a deliberately empty cassette directory is not that.

* ``test_cassette_sets_are_wellformed`` always runs: every committed set has a
  valid manifest, parseable cassettes and no credential in them.
* ``test_replay_through_the_real_pipeline`` runs the real pipeline against the
  cassettes in a subprocess (the model configuration is read at import time)
  when ``LEXIS_REPLAY_PIPELINE=1``. The dedicated CI step sets it, after the
  main test run, because it re-ingests the fixture database into the CI
  Postgres and the main run's golden tests must not see that.

See ``docs/recorded-evaluation.md``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from dev_tools.cassettes import run_set

_HASH_FILE = re.compile(r"^[0-9a-f]{64}\.json$")
# Shapes of credentials that must never be committed.
_SECRET_SHAPES = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{12,}|nvapi-[A-Za-z0-9_-]{16,}"
    r"|\"authorization\"|\"x-api-key\")",
    re.IGNORECASE,
)


def _note(message: str) -> None:
    print(f"NOTE: {message}")


def test_cassette_sets_are_wellformed() -> None:
    sets = run_set.discover_sets()
    if not sets:
        _note(
            "no cassette set is committed under dev_tools/cassettes/, so there is "
            "nothing to check yet; see docs/recorded-evaluation.md to record one."
        )
        return
    for name in sets:
        directory = run_set.CASSETTES_DIR / name
        manifest: dict[str, Any] = json.loads(
            (directory / "manifest.json").read_text("utf-8")
        )
        run_set.validate_manifest(manifest)
        files = [p for p in directory.glob("*.json") if p.name != "manifest.json"]
        assert files, f"set {name} has a manifest but no cassettes"
        for file in files:
            assert _HASH_FILE.match(file.name), f"{name}/{file.name}: not a cassette"
            document = json.loads(file.read_text("utf-8"))
            assert document["responses"], f"{name}/{file.name}: no response"
            leaked = _SECRET_SHAPES.search(file.read_text("utf-8"))
            assert leaked is None, f"{name}/{file.name}: looks like a credential"


def test_replay_through_the_real_pipeline() -> None:
    sets = run_set.discover_sets()
    if os.environ.get("LEXIS_REPLAY_PIPELINE") != "1":
        _note("LEXIS_REPLAY_PIPELINE is not 1: the replay runs in its own CI step.")
        return
    if not sets:
        _note("no cassette set is committed yet: replay has nothing to run.")
        return
    for name in sets:
        done = subprocess.run(
            [sys.executable, "-m", "dev_tools.cassettes.run_set"]
            + ["--set", name, "--mode", "replay"],
            cwd=run_set.REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        assert done.returncode == 0, (
            f"replay of set {name} failed:\n{done.stderr[-4000:]}\n"
            "A 'No recorded response' error means the prompt or request changed; "
            "if that is intended, re-record (docs/recorded-evaluation.md)."
        )
        assert run_set.RESULT_PREFIX in done.stdout, done.stdout[-2000:]


def test_replay_environment_is_offline_and_keyless() -> None:
    env = run_set.replay_environment({"env": {"REASONING_MODEL": "m"}}, Path("d"))
    assert env["LLM_CASSETTE_MODE"] == "replay"
    assert env["REASONING_MODEL"] == "m"
    for prefix in run_set.PREFIXES:
        assert env[f"{prefix}_ENDPOINT"].startswith("http://cassette.invalid")
        assert env[f"{prefix}_API_KEY"] == run_set.REPLAY_KEY


def test_compare_names_what_changed() -> None:
    recorded = {
        "a": {"sql": "SELECT 1", "steps": ["x", "y"]},
        "b": {"sql": "SELECT 2", "steps": ["x"]},
        "c": {"sql": "SELECT 3", "steps": ["x"]},
        "d": {"sql": "SELECT 4", "steps": ["x"]},
    }
    outcomes = {
        "a": {"sql": "SELECT 1", "steps": ["x", "y"], "error": ""},
        "b": {"sql": "SELECT 9", "steps": ["x"], "error": ""},
        "c": {"sql": "SELECT 3", "steps": ["z"], "error": ""},
        "d": {"sql": "", "steps": [], "error": "CassetteMiss: hash abc"},
    }
    problems = run_set.compare(recorded, outcomes)
    assert len(problems) == 3
    assert not any(p.startswith("a:") for p in problems)
    assert any(p.startswith("b: SQL changed") for p in problems)
    assert any(p.startswith("c: graph steps changed") for p in problems)
    assert any("CassetteMiss" in p for p in problems)


def test_manifest_validation_rejects_unknown_cases_and_missing_recordings() -> None:
    good: dict[str, Any] = {
        "database": "pagila",
        "cases_file": "pagila.json",
        "case_ids": ["pagila.top5_films_revenue"],
        "recorded": {"pagila.top5_films_revenue": {"sql": "x", "steps": []}},
    }
    run_set.validate_manifest(good)
    with pytest.raises(ValueError, match="not in pagila.json"):
        run_set.validate_manifest({**good, "case_ids": ["pagila.nope"]})
    with pytest.raises(ValueError, match="no recorded outcome"):
        run_set.validate_manifest({**good, "recorded": {}})
    with pytest.raises(ValueError, match="database"):
        run_set.validate_manifest({**good, "database": "oracle"})
