"""The loop guard must catch GROWTH, wherever the growth happens.

Two measured runaway turns:

  1. ten `psql -c … -c … -c …` calls — growth at the END of the command;
  2. seventy-eight `execute` calls of `grep -rn "samples" f1 … fN 2>/dev/null | head -20` — growth in the
     MIDDLE, because the `2>/dev/null | head -20` tail never moved. The prefix test was false on every call,
     so the guard stayed silent and the turn ran to the recursion limit with nothing produced.

A guard that cannot see the second shape is decoration, so the shapes are pinned here.
"""
from api.chat.messages import _args_grow


def test_growth_at_the_end_is_seen():
    a = '{"command": "psql -h 127.0.0.1 -d new_coldchain -c \\"select count(*) from trips where trip_date < 2025-01-01\\""}'
    b = a[:-2] + ' -c \\"select count(*) from trips where trip_date < 2025-02-01\\""}'
    assert _args_grow(a, b)


def test_growth_in_the_middle_is_seen():
    """The shape that got through: one more file appended, fixed shell tail unchanged."""
    head = '{"command": "cd /app && grep -rn \\"samples\\" '
    tail = ' 2>/dev/null | head -20"}'
    a = head + "sqlgen.py nl.py" + tail
    b = head + "sqlgen.py nl.py guard.py" + tail
    c = head + "sqlgen.py nl.py guard.py capability.py" + tail
    assert _args_grow(a, b), "middle growth (one more file) must count as growth"
    assert _args_grow(b, c)


def test_unrelated_commands_are_not_growth():
    assert not _args_grow('{"command": "ls -la /tmp"}', '{"command": "ls -la /var"}')
    assert not _args_grow('{"command": "cat a.txt"}', '{"command": "cat b.txt c.txt"}')
    assert not _args_grow('{"command": "grep -n foo a.py"}', '{"command": "grep -n bar b.py"}')


def test_shrinking_or_repeating_is_not_growth():
    a = '{"command": "grep -rn x a.py b.py c.py"}'
    b = '{"command": "grep -rn x a.py"}'
    assert not _args_grow(a, b), "a SHORTER call is not growth (it may be the fix)"
    assert not _args_grow(a, a), "equality is handled by the separate identical-call counter"


def test_a_legit_different_step_after_a_long_command_is_not_growth():
    """Honest work: write a file, then run the gate — neither is a repeat of the other."""
    write = '{"file_path": "/w/samples.json", "content": "[{\\"question\\": \\"x\\"}]"}'
    gate = '{"command": "python gates/check_samples.py --profile w/new_coldchain_settings.json"}'
    assert not _args_grow(write, gate)
    assert not _args_grow(gate, write)
