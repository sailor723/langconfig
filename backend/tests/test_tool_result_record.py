"""What the transcript keeps of a tool result — and why 500 characters was not enough.

Measured on one real ontology build (session `9b8c8bf8…`, 260 tool calls): every result was clipped at 500
characters, the median result *was* 500, 190 of 260 were cut mid-sentence, and only 70 still carried the harness's
`[Command succeeded…]` / `[Command failed…]` marker. The evidence that explains why a number changed was frequently
past the cut — which matters the moment someone asks an agent to turn a session into a skill.

The same session also exposed a second lie: `status` said `completed` for all 260 calls, including eight that failed
with `No such file`, `timed out after 120 seconds`, `ModuleNotFoundError` and `ERROR: column … does not exist`.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from api.chat.messages import (
    TOOL_RESULT_MAX_CHARS,
    clip_tool_result,
    derive_tool_status,
)

MESSAGES = pathlib.Path(__file__).resolve().parents[1] / "api" / "chat" / "messages.py"


def test_a_long_result_is_kept_well_past_the_old_cut():
    payload = "x" * 5_000 + "\n[Command succeeded with exit code 0]"
    clipped = clip_tool_result(payload)
    assert len(clipped["result"]) == len(payload), "a 5 000-character result must survive intact"
    assert clipped["result_truncated"] is False
    assert clipped["result_length"] == len(payload)
    assert "[Command succeeded with exit code 0]" in clipped["result"], (
        "the harness marker is how a reader tells success from failure — cutting it made 190 of 260 results "
        "unreadable")


def test_an_enormous_result_says_that_it_was_cut():
    payload = "y" * (TOOL_RESULT_MAX_CHARS + 1234)
    clipped = clip_tool_result(payload)
    assert len(clipped["result"]) == TOOL_RESULT_MAX_CHARS
    assert clipped["result_truncated"] is True, (
        "a reader must be able to tell 'the output ended here' from 'the record ended here'")
    assert clipped["result_length"] == len(payload)


def test_an_empty_result_records_that_it_was_empty():
    clipped = clip_tool_result("")
    assert clipped == {"result": "", "result_length": 0, "result_truncated": False}


@pytest.mark.parametrize("text", [
    "[stderr] bash: ontology/01-structure.ttl: No such file or directory\n[Command failed with exit code 1]",
    "Error: Command timed out after 120 seconds.",
    "ModuleNotFoundError: No module named 'psycopg2'",
    '[stderr] ERROR:  column "trip_id" specified in USING clause does not exist in right table',
])
def test_a_failure_is_recorded_as_a_failure(text: str):
    assert derive_tool_status(text) == "failed", (
        "the harness reports every call as completed; the transcript has to carry what happened")


@pytest.mark.parametrize("text", [
    "[Command succeeded with exit code 0]\n14/14 gates PASS",
    "stops | ontime | pct\n 51210 |  47920 | 93.6",
    "",
])
def test_a_success_is_not_flagged(text: str):
    assert derive_tool_status(text) == "completed"


def test_the_500_character_clip_is_gone_from_the_persistence_path():
    source = MESSAGES.read_text(encoding="utf-8")
    offenders = [m.group(0) for m in re.finditer(r'\[:500\]', source)]
    assert not offenders, (
        f"{len(offenders)} site(s) still clip a tool result to 500 characters — that is the cut that hid the "
        "evidence")
    assert source.count("clip_tool_result(") >= 2, "both persistence sites should record results the same way"
    assert "derive_tool_status(" in source, "status still comes straight from the harness"


def test_a_probe_command_that_finds_nothing_missing_is_not_a_failure():
    """Measured on the coding agent's first recon run.

    `ls -d backend docs start.sh` exists to find out what is *absent*; it prints `No such file or directory` on stderr
    and still exits 0. The heuristic alone marked three of eighteen calls `failed` for doing exactly what was asked,
    so an explicit success marker now wins over the markers below it.
    """
    probe = ("ls: cannot access 'backend': No such file or directory\n"
             "[stderr] ls: cannot access 'docs': No such file or directory\n"
             "[Command succeeded with exit code 0]")
    assert derive_tool_status(probe) == "completed"


def test_an_explicit_failure_marker_still_wins():
    out = "[stderr] psql: error: connection refused\n[Command failed with exit code 2]"
    assert derive_tool_status(out) == "failed"
