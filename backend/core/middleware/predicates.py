"""Named review predicates for Human-in-the-loop.

LangChain's `InterruptOnConfig` accepts a `when` callable — ``True`` means
"stop and ask", ``False`` means "let it run". A policy that lives in JSON cannot
carry a Python callable, so the platform stores a *name* and resolves it here:

    "interrupt_on": {
        "bash":       {"allowed_decisions": ["approve", "reject"],
                       "when": "bash_may_mutate"},
        "write_file": {"allowed_decisions": ["approve", "reject"],
                       "when": "writes_deliverable"}
    }

Why this exists: a deep agent uses the same `bash` / `write_file` tools for its
own bookkeeping (`ls` of the workspace, `other/.tmp`, skill files). Gating the
tool gates all of that, so one user request turned into a queue of approvals
over the agent's own housekeeping. Predicates gate the *call*, not the tool.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

#: Commands that only read. Anything else (or any redirection/pipe) may change
#: state, so it is worth a review.
#: `2>/dev/null`, `2>&1`, `>/dev/null`, `&>/dev/null` — output that goes nowhere.
_DISCARD_REDIRECTS = re.compile(r"(\d?&?>\s*/dev/null|\d?>&\s*\d|&>\s*/dev/null)")

_READ_ONLY_COMMANDS = {
    "cd", "ls", "cat", "head", "tail", "wc", "grep", "rg", "find", "pwd", "echo",
    "which", "whoami", "date", "file", "stat", "du", "df", "tree", "sort",
    "uniq", "cut", "tr", "jq", "ps", "env", "printenv", "dirname", "basename",
}


def _command_of(request: Any) -> str:
    args = (getattr(request, "tool_call", None) or {}).get("args") or {}
    return str(args.get("command") or "")


def bash_may_mutate(request: Any) -> bool:
    """Interrupt a shell command unless it is plainly read-only."""
    command = _command_of(request).strip()
    if not command:
        return True

    # Strip redirects that discard output (`2>/dev/null`, `2>&1`, `>/dev/null`)
    # before looking for one that writes a file — those are part of everyday
    # read-only commands and an agent's `ls … 2>/dev/null` is not a write.
    residue = _DISCARD_REDIRECTS.sub(" ", command)
    if ">" in residue or "tee " in residue:
        return True

    for segment in command.replace("&&", ";").replace("||", ";").split(";"):
        segment = segment.strip()
        if not segment:
            continue
        for pipeline in segment.split("|"):
            pipeline = pipeline.strip()
            if not pipeline:
                continue
            first = pipeline.split()[0]
            if first.startswith("$") or first in ("sudo", "sh", "bash", "zsh"):
                return True
            if first not in _READ_ONLY_COMMANDS:
                return True
    return False


def writes_deliverable(request: Any) -> bool:
    """Interrupt a file write that lands outside the scratch folder.

    A workspace has `other/` for scratch and `skills/` for the agent's own
    reading material; everything else (`generated/`, uploads, absolute paths) is
    the user's world and is worth reviewing.
    """
    args = (getattr(request, "tool_call", None) or {}).get("args") or {}
    path = str(args.get("file_path") or args.get("path") or "")
    if not path:
        return True
    scratch = ("/other/", "\\other\\", "/skills/", "\\skills\\")
    return not any(marker in path for marker in scratch)


#: name → predicate. Keep this list short and legible: each entry is a promise
#: the editor offers in a dropdown.
PREDICATES: Dict[str, Callable[[Any], bool]] = {
    "bash_may_mutate": bash_may_mutate,
    "writes_deliverable": writes_deliverable,
}


def resolve_when(spec: Any, tool_name: Optional[str] = None) -> Optional[Callable[[Any], bool]]:
    """Translate a policy entry's ``when`` into a callable.

    Accepts a callable (already resolved), a known name, or nothing. An unknown
    name fails open toward review — we would rather ask than silently allow.
    """
    if spec is None:
        return None
    if callable(spec):
        return spec
    name = str(spec).strip()
    predicate = PREDICATES.get(name)
    if predicate is None:
        logger.warning(
            "Unknown HITL predicate '%s' for tool '%s' — the call will always "
            "require review (fail toward asking)", name, tool_name,
        )
        return lambda _request: True
    return predicate


__all__ = ["PREDICATES", "bash_may_mutate", "writes_deliverable", "resolve_when"]
