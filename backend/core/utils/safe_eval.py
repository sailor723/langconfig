# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Safe evaluation of user-authored workflow conditions.

Workflow CONDITIONAL/LOOP nodes let users write expressions like
``state.get("retry_count", 0) < 3``. These were previously evaluated with
``eval(expr, {"__builtins__": {}}, ctx)`` — the empty-builtins sandbox is
trivially bypassable via object-graph escapes (``().__class__.__bases__[0]
.__subclasses__()``), so a malicious condition string was arbitrary code
execution.

``safe_eval_expression`` validates the expression's AST first and only then
evaluates it:

- attribute access to any dunder (``__class__`` etc.) is rejected,
- calls are limited to an allowlist of safe builtins or methods on context
  values (e.g. ``state.get(...)``),
- names resolve exclusively against the provided context — any other name
  raises NameError (caught by the caller).
"""
import ast
import operator as _operator
from typing import Any, Dict

# Calls whose target is a bare Name must be in this allowlist.
_SAFE_CALLS = frozenset({
    "len", "str", "int", "float", "bool", "abs", "min", "max", "sum",
    "round", "list", "dict", "set", "tuple", "sorted", "reversed", "any",
    "all", "enumerate", "zip", "range", "isinstance", "type", "repr",
    "format", "chr", "ord", "hex", "oct", "bin", "divmod", "pow",
})

# Binary / unary / comparison operators are whitelisted explicitly.
_BINOPS = {
    ast.Add: _operator.add, ast.Sub: _operator.sub,
    ast.Mult: _operator.mul, ast.Div: _operator.truediv,
    ast.FloorDiv: _operator.floordiv, ast.Mod: _operator.mod,
    ast.Pow: _operator.pow, ast.BitAnd: _operator.and_,
    ast.BitOr: _operator.or_, ast.BitXor: _operator.xor,
    ast.LShift: _operator.lshift, ast.RShift: _operator.rshift,
    ast.MatMult: _operator.matmul,
}
_UNOPS = {ast.USub: _operator.neg, ast.UAdd: _operator.pos, ast.Not: _operator.not_}
_CMPOPS = {
    ast.Eq: _operator.eq, ast.NotEq: _operator.ne,
    ast.Lt: _operator.lt, ast.LtE: _operator.le,
    ast.Gt: _operator.gt, ast.GtE: _operator.ge,
    ast.Is: _operator.is_, ast.IsNot: _operator.is_not,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
}


class UnsafeExpressionError(ValueError):
    """Raised when an expression contains constructs outside the allowlist."""


def _validate(node: ast.AST) -> None:
    """Walk the AST and reject anything outside the safe subset."""
    if isinstance(node, ast.Expression):
        _validate(node.body)
    elif isinstance(node, ast.Attribute):
        # Dunder attribute access is the classic object-graph escape.
        if node.attr.startswith("__"):
            raise UnsafeExpressionError(
                f"attribute access to '{node.attr}' is not allowed"
            )
        _validate(node.value)
    elif isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            if node.func.id not in _SAFE_CALLS:
                raise UnsafeExpressionError(
                    f"call to '{node.func.id}()' is not allowed"
                )
        elif isinstance(node.func, ast.Attribute):
            _validate(node.func)  # method call on a context value (e.g. state.get)
        else:
            raise UnsafeExpressionError("unsupported call target")
        for a in node.args:
            _validate(a)
        for kw in node.keywords:
            _validate(kw.value)
    elif isinstance(node, ast.BinOp):
        if type(node.op) not in _BINOPS:
            raise UnsafeExpressionError(f"operator {type(node.op).__name__} is not allowed")
        _validate(node.left)
        _validate(node.right)
    elif isinstance(node, ast.UnaryOp):
        if type(node.op) not in _UNOPS:
            raise UnsafeExpressionError(f"operator {type(node.op).__name__} is not allowed")
        _validate(node.operand)
    elif isinstance(node, ast.BoolOp):
        for v in node.values:
            _validate(v)
    elif isinstance(node, ast.Compare):
        for c in node.comparators:
            _validate(c)
        for op in node.ops:
            if type(op) not in _CMPOPS:
                raise UnsafeExpressionError(f"comparison {type(op).__name__} is not allowed")
        _validate(node.left)
    elif isinstance(node, ast.IfExp):
        _validate(node.test)
        _validate(node.body)
        _validate(node.orelse)
    elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for e in node.elts:
            _validate(e)
    elif isinstance(node, ast.Dict):
        for k, v in zip(node.keys, node.values):
            if k is not None:
                _validate(k)
            _validate(v)
    elif isinstance(node, ast.Subscript):
        _validate(node.value)
        _validate(node.slice)
    elif isinstance(node, ast.Slice):
        if node.lower:
            _validate(node.lower)
        if node.upper:
            _validate(node.upper)
        if node.step:
            _validate(node.step)
    elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        _validate(node.elt)
        for gen in node.generators:
            _validate(gen.iter)
            if gen.ifs:
                for cond in gen.ifs:
                    _validate(cond)
    elif isinstance(node, ast.DictComp):
        _validate(node.key)
        _validate(node.value)
        for gen in node.generators:
            _validate(gen.iter)
            for cond in gen.ifs:
                _validate(cond)
    elif isinstance(node, ast.Lambda):
        _validate(node.body)
    elif isinstance(node, ast.Name):
        pass  # resolved against the caller-provided context at eval time
    elif isinstance(node, (ast.Constant, ast.Load, ast.Store, ast.arg,
                           ast.Starred, ast.keyword, ast.comprehension)):
        pass
    else:
        raise UnsafeExpressionError(
            f"expression construct '{type(node).__name__}' is not allowed"
        )


def safe_eval_expression(expr: str, context: Dict[str, Any]) -> Any:
    """Evaluate a user-authored expression against a restricted context.

    Raises:
        UnsafeExpressionError: if the expression uses disallowed constructs.
        NameError / others: if a name is missing or evaluation fails.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise UnsafeExpressionError(f"invalid expression: {e}") from e

    _validate(tree)

    # Names may only resolve from the caller's context. No builtins are
    # exposed (empty builtins dict) — safe callables are injected explicitly.
    import builtins as _builtins_mod
    namespace = dict(context)
    namespace.update(
        {name: getattr(_builtins_mod, name)
         for name in _SAFE_CALLS if hasattr(_builtins_mod, name)}
    )
    code = compile(tree, "<safe_expression>", "eval")
    return eval(code, {"__builtins__": {}}, namespace)  # noqa: S307 — AST pre-validated
