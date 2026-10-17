"""Single source of truth for the seed tree's layout.

The seed scripts live in three subfolders, and *every* script needs to find its
siblings regardless of where it sits:

    scripts/seeds/
    ├── _seedpaths.py      <- this file, always at the root
    ├── seed_all.py        <- entrypoint: seed IN  (the documented command)
    ├── out/               <- export live DB -> committable artifact
    ├── in/                <- artifacts + scripts that load them
    └── verify/            <- tests, reports and the two-machine rehearsal

Before this module existed each script derived its paths from its own depth with
a hardcoded ``Path(__file__).parents[N]``, so moving a file one directory down
silently pointed it at the wrong place. Import this instead:

    import sys
    from pathlib import Path
    for _p in Path(__file__).resolve().parents:
        if (_p / "_seedpaths.py").exists():
            sys.path.insert(0, str(_p))
            break
    from _seedpaths import BACKEND, IN_DIR, OUT_DIR, REPO, SEEDS

Importing also puts ``backend/`` on ``sys.path``, so ``db.database`` and friends
resolve exactly as they do when a script is run from ``backend/``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# _seedpaths.py is at the seed root, so its own location is authoritative —
# no walking up and no depth arithmetic to get wrong.
SEEDS: Path = Path(__file__).resolve().parent
SCRIPTS: Path = SEEDS.parent            # backend/scripts
BACKEND: Path = SCRIPTS.parent          # backend
REPO: Path = BACKEND.parent             # repository root

OUT_DIR: Path = SEEDS / "out"
IN_DIR: Path = SEEDS / "in"
VERIFY_DIR: Path = SEEDS / "verify"

# Artifacts. Named here so a rename is a one-line change instead of a grep.
AGENTS_MERGE = IN_DIR / "deep_agents_merge.sql"
TOOLS_MERGE = IN_DIR / "custom_tools_merge.sql"
SETTINGS_SEED = IN_DIR / "settings_seed.json"
MODELS_CSV = IN_DIR / "models_seed.csv"

# Explicit-id snapshots. Retained for reference only: seed_all.py no longer
# restores them (see _replace_* in seed_all.py), because they had drifted
# behind the merge files.
AGENTS_DUMP = IN_DIR / "deep_agents_dump.sql"
TOOLS_DUMP = IN_DIR / "custom_tools_dump.sql"

# Script entrypoints, for subprocess calls.
SEED_ALL = IN_DIR / "seed_all.py"
EXPORT_BASELINE = OUT_DIR / "export_baseline.py"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
