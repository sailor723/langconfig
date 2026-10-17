"""Detect credentials in text that is about to be committed to the repo.

Why this exists: the settings export is scrubbed from the schema (every
``role="secret"`` field is dropped — see ``export_settings.py``), but the **agents**
and **tools** exports carry user-authored text: a system prompt, an ``AGENTS.md``
document, a tool's ``implementation_config``. Someone pasting a token into any of
those ships it to every teammate, and unlike a settings document there is no
schema to consult — the credential is just prose or code.

So the export refuses to write a file that looks like it holds a credential. The
point is not to be clever about detection; it is to make the leak impossible to
commit *silently*. A false positive costs one ``--redact`` run; a false negative
costs a key.

Usage in an exporter::

    from _secretscan import guard
    guard(sql, path=args.out, redact=args.redact)   # exits 1 unless clean/redacted
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Iterable

REDACTED = "***REDACTED-BY-SEED-OUT***"


@dataclass
class Finding:
    pattern: str
    line: int
    excerpt: str          # masked, safe to print

    def __str__(self) -> str:
        return f"line {self.line}: {self.pattern} — {self.excerpt}"


def _mask(value: str) -> str:
    """Show enough to locate the value, never enough to use it."""
    v = value.strip().strip("'\"")
    if len(v) <= 8:
        return "*" * len(v)
    return f"{v[:4]}…{v[-2:]} ({len(v)} chars)"


# Ordered most-specific first: a named pattern gives a better message than the
# generic assignment rule, and both are reported if both fire.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("OpenAI/Anthropic key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("Tavily key",           re.compile(r"\btvly-[A-Za-z0-9]{12,}")),
    ("Groq key",             re.compile(r"\bgsk_[A-Za-z0-9]{20,}")),
    ("Google API key",       re.compile(r"\bAIza[0-9A-Za-z_-]{30,}")),
    ("AWS access key id",    re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token",         re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("Slack token",          re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("Slack webhook",        re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/]{10,}")),
    ("Discord webhook",      re.compile(r"https://(?:discord|discordapp)\.com/api/webhooks/\d+/[A-Za-z0-9_-]{10,}")),
    ("Fernet ciphertext",    re.compile(r"\bgAAAAA[A-Za-z0-9_=-]{25,}")),
    ("private key block",    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("JWT",                  re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("Bearer token",         re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}=*")),
    # Generic: key/secret/token/password assigned a literal. Placeholders and
    # env indirection are excluded so this does not cry wolf on templates.
    ("assigned secret",      re.compile(
        r"""(?ix)
        \b(?:api[_-]?key|apikey|secret|token|password|passwd|access[_-]?key)
        \s*["']?\s*[:=]\s*        # key, optional closing quote (JSON/YAML), separator
        (?P<q>["'])(?P<val>[^"'\n]{16,})(?P=q)
        """)),
]

# Values that mean "not a real credential".
# Values that mean "not a real credential". Deliberately broad: a false positive
# here means a real key slips past, a false negative means the guard cries wolf
# until people learn to bypass it — which is worse.
_PLACEHOLDER = re.compile(
    r"(?i)(?:\$\{|\{\{|os\.getenv|getenv\(|process\.env|env\[|"
    r"your|my[_-]|here\b|x{6,}|placeholder|example|changeme|redacted|\*\*\*|"
    r"<[^>]{1,30}>|none|null|todo|dummy|sample|fake|fixture|"
    r"test|abc123|1234567890|abcdef\b)"
)


def scan(text: str) -> list[Finding]:
    """Every credential-shaped match, in line order."""
    out: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for name, rx in _PATTERNS:
            for m in rx.finditer(line):
                value = m.group("val") if name == "assigned secret" else m.group(0)
                if _PLACEHOLDER.search(value):
                    continue                      # template / fixture / redacted
                out.append(Finding(name, lineno, _mask(value)))
    return out


def redact(text: str) -> tuple[str, list[Finding]]:
    """Replace every credential-shaped match with a marker."""
    findings: list[Finding] = []
    for name, rx in _PATTERNS:
        def _sub(m: re.Match) -> str:
            value = m.group("val") if name == "assigned secret" else m.group(0)
            if _PLACEHOLDER.search(value):
                return m.group(0)                 # leave templates alone
            findings.append(Finding(name, 0, _mask(value)))
            return m.group(0).replace(value, REDACTED)
        text = rx.sub(_sub, text)
    return text, findings


def report(findings: Iterable[Finding], *, source: str) -> None:
    findings = list(findings)
    print(f"\n  !! {len(findings)} credential-shaped value(s) found in {source}:",
          file=sys.stderr)
    for f in findings[:20]:
        print(f"     {f}", file=sys.stderr)
    if len(findings) > 20:
        print(f"     … and {len(findings) - 20} more", file=sys.stderr)


def guard(text: str, *, source: str, redact_instead: bool = False) -> str:
    """Return text safe to write, or exit(1) after explaining what was found.

    Called with the fully generated artefact, before it touches the disk, so a
    leaky export leaves no file behind for anyone to commit by accident.
    """
    findings = scan(text)
    if not findings:
        return text

    if redact_instead:
        clean, _ = redact(text)
        report(findings, source=source)
        print("     --redact: wrote the file with those values replaced by "
              f"{REDACTED}.", file=sys.stderr)
        print("     The affected agent/tool will NOT work for teammates until the "
              "credential moves to Settings.\n", file=sys.stderr)
        return clean

    report(findings, source=source)
    print("     Refusing to write. A credential in this artefact would be committed "
          "and pushed to every teammate.", file=sys.stderr)
    print("     Fix the source: move the value to Settings → API Keys, which is "
          "never exported.", file=sys.stderr)
    print("     Or re-run with --redact to ship the artefact with the values "
          "blanked.\n", file=sys.stderr)
    raise SystemExit(1)
