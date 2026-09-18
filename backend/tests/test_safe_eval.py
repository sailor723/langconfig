# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests for the safe workflow-condition evaluator.

Workflow CONDITIONAL/LOOP conditions were evaluated with
``eval(expr, {"__builtins__": {}}, ctx)`` — bypassable via object-graph
escapes (``().__class__.__bases__[0].__subclasses__()``), i.e. RCE from a
crafted workflow. safe_eval_expression AST-validates first.
"""
import pytest

from core.utils.safe_eval import UnsafeExpressionError, safe_eval_expression


# ── legitimate conditions must keep working ─────────────────────────

def test_dict_get_comparison():
    ctx = {"state": {"retry_count": 2}}
    assert safe_eval_expression('state.get("retry_count", 0) < 3', ctx) is True


def test_len_call():
    ctx = {"state": {"messages": [1, 2, 3]}}
    assert safe_eval_expression('len(state.get("messages", [])) > 0', ctx) is True


def test_arithmetic_and_boolean_ops():
    ctx = {"state": {"x": 5}}
    assert safe_eval_expression("state.get('x') >= 3 and state.get('x') <= 10", ctx) is True
    assert safe_eval_expression("(state.get('x') * 2) == 10", ctx) is True
    assert safe_eval_expression("not state.get('missing', False)", ctx) is True


def test_membership_and_comparisons():
    ctx = {"state": {"tags": ["a", "b"]}}
    assert safe_eval_expression('"a" in state.get("tags", [])', ctx) is True
    assert safe_eval_expression('state.get("tags") != []', ctx) is True


def test_plain_true():
    assert safe_eval_expression("True", {}) is True


# ── escapes must be rejected ─────────────────────────────────────────

@pytest.mark.parametrize("evil", [
    "().__class__.__bases__[0].__subclasses__()",
    "state.__class__",
    "state.get('x').__class__",
    "getattr(state, '__class__')",
    "__import__('os').system('id')",
    "open('/etc/passwd').read()",
    "eval('1+1')",
    "exec('pass')",
    "compile('1', '<s>', 'eval')",
    "globals()",
    "locals()",
    "type(state)()",
    "state.items().__class__",
    "(lambda: 1)() and __import__('os')",
])
def test_evil_conditions_rejected(evil):
    with pytest.raises(UnsafeExpressionError):
        safe_eval_expression(evil, {"state": {"x": 1}})


def test_unknown_name_raises_nameerror():
    with pytest.raises(NameError):
        safe_eval_expression("os.system('id')", {})
    with pytest.raises(NameError):
        safe_eval_expression("subprocess.run('id')", {})


def test_syntax_error_rejected():
    with pytest.raises(UnsafeExpressionError):
        safe_eval_expression("state.get(", {})


# ── executor sites no longer use raw eval ───────────────────────────

def test_executor_nodes_no_raw_eval():
    import inspect
    from core.workflows.executor import nodes

    src = inspect.getsource(nodes)
    assert "eval(condition_expr" not in src
    assert "eval(exit_condition" not in src
    assert "safe_eval_expression" in src
