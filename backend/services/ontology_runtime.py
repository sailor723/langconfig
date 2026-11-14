"""The ontology runtime: ONE process, one lock, every ontology.

Why this module exists. The compiler was written as a command-line tool: it read `$APP_SETTINGS`
once at import and bound that profile into module state (`sqlgen.NS` / `CUBE` / `OVERLAY`,
`guard.SETTINGS`, `actions.SETTINGS` / `SCHEMA` / `DSN`, `i18n.SETTINGS`). The app therefore served
every ontology through a CHILD PROCESS — a virtualenv, an interpreter start and a re-import per
request — because two profiles in one interpreter would have fought over those names, and the loser
would answer with the other ontology's tables.

M1 moved the compiler into the app (and its dependencies into the app's venv). This module finishes
the job: `ontology_profile.use()` points the compiler at the profile being served, and `_LOCK`
serialises `use() + compile()` so two concurrent requests cannot interleave. Compiling is
milliseconds; the database round-trip happens under the same lock because the guard's limits and
the connection's DSN are profile state too — measured at 43–280 ms per question, i.e. cheaper than
starting a process was (≈390 ms).

What does NOT happen here: the gates. They still run as their own process, on purpose — a gate must
see the files on disk exactly as a user would, and a crashing gate must not take the app with it.
"""
from __future__ import annotations

import re

import json
import logging
import os
import pathlib
import threading

logger = logging.getLogger(__name__)

#: The compiler's state is process-wide, so every entry point takes this lock.
_LOCK = threading.RLock()

FEATURE = pathlib.Path(__file__).resolve().parents[1] / "features" / "ontology"
COMPILER = FEATURE / "compiler"
GATES = FEATURE / "gates"
PROFILES = FEATURE / "profiles"
#: The learning mirror, consulted ONLY when a checkout sets `ONTOLOGY_REPO` explicitly. A deployment
#: never sets it: the declarations live in `profiles/`, inside this app.
MIRROR = pathlib.Path(os.environ["ONTOLOGY_REPO"]) if os.environ.get("ONTOLOGY_REPO") else None


class OntologyError(Exception):
    """The ontology cannot be resolved or the compiler refused the request."""


def profile_for(key: str) -> pathlib.Path | None:
    """Where one ontology's DECLARATIONS live: in this app's feature.

    The learning mirror is a fallback only when `ONTOLOGY_REPO` is set — so a checkout that still keeps
    the mirror can read it, and a deployment that has never heard of it resolves everything locally.
    """
    candidates = [
        PROFILES / key / f"{key}_settings.json",
        PROFILES / key / "settings.json",
    ]
    if MIRROR is not None:
        candidates += [
            MIRROR / "ontologies" / key / f"{key}_settings.json",
            MIRROR / "ontologies" / key / "settings.json",
            MIRROR / "retail_graph" / f"{key}_settings.json",
        ]
        if key == "retail":
            candidates.append(MIRROR / "retail_graph" / "settings.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _require(key: str) -> pathlib.Path:
    profile = profile_for(key)
    if profile is None:
        raise OntologyError(f"no ontology {key!r} — nothing to compile")
    return profile


def _compiler():
    """Import the compiler modules, in one place, with the feature on sys.path."""
    import sys

    for path in (str(COMPILER), str(FEATURE)):
        if path not in sys.path:
            sys.path.insert(0, path)
    import ontology_profile  # noqa: PLC0415

    return ontology_profile


def dashboards() -> list[dict]:
    """Which ontologies DECLARE a dashboard (a board is a declaration, not a default)."""
    out = []
    for folder in sorted(PROFILES.glob("*")):
        if folder.is_dir() and (folder / "dashboard.json").is_file():
            out.append({"key": folder.name, "path": str(folder / "dashboard.json")})
    return out


# ── the dashboard ───────────────────────────────────────────────────────────
def panels(key: str, *, filters: dict | None = None) -> dict:
    """Run `<profile dir>/dashboard.json` in this process and return the payload."""
    profile = _require(key)
    path = profile.parent / "dashboard.json"
    if not path.is_file():
        raise OntologyError(
            f"{key} has no dashboard declaration ({path}); the dashboard is a declaration, not a "
            f"default — write one, or this ontology simply has no dashboard yet")
    with _LOCK:
        _compiler().use(profile)
        import run_dashboard  # noqa: PLC0415

        payload = run_dashboard.build(profile, dim_filters=filters or None)
    if payload.get("error") and not payload.get("panels"):
        raise OntologyError(str(payload["error"]))
    return payload


# ── a business question ─────────────────────────────────────────────────────
def ask(key: str, question: str, *, polish: bool = False) -> dict:
    """One question through the ontology's own pipeline (rules first, model only when unsure)."""
    text = (question or "").strip()
    if not text:
        raise OntologyError("ask a question; an empty one has no answer")
    profile = _require(key)
    # the deterministic template answers unless a caller asks for polished prose: an answer here is
    # the number and the SQL behind it, not a paragraph about them
    os.environ.setdefault("NL_ANSWER_LLM", "1" if polish else "0")
    # The answer and its interpretation must agree: rules-answer + model-intent is how a
    # refusal became an engine error in the first place.
    os.environ.setdefault("NL_INTENT_LLM", "1" if polish else "0")
    with _LOCK:
        prof = _compiler()
        prof.use(profile)
        import nl  # noqa: PLC0415

        graph = prof.graph()
        try:
            out = nl.ask(text, graph=graph, record=False, slots=False)
        except getattr(nl, "NlRefusal", Exception) as exc:      # a refusal is an answer
            # …UNLESS the question is one only the reasoner can answer. An ontology whose facts are
            # entailed (talent_v1: "who clears this role's bar") has questions no metric names, and
            # refusing them in the chat panel would hide the one thing this ontology can do. The
            # fallback is narrow and named: it fires only for questions shaped like the three the
            # reasoner answers, and it says so in `source`.
            reasoner_answer = _reasoner_fallback(key, text)
            if reasoner_answer is not None:
                return reasoner_answer
            return {"ok": False, "key": key, "question": text,
                    "refused": str(exc), "answer": getattr(exc, "polished", None) or str(exc)}
    result = out.get("result") or {}
    return {
        "ok": True, "key": key, "question": text,
        "answer": out.get("answer"),
        "kind": result.get("kind"),
        "metric": result.get("name"),
        "value": result.get("value"),
        "rows": result.get("rows"),
        "sql": result.get("sql"),
        "guard": result.get("guard"),
        "notes": result.get("notes"),
        "source": out.get("answer_source"),
        "needs_confirmation": out.get("needs_confirmation"),
        "intent": out.get("intent"),
        "steps": [{"step": s.get("step"), "ms": s.get("ms"), "detail": s.get("detail")}
                  for s in (out.get("steps") or [])],
    }


# ── the declared write verbs ────────────────────────────────────────────────
def _actions():
    with _LOCK:
        prof = _compiler()
        import actions  # noqa: PLC0415

        return prof, actions


def declared_actions(key: str) -> dict:
    """Every verb this ontology declares, with its compiled preconditions."""
    profile = _require(key)
    try:
        prof, actions = _actions()
        with _LOCK:
            prof.use(profile)
            if actions.actions_path() is None or not pathlib.Path(actions.actions_path()).is_file():
                return {"ok": True, "key": key, "actions": [],
                        "note": "this ontology declares no write verbs (no actions file)"}
            compiled = actions.compile_actions(actions.load_graph(), actions.load_config())
            return {"ok": True, "key": key, "actions": actions.list_actions(compiled)}
    except Exception as exc:                                    # noqa: BLE001
        return {"ok": False, "key": key, "actions": [], "error": f"{type(exc).__name__}: {exc}"}


def invoke(key: str, action: str, params: dict, *, dry_run: bool = False,
           actor: str | None = None) -> dict:
    """`check` (read-only) or `run` (one transaction + an audit row). A refusal is a result."""
    profile = _require(key)
    prof, actions = _actions()
    with _LOCK:
        prof.use(profile)
        try:
            compiled = actions.compile_actions(actions.load_graph(), actions.load_config())
            if dry_run:
                payload = actions.check_action(action, params, compiled=compiled)
            else:
                payload = actions.run_action(action, params, actor or "app", compiled=compiled)
            # a dry run that would not be admitted IS the refusal a caller is asking about
            ok = payload.get("admitted") if dry_run else payload.get("ok")
            return {"ok": bool(ok), "exit_code": 0 if ok else 2, "key": key, "action": action,
                    "verb": "check" if dry_run else "run", "result": payload}
        except Exception as exc:                                # noqa: BLE001 — a refusal, by name
            return {"ok": False, "exit_code": 2, "key": key, "action": action,
                    "verb": "check" if dry_run else "run",
                    "result": {"ok": False, "refused": str(exc)}}


def audit(key: str, limit: int = 50) -> dict:
    """The append-only trail of the writes this ontology's verbs have made."""
    profile = _require(key)
    prof, actions = _actions()
    try:
        with _LOCK:
            prof.use(profile)
            return {"ok": True, "key": key, "events": actions.recent_audit(limit=limit)}
    except Exception as exc:                                    # noqa: BLE001
        return {"ok": False, "key": key, "events": [], "error": f"{type(exc).__name__}: {exc}"}


def profile_info(key: str) -> dict:
    """What the runtime is pointed at — for a health check that does not guess."""
    profile = _require(key)
    settings = json.loads(profile.read_text(encoding="utf-8"))
    return {"key": key, "profile": str(profile), "ns": settings.get("ns"),
            "dsn": {k: v for k, v in (settings.get("dsn") or {}).items() if k != "password"},
            "features": settings.get("features") or {},
            "dashboard": str(profile.parent / "dashboard.json")
            if (profile.parent / "dashboard.json").is_file() else None}


#: The three shapes the reasoner answers in the chat panel. Deliberately few and explicit: a chat that
#: silently reinterprets any refused question would teach users that a refusal is negotiable.
_REASONER_PATTERNS = (
    ("members", re.compile(r"^(?:谁|哪些人|哪几个人)(?:能|可以)?(?:过|通过|符合|合格|满足)"
                           r"(?P<role>.+?)(?:的)?(?:门槛|要求|条件)?\s*[?？]?$")),
    ("count", re.compile(r"^(?P<role>.+?)(?:岗位)?(?:有)?(?:多少|几个)(?:人|名)(?:过线|合格|符合|满足)"
                         r"\s*[?？]?$")),
    ("why", re.compile(r"^为什么(?P<cand>[^\s，,]+?)(?:能|可以)?(?:过|通过|符合|合格)(?P<role>.+?)"
                       r"(?:的)?(?:门槛|要求|条件)?\s*[?？]?$")),
)


_ROLE_NOISE = re.compile(r"(这道|那个|这个|的|门槛|要求|条件|岗位|职位|匹配)$")


def _resolve_role(key: str, raw: str) -> str:
    """The role the question means, as a class this ontology defines.

    Measured: "谁过业务跟单这道门槛" captured `业务跟单这道` and refused, because a reasoner-shaped
    question wraps the role in words the pattern cannot know. Rather than grow the regex, ask the ontology
    which of ITS classes appears in the text — longest first, so `副总助理` beats `助理`.
    """
    from services import ontology_reasoner

    text = _ROLE_NOISE.sub("", raw.strip())
    known = ontology_reasoner.reasoned(key)["classes"]
    local = [(c.rsplit("#", 1)[-1], c) for c in known]
    for name, _iri in sorted(local, key=lambda x: -len(x[0])):
        short = name[len("matches_"):] if name.startswith("matches_") else name
        if short and short in raw:
            return short
    return text


def _reasoner_fallback(key: str, question: str) -> dict | None:
    """{...} when the question is reasoner-shaped and the profile has an ABox, else None."""
    from services import ontology_reasoner

    text = question.strip()
    for kind, pattern in _REASONER_PATTERNS:
        m = pattern.match(text)
        if not m:
            continue
        role = _resolve_role(key, (m.groupdict().get("role") or "").strip())
        if not role:
            continue
        try:
            if kind == "members":
                view = ontology_reasoner.reason_view(key, "matches_" + role, 10)
                return {"ok": True, "key": key, "question": text, "source": "reasoner",
                        "answer": (f"{role}：ABox 里断言 0 人，推理得出 {view['entailed']} 人"
                                   f"（{view['engine']} {view['elapsed_ms']} ms）。"),
                        "kind": "reasoned_members", "metric": f"matches_{role}",
                        "rows": [{"candidate": r} for r in view["rows"]],
                        "value": view["entailed"],
                        "sql": None,
                        "notes": ["这批人没有任何一行写着「合格」——类型是推理出来的",
                                  "check_abox 的 A7 会在删掉定义后要求这个数变成 0"]}
            if kind == "count":
                view = ontology_reasoner.reason_view(key, "matches_" + role, 1)
                return {"ok": True, "key": key, "question": text, "source": "reasoner",
                        "answer": (f"{role}：推理得出 {view['entailed']} 人过线"
                                   f"（ABox 断言 {view['asserted']} 人）。"),
                        "kind": "reasoned_count", "metric": f"matches_{role}",
                        "value": view["entailed"], "sql": None}
            cand = (m.groupdict().get("cand") or "").strip()
            detail = ontology_reasoner.why(key, cand, "matches_" + role)
            return {"ok": True, "key": key, "question": text, "source": "reasoner",
                    "answer": ("为什么 " + detail["candidate"] + " 能过 " + role + "："
                               + "；".join(detail["facts"])),
                    "kind": "reasoned_why", "metric": f"matches_{role}",
                    "rows": [{"事实": f} for f in detail["facts"]],
                    "notes": [detail["axiom"]], "sql": None}
        except ontology_reasoner.Unavailable:
            return None
    return None
