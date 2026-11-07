"""Which DASHBOARD databases exist on disk — the grouping rule, in one place.

The dashboard browser groups ~40 HTML pages into the handful of databases they
belong to ("sunhing", "chinook", …). Two questions read that rule:

  * `GET /api/analysis/databases` — what the browser shows (pages → groups), and
  * `GET /api/graph-studio/databases/catalog` — the Settings table, which must
    list a database that has pages even when it is switched off, otherwise there
    is no switch to switch back on.

Keeping the rule here (rather than only inside the analysis routes) is what makes
those two agree: a dashboard that exists is a row in Settings, on or off.
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# backend/data/analysis_dbs — generated dashboards, their registry and skills.
ANALYSIS_DBS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "analysis_dbs"
_REGISTRY_PATH = ANALYSIS_DBS_DIR / "databases.json"


def load_registry() -> Dict[str, dict]:
    """Curated {db_key: {name, intro, home, match[]}}; {} when absent/unreadable.

    A bare `except: return {}` here hid a NameError (`json` was not imported at
    module scope) and silently degraded every database to its filename prefix —
    `registered` stayed False on all nine. Log the reason instead.
    """
    try:
        raw = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.info(f"no dashboard registry at {_REGISTRY_PATH} — using filename prefixes")
        return {}
    except Exception as exc:  # noqa: BLE001 — say why, do not silently degrade
        logger.warning(f"dashboard registry unreadable ({type(exc).__name__}: {exc}) — using filename prefixes")
        return {}
    dbs = raw.get("databases") if isinstance(raw, dict) else None
    if not isinstance(dbs, dict):
        logger.warning("dashboard registry has no 'databases' object — using filename prefixes")
        return {}
    return dbs


def _explicitly_listed(filename: str, registry: dict) -> bool:
    """True when a family names this exact file in its `match` list.

    The own-database rule above must not override a curation decision. A *prefix*
    needle ("sales") is a convenience; a needle that is a full filename
    ("sample_sales_dashboard.html") is somebody saying "this page belongs to that
    database" — which is exactly the case for the older upload-generated pages that
    are deliberately filed under `sales`.
    """
    lowered = filename.lower()
    return any(
        "." in str(needle) and str(needle).lower() == lowered
        for cfg in registry.values()
        for needle in (cfg.get("match") or [])
    )


def family_key_of(filename: str, db_path: Optional[str], registry: dict) -> str:
    """Which registered database a page belongs to."""
    meta_name = (db_path or "").split("/")[-1]
    hay = [filename.lower()]
    if meta_name and meta_name != "None":
        hay.append(meta_name.lower())
    # A freshly generated dataset dashboard is its OWN database.
    #
    # `<stem>_dashboard.html` is the naming the generator uses (`sales_2024_2025`
    # from `sales_2024_2025.csv`). Without this rule the family came from the
    # registry's `sales` prefix, so the new page was folded into the `sales`
    # database whose home is `sales_dashboard.html` — the rail lists DATABASES, so
    # the page existed, was served, and had no way to be opened from the UI.
    #
    # Curated databases are unaffected: their home pages are declared in the
    # registry (`sunhing_dashboard.html`, `tesla_strategy_dashboard.html`, …) and
    # are skipped here, so the rule can only claim names nobody has curated.
    if filename.endswith("_dashboard.html") and not _explicitly_listed(filename, registry):
        stem = filename[: -len("_dashboard.html")]
        known_keys = {k.lower() for k in registry}
        known_homes = {str(c.get("home") or "").lower() for c in registry.values()}
        if stem and stem.lower() not in known_keys and filename.lower() not in known_homes:
            return stem

    for key, cfg in registry.items():
        for needle in cfg.get("match") or []:
            n = str(needle).lower()
            # A needle with a dot is a whole filename ("dashboard.html") → exact;
            # otherwise it is a prefix. Substring matching was wrong: "dashboard.html"
            # swallowed business_dashboard.html and tesla_strategy_dashboard.html,
            # folding two databases into the sales family.
            if "." in n:
                if hay[0] == n:
                    return key
            elif any(h.startswith(n) for h in hay[1:]) or hay[0].startswith(n):
                return key
    # Unregistered pages: keep them visible under their own filename prefix
    # rather than hiding them behind a registry edit.
    return filename.split("_")[0] or "other"


def dashboard_keys() -> List[str]:
    """Every database that owns at least one dashboard page, sorted.

    Filenames only (no meta parsing): a page's `db:` field refines the grouping
    when pages are listed, but the registered `match` prefixes already cover the
    curated set, so this is enough to decide "does this dashboard exist".
    """
    if not ANALYSIS_DBS_DIR.exists():
        return []
    registry = load_registry()
    keys = set(registry)
    for f in ANALYSIS_DBS_DIR.glob("*.html"):
        keys.add(family_key_of(f.name, None, registry))
    return sorted(k for k in keys if k)
