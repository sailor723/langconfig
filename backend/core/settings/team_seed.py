"""Apply the team's exported settings, without trampling anyone's own changes.

`scripts/seeds/out/export_settings.py` writes ``scripts/seeds/in/settings_seed.json``;
this applies it, and the merge is the whole point:

    base   = the CODE defaults (core/settings/defaults.py)
    ours   = the exported team document
    theirs = the document in this database right now

For every key in `ours`:

  * absent from `theirs`            -> take the team value (a key the team added);
  * `theirs` still equals `base`     -> take the team value. They never touched
                                        it, so the team's decision is news;
  * `theirs` differs from `base`     -> KEEP THEIRS. They changed it deliberately,
                                        and a seed has no business overwriting a
                                        person's setting.

That is what makes this safe to re-run on a database somebody has been using,
unlike a plain write, and it is the settings equivalent of the additive rule the
agent and tool seeds follow.

Namespaces with no code default (`general`, `onboarding`) are not in the export at
all — see export_settings.py for why.

Called by ``scripts/seeds/in/seed_all.py`` (step 4b) and safe to call at any time.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from . import store
from .defaults import get_defaults

logger = logging.getLogger(__name__)

DEFAULT_SEED_PATH = Path(__file__).resolve().parents[2] / "scripts/seeds/in/settings_seed.json"


def _merge(base: Any, ours: Any, theirs: Any, path: str,
           applied: List[str], kept: List[str]) -> Any:
    """Three-way merge of one document (or sub-document)."""
    if isinstance(ours, dict):
        theirs_dict = theirs if isinstance(theirs, dict) else {}
        base_dict = base if isinstance(base, dict) else {}
        out = dict(theirs_dict)
        for key, our_value in ours.items():
            sub = f"{path}.{key}" if path else key
            if key not in theirs_dict:
                out[key] = our_value
                applied.append(sub)          # a key the team added
                continue
            out[key] = _merge(base_dict.get(key), our_value, theirs_dict[key], sub,
                              applied, kept)
        return out

    # Scalar or list, taken whole. Ours wins only where they never moved off the
    # code default; anything they changed stays theirs.
    if theirs == base:
        if theirs != ours:
            applied.append(path)
        return ours
    if theirs != ours:
        kept.append(path)
    return theirs



def _strip_secrets(ns: str, doc: dict, blocked: List[str]) -> dict:
    """Remove every secret field from an incoming team document.

    Credentials never travel: not out of the owner's database (the exporter
    scrubs them from the schema) and not back in. This is the inbound half of
    that rule, and it is deliberately independent of the exporter, so a
    hand-edited or regressed ``settings_seed.json`` still cannot write a key
    into somebody else's database.

    Dropping the key is also what keeps the teammate's own credential: the
    merge only takes a key that is present in the team document, so an absent
    ``api_keys`` means "leave theirs alone".

    Returns a copy with the secrets removed; ``blocked`` collects the paths so
    the caller can tell the operator the repository carries a credential.
    """
    from . import registry
    from .secrets import delete_at_path, secret_paths

    try:
        schema = registry.get(ns).schema
    except Exception:                                  # noqa: BLE001
        # Unknown namespace: refuse the whole section rather than guess.
        blocked.append(f"{ns}.* (no schema registered)")
        return {}

    out = copy.deepcopy(doc)
    for path in secret_paths(schema):
        if delete_at_path(out, path):
            blocked.append(f"{ns}." + ".".join(path))
    # A container whose every field was a secret (models.api_keys) is now {}.
    for key in [k for k, v in out.items() if isinstance(v, dict) and not v]:
        out.pop(key)
        blocked.append(f"{ns}.{key} (emptied)")
    return out


def apply_team_seed(path: Optional[Path] = None, db: Optional[Session] = None) -> Dict[str, Any]:
    """Apply the seed file. Returns a summary of what moved and what was kept."""
    seed_path = Path(path) if path else DEFAULT_SEED_PATH
    if not seed_path.exists():
        return {"present": False, "written": 0, "applied": [], "kept": []}

    try:
        payload = json.loads(seed_path.read_text(encoding="utf-8"))
    except Exception as exc:                      # noqa: BLE001
        logger.warning("settings seed unreadable (%s): %s", seed_path, exc)
        return {"present": False, "written": 0, "applied": [], "kept": [],
                "error": str(exc)}

    ours_ns = [k for k in payload if not k.startswith("__")]
    base_all = get_defaults()

    own_session = db is None
    if own_session:
        from db.database import SessionLocal
        db = SessionLocal()

    written = 0
    applied: List[str] = []
    kept: List[str] = []
    unreadable: List[str] = []
    blocked: List[str] = []
    try:
        for ns in ours_ns:
            ours = payload.get(ns)
            if not isinstance(ours, dict):
                continue
            ours = _strip_secrets(ns, ours, blocked)
            base = base_all.get(ns, {})
            try:
                theirs = store.get_document(db, ns) if store.row_exists(db, ns) else {}
            except Exception as exc:              # noqa: BLE001 — one field must not stop a seed
                # Reading a namespace decrypts its secrets, so a single value written under a
                # different API_KEY_ENCRYPTION_KEY used to abort the whole run here — after nine
                # other steps had already succeeded. Skipping the namespace leaves its stored
                # document untouched (nothing is rewritten, so nothing is destroyed), and the
                # caller reports it rather than failing silently.
                unreadable.append(ns)
                logger.warning(
                    "team settings seed: skipping %r — a stored secret cannot be decrypted with "
                    "the current key (%s). Fix with backend/scripts/audit_settings_secrets.py",
                    ns, type(exc).__name__,
                )
                continue
            before = json.dumps(theirs, sort_keys=True)
            merged = _merge(base, ours, theirs, ns, applied, kept)
            if json.dumps(merged, sort_keys=True) != before:
                store.put_document(db, ns, merged)
                written += 1
        if written:
            db.commit()
        if blocked:
            logger.warning(
                "team settings seed: REFUSED %d credential field(s) found in the seed "
                "(%s). Credentials are never seeded — every machine enters its own. "
                "Remove them from the published settings_seed.json.",
                len(blocked), ", ".join(blocked),
            )
        logger.info("team settings seed: %d document(s) written, %d key(s) applied, "
                    "%d kept (locally changed), %d skipped (unreadable secret), "
                    "%d credential field(s) refused",
                    written, len(applied), len(kept), len(unreadable), len(blocked))
    finally:
        if own_session:
            db.close()

    return {"present": True, "written": written, "applied": applied, "kept": kept,
            "unreadable": unreadable, "blocked": blocked}
