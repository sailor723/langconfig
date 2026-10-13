"""Apply the team's exported settings, without trampling anyone's own changes.

`scripts/seeds/export_settings.py` writes ``scripts/seeds/settings_seed.json``;
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

Called by ``scripts/seeds/seed_all.py`` (step 4b) and safe to call at any time.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from . import store
from .defaults import get_defaults

logger = logging.getLogger(__name__)

DEFAULT_SEED_PATH = Path(__file__).resolve().parents[2] / "scripts/seeds/settings_seed.json"


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
    try:
        for ns in ours_ns:
            ours = payload.get(ns)
            if not isinstance(ours, dict):
                continue
            base = base_all.get(ns, {})
            theirs = store.get_document(db, ns) if store.row_exists(db, ns) else {}
            before = json.dumps(theirs, sort_keys=True)
            merged = _merge(base, ours, theirs, ns, applied, kept)
            if json.dumps(merged, sort_keys=True) != before:
                store.put_document(db, ns, merged)
                written += 1
        if written:
            db.commit()
        logger.info("team settings seed: %d document(s) written, %d key(s) applied, "
                    "%d kept (locally changed)", written, len(applied), len(kept))
    finally:
        if own_session:
            db.close()

    return {"present": True, "written": written, "applied": applied, "kept": kept}
