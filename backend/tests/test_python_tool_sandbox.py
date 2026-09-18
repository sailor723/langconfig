# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests for the python_function tool exec sandbox.

python_function tool code was exec'd with full builtins plus os/pathlib/io
pre-loaded in the backend process — RCE at tool-creation time for any
user/agent/bundle-authored tool. Fix: platform-seeded built-ins keep the
full namespace; all other tools get static AST validation + a restricted
namespace (no __import__/open/eval/exec/compile, no os/sys/pathlib/io).
"""
import pytest

from core.tools.factory.builders import (
    _validate_untrusted_python,
    _untrusted_tool_namespace,
)

SAFE_CODE = '''
import math
import json
from typing import Optional

def my_tool(x: float, label: Optional[str] = None) -> str:
    return f"{label or 'val'}: {math.sqrt(x)}"
'''


# ── AST validation ───────────────────────────────────────────────────

@pytest.mark.parametrize("code,what", [
    ("import os\ndef f(): pass", "import 'os'"),
    ("import subprocess\ndef f(): pass", "import 'subprocess'"),
    ("import pathlib\ndef f(): pass", "import 'pathlib'"),
    ("import io\ndef f(): pass", "import 'io'"),
    ("import sys\ndef f(): pass", "import 'sys'"),
    ("from os import system\ndef f(): pass", "import 'os'"),
    ("import httpx\ndef f(): pass", "import 'httpx'"),
    ("def f():\n    return open('/etc/passwd').read()", "calls forbidden builtin 'open()'"),
    ("def f():\n    return eval('1+1')", "calls forbidden builtin 'eval()'"),
    ("def f():\n    return __import__('os').system('id')", "calls forbidden builtin '__import__()'"),
    ("def f():\n    return ().__class__.__bases__", "forbidden attribute '__class__'"),
    ("def f():\n    return ().__class__.__subclasses__()", "forbidden attribute '__subclasses__'"),
    ("def f():\n    return compile('x', '<s>', 'exec')", "calls forbidden builtin 'compile()'"),
])
def test_untrusted_code_rejected(code, what):
    with pytest.raises(ValueError, match="python_function tool"):
        _validate_untrusted_python(code, "evil")


def test_safe_code_accepted():
    _validate_untrusted_python(SAFE_CODE, "my_tool")  # must not raise


# ── restricted namespace ─────────────────────────────────────────────

def test_restricted_namespace_has_no_dangerous_names():
    ns = _untrusted_tool_namespace()
    for name in ("os", "sys", "pathlib", "io", "subprocess", "socket", "requests"):
        assert name not in ns, f"{name} leaked into the untrusted namespace"


def test_restricted_namespace_builtins_exclude_escapes():
    ns = _untrusted_tool_namespace()
    builtins = ns["__builtins__"]
    for name in ("open", "eval", "exec", "compile", "input",
                 "globals", "locals", "breakpoint"):
        assert name not in builtins, f"{name} must not be available to untrusted code"
    # __import__ is present but gated to the safe-module list.
    assert "__import__" in builtins


def test_restricted_import_gate_blocks_dangerous_modules():
    ns = _untrusted_tool_namespace()
    with pytest.raises(ImportError, match="not allowed"):
        exec("import os\ndef f(): return 1", ns)  # noqa: S102
    with pytest.raises(ImportError, match="not allowed"):
        exec("import subprocess\ndef f(): return 1", ns)  # noqa: S102


def test_safe_tool_runs_in_restricted_namespace():
    ns = _untrusted_tool_namespace()
    exec(SAFE_CODE, ns)  # noqa: S102 — deliberate: testing the sandbox itself
    assert ns["my_tool"](9.0, "sqrt") == "sqrt: 3.0"


def test_import_os_fails_at_runtime_even_if_ast_check_bypassed():
    """Defense in depth: the runtime import gate blocks `import os`."""
    ns = _untrusted_tool_namespace()
    with pytest.raises(ImportError, match="not allowed"):
        exec("import os\ndef f(): return 1", ns)  # noqa: S102
