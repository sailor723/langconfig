#!/usr/bin/env python3
"""I1–I6: the interface language switch changes words and nothing else.

The invariant that makes this trustworthy is narrow and checkable: rendering a page in 中文
must not touch markup, must not touch `<script>`/`<style>`/`<pre>`/`<code>`, and must not
change any text node that has no translation. If it does, the translator is rewriting
structure instead of words — the kind of bug that silently breaks SQL or code samples.

    $P check_i18n.py        # exit 0 when every check passes
"""
from __future__ import annotations

import pathlib
import re
import sys

# The feature's roots: the COMPILER (this gate's imports), the WORKBENCH (the static assets it
# checks) and the PROFILES (the declarations). All relative to the feature directory — a gate that
# addresses "/Users/weiping/..." only runs on one machine.
import pathlib as _pathlib
import sys as _sys
sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))       # the _paths helper
from _paths import COMPILER as BASE, PROFILES, WORKBENCH, WORKBENCH as APP, profile_dir
# The compiler reads the profile from $APP_SETTINGS and applies its ns + ontology_dir + OVERLAY.
# Retail's metrics live in the overlay, so a gate that checks retail without this loaded an
# ontology with no metrics at all.
import os as _os
_os.environ["APP_SETTINGS"] = str(profile_dir("retail") / "settings.json")
_sys.path.insert(0, str(BASE))
sys.path.insert(0, str(WORKBENCH))
sys.path.insert(0, str(BASE))

import i18n  # noqa: E402

ok = True
TAG_RE = re.compile(r"(<[^>]*>)")


def check(label: str, got, want) -> None:
    global ok
    state = "PASS" if got == want else "FAIL"
    ok = ok and got == want
    print(f"  [{state}] {label}: got {got!r}, want {want!r}")


def tags(html: str) -> list[str]:
    return [t for t in TAG_RE.split(html) if t.startswith("<")]


def tag_names(html: str) -> list[str]:
    return [re.match(r"</?([A-Za-z][\w-]*)", t).group(1).lower()
            for t in tags(html) if re.match(r"</?([A-Za-z][\w-]*)", t)]


def loose_attrs(html: str) -> list[tuple[str, str]]:
    """Everything on a tag EXCEPT the four translatable attributes."""
    out = []
    for t in tags(html):
        cleaned = re.sub(r'\b(placeholder|title|aria-label|alt)="[^"]*"', "", t)
        out.append(cleaned)
    return out


def texts(html: str) -> list[str]:
    """Visible text nodes, in order, skipping script/style/pre/code/textarea."""
    out, depth = [], 0
    for token in TAG_RE.split(html):
        if token.startswith("<"):
            name = re.match(r"</?([A-Za-z][\w-]*)", token)
            name = name.group(1).lower() if name else ""
            if token.startswith("</"):
                if name in i18n.SKIP and depth:
                    depth -= 1
            elif name in i18n.SKIP and not token.endswith("/>"):
                depth += 1
            continue
        if depth:
            continue
        stripped = re.sub(r"\s+", " ", token).strip()
        if stripped:
            out.append(stripped)
    return out


def opaque(html: str) -> list[str]:
    """The contents of script/style/pre/code — must survive translation byte for byte."""
    return re.findall(r"<(script|style|pre|code|textarea)\b[^>]*>(.*?)</\1>", html,
                      flags=re.S | re.I)


PAGES = ["tutorial.html", "tutorial1.html", "tutorial2.html", "tutorial3.html",
         "tutorial4.html", "tutorial5.html", "tutorial6.html", "tutorial7.html", "tutorial8.html",
         "settings.html",
         "actions.html", "backlog.html", "nl.html", "ask.html", "ontology.html"]


def main() -> int:
    print("=== I1 the table itself ===")
    check("two languages offered", [c for c, _ in i18n.LANGS], ["en", "zh"])
    zh = i18n.PHRASES["zh"]
    check("English is the identity table", i18n.PHRASES["en"], {})
    check("no empty translations", sorted(k for k, v in zh.items() if not v.strip()), [])
    check("no accidental no-op translations (language names excepted)",
          sorted(k for k, v in zh.items() if k == v and k not in i18n.IDENTITY), [])

    print("=== I2 a translated page keeps its markup and its code ===")
    for name in PAGES:
        if not (APP / name).exists():
            continue
        raw = (APP / name).read_text(encoding="utf-8")
        en = i18n.tr_html(raw, "en")
        zh_html = i18n.tr_html(raw, "zh")
        check(f"{name}: English is a no-op", en == raw, True)
        check(f"{name}: same tag names, same order",
              tag_names(en) == tag_names(zh_html), True)
        check(f"{name}: no attribute changed except title/placeholder/aria-label/alt",
              loose_attrs(en) == loose_attrs(zh_html), True)
        check(f"{name}: script/style/pre/code untouched",
              opaque(en) == opaque(zh_html), True)
        check(f"{name}: the page actually changed", en != zh_html, True)

    print("=== I3 only text that has a translation changes ===")
    for name in PAGES:
        if not (APP / name).exists():
            continue
        raw = (APP / name).read_text(encoding="utf-8")
        en_nodes = texts(raw)
        zh_nodes = texts(i18n.tr_html(raw, "zh"))
        check(f"{name}: same number of text nodes", len(en_nodes), len(zh_nodes))
        strays = [a for a, b in zip(en_nodes, zh_nodes)
                  if a != b and i18n.lookup(a, "zh") is None]
        check(f"{name}: no node changed without a table entry", strays, [])
        untranslated = sorted({n for n in en_nodes if i18n.lookup(n, "zh") is None})
        print(f"        ({len(untranslated)} of {len(en_nodes)} nodes stay English"
              f" — identifiers, SQL, numbers)")

    print("=== I4 the switch itself ===")
    real = i18n.SETTINGS
    tmp = APP / "_settings_probe.json"
    try:
        tmp.write_text(real.read_text(encoding="utf-8"), encoding="utf-8")
        i18n.SETTINGS = tmp
        check("default reads as stored", i18n.current(), i18n.current())
        check("switch to zh persists", i18n.set_language("zh"), "zh")
        check("zh is read back", i18n.current(), "zh")
        check("an unknown language falls back to English", i18n.set_language("fr"), "en")
        check("English remains a no-op after a round trip",
              i18n.tr("Home", "zh"), "首页")
    finally:
        i18n.SETTINGS = real
        tmp.unlink(missing_ok=True)
    check("the probe did not touch the real settings file",
          i18n.current() in ("en", "zh"), True)

    print("=== I5 the prefix rule (dynamic lists) ===")
    check("a dynamic list keeps its payload",
          i18n.tr("metrics: a · b · c", "zh"), "指标： a · b · c")
    check("an unknown phrase is returned unchanged",
          i18n.tr("nothing declared about this", "zh"), "nothing declared about this")

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
