"""`./start.sh` must never kill the process it is running inside.

Measured twice on 2026-11-11: an agent whose `bash` tool is a real shell was
asked to restart the stack, ran `./start.sh`, and the script killed the listener
on :8765 — the backend hosting that very chat turn. The turn vanished mid-tool
(the UI spun, then said "Load failed"), and because LangGraph re-runs an
unfinished tool call when the thread resumes, the *next* message killed the
freshly started backend again. The user saw an agent that could not finish a
sentence, and a stack that needed restarting by hand each time.

The guard that fixes it lives in start.sh (`ancestor_pids` / `is_protected_pid`):
a PID that is an ancestor of the script is hosting the command and is skipped.
These tests keep the guard honest — one checks the text (so the call sites cannot
quietly drop it), one exercises the decision with a stubbed process table (so it
is verified on a machine where `ps` is unavailable, which is how the first
version of this guard silently degraded to doing nothing).
"""
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
START_SH = REPO / "start.sh"

GUARD_START = "# ── ancestor guard"
GUARD_END = "# ── port helpers"


def _guard_snippet() -> str:
    """The guard block of start.sh, verbatim — the test must run the real code."""
    if not START_SH.is_file():
        pytest.skip("start.sh not present")
    text = START_SH.read_text(encoding="utf-8")
    start = text.find(GUARD_START)
    end = text.find(GUARD_END)
    assert start != -1 and end != -1 and start < end, "the ancestor-guard block moved: update this test"
    return text[start:end]


# ── the text guard: both call sites consult the guard ──

def test_kill_old_consults_the_ancestor_guard_at_both_call_sites():
    """Two ways to kill exist — the PID file and the port listener — and a fix at
    only one of them still kills the turn that asked for the restart."""
    text = START_SH.read_text(encoding="utf-8")
    kill_old = text[text.index("kill_old() {"):text.index("start_postgres() {")]

    # 1) PID file branch
    assert "is_protected_pid \"$old_pid\"" in kill_old, "the PID-file branch no longer checks ancestry"
    # 2) port-listener branch
    assert "is_protected_pid \"$p\"" in kill_old, "the port-listener branch no longer checks ancestry"
    # The old form — comparing against SELF_PID only — must be gone from both.
    assert '[ "$old_pid" != "$SELF_PID" ]' not in kill_old
    assert '[ "$p" != "$SELF_PID" ]' not in kill_old


def test_the_guard_has_a_parent_lookup_that_does_not_need_ps():
    """`ps` is the obvious way to walk up the tree and the one that was blocked
    when this gap was found. /proc and lsof have to remain as fallbacks."""
    text = START_SH.read_text(encoding="utf-8")
    assert "/proc/$p/stat" in text, "the Linux /proc fallback is gone"
    assert "lsof -p \"$p\" -F pR" in text, "the lsof fallback is gone"


# ── the behavioural test: with a stubbed process table ──

STUB_PS = r"""#!/bin/bash
# Answers `ps -o ppid= -p PID` from a fixed tree: 100 -> 200 -> 300 -> 1
while [ $# -gt 0 ]; do
    case "$1" in
        -p) shift; pid="$1" ;;
    esac
    shift
done
case "$pid" in
    100) echo 200 ;;
    200) echo 300 ;;
    300) echo 1 ;;
    999) echo 42 ;;
    *) exit 1 ;;
esac
"""


def test_the_guard_protects_ancestors_and_nothing_else(tmp_path):
    """PID 100 is "this script"; the tree above it must be untouchable, and an
    unrelated PID must still be killable (otherwise a normal restart breaks)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "ps"
    stub.write_text(STUB_PS, encoding="utf-8")
    stub.chmod(0o755)

    probe = tmp_path / "probe.sh"
    probe.write_text(
        "set -u\n"
        "SELF_PID=100\n"
        + _guard_snippet()
        + "\n"
        'echo "PROTECTED=$PROTECTED_PIDS"\n'
        'if is_protected_pid 200; then echo "parent:protected"; else echo "parent:MISSED"; fi\n'
        'if is_protected_pid 300; then echo "grandparent:protected"; else echo "grandparent:MISSED"; fi\n'
        'if is_protected_pid 100; then echo "self:protected"; else echo "self:MISSED"; fi\n'
        'if is_protected_pid 999; then echo "unrelated:protected"; else echo "unrelated:killable"; fi\n',
        encoding="utf-8",
    )

    env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    out = subprocess.run(
        ["bash", str(probe)], capture_output=True, text=True, timeout=60, env=env,
    )
    assert out.returncode == 0, out.stderr
    lines = set(out.stdout.split())

    assert "parent:protected" in lines, out.stdout
    assert "grandparent:protected" in lines, out.stdout
    assert "self:protected" in lines, out.stdout
    assert "unrelated:killable" in lines, (
        "an unrelated PID must stay killable, or `./start.sh` from a terminal stops replacing "
        f"the old server:\n{out.stdout}"
    )
