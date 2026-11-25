"""Ontology version numbering: the customer supplies a NAME, the platform assigns the version.

Decided 2026-11-12 (option A of the builder review): a new ontology is never written in place.
The name is what a customer says out loud ("新鸿" → `sunhing`); the version is what the platform
adds, so that

* a published URL, a Settings row, a staging directory and a publish history entry all keep
  pointing at the thing they were made for — an overwrite cannot move them;
* "which build is the customer running?" is a lookup in one file (`latest`), not an interview;
* the previous build stays readable and gateable, with `superseded_by` naming its replacement.

Rules this module enforces:

1. `<base>_v<N>` with N = max(existing N for that family) + 1. N is never reused — not after a
   delete, not after a failed build, not when the next build is smaller. A key that shrinks its
   number is indistinguishable from a key that overwrote history.
2. Exactly one entry per family is `latest`. Recording a new version flips the previous latest to
   `superseded_by=<new key>`, so the chain is walkable in both directions.
3. `kind` is required and recorded: `customer` (a real client deliverable), `demo` (a shipped
   illustration, e.g. tpch/retail/logistics), `trial` (throwaway, safe to delete, e.g. abc,
   probe_key) or `tutorial` (teaching material that must keep running, e.g. talent_steps). Nothing
   in the repo deletes a `customer` or `tutorial` key; nothing presents a `trial` key as a
   deliverable.

The registry is `backend/features/ontology/profiles/_versions.json`. Keys also live as directories
under `profiles/` and as declarations in `gates.json`; the numbering takes the MAXIMUM across all
three, so an ontology registered by any route (script, agent, hand edit) still gets a free number.
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
import re
from typing import Any, Iterable, Mapping

PROFILES = pathlib.Path(__file__).resolve().parent / "profiles"
REGISTRY_NAME = "_versions.json"

#: A key is a directory name, a Settings `items[].key`, a JSON pointer fragment and a turtle prefix.
#: Keep it to that: lowercase, digits, underscore.
KEY_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
#: `<base>_v<N>` — the suffix the platform owns. `_v1x` is not a version, it is a name.
VERSION_RE = re.compile(r"(?P<base>.+)_v(?P<n>[0-9]+)\Z")

KINDS = frozenset({"customer", "demo", "trial", "tutorial"})

_DOC = (
    "Ontology versions. Written by scripts/seeds/in/add_ontology_builder.py (and by the ontology "
    "builder's own registration step). One entry per built key: base name, version number, kind, "
    "and superseded_by. `latest` names the ONE build a customer is expected to be running. Edit by "
    "hand only to correct a mistake — the numbers are a contract, not a cache."
)


class VersionError(ValueError):
    """A key/kind/registry that cannot be recorded as asked."""


# ───────────────────────────────────────────────────────────────── registry
def load(path: pathlib.Path | None = None) -> dict[str, Any]:
    """Read the registry. A missing file is an empty registry, not an error."""
    p = pathlib.Path(path or PROFILES / REGISTRY_NAME)
    if not p.is_file():
        return {"_doc": _DOC, "families": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VersionError(f"{p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise VersionError(f"{p} must hold an object")
    data.setdefault("_doc", _DOC)
    fams = data.setdefault("families", {})
    if not isinstance(fams, dict):
        raise VersionError(f"{p}: 'families' must be an object")
    return data


def save(registry: Mapping[str, Any], path: pathlib.Path | None = None) -> pathlib.Path:
    """Write the registry atomically (a half-written registry is worse than a stale one)."""
    p = pathlib.Path(path or PROFILES / REGISTRY_NAME)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)
    return p


# ───────────────────────────────────────────────────────────────── numbering
def parse_key(key: str) -> tuple[str, int]:
    """`sunhing_v3` → ('sunhing', 3); `abc` → ('abc', 1). The base is never empty.

    Three names are refused rather than parsed, because each one silently creates a second family
    next to the real one: a trailing `_v` (`x_v`), a bare trailing number (`sunhing_1` — is that
    version 1 or a name?), and version 0 (`x_v0`; numbering starts at 1).
    """
    k = (key or "").strip()
    if not KEY_RE.fullmatch(k):
        raise VersionError(f"invalid ontology key {key!r}: lowercase letters, digits, underscore")
    if k.endswith("_v"):
        raise VersionError(f"key {key!r} ends with '_v' — a version needs a number: {k}1")
    m = VERSION_RE.match(k)
    if m and KEY_RE.fullmatch(m.group("base")):
        if int(m.group("n")) < 1:
            raise VersionError(f"key {key!r}: versions start at 1")
        if m.group("n") != str(int(m.group("n"))):
            raise VersionError(f"key {key!r}: version numbers are not zero-padded "
                               f"(write {m.group('base')}_v{int(m.group('n'))})")
        return m.group("base"), int(m.group("n"))
    if re.search(r"_[0-9]+\Z", k):
        raise VersionError(f"key {key!r} ends with a number but not '_v<number>' — write "
                           f"{re.sub(r'_[0-9]+\Z', '', k)}_v{re.search(r'_([0-9]+)\Z', k).group(1)} "
                           f"if you meant a version, or rename it")
    return k, 1


def existing_keys(profile_root: pathlib.Path | None = None,
                  gate_keys: Iterable[str] = ()) -> set[str]:
    """Every key the platform already knows about, from the three places a key can be declared."""
    root = pathlib.Path(profile_root or PROFILES)
    keys = {p.name for p in root.iterdir() if p.is_dir() and KEY_RE.fullmatch(p.name)}
    return keys | {k for k in gate_keys if KEY_RE.fullmatch(str(k))}


def next_version(base: str, *, registry: Mapping[str, Any] | None = None,
                 known: Iterable[str] = ()) -> int:
    """The next free N for `base`: max over registry, directories and gates, plus one."""
    b = (base or "").strip()
    if not KEY_RE.fullmatch(b):
        raise VersionError(f"invalid base name {base!r}: give the customer's name, e.g. 'sunhing'")
    seen = 0
    reg = registry if registry is not None else load()
    fam = (reg.get("families") or {}).get(b) or {}
    for entry in fam.get("versions") or []:
        try:
            _, n = parse_key(str(entry.get("key")))
        except VersionError:
            continue
        if str(entry.get("key")) == b or str(entry.get("key", "")).startswith(b + "_v"):
            seen = max(seen, n)
    for key in known:
        try:
            parsed_base, n = parse_key(str(key))
        except VersionError:
            continue
        if parsed_base == b and str(key) != b:
            seen = max(seen, n)
        elif str(key) == b:
            seen = max(seen, 1)
    return seen + 1


def key_for(base: str, *, registry: Mapping[str, Any] | None = None,
            known: Iterable[str] = ()) -> tuple[str, int]:
    """`('sunhing', {})` → ('sunhing_v1', 1). Never returns an occupied key."""
    n = next_version(base, registry=registry, known=known)
    return f"{base}_v{n}", n


# ───────────────────────────────────────────────────────────────── recording
def record(registry: dict[str, Any], *, key: str, kind: str, theme: str = "",
           datasource: str = "", now: str | None = None) -> dict[str, Any]:
    """Record `key` as a build of its family and return the entry.

    Idempotent for the same key (a re-run refreshes theme/datasource and changes nothing else);
    a NEW key flips the family's previous `latest` to `superseded_by=<key>`.
    """
    if kind not in KINDS:
        raise VersionError(f"kind {kind!r} is not one of {sorted(KINDS)}")
    base, version = parse_key(key)
    canonical = base if version == 1 and key == base else f"{base}_v{version}"
    if canonical != key:
        raise VersionError(f"key {key!r} is not canonical; did you mean {canonical!r}?")
    fams = registry.setdefault("families", {})
    fam = fams.setdefault(base, {"latest": None, "versions": []})
    versions = fam.setdefault("versions", [])
    entry = next((v for v in versions if str(v.get("key")) == key), None)
    stamp = now or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if entry is None:
        entry = {"key": key, "version": version, "kind": kind, "theme": theme or base,
                 "datasource": datasource or base, "created": stamp, "superseded_by": None}
        versions.append(entry)
        versions.sort(key=lambda v: int(v.get("version") or 0))
    else:
        entry.update({"kind": kind, "theme": theme or entry.get("theme") or base,
                      "datasource": datasource or entry.get("datasource") or base})
    # the newest version wins `latest`; each older build points at the build that replaced IT
    # (v1→v2 stays v1→v2 when v3 arrives), so the chain is walkable from either end
    top = max(int(v.get("version") or 0) for v in versions)
    for v in versions:
        if int(v.get("version") or 0) == top:
            v["superseded_by"] = None
        elif not v.get("superseded_by"):
            v["superseded_by"] = key
    fam["latest"] = next(v["key"] for v in versions if int(v.get("version") or 0) == top)
    return entry


def latest_of(base: str, *, registry: Mapping[str, Any] | None = None) -> str | None:
    reg = registry if registry is not None else load()
    return ((reg.get("families") or {}).get(base) or {}).get("latest") or None


def chain(key: str, *, registry: Mapping[str, Any] | None = None) -> list[str]:
    """Oldest → newest keys of `key`'s family. Used by audits and by the profile's own history."""
    reg = registry if registry is not None else load()
    base, _ = parse_key(key)
    fam = (reg.get("families") or {}).get(base) or {}
    return [str(v.get("key")) for v in sorted(fam.get("versions") or [],
                                              key=lambda v: int(v.get("version") or 0))]


# ───────────────────────────────────────────────────────────────── paths
def profile_dir(key: str, root: pathlib.Path | None = None) -> pathlib.Path:
    """`profiles/<key>` — and it must stay under `profiles/`.

    The builder writes through a tool that takes the key from a conversation, so the containment
    check lives next to the numbering: a key is a NAME, never a path.
    """
    if not KEY_RE.fullmatch(str(key or "")):
        raise VersionError(f"invalid ontology key {key!r}: lowercase letters, digits, underscore")
    base = pathlib.Path(root or PROFILES).resolve()
    dest = (base / key).resolve()
    if dest != base and base not in dest.parents:
        raise VersionError(f"key {key!r} would escape {base}")
    return dest


if __name__ == "__main__":                                  # a quick inventory, no side effects
    import sys

    reg = load()
    known = existing_keys()
    # gates.json declares keys too — a declared-but-unbuilt key still occupies its number
    try:
        known |= {str(k) for k in json.loads((pathlib.Path(__file__).resolve().parent
                                             / "gates.json").read_text(encoding="utf-8"))
                  if KEY_RE.fullmatch(str(k))}
    except Exception:                                                   # noqa: BLE001
        pass
    for base in sorted({parse_key(k)[0] for k in known} | set((reg.get("families") or {}))):
        latest = latest_of(base, registry=reg) or "—"
        print(f"{base:<16} latest={latest:<20} next={base}_v{next_version(base, registry=reg, known=known):<3} "
              f"versions={', '.join(chain(base + '_v1' if base + '_v1' in known else base, registry=reg)) or '—'}")
    sys.exit(0)
