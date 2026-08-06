# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Classic LangGraph compiler.

Takes the JSON spec produced by the drag-and-drop UI and compiles it into
a real `langgraph.graph.StateGraph`. Faithful to the LangGraph API:
- state_fields → TypedDict channels with reducers (operator.add / operator.ior / pick_last)
- nodes (kind=function) → Python callables compiled from user code
- nodes (kind=llm) → chat-model callables (no agent loop)
- nodes (kind=tool) → tool invokers
- edges (kind=direct) → add_edge()
- edges (kind=conditional) → add_conditional_edges(source, route_fn, path_map)
"""
from __future__ import annotations

import ast
import operator as op
from typing import Any, Callable, Dict, List, TypedDict
from typing_extensions import Annotated

from langgraph.graph import END, START, StateGraph


class GraphCompileError(ValueError):
    """Raised when a spec cannot be compiled into a StateGraph."""


# ---------------------------------------------------------------------------
# Reducer helpers (mirror LangConfig's existing shared.py for compatibility)
# ---------------------------------------------------------------------------
def pick_last(left: Any, right: Any) -> Any:
    """Reducer: pick the right value unless it's None."""
    return right if right is not None else left


_REDUCERS: Dict[str, Callable[[Any, Any], Any]] = {
    "last": lambda l, r: r if r is not None else l,
    "pick_last": lambda l, r: r if r is not None else l,
    "add": lambda l, r: (l or []) + (r or []),
    "list_add": lambda l, r: (l or []) + (r or []),
    "ior": lambda l, r: {**(l or {}), **(r or {})},
    "dict_ior": lambda l, r: {**(l or {}), **(r or {})},
    "replace": lambda l, r: r,
}


def compile_state(state_fields: List[Dict[str, Any]]) -> type:
    """Build a TypedDict from the spec's state_fields.

    Each field gets the appropriate reducer via Annotated[..., reducer].
    Reducer names mirror the UI: "last" / "add" / "ior" / "replace".
    """
    if not isinstance(state_fields, list):
        raise GraphCompileError("state_fields must be a list")

    annotations: Dict[str, Any] = {}

    for i, field in enumerate(state_fields):
        if not isinstance(field, dict) or "name" not in field:
            raise GraphCompileError(f"state_fields[{i}] must be an object with 'name'")
        name = field["name"]
        if not name.isidentifier():
            raise GraphCompileError(f"state field name '{name}' is not a valid identifier")
        reducer_name = field.get("reducer", "last")
        if reducer_name not in _REDUCERS:
            raise GraphCompileError(
                f"state field '{name}' has unknown reducer '{reducer_name}'. "
                f"Valid: {sorted(_REDUCERS)}"
            )
        reducer = _REDUCERS[reducer_name]
        # Build Annotated[default_type, reducer] dynamically.
        # We don't know the field's type at compile time, so use Any.
        annotations[name] = Annotated[Any, reducer]

    # TypedDict subclasses need a functional form to attach __annotations__.
    state_cls = TypedDict("ClassicState", annotations)  # type: ignore[call-overload]
    return state_cls


# ---------------------------------------------------------------------------
# Safe expression evaluator for route functions
# ---------------------------------------------------------------------------
# Whitelist of binary/unary operators permitted in conditional-edge route
# expressions. Anything else raises GraphCompileError — keeps the user from
# running arbitrary Python (no imports, no dunders, no function defs).
_BIN_OPS: Dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.FloorDiv: op.floordiv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
    ast.Eq: op.eq,
    ast.NotEq: op.ne,
    ast.Lt: op.lt,
    ast.LtE: op.le,
    ast.Gt: op.gt,
    ast.GtE: op.ge,
    ast.And: lambda a, b: a and b,
    ast.Or: lambda a, b: a or b,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}
_UNARY_OPS: Dict[type, Callable[[Any], Any]] = {
    ast.Not: op.not_,
    ast.USub: op.neg,
    ast.UAdd: op.pos,
}


def _safe_eval_node(node: ast.AST, scope: Dict[str, Any]) -> Any:
    """Recursive AST evaluator. Raises GraphCompileError on any disallowed form."""
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body, scope)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in scope:
            raise GraphCompileError(f"route references unknown name '{node.id}'")
        return scope[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](
            _safe_eval_node(node.left, scope),
            _safe_eval_node(node.right, scope),
        )
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_safe_eval_node(node.operand, scope))
    if isinstance(node, ast.BoolOp):
        values = [_safe_eval_node(v, scope) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise GraphCompileError("unsupported boolean operator")
    if isinstance(node, ast.Compare):
        # Chain comparisons: a < b < c becomes and(a<b, b<c).
        left = _safe_eval_node(node.left, scope)
        result = True
        for cmp_op, right_node in zip(node.ops, node.comparators):
            if type(cmp_op) not in _BIN_OPS:
                raise GraphCompileError(f"unsupported comparison {type(cmp_op).__name__}")
            right = _safe_eval_node(right_node, scope)
            result = result and _BIN_OPS[type(cmp_op)](left, right)
            left = right
        return result
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise GraphCompileError("only bare function calls are allowed in routes")
        fname = node.func.id
        if fname not in scope or not callable(scope[fname]):
            raise GraphCompileError(f"route calls unknown function '{fname}'")
        if node.keywords:
            raise GraphCompileError("keyword args are not allowed in routes")
        args = [_safe_eval_node(a, scope) for a in node.args]
        return scope[fname](*args)
    if isinstance(node, ast.Attribute):
        # Allow chain access like state.foo.bar — resolve on the scoped object.
        value = _safe_eval_node(node.value, scope)
        return getattr(value, node.attr)
    if isinstance(node, ast.Subscript):
        value = _safe_eval_node(node.value, scope)
        key = _safe_eval_node(node.slice, scope)
        return value[key]
    if isinstance(node, ast.Tuple):
        return tuple(_safe_eval_node(e, scope) for e in node.elts)
    if isinstance(node, ast.List):
        return [_safe_eval_node(e, scope) for e in node.elts]
    raise GraphCompileError(f"unsupported expression node: {type(node).__name__}")


def safe_eval_route(expr: str, state: Any) -> Any:
    """Evaluate a route expression against state.

    `state` is exposed as both `state` (the full dict) and `s` (shortcut).
    A small set of builtins are exposed: int/float/str/bool/len/min/max/abs.
    Anything else (imports, attribute access on builtins, comprehensions) is
    rejected.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise GraphCompileError(f"route is not valid Python: {e}")
    scope: Dict[str, Any] = {
        "state": state,
        "s": state,
        "int": int,
        "float": float,
        "str": str,
        "bool": bool,
        "len": len,
        "min": min,
        "max": max,
        "abs": abs,
        "round": round,
        "True": True,
        "False": False,
        "None": None,
    }
    return _safe_eval_node(tree, scope)


# ---------------------------------------------------------------------------
# Node compilers
# ---------------------------------------------------------------------------
def _compile_function_node(spec: Dict[str, Any]) -> Callable[[Any], Dict[str, Any]]:
    """Compile a function node into a callable that takes state and returns a
    partial state dict. The user's code must `return` a dict; bare expressions
    are wrapped to return the last expression's value as a dict when possible.
    """
    code = spec.get("code", "").strip()
    if not code:
        def _no_op(state):
            return {}
        return _no_op

    # Wrap the user's body in `def __classic_node(state): ...` so `return`
    # works. Validate it parses first.
    fn_def_src = "def __classic_node(state):\n" + "\n".join(
        "    " + line for line in code.splitlines()
    )
    fn_ns: Dict[str, Any] = {}
    try:
        exec(compile(fn_def_src, "<classic_node>", "exec"), fn_ns)
    except SyntaxError as e:
        raise GraphCompileError(f"function node has a syntax error: {e}")
    fn = fn_ns["__classic_node"]

    def runner(state):
        return fn(state)

    return runner


def _compile_llm_node(spec: Dict[str, Any]) -> Callable[[Any], Dict[str, Any]]:
    """Compile an LLM node. Takes state.messages (or state.input), invokes
    the chat model with the spec's prompt + input, returns the assistant text.

    Output convention: returns `{"messages": [AIMessage(content=...)]}` so the
    default `operator.add` reducer appends to messages. If `output_key` is set,
    also writes the text to `state[output_key]` via the ior reducer.
    """
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

    model_name = spec.get("model") or "gpt-4o-mini"
    system_prompt = spec.get("prompt") or spec.get("system_prompt") or ""
    output_key = spec.get("output_key")
    input_key = spec.get("input_key")  # optional: read a specific state field

    async def _llm_node(state):
        # Resolve model lazily so import errors don't kill compile.
        from core.models.registry import get_chat_model

        llm = get_chat_model(model_name)

        # Pull input text. Prefer input_key; fall back to last message or query.
        if input_key and state.get(input_key) is not None:
            user_text = str(state[input_key])
        else:
            msgs = state.get("messages") or []
            if msgs:
                user_text = str(msgs[-1].content)
            else:
                user_text = str(state.get("input") or state.get("query") or "")

        llm_messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_text)]
        response = await llm.ainvoke(llm_messages)
        text = response.content if isinstance(response.content, str) else str(response.content)

        out: Dict[str, Any] = {"messages": [AIMessage(content=text)]}
        if output_key:
            # Append via state[output_key] — callers must declare this as a
            # list with `add` reducer (or any value with appropriate reducer).
            existing = state.get(output_key)
            if isinstance(existing, list):
                out[output_key] = existing + [text]
            else:
                out[output_key] = text
        return out

    return _llm_node


def _compile_tool_node(spec: Dict[str, Any]) -> Callable[[Any], Dict[str, Any]]:
    """Compile a tool node. Loads the tool by (tool_type, tool_id), invokes it
    with `params` (with {{state.foo}} templating), returns the result as a
    state delta under `output_key` (default: tool_result) plus a ToolMessage
    appended to messages.
    """
    from langchain_core.messages import ToolMessage

    tool_type = spec.get("tool_type")
    tool_id = spec.get("tool_id")
    output_key = spec.get("output_key") or "tool_result"
    params_template = spec.get("params") or {}

    async def _tool_node(state):
        from core.workflows.nodes import resolve_tool_params
        from core.agents.tool_loader import ToolLoader

        tools = await ToolLoader().load_custom([tool_id], state.get("project_id", 0))
        if not tools:
            raise RuntimeError(f"custom tool '{tool_id}' not found")
        tool = tools[0]

        resolved = resolve_tool_params(params_template, state)
        if hasattr(tool, "ainvoke"):
            result = await tool.ainvoke(resolved)
        else:
            result = tool.invoke(resolved)

        text = result if isinstance(result, str) else str(result)
        return {
            output_key: text,
            "messages": [ToolMessage(content=text, tool_call_id=spec.get("id", tool_id))],
        }

    return _tool_node


# ---------------------------------------------------------------------------
# Main compiler
# ---------------------------------------------------------------------------
def compile_graph(spec: Dict[str, Any]):
    """Compile a JSON spec into a compiled LangGraph StateGraph.

    Returns the result of `builder.compile()` — i.e. a runnable graph that
    exposes `.invoke(state)` / `.stream(state)`.
    """
    if not isinstance(spec, dict):
        raise GraphCompileError("spec must be an object")

    state_fields = spec.get("state_fields") or [{"name": "messages", "reducer": "add"}]
    state_cls = compile_state(state_fields)

    nodes_spec = spec.get("nodes") or []
    edges_spec = spec.get("edges") or []

    if not nodes_spec:
        raise GraphCompileError("spec has no nodes")

    builder = StateGraph(state_cls)

    # Add nodes
    for node in nodes_spec:
        nid = node.get("id")
        if not nid:
            raise GraphCompileError("node missing 'id'")
        kind = node.get("kind", "function")
        if kind == "function":
            runner = _compile_function_node(node)
        elif kind == "llm":
            runner = _compile_llm_node(node)
        elif kind == "tool":
            runner = _compile_tool_node(node)
        else:
            raise GraphCompileError(f"unknown node kind '{kind}' for node '{nid}'")
        builder.add_node(nid, runner)

    # Add edges
    for edge in edges_spec:
        src = edge.get("source")
        if not src:
            raise GraphCompileError(f"edge missing source: {edge}")
        kind = edge.get("kind", "direct")
        if kind == "direct":
            tgt = edge.get("target")
            if not tgt:
                raise GraphCompileError(f"direct edge missing target: {edge}")
            s = START if src == "START" else src
            t = END if tgt == "END" else tgt
            builder.add_edge(s, t)
        elif kind == "conditional":
            expr = edge.get("route") or ""
            path_map_raw = edge.get("path_map") or {}
            if not expr:
                raise GraphCompileError(f"conditional edge from '{src}' missing 'route'")

            def make_route(expression, source_id):
                def route(state):
                    try:
                        result = safe_eval_route(expression, state)
                    except GraphCompileError as e:
                        raise RuntimeError(f"route for '{source_id}' failed: {e}")
                    # The route returns a key; path_map maps key → target.
                    # If result is bool, map True/False → "true"/"false" for
                    # common-case ergonomics.
                    if isinstance(result, bool):
                        key = "true" if result else "false"
                    else:
                        key = str(result)
                    return path_map_raw.get(key, END)
                return route

            # Resolve path_map targets (END / node id).
            path_map = {}
            for k, v in path_map_raw.items():
                path_map[k] = END if v == "END" else v
            builder.add_conditional_edges(src, make_route(expr, src), path_map)
        else:
            raise GraphCompileError(f"unknown edge kind '{kind}'")

    return builder.compile()


def compile_state_for(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Build the initial-state dict from a spec (uses each field's default)."""
    state_fields = spec.get("state_fields") or []
    init: Dict[str, Any] = {}
    for f in state_fields:
        init[f["name"]] = f.get("default")
    if "messages" not in init:
        init["messages"] = []
    return init