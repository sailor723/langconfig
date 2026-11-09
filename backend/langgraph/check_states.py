"""check_states — does every node read only fields its State annotation carries?

WHY THIS EXISTS. LangGraph builds a node's input from the annotation on its first
parameter. A node declared `state: MessagesState` receives ONLY `messages` — the
other fields of the graph's real state (`semantics`, `sql_database`, a plan, a
connection override) are silently dropped. Nothing raises:

    def generate_query(state: MessagesState):
        prompt = _semantics_prompt(state)      # state has no "semantics" -> ""
        ...

The bug that cost an afternoon of measurement: `load_semantics` wrote
`state["semantics"]`, `generate_query` declared `MessagesState`, and the business
rules never reached the model — while every test looked like "the model ignores
the rules".

This checker is static (ast only, no imports, no database): for each node it
compares the fields the function body reads against the fields the annotated
State class declares.

    python backend/langgraph/check_states.py

Exit code 0 = clean, 1 = at least one node reads a field its State cannot carry.
"""
from __future__ import annotations

import ast
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent

# LangGraph's built-ins: fields every MessagesState-compatible schema carries.
BUILTIN_STATE_FIELDS = {
    "MessagesState": {"messages"},
    "State": set(),
}


def state_fields(tree: ast.Module) -> dict[str, set[str]]:
    """Class name -> the field names it declares (inheriting from MessagesState)."""
    out: dict[str, set[str]] = dict(BUILTIN_STATE_FIELDS)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        fields: set[str] = set()
        bases = {getattr(b, "id", None) or getattr(b, "attr", None) for b in node.bases}
        for base in bases:
            if base in out:
                fields |= out[base]
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                fields.add(stmt.target.id)
        out[node.name] = fields
    return out


def reads_of_state(func: ast.FunctionDef) -> set[str]:
    """Field names the function reads off `state` — state.get("x") / state["x"]."""
    reads: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            fn = node.func
            if (isinstance(fn, ast.Attribute) and fn.attr == "get"
                    and isinstance(fn.value, ast.Name) and fn.value.id == "state"
                    and node.args and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                reads.add(node.args[0].value)
        elif isinstance(node, ast.Subscript):
            if (isinstance(node.value, ast.Name) and node.value.id == "state"
                    and isinstance(node.slice, ast.Constant)
                    and isinstance(node.slice.value, str)):
                reads.add(node.slice.value)
    return reads


def helper_calls(func: ast.FunctionDef) -> set[str]:
    """Names of local functions called as `helper(state)` inside this function."""
    called: set[str] = set()
    for node in ast.walk(func):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and any(isinstance(a, ast.Name) and a.id == "state" for a in node.args)):
            called.add(node.func.id)
    return called


def transitive_reads(func: ast.FunctionDef, direct: dict[str, set[str]]) -> set[str]:
    """Everything this function reads off state, following `helper(state)` calls.

    The bug this catches is usually indirect: the node calls `_semantics_prompt(state)`
    and the field access lives inside that helper. Checking only the node's own body
    would pass a graph that is broken.
    """
    seen: set[str] = set()
    stack = [func]
    while stack:
        cur = stack.pop()
        if cur.name in seen:
            continue
        seen.add(cur.name)
        for name in helper_calls(cur):
            if name in direct:
                stack.append(direct_targets[name]) if name in direct_targets else None
    # merge direct reads of every function reached
    out: set[str] = set()
    for name in seen:
        out |= direct.get(name, set())
    return out


def node_signature(func: ast.FunctionDef) -> str | None:
    """The annotation on the first parameter, when it is a plain name."""
    if not func.args.args:
        return None
    ann = func.args.args[0].annotation
    if isinstance(ann, ast.Name):
        return ann.id
    if isinstance(ann, ast.Attribute):
        return ann.attr
    return None


def main() -> int:
    problems: list[str] = []
    checked = 0
    for path in sorted(HERE.glob("*.py")):
        if path.name.startswith("check_") or path.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            problems.append(f"{path.name}: syntax error — {exc}")
            continue
        fields = state_fields(tree)
        funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        global direct_targets
        direct_targets = {f.name: f for f in funcs}
        direct = {f.name: reads_of_state(f) for f in funcs}
        for func in funcs:
            sig = node_signature(func)
            if sig is None or sig not in fields:
                continue
            reads = transitive_reads(func, direct)
            if not reads:
                continue
            checked += 1
            missing = sorted(reads - fields[sig])
            if missing:
                problems.append(
                    f"{path.name}:{func.lineno} {func.name}(state: {sig}) reads "
                    f"{missing} — not in {sig}, so LangGraph never passes them"
                )

    print(f"== check_states: {checked} node(s) read state fields\n")
    for line in problems:
        print(f"  FAIL {line}")
    if problems:
        print(f"\n{len(problems)} node(s) read a field their State annotation cannot carry")
        return 1
    print("  gate: every node reads only fields its State declares — PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
